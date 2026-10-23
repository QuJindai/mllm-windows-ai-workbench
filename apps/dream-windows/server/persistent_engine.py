from __future__ import annotations

import base64
import json
import math
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
            # base_url is validated as loopback; Windows/system proxies must
            # not turn a refused local endpoint into a remote proxy timeout.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=timeout) as response:
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
        psutil = self._process_library()
        if self._process is None:
            raise PersistentEngineUnavailable("无法记录常驻引擎身份：缺少本服务启动的进程")
        try:
            identity = psutil.Process(self._process.pid)
            start_time = identity.create_time()
            executable = identity.exe()
            if not identity.is_running() or not self._same_path(executable, self.executable):
                raise PersistentEngineUnavailable("常驻引擎身份校验失败，无法保存启动状态")
        except psutil.Error as exc:
            raise PersistentEngineUnavailable("无法读取常驻引擎启动时间及程序路径，请检查进程访问权限") from exc
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "pid": self._process.pid,
            "executable": executable,
            "startTime": start_time,
            "base_url": self.base_url,
            "model_path": str(model_path),
            "flash_attention": True,
        }
        temporary = self._state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self._state_path)

    @staticmethod
    def _process_library():
        try:
            import psutil
        except ImportError as exc:
            raise PersistentEngineUnavailable("缺少进程身份校验组件，无法安全释放常驻引擎") from exc
        return psutil

    def _release_snapshot(self) -> tuple[bytes, float, dict[str, Any]] | None:
        try:
            with self._state_path.open("rb") as stream:
                raw = stream.read(65537)
                modified = os.fstat(stream.fileno()).st_mtime
            state = json.loads(raw.decode("utf-8-sig")) if len(raw) <= 65536 else None
            if not isinstance(state, dict):
                raise ValueError("invalid state")
            return raw, modified, state
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise PersistentEngineUnavailable("常驻引擎状态文件损坏或无法读取，无法确认进程归属") from exc

    def _state_unchanged(self, snapshot: tuple[bytes, float, dict[str, Any]]) -> None:
        current = self._release_snapshot()
        if current is None or current[0] != snapshot[0]:
            raise PersistentEngineUnavailable("常驻引擎状态已被其他服务更新，已停止释放操作")

    def _clear_release_state(self, snapshot: tuple[bytes, float, dict[str, Any]] | None) -> None:
        if snapshot is not None:
            self._state_unchanged(snapshot)
            self._state_path.unlink()

    def _release_endpoint(self) -> dict[str, Any] | None:
        """Only an actual refused connection proves that no listener remains."""
        try:
            # Windows may deliver loopback ECONNREFUSED after roughly 2.05s.
            # A 2s timeout masks that evidence as an ambiguous timeout.
            return self._transport("GET", "/sdcpp/v1/capabilities", None, 5.0)
        except PersistentEngineUnavailable as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.URLError) and isinstance(cause.reason, ConnectionRefusedError):
                return None
            raise PersistentEngineUnavailable("常驻引擎接口无响应或返回异常，无法确认进程归属；请稍后重试") from exc

    @staticmethod
    def _command_option(command: list[str], names: set[str]) -> str:
        values = []
        for index, token in enumerate(command[1:], 1):
            key, separator, value = token.partition("=")
            if key in names:
                if not separator:
                    if index + 1 >= len(command):
                        raise ValueError("missing command option")
                    value = command[index + 1]
                values.append(value)
        if len(values) != 1 or not values[0]:
            raise ValueError("missing or duplicate command option")
        return values[0]

    def _adopt_for_release(self, snapshot: tuple[bytes, float, dict[str, Any]]):
        """Return the same psutil identity that was verified, never just a PID."""
        psutil = self._process_library()
        state = snapshot[2]
        pid = state.get("pid")
        model_path = state.get("model_path")
        if type(pid) is not int or pid <= 0 or state.get("base_url") != self.base_url or not isinstance(model_path, str) or not Path(model_path).is_absolute():
            raise PersistentEngineUnavailable("常驻引擎状态与当前服务配置不一致，无法确认进程归属")
        if "executable" in state and (not isinstance(state["executable"], str) or not self._same_path(state["executable"], self.executable)):
            raise PersistentEngineUnavailable("常驻引擎记录的程序路径不一致，进程身份校验失败")
        try:
            process = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return None
        except psutil.Error as exc:
            raise PersistentEngineUnavailable("无法读取常驻引擎进程身份，访问权限不足；未执行终止操作") from exc
        try:
            parsed = urlparse(self.base_url)
            if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.port is None or parsed.username or parsed.path or parsed.query or parsed.fragment:
                raise ValueError("invalid endpoint")
            started = process.create_time()
            if type(started) not in {int, float} or not math.isfinite(started) or started <= 0:
                raise ValueError("invalid creation time")
            if "startTime" in state:
                recorded = state["startTime"]
                if type(recorded) not in {int, float} or not math.isfinite(recorded) or recorded != started:
                    raise PersistentEngineUnavailable("常驻引擎启动时间与记录不一致，PID 可能已复用；已拒绝终止")
            elif started > snapshot[1]:
                # Legacy records lack startTime. A process created after the
                # original record cannot be the process that record described.
                raise PersistentEngineUnavailable("常驻引擎启动时间晚于旧状态文件，无法确认进程归属")
            command = process.cmdline()
            if not isinstance(command, list) or not command or not all(isinstance(arg, str) for arg in command):
                raise ValueError("invalid command line")
            if not self._same_path(process.exe(), self.executable) or not self._same_path(command[0], self.executable):
                raise ValueError("wrong executable")
            if not self._same_path(self._command_option(command, {"-m", "--model"}), model_path):
                raise ValueError("wrong model")
            listen_ip = self._command_option(command, {"--listen-ip"})
            addresses = {parsed.hostname} if parsed.hostname != "localhost" else {"localhost", "127.0.0.1", "::1"}
            if listen_ip not in addresses or self._command_option(command, {"--listen-port"}) != str(parsed.port):
                raise ValueError("wrong bind endpoint")
            listener_addresses = {"127.0.0.1", "::1"} if listen_ip == "localhost" else {listen_ip}
            if not any(connection.status == psutil.CONN_LISTEN and connection.laddr.ip in listener_addresses and connection.laddr.port == parsed.port for connection in process.net_connections(kind="tcp")):
                raise ValueError("listener belongs to another process")
            capabilities = self._release_endpoint()
            if capabilities is None:
                raise ValueError("live process has no responding endpoint")
            try:
                self._verify_capabilities(capabilities, Path(model_path))
            except PersistentEngineUnavailable as exc:
                raise ValueError("model capabilities mismatch") from exc
            self._state_unchanged(snapshot)
            if not process.is_running():
                raise ValueError("process exited or PID was reused")
            return process
        except (psutil.Error, OSError, ValueError, TypeError, AttributeError) as exc:
            raise PersistentEngineUnavailable("常驻引擎进程身份校验失败：程序、模型、监听地址或访问权限不匹配；未终止任何未知进程") from exc

    def release_for_identity(self) -> None:
        """Release a held child or a fully verified inherited native resident."""
        with self._start_lock:
            snapshot = self._release_snapshot()
            process = self._process
            if process is not None:
                if snapshot is not None and (snapshot[2].get("pid") != getattr(process, "pid", None) or snapshot[2].get("base_url") != self.base_url):
                    raise PersistentEngineUnavailable("常驻引擎状态属于另一个进程或服务，已停止释放操作")
                try:
                    if process.poll() is None:
                        process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                except OSError as exc:
                    raise PersistentEngineUnavailable("无法释放本服务启动的常驻引擎，请检查进程访问权限") from exc
                self._process = None
            elif snapshot is not None:
                psutil = self._process_library()
                identity = self._adopt_for_release(snapshot)
                if identity is not None:
                    try:
                        # psutil rechecks PID + creation time for terminate/kill.
                        # Retain this object through wait; do not reopen by PID.
                        identity.terminate()
                        try:
                            identity.wait(timeout=5)
                        except psutil.TimeoutExpired:
                            identity.kill()
                            identity.wait()
                    except psutil.Error as exc:
                        raise PersistentEngineUnavailable("常驻引擎身份发生变化或无法终止，已停止释放操作") from exc
            if self._release_endpoint() is not None:
                raise PersistentEngineUnavailable("常驻引擎接口仍有进程监听且归属未确认，暂不能启动人物生成")
            self._clear_release_state(snapshot)
            self._flash_attention_verified = False

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
