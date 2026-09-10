from __future__ import annotations

import base64
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from config import DreamServerConfig
from models import GenerateRequest


class PersistentEngineUnavailable(RuntimeError):
    """The persistent engine could not be used before a native job was accepted."""


class PersistentEngineError(RuntimeError):
    """The persistent engine accepted work but failed to produce a valid image."""


class PersistentGenerationCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class PersistentGenerationResult:
    native_job_id: str
    image_bytes: bytes
    engine_wall_time_ms: int
    postprocess_time_ms: int
    flash_attention: bool | None = None


Transport = Callable[[str, str, dict[str, Any] | None, float], dict[str, Any]]


class PersistentEngineClient:
    def __init__(
        self,
        config: DreamServerConfig,
        *,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.base_url = config.persistent_engine_url
        self.executable = config.persistent_engine_exe
        self._transport = transport or self._http_json
        self._transport_injected = transport is not None
        self._sleep = sleep
        self._process: subprocess.Popen[bytes] | None = None
        self._start_lock = threading.Lock()
        self._flash_attention_verified = False

    @property
    def available(self) -> bool:
        return self._transport_injected or self.executable.is_file()

    @property
    def _state_path(self) -> Path:
        return self.config.dream_root / "data" / "sd-server-state.json"

    def _http_json(self, method: str, path: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise PersistentEngineUnavailable(f"sd-server HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PersistentEngineUnavailable(f"sd-server is unavailable: {exc}") from exc
        try:
            value = json.loads(body.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PersistentEngineUnavailable("sd-server returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise PersistentEngineUnavailable("sd-server returned a non-object response")
        return value

    @staticmethod
    def _same_path(left: str | Path, right: str | Path) -> bool:
        return os.path.normcase(os.path.abspath(str(left))).casefold() == os.path.normcase(os.path.abspath(str(right))).casefold()

    def _verify_capabilities(self, capabilities: dict[str, Any], model_path: Path) -> None:
        modes = capabilities.get("supported_modes")
        loaded_path = (capabilities.get("model") or {}).get("path")
        if not isinstance(modes, list) or "img_gen" not in modes:
            raise PersistentEngineUnavailable("sd-server does not support image generation")
        if not loaded_path or not self._same_path(str(loaded_path), model_path):
            raise PersistentEngineUnavailable(f"sd-server is using a different model: {loaded_path or 'unknown'}")

    def _probe(self, model_path: Path) -> bool:
        try:
            capabilities = self._transport("GET", "/sdcpp/v1/capabilities", None, 2.0)
        except PersistentEngineUnavailable:
            return False
        self._verify_capabilities(capabilities, model_path)
        self._restore_verified_state(model_path)
        return True

    def _restore_verified_state(self, model_path: Path) -> None:
        try:
            state = json.loads(self._state_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return
        if state.get("base_url") == self.base_url and self._same_path(str(state.get("model_path") or ""), model_path):
            self._flash_attention_verified = state.get("flash_attention") is True

    def ensure_ready(self, model_path: Path) -> None:
        with self._start_lock:
            try:
                if self._probe(model_path):
                    return
            except PersistentEngineUnavailable:
                raise
            if self._transport_injected:
                raise PersistentEngineUnavailable("injected sd-server transport is not ready")
            if not self.executable.is_file():
                raise PersistentEngineUnavailable(f"sd-server.exe is missing: {self.executable}")

            parsed = urlparse(self.base_url)
            if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.port is None:
                raise PersistentEngineUnavailable("sd-server must bind to localhost")
            log_dir = self.config.dream_root / "logs" / "engine-server"
            log_dir.mkdir(parents=True, exist_ok=True)
            stdout_path = log_dir / "sd-server.out.log"
            stderr_path = log_dir / "sd-server.err.log"
            command = [
                str(self.executable),
                "-m", str(model_path),
                "--backend", "cuda",
                "--max-vram", os.environ.get("DREAM_CUDA_BUDGET_GB", "4.4"),
                "--offload-to-cpu",
                "--diffusion-fa",
                "--listen-ip", parsed.hostname,
                "--listen-port", str(parsed.port),
                "--verbose",
            ]
            try:
                with stdout_path.open("ab") as stdout_log, stderr_path.open("ab") as stderr_log:
                    self._process = subprocess.Popen(
                        command,
                        cwd=str(self.executable.parent),
                        stdout=stdout_log,
                        stderr=stderr_log,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
            except OSError as exc:
                raise PersistentEngineUnavailable(f"failed to start sd-server: {exc}") from exc

            deadline = time.monotonic() + float(os.environ.get("DREAM_SDCPP_SERVER_START_TIMEOUT", "45"))
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    raise PersistentEngineUnavailable(f"sd-server exited during startup with code {self._process.returncode}")
                try:
                    if self._probe(model_path):
                        self._flash_attention_verified = True
                        self._persist_state(model_path)
                        return
                except PersistentEngineUnavailable:
                    if self._process.poll() is not None:
                        break
                self._sleep(0.25)
            if self._process.poll() is None:
                self._process.terminate()
            raise PersistentEngineUnavailable("sd-server did not become ready before the startup timeout")

    def _persist_state(self, model_path: Path) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "pid": self._process.pid if self._process is not None else None,
            "base_url": self.base_url,
            "model_path": str(model_path),
            "flash_attention": True,
        }
        temporary = self._state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self._state_path)

    @staticmethod
    def _payload(request: GenerateRequest, seed: int) -> dict[str, Any]:
        return {
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt,
            "width": request.width,
            "height": request.height,
            "seed": seed,
            "batch_count": 1,
            "output_format": "png",
            "output_compression": 100,
            "sample_params": {
                "sample_method": request.sampling_method,
                "scheduler": request.scheduler,
                "sample_steps": request.steps,
                "guidance": {"txt_cfg": request.cfg},
            },
        }

    def generate(
        self,
        request: GenerateRequest,
        *,
        seed: int,
        model_path: Path,
        on_submitted: Callable[[str], None],
        is_cancelled: Callable[[], bool],
    ) -> PersistentGenerationResult:
        self.ensure_ready(model_path)
        started = time.monotonic()
        submission = self._transport("POST", "/sdcpp/v1/img_gen", self._payload(request, seed), 10.0)
        native_job_id = submission.get("id")
        if not isinstance(native_job_id, str) or not native_job_id:
            raise PersistentEngineUnavailable("sd-server did not return a native job id")
        on_submitted(native_job_id)
        poll_path = str(submission.get("poll_url") or f"/sdcpp/v1/jobs/{native_job_id}")
        deadline = time.monotonic() + float(os.environ.get("DREAM_SDCPP_GENERATION_TIMEOUT", "900"))
        while time.monotonic() < deadline:
            if is_cancelled():
                self.cancel(native_job_id)
                raise PersistentGenerationCancelled("generation was cancelled")
            try:
                status_value = self._transport("GET", poll_path, None, 30.0)
            except PersistentEngineUnavailable as exc:
                raise PersistentEngineError(str(exc)) from exc
            status = str(status_value.get("status") or "").casefold()
            if status == "completed":
                engine_wall_time_ms = round((time.monotonic() - started) * 1000)
                try:
                    encoded = status_value["result"]["images"][0]["b64_json"]
                    decode_started = time.monotonic()
                    image_bytes = base64.b64decode(encoded, validate=True)
                    postprocess_time_ms = round((time.monotonic() - decode_started) * 1000)
                except (KeyError, IndexError, TypeError, ValueError) as exc:
                    raise PersistentEngineError("sd-server completed without a valid image payload") from exc
                if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise PersistentEngineError("sd-server result is not a PNG image")
                return PersistentGenerationResult(
                    native_job_id=native_job_id,
                    image_bytes=image_bytes,
                    engine_wall_time_ms=engine_wall_time_ms,
                    postprocess_time_ms=postprocess_time_ms,
                    flash_attention=True if self._flash_attention_verified else None,
                )
            if status in {"failed", "cancelled"}:
                error = status_value.get("error") or {}
                message = error.get("message") if isinstance(error, dict) else None
                if status == "cancelled":
                    raise PersistentGenerationCancelled(str(message or "generation was cancelled"))
                raise PersistentEngineError(str(message or "sd-server generation failed"))
            self._sleep(0.1)
        raise PersistentEngineError("sd-server generation timed out")

    def cancel(self, native_job_id: str) -> None:
        try:
            self._transport("POST", f"/sdcpp/v1/jobs/{native_job_id}/cancel", None, 5.0)
        except PersistentEngineUnavailable:
            # The native API cannot interrupt every running backend. Dream still keeps
            # the user-visible job terminal and ignores any late native result.
            return
