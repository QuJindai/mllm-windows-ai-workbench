from __future__ import annotations

import json
import math
import os
import re
import secrets
import subprocess
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from config import DreamServerConfig
from errors import DreamApiError
from models import GenerateRequest
from persistent_engine import (
    PersistentEngineClient,
    PersistentEngineError,
    PersistentEngineUnavailable,
    PersistentGenerationCancelled,
)


@dataclass(frozen=True)
class NativeRunResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[list[str], dict[str, str], Path, Path, Path], NativeRunResult]


class JobRunner:
    MAX_LATENT_STEP = 50
    MAX_LATENT_DIMENSION = 4096
    MAX_HISTOGRAM_BIN = 16_777_216

    def __init__(
        self,
        config: DreamServerConfig,
        command_runner: CommandRunner | None = None,
        persistent_engine: PersistentEngineClient | None = None,
    ):
        self.config = config
        self.command_runner = command_runner
        self.persistent_engine = persistent_engine or PersistentEngineClient(config)
        self._jobs: dict[str, dict[str, Any]] = {}
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._persistent_jobs: dict[str, str] = {}
        self._command_runner_invocations: dict[str, tuple[threading.Thread, threading.Event]] = {}
        self._cancelled: set[str] = set()
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dream-generate")
        self._before_run: list[Callable[[], None]] = []

    def add_before_run(self, callback: Callable[[], None]) -> None:
        """Register a release barrier before every native inference path."""
        with self._lock:
            if callback not in self._before_run:
                self._before_run.append(callback)

    def remove_before_run(self, callback: Callable[[], None]) -> None:
        with self._lock:
            if callback in self._before_run:
                self._before_run.remove(callback)

    def submit_serial(self, operation: Callable[..., Any], *args: Any) -> Future:
        """Schedule work on the same exclusive queue as native generation."""
        return self._executor.submit(operation, *args)

    def release_native_for_identity(self) -> None:
        """Must be called from queued work before loading an identity model."""
        self.persistent_engine.release_for_identity()

    def _job_path(self, job_id: str) -> Path:
        return self.config.dream_root / "data" / "jobs" / f"{job_id}.json"

    def _trace_path(self, job_id: str) -> Path:
        return self.config.dream_root / "traces" / f"{job_id}.json"

    def _trace_dir(self, job_id: str) -> Path:
        return self.config.dream_root / "traces" / job_id

    def _persist(self, record: dict[str, Any]) -> None:
        path = self._job_path(record["id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def _update(self, job_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            record = self._jobs[job_id]
            record.update(changes)
            self._persist(record)
            return dict(record)

    def _update_if_active(self, job_id: str, **changes: Any) -> dict[str, Any] | None:
        with self._lock:
            record = self._jobs[job_id]
            if job_id in self._cancelled or record.get("state") == "cancelled":
                return None
            record.update(changes)
            self._persist(record)
            return dict(record)

    def _is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancelled or self._jobs[job_id].get("state") == "cancelled"

    def submit(self, request: GenerateRequest) -> dict[str, Any]:
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        output_dir = self.config.dream_root / "outputs" / date.today().isoformat()
        output = output_dir / f"{job_id}.png"
        metadata = output_dir / f"{job_id}.json"
        seed = request.seed if isinstance(request.seed, int) else secrets.randbelow(2_000_000_000) + 1
        request_data = request.model_dump(by_alias=True)
        request_data["seed"] = seed
        record = {
            "id": job_id,
            "request": request_data,
            "state": "queued",
            "progress": 2,
            "message": "等待本地生成队列",
            "result": None,
            "error": None,
            "outputPath": str(output),
            "metadataPath": str(metadata),
            "tracePath": str(self._trace_path(job_id)),
            "traceAssetsPath": str(self._trace_dir(job_id)),
            "stdoutLog": str(self.config.dream_root / "logs" / "web" / f"{job_id}.out.log"),
            "stderrLog": str(self.config.dream_root / "logs" / "web" / f"{job_id}.err.log"),
        }
        with self._lock:
            self._jobs[job_id] = record
            self._persist(record)
        self.submit_serial(self._execute, job_id, request, seed, output, metadata)
        return dict(record)

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is not None:
                return dict(record)
        path = self._job_path(job_id)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        raise DreamApiError("JOB_NOT_FOUND", f"Generation job was not found: {job_id}", status_code=404)

    def cancel(self, job_id: str) -> dict[str, Any]:
        command_runner_invocation: tuple[threading.Thread, threading.Event] | None = None
        native_job_id: str | None = None
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                path = self._job_path(job_id)
                if not path.exists():
                    raise DreamApiError("JOB_NOT_FOUND", f"Generation job was not found: {job_id}", status_code=404)
                record = json.loads(path.read_text(encoding="utf-8"))
                self._jobs[job_id] = record
            state = record.get("state")
            if state in {"complete", "failed"}:
                return dict(record)
            if state == "cancelled":
                command_runner_invocation = self._command_runner_invocations.get(job_id)
                native_job_id = self._persistent_jobs.get(job_id)
                cancelled_record = dict(record)
            else:
                self._cancelled.add(job_id)
                process = self._processes.get(job_id)
                if process is not None and process.poll() is None:
                    process.terminate()
                command_runner_invocation = self._command_runner_invocations.get(job_id)
                native_job_id = self._persistent_jobs.get(job_id)
                cancelled_record = self._update(job_id, state="cancelled", message="已取消生成", progress=0)
        if native_job_id is not None:
            self.persistent_engine.cancel(native_job_id)
        if command_runner_invocation is not None and command_runner_invocation[0] is not threading.current_thread():
            command_runner_invocation[1].wait()
        return cancelled_record

    def _command(self, request: GenerateRequest, seed: int, output: Path, metadata: Path, trace_dir: Path) -> list[str]:
        return [
            str(self.config.core_exe),
            "generate",
            "--model", request.model_id,
            "--prompt", request.prompt,
            "--negative", request.negative_prompt,
            "--seed", str(seed),
            "--steps", str(request.steps),
            "--cfg", str(request.cfg),
            "--width", str(request.width),
            "--height", str(request.height),
            "--sampling-method", request.sampling_method,
            "--scheduler", request.scheduler,
            "--trace-level", request.trace_level,
            "--trace-dir", str(trace_dir),
            "--output", str(output),
            "--metadata", str(metadata),
        ]

    def _run_command_runner(self, job_id: str, command: list[str], env: dict[str, str], cwd: Path, stdout_log: Path, stderr_log: Path) -> NativeRunResult | None:
        runner = self.command_runner
        if runner is None:
            return None
        finished = threading.Event()
        invocation_thread = threading.current_thread()
        with self._lock:
            if job_id in self._cancelled or self._jobs[job_id].get("state") == "cancelled":
                return None
            self._command_runner_invocations[job_id] = (invocation_thread, finished)
        try:
            return self._invoke_command_runner(runner, command, env, cwd, stdout_log, stderr_log)
        finally:
            finished.set()
            with self._lock:
                current = self._command_runner_invocations.get(job_id)
                if current == (invocation_thread, finished):
                    self._command_runner_invocations.pop(job_id, None)

    def _invoke_command_runner(self, runner: CommandRunner, command: list[str], env: dict[str, str], cwd: Path, stdout_log: Path, stderr_log: Path) -> NativeRunResult:
        return runner(command, env, cwd, stdout_log, stderr_log)

    def _run_process(self, job_id: str, command: list[str], env: dict[str, str], cwd: Path, stdout_log: Path, stderr_log: Path) -> NativeRunResult | None:
        stdout_log.parent.mkdir(parents=True, exist_ok=True)
        stderr_log.parent.mkdir(parents=True, exist_ok=True)
        process: subprocess.Popen[str] | None = None
        try:
            with self._lock:
                if job_id in self._cancelled or self._jobs[job_id].get("state") == "cancelled":
                    return None
                process = subprocess.Popen(
                    command,
                    cwd=str(cwd),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                self._processes[job_id] = process
            stdout, stderr = process.communicate()
            stdout_log.write_text(stdout, encoding="utf-8")
            stderr_log.write_text(stderr, encoding="utf-8")
            return NativeRunResult(process.returncode or 0, stdout, stderr)
        except OSError as exc:
            return NativeRunResult(1, "", str(exc))
        finally:
            with self._lock:
                if self._processes.get(job_id) is process:
                    self._processes.pop(job_id, None)

    def _execute(self, job_id: str, request: GenerateRequest, seed: int, output: Path, metadata: Path) -> None:
        if self._update_if_active(job_id, state="preparing", progress=12, message="正在验证模型并准备 CUDA") is None:
            return
        try:
            with self._lock:
                barriers = tuple(self._before_run)
            for barrier in barriers:
                barrier()
        except Exception:
            self._update_if_active(job_id, state="failed", progress=0, message="无法确认上一任务已释放 GPU", error="GPU release barrier failed; no native generation was started")
            return
        output.parent.mkdir(parents=True, exist_ok=True)
        trace_dir = self._trace_dir(job_id)
        trace_dir.mkdir(parents=True, exist_ok=True)
        command = self._command(request, seed, output, metadata, trace_dir)
        use_persistent = self.command_runner is None and request.trace_level in {"off", "basic"} and self.persistent_engine.available
        sampling_message = "正在使用常驻 CUDA 引擎生成" if use_persistent else "正在使用 CUDA 运行 stable-diffusion.cpp"
        if self._update_if_active(job_id, state="sampling", progress=24, message=sampling_message) is None:
            return
        stdout_log = Path(self.get(job_id)["stdoutLog"])
        stderr_log = Path(self.get(job_id)["stderrLog"])
        if self._is_cancelled(job_id):
            return
        result: NativeRunResult | None = None
        if use_persistent:
            result = self._run_persistent(job_id, request, seed, output, metadata, stdout_log, stderr_log)
        if result is None and not self._is_cancelled(job_id) and self.command_runner is not None:
            result = self._run_command_runner(job_id, command, self._environment(request), self.config.dream_root, stdout_log, stderr_log)
        elif result is None and not self._is_cancelled(job_id):
            result = self._run_process(job_id, command, self._environment(request), self.config.dream_root, stdout_log, stderr_log)
        if result is None or self._is_cancelled(job_id):
            return
        if result.returncode != 0:
            self._update_if_active(job_id, state="failed", progress=0, message="原生生成失败", error=result.stderr.strip() or result.stdout.strip() or "dream-core failed")
            return
        if self._update_if_active(job_id, state="decoding", progress=92, message="正在检查 PNG 和生成 metadata") is None:
            return
        if not output.exists() or not metadata.exists():
            self._update_if_active(job_id, state="failed", progress=0, message="原生生成未返回完整输出", error="PNG or metadata file is missing")
            return
        try:
            metadata_value = json.loads(metadata.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            self._update_if_active(job_id, state="failed", progress=0, message="生成 metadata 无效", error=str(exc))
            return
        if request.trace_level != "off":
            self._write_process_trace(job_id, request, output, metadata, metadata_value, result.stdout)

        self._update_if_active(
            job_id,
            state="complete",
            progress=100,
            message="生成完成",
            result={
                "id": job_id,
                "imageUrl": f"/api/history/{job_id}/image",
                "filePath": str(output),
                "metadataPath": str(metadata),
                "truth": "observed",
                "metadata": metadata_value,
            },
        )

    def _registered_model(self, model_id: str) -> dict[str, Any]:
        registry = json.loads(self.config.registry_path.read_text(encoding="utf-8-sig"))
        for model in registry.get("models", []):
            if model.get("model_id") == model_id or model_id in model.get("aliases", []):
                return model
        raise PersistentEngineUnavailable(f"model is missing from the registry: {model_id}")

    def _run_persistent(
        self,
        job_id: str,
        request: GenerateRequest,
        seed: int,
        output: Path,
        metadata: Path,
        stdout_log: Path,
        stderr_log: Path,
    ) -> NativeRunResult | None:
        try:
            model = self._registered_model(request.model_id)
            model_path = Path(str(model["windows"]["path"]))

            def register_native(native_job_id: str) -> None:
                with self._lock:
                    self._persistent_jobs[job_id] = native_job_id

            result = self.persistent_engine.generate(
                request,
                seed=seed,
                model_path=model_path,
                on_submitted=register_native,
                is_cancelled=lambda: self._is_cancelled(job_id),
            )
        except PersistentEngineUnavailable as exc:
            stderr_log.parent.mkdir(parents=True, exist_ok=True)
            stderr_log.write_text(f"persistent engine unavailable; falling back to CLI: {exc}\n", encoding="utf-8")
            return None
        except PersistentGenerationCancelled:
            return None
        except (PersistentEngineError, OSError, KeyError, json.JSONDecodeError) as exc:
            stderr_log.parent.mkdir(parents=True, exist_ok=True)
            stderr_log.write_text(str(exc), encoding="utf-8")
            return NativeRunResult(1, "", str(exc))
        finally:
            with self._lock:
                self._persistent_jobs.pop(job_id, None)

        if self._is_cancelled(job_id):
            return None
        output.write_bytes(result.image_bytes)
        total_time_ms = result.engine_wall_time_ms + result.postprocess_time_ms
        metadata_value = {
            "schema_version": 1,
            "model_id": str(model.get("model_id") or request.model_id),
            "model_path": str(model_path),
            "model_sha256": str(model.get("windows", {}).get("sha256") or ""),
            "architecture": str(model.get("architecture") or "unknown"),
            "dmd2": model.get("dmd2") or {"enabled": False},
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt,
            "seed": seed,
            "steps": request.steps,
            "cfg": request.cfg,
            "width": request.width,
            "height": request.height,
            "sampling_method": request.sampling_method,
            "scheduler": request.scheduler,
            "backend": "cuda",
            "execution_mode": "persistent-server",
            "persistent_server_job_id": result.native_job_id,
            "generation_time_ms": total_time_ms,
            "engine_wall_time_ms": result.engine_wall_time_ms,
            "postprocess_time_ms": result.postprocess_time_ms,
            "flash_attention": result.flash_attention,
            "output": str(output),
            "generated_at": datetime.now().astimezone().isoformat(),
        }
        metadata.write_text(json.dumps(metadata_value, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = json.dumps(
            {
                "ok": True,
                "execution_mode": "persistent-server",
                "native_job_id": result.native_job_id,
                "generation_time_ms": total_time_ms,
            },
            ensure_ascii=False,
        )
        stdout_log.parent.mkdir(parents=True, exist_ok=True)
        stdout_log.write_text(summary + "\n", encoding="utf-8")
        stderr_log.write_text("", encoding="utf-8")
        return NativeRunResult(0, summary, "")

    def _write_process_trace(
        self,
        job_id: str,
        request: GenerateRequest,
        output: Path,
        metadata: Path,
        metadata_value: dict[str, Any],
        native_stdout: str,
    ) -> None:
        generation_time_ms = int(metadata_value.get("generation_time_ms") or 0)
        if generation_time_ms <= 0:
            for line in reversed(native_stdout.splitlines()):
                try:
                    native_result = json.loads(line.strip())
                except json.JSONDecodeError:
                    continue
                if isinstance(native_result, dict):
                    generation_time_ms = int(native_result.get("generation_time_ms") or 0)
                    if generation_time_ms > 0:
                        break
        backend = str(metadata_value.get("backend") or "cuda").upper()
        events, wrapper_log_path = self._measured_phase_events(native_stdout)
        latent_preview_frames = self._latent_preview_frames(job_id, request)
        latent_telemetry = self._latent_telemetry(job_id, request)
        nodes = self._phase_nodes(events, request, backend) if events else [{
            "id": "native-generation",
            "name": "Native generation",
            "backend": backend,
            "shape": f"{request.width} × {request.height}",
            "observedCalls": 1,
            "durationMs": max(0, generation_time_ms),
            "status": "executed",
            "truth": "observed",
        }]
        evidence = {
            "modelId": request.model_id,
            "backend": backend,
            "outputPath": str(output),
            "metadataPath": str(metadata),
            "steps": request.steps,
            "cfg": request.cfg,
            "samplingMethod": request.sampling_method,
            "scheduler": request.scheduler,
            "peakVramMiB": metadata_value.get("peak_vram_mib"),
            "peakRamBytes": metadata_value.get("peak_ram_bytes"),
        }
        if wrapper_log_path is not None:
            evidence["wrapperLogPath"] = str(wrapper_log_path)
        trace = {
            "available": True,
            "runId": job_id,
            "totalTimeMs": max(0, generation_time_ms),
            "nodes": nodes,
            "events": events,
            "latentPreviewFrames": latent_preview_frames,
            "latentTelemetry": latent_telemetry,
            "evidence": evidence,
        }
        trace_path = self._trace_path(job_id)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")

    def _measured_phase_events(self, native_stdout: str) -> tuple[list[dict[str, Any]], Path | None]:
        wrapper_log_path: Path | None = None
        for line in reversed(native_stdout.splitlines()):
            try:
                native_result = json.loads(line.strip())
            except json.JSONDecodeError:
                continue
            if isinstance(native_result, dict) and native_result.get("wrapper_log"):
                candidate = Path(str(native_result["wrapper_log"]))
                if self.config.path_under_dream(candidate) and candidate.exists():
                    wrapper_log_path = candidate
                break
        if wrapper_log_path is None:
            return [], None
        try:
            log_text = wrapper_log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return [], None
        specs = [
            ("get_learned_condition completed, taking ([0-9]+(?:[.][0-9]+)?)s", "conditioning", "Conditioning"),
            ("sampling completed, taking ([0-9]+(?:[.][0-9]+)?)s", "unet_sampling", "UNet sampling"),
            ("decode_first_stage completed, taking ([0-9]+(?:[.][0-9]+)?)s", "vae_decode", "VAE decode"),
            ("generate_image completed in ([0-9]+(?:[.][0-9]+)?)s", "generate_image", "Image generation"),
        ]
        events: list[dict[str, Any]] = []
        for pattern, phase, label in specs:
            match = re.search(pattern, log_text)
            if match:
                events.append(
                    {
                        "phase": phase,
                        "label": label,
                        "durationMs": round(float(match.group(1)) * 1000),
                        "truth": "observed",
                    }
                )
        return events, wrapper_log_path

    def _latent_preview_frames(self, job_id: str, request: GenerateRequest) -> list[dict[str, Any]]:
        if request.trace_level not in {"h6", "h7"}:
            return []
        trace_dir = self._trace_dir(job_id)
        if not self.config.path_under_dream(trace_dir) or not trace_dir.exists():
            return []
        frames: list[dict[str, Any]] = []
        for path in sorted(trace_dir.glob("latent-step-*.png")):
            if not self.config.path_under_dream(path) or not path.is_file():
                continue
            match = re.fullmatch(r"latent-step-(\d{3,})\.png", path.name, re.IGNORECASE)
            if match is None:
                continue
            frames.append({
                "step": int(match.group(1)),
                "fileName": path.name,
                "truth": "observed",
                "kind": "latent-projection",
            })
        return frames

    def _latent_telemetry(self, job_id: str, request: GenerateRequest) -> list[dict[str, Any]]:
        if request.trace_level not in {"h6", "h7"}:
            return []
        trace_dir = self._trace_dir(job_id)
        metrics_path = trace_dir / "latent-metrics.jsonl"
        if not self.config.path_under_dream(metrics_path) or not metrics_path.is_file():
            return []
        samples: list[dict[str, Any]] = []
        try:
            lines = metrics_path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            return []
        for line in lines:
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            sample = self._validated_latent_sample(raw, trace_dir)
            if sample is not None:
                samples.append(sample)
        return sorted(samples, key=lambda item: item["step"])

    def _validated_latent_sample(self, raw: Any, trace_dir: Path) -> dict[str, Any] | None:
        if not isinstance(raw, dict) or raw.get("truth") != "observed" or raw.get("kind") != "latent-state":
            return None
        raw_shape = raw.get("shape")
        step = self._bounded_int(raw.get("step"), minimum=0, maximum=self.MAX_LATENT_STEP)
        if step is None or not isinstance(raw_shape, list):
            return None
        shape = [self._bounded_int(value, minimum=1, maximum=self.MAX_LATENT_DIMENSION) for value in raw_shape]
        if len(shape) < 2 or len(shape) > 4 or any(value is None for value in shape):
            return None
        validated_shape = [value for value in shape if value is not None]
        if not all(self._finite_number(raw.get(key)) for key in ("mean", "std", "l2")):
            return None
        channels_raw = raw.get("channels")
        channel_limit = min(16, validated_shape[2] if len(validated_shape) >= 3 else 1)
        if not isinstance(channels_raw, list) or not channels_raw or len(channels_raw) > channel_limit:
            return None
        channels: list[dict[str, Any]] = []
        for raw_channel in channels_raw:
            channel = self._validated_latent_channel(raw_channel, trace_dir, step)
            if channel is None:
                return None
            channels.append(channel)
        channel_ids = [channel["channel"] for channel in channels]
        if len(set(channel_ids)) != len(channel_ids) or any(channel >= channel_limit for channel in channel_ids):
            return None
        sample = {
            "step": step,
            "shape": validated_shape,
            "mean": float(raw["mean"]),
            "std": float(raw["std"]),
            "l2": float(raw["l2"]),
            "truth": "observed",
            "kind": "latent-state",
            "channels": channels,
        }
        for raw_key, public_key in (("delta_l2", "deltaL2"), ("delta_mean_abs", "deltaMeanAbs"), ("cosine", "cosine")):
            # Native JSONL uses snake_case; persisted/public traces use camelCase.
            # Preserve measured deltas (including zero) when reading a saved run.
            value = raw.get(raw_key, raw.get(public_key))
            sample[public_key] = float(value) if self._finite_number(value) else None
        if "channel_correlation" in raw or "channelCorrelation" in raw:
            channel_count = validated_shape[2] if len(validated_shape) >= 3 else 1
            if channel_count > 16 or sorted(channel_ids) != list(range(channel_count)):
                return None
            for key in ("correlation_method", "correlationMethod"):
                if key in raw and raw[key] != "pearson":
                    return None
            matrices = [self._validated_channel_correlation(raw[key], channel_count)
                        for key in ("channel_correlation", "channelCorrelation") if key in raw]
            if any(matrix is None for matrix in matrices) or any(matrix != matrices[0] for matrix in matrices):
                return None
            sample["channelCorrelation"] = matrices[0]
            sample["correlationMethod"] = "pearson"
        delta_names = [raw[key] for key in ("delta_file_name", "deltaFileName") if key in raw]
        if delta_names:
            name = delta_names[0]
            match = re.fullmatch(r"latent-step-(\d{3,})-delta\.png", name) if isinstance(name, str) else None
            if (match is None or self._bounded_int(match.group(1), minimum=0, maximum=self.MAX_LATENT_STEP) != step
                    or any(value != name for value in delta_names)):
                return None
            path = trace_dir / name
            if not self.config.path_under_dream(path) or not path.is_file():
                return None
            sample["deltaFileName"] = name
        return sample

    @staticmethod
    def _validated_channel_correlation(raw: Any, channels: int) -> list[list[float | None]] | None:
        if not isinstance(raw, list) or len(raw) != channels:
            return None
        matrix: list[list[float | None]] = []
        for row in raw:
            if not isinstance(row, list) or len(row) != channels:
                return None
            if any(value is not None and (type(value) not in (int, float)
                   or not JobRunner._finite_number(value) or not -1 <= value <= 1) for value in row):
                return None
            matrix.append([None if value is None else float(value) for value in row])
        for row in range(channels):
            diagonal = matrix[row][row]
            # Identity's float64 norm product can round a valid diagonal below one.
            if diagonal is not None and not math.isclose(diagonal, 1.0, rel_tol=0.0, abs_tol=1e-12):
                return None
            for column in range(channels):
                value = matrix[row][column]
                # Undefined variance invalidates the entire row/column, including its diagonal.
                undefined = diagonal is None or matrix[column][column] is None
                if (value is None) != undefined or value != matrix[column][row]:
                    return None
        return matrix

    def _validated_latent_channel(self, raw: Any, trace_dir: Path, step: int) -> dict[str, Any] | None:
        if not isinstance(raw, dict) or raw.get("truth", "observed") != "observed" or raw.get("kind", "latent-channel") != "latent-channel":
            return None
        raw_histogram = raw.get("histogram")
        channel = self._bounded_int(raw.get("channel"), minimum=0, maximum=15)
        if channel is None or not isinstance(raw_histogram, list):
            return None
        histogram = [self._bounded_int(value, minimum=0, maximum=self.MAX_HISTOGRAM_BIN) for value in raw_histogram]
        if len(histogram) != 32 or any(value is None for value in histogram):
            return None
        validated_histogram = [value for value in histogram if value is not None]
        file_name = str(raw.get("file_name") or raw.get("fileName") or "")
        if re.fullmatch(r"latent-step-(\d{3,})-ch(\d{1,2})\.png", file_name, re.IGNORECASE) is None:
            return None
        match = re.fullmatch(r"latent-step-(\d{3,})-ch(\d{1,2})\.png", file_name, re.IGNORECASE)
        file_step = self._bounded_int(match.group(1), minimum=0, maximum=self.MAX_LATENT_STEP) if match else None
        file_channel = self._bounded_int(match.group(2), minimum=0, maximum=15) if match else None
        if file_step != step or file_channel != channel:
            return None
        path = trace_dir / file_name
        if not self.config.path_under_dream(path) or not path.is_file():
            return None
        numeric = ("min", "max", "mean", "std", "l2")
        if not all(self._finite_number(raw.get(key)) for key in numeric):
            return None
        return {
            "channel": channel,
            "fileName": file_name,
            "min": float(raw["min"]),
            "max": float(raw["max"]),
            "mean": float(raw["mean"]),
            "std": float(raw["std"]),
            "l2": float(raw["l2"]),
            "histogram": validated_histogram,
            "truth": "observed",
            "kind": "latent-channel",
        }

    @staticmethod
    def _finite_number(value: Any) -> bool:
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError, OverflowError):
            return False

    @staticmethod
    def _bounded_int(value: Any, *, minimum: int, maximum: int) -> int | None:
        if isinstance(value, bool) or not JobRunner._finite_number(value):
            return None
        try:
            numeric = float(value)
            if not numeric.is_integer():
                return None
            integer = int(numeric)
        except (TypeError, ValueError, OverflowError):
            return None
        return integer if minimum <= integer <= maximum else None

    def _phase_nodes(self, events: list[dict[str, Any]], request: GenerateRequest, backend: str) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        for event in events:
            phase = event["phase"]
            node: dict[str, Any] = {
                "id": phase,
                "name": event["label"],
                "backend": backend,
                "durationMs": event["durationMs"],
                "status": "executed",
                "truth": event["truth"],
            }
            if phase == "conditioning":
                node["shape"] = "text conditioning"
            elif phase == "unet_sampling":
                node["shape"] = f"{request.width} × {request.height}"
                node["expectedCalls"] = request.steps
            elif phase == "vae_decode":
                node["shape"] = "latent → RGB"
            elif phase == "generate_image":
                node["shape"] = "PNG output"
            nodes.append(node)
        return nodes

    def _environment(self, request: GenerateRequest | None = None) -> dict[str, str]:
        env = os.environ.copy()
        engine = self.config.h7_engine_exe if request is not None and request.trace_level in {"h6", "h7"} else self.config.engine_exe
        env.update(
            {
                "DREAM_HOME": str(self.config.dream_root),
                "DREAM_MODEL_REGISTRY": str(self.config.registry_path),
                "DREAM_STABLE_DIFFUSION_CPP_EXE": str(engine),
                "DREAM_SDCPP_GENERATE_WRAPPER": str(self.config.wrapper),
            }
        )
        return env
