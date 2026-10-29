"""Bounded JSON-lines identity transport (no GPU imports at module load).

The child owns ONE IdentitySession or restore processor, ever. Incompatibility/error/EOF/60s idle
ends that process; parent release/cancel/close waits for exit before returning.
Main must serialize identity work with native work and register release as the
native before-run barrier. lifetime_factory must bind the owned process to the
parent (the service supplies WorkerLifetime). No request is retried after work
may have started. This module makes no inference-speed or quality claims.
"""
from __future__ import annotations

import gc
import hashlib
import json
import math
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from contextlib import redirect_stdout
from pathlib import Path

IDLE_TTL = 60.0
MAX_REQUEST = 256 * 1024
MAX_RESPONSE = 4 * 1024 * 1024
MAX_ASSET_FILES = 10000
MAX_BATCHES = 32
ASSET_KEYS = ("checkpoint", "adapter", "faceLora", "clipVision", "pipelineConfig", "insightfaceRoot", "lorasDir", "faceSwapModel", "faceRestoreModel", "faceDetectionRoot", "animeFaceDetector", "faceParsingModel")
PER_RENDER = {"prompt", "negativePrompt", "seed", "steps"}
OUTPUT_KEYS = {"jobId", "outputPath", "metadataPath"}


class WorkerRestartRequired(RuntimeError):
    """Validated request has not begun rendering; start a fresh process."""


class PersistentWorkerCancelled(RuntimeError):
    pass


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _file_hash(path):
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino):
        raise ValueError("Identity asset changed during verification")
    return digest.hexdigest()


def _asset(path):
    path = Path(path).resolve()
    if not path.exists():
        return {"path": str(path), "missing": True}
    if path.is_file():
        return {"path": str(path), "sha256": _file_hash(path)}
    entries = []
    visited = 0
    def scan_error(error):
        # An incomplete asset scan must never authorize a warm-session reuse.
        raise error
    for root, directories, files in os.walk(path, followlinks=False, onerror=scan_error):
        visited += 1 + len(files) + len(directories)
        if visited > MAX_ASSET_FILES:
            raise ValueError("Identity asset directory exceeds verification bound")
        for name in directories + files:
            entry = Path(root) / name
            if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
                raise ValueError("Linked identity asset entries are unsupported")
        for name in sorted(files):
            entry = Path(root) / name
            entries.append((entry.relative_to(path).as_posix(), _file_hash(entry)))
    return {"path": str(path), "entries": sorted(entries)}


def build_compatibility_key(config, request):
    """Rehash local bytes; never trust stale size/mtime-only fingerprints.

    Only prompt/negativePrompt/seed/steps and publication paths may vary. All
    other normalized contract fields and unknown future fields enter the key.
    Hashing large weights has a real I/O cost that needs measured evaluation.
    """
    from identity_contract import IdentityGenerateRequest
    from identity_pipeline import validate_batch_items
    items = request.get("items")
    validate_batch_items(items)
    fixed = []
    for item in items:
        normalized = IdentityGenerateRequest.model_validate({key: value for key, value in item.items() if key in IdentityGenerateRequest.model_fields}).model_dump()
        combined = {**item, **normalized}
        fixed.append({key: value for key, value in combined.items() if key not in PER_RENDER | OUTPUT_KEYS})
    if any(value != fixed[0] for value in fixed[1:]):
        raise ValueError("Batch fixed parameters differ")
    inputs = {key: _asset(config[key]) for key in ASSET_KEYS if config.get(key)}
    for key in ("imagePath", "animeImagePath", "animeFeaturesPath"):
        if items[0].get(key):
            path = Path(items[0][key])
            if not path.is_file():
                raise ValueError("Reference asset is missing")
            inputs[key] = _asset(path)
    if request.get("configPath"):
        inputs["runtimeConfig"] = _asset(request["configPath"])
    controls = {key: value for key, value in request.items() if key not in {"items", "eventPath", "previewDir"}}
    return hashlib.sha256(_json({"version": 1, "config": config, "inputs": inputs, "fixed": fixed[0], "controls": controls})).hexdigest()


def _reset_cuda_peaks():
    # Called only after an actual IdentitySession was successfully initialized.
    import torch
    torch.cuda.reset_peak_memory_stats()


def _load_identity_session():
    # Resolve the constructor's native/lazy imports before announcing CUDA
    # initialization. Imports only: no model load or CUDA allocation here.
    import torch
    from safetensors.torch import load_file
    from diffusers import EulerDiscreteScheduler
    from diffusers.models.embeddings import MultiIPAdapterImageProjection
    from identity_pipeline import IdentitySession
    return IdentitySession


class WarmBatchWorker:
    def __init__(self, config_loader, *, session_factory=None, reset_metrics=None):
        self.config_loader = config_loader
        self.session_factory = session_factory
        self.reset_metrics = reset_metrics or _reset_cuda_peaks
        self.session = None
        self.key = None
        self.closed = False
        self.completed_batches = 0

    def close(self):
        self.closed = True
        self.session = None
        gc.collect()

    def run_batch(self, request):
        if self.closed:
            raise RuntimeError("Identity worker is closed")
        try:
            from identity_events import emit_event
            started = time.perf_counter()
            def emit(event):
                emit_event(request.get("eventPath"), {**event, "elapsedMs": round((time.perf_counter() - started) * 1000)})
            emit({"type": "stage", "stage": "校验模型与参考文件"})
            config = self.config_loader(request)
            key = build_compatibility_key(config, request)
            if self.session is not None and (key != self.key or self.completed_batches >= MAX_BATCHES):
                raise WorkerRestartRequired("A fresh identity session is required")
            interval = request.get("previewEvery", 0)
            if type(interval) is not int or interval not in (0, 5, 10):
                raise ValueError("Invalid preview interval")
            for item in request["items"]:
                if any(Path(item[name]).exists() for name in OUTPUT_KEYS - {"jobId"}):
                    raise ValueError("Output already exists")
            reused = self.session is not None
            if not reused:
                factory = self.session_factory
                if factory is None:
                    emit({"type": "stage", "stage": "导入推理组件"})
                    factory = _load_identity_session()
                emit({"type": "stage", "stage": "初始化 CUDA 与身份会话"})
                self.session = factory(config, {**request["items"][0], "forceFingerprint": True}, emit)
                self.key = key
            else:
                # Session.render uses these for the first item in each batch.
                # Preserve local itemIndex while excluding previous load/idle time.
                self.session.started = time.perf_counter()
                self.session.initial_stages = []
                self.reset_metrics()
            results = []
            for index, item in enumerate(request["items"]):
                result = self.session.render(item, index, emit, request.get("previewDir"), interval)
                if not Path(item["outputPath"]).is_file() or not Path(item["metadataPath"]).is_file():
                    raise RuntimeError("Identity output publication incomplete")
                # Distinct from modelReused (which records reuse within a batch).
                # Add provenance before emitting item_complete, preserving the
                # existing journal's publication ordering and local item indices.
                metadata = result.get("metadata")
                if not isinstance(metadata, dict):
                    raise ValueError("Identity metadata missing")
                metadata["sessionReused"] = reused
                target = Path(item["metadataPath"])
                temporary = target.with_suffix(".session.tmp")
                temporary.write_bytes(_json(metadata))
                os.replace(temporary, target)
                results.append(result)
                emit({"type": "item_complete", "itemIndex": index, "jobId": item["jobId"]})
            self.completed_batches += 1
            return {"ok": True, "items": results, "sessionReused": reused}
        except BaseException:
            self.close()
            raise


def _reader(stream, inbox, limit, stop, *, single=False):
    def deliver(line):
        while not stop.is_set():
            try:
                inbox.put(line, timeout=.05)
                return
            except queue.Full:
                continue
    try:
        while not stop.is_set():
            line = stream.readline(limit + 1)
            deliver(line)
            if single or not line or len(line) > limit:
                return
    except (OSError, ValueError):
        deliver(b"")


def serve(worker, source, target, *, idle_ttl=IDLE_TTL, ownership_handshake=False, operation='batch'):
    if operation not in ('batch', 'refine'):
        raise ValueError('Unsupported worker operation')
    if not math.isfinite(idle_ttl) or not 0 < idle_ttl <= IDLE_TTL:
        raise ValueError("Idle TTL must be positive and at most 60 seconds")
    inbox = queue.Queue(maxsize=1)
    stop = threading.Event()
    try:
        if ownership_handshake:
            # Standard-library code only. No request, model imports or CUDA
            # initialization until the parent has bound this actual interpreter.
            target.write(_json({"type": "worker_ready", "protocol": 1, "pid": os.getpid()}) + b"\n")
            target.flush()
        while True:
            # Never read ahead while initializing/running the session. On
            # Windows a blocked stdin read owns the CRT descriptor lock;
            # native imports that duplicate stdin (including torch) then hang.
            reader = threading.Thread(target=_reader, args=(source, inbox, MAX_REQUEST, stop),
                                      kwargs={"single": True}, daemon=True)
            reader.start()
            try:
                line = inbox.get(timeout=idle_ttl)
            except queue.Empty:
                return 0
            reader.join()  # Release the descriptor lock BEFORE native imports.
            if not line:
                return 0
            request_id = None
            try:
                if len(line) > MAX_REQUEST or not line.endswith(b"\n"):
                    raise ValueError("Invalid request frame")
                message = json.loads(line)
                if not isinstance(message, dict) or not isinstance(message.get("id"), str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", message["id"]):
                    raise ValueError("Invalid request id")
                request_id = message["id"]
                if message.get("op") == "close":
                    return 0
                if message.get("op") != operation or not isinstance(message.get("payload"), dict):
                    raise ValueError("Unsupported operation")
                # Pipeline/library progress cannot contaminate the JSON channel.
                with redirect_stdout(sys.stderr):
                    result = (worker.run_batch if operation == 'batch' else worker.run_refine)(message["payload"])
                reply = {"id": request_id, "ok": True, "result": result}
                code = 0
            except Exception as exc:
                reply = {"id": request_id, "ok": False, "code": "RESTART_REQUIRED" if isinstance(exc, WorkerRestartRequired) else "IDENTITY_WORKER_FAILED"}
                code = 1
            encoded = _json(reply) + b"\n"
            if len(encoded) > MAX_RESPONSE:
                encoded = _json({"id": request_id, "ok": False, "code": "IDENTITY_RESPONSE_TOO_LARGE"}) + b"\n"
                code = 1
            target.write(encoded)
            target.flush()
            if code:
                return code
    finally:
        stop.set()
        worker.close()


class PersistentWorkerClient:
    """One owned child; callers use the shared executor, not concurrent sends."""
    def __init__(self, command, *, cwd, env, lifetime_factory, stderr=None, ownership_handshake=False):
        self.command, self.cwd, self.env = command, cwd, env
        self.lifetime_factory = lifetime_factory
        self.stderr = stderr if stderr is not None else subprocess.DEVNULL
        self._state = threading.RLock()
        self._request = threading.Lock()
        self._process = self._lifetime = self._responses = None
        self._reader_stop = self._reader_thread = self._writer_thread = None
        self._closed = False
        self._epoch = 0
        self._ownership_handshake = ownership_handshake
        self._ownership_confirmed = False

    @property
    def process(self):
        with self._state:
            return self._process

    def _release(self):
        process = self._process
        if process is None:
            return
        tree_barrier = getattr(self._lifetime, "terminate_and_wait", None)
        if tree_barrier is not None:
            tree_barrier()
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        # If wait fails, retain ownership and fail the native before-run barrier.
        if self._lifetime is not None and tree_barrier is None:
            self._lifetime.close()
        if self._reader_stop is not None:
            self._reader_stop.set()
        for thread in (self._reader_thread, self._writer_thread):
            if thread is not None:
                thread.join(timeout=1)
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        self._process = self._lifetime = self._responses = None
        self._reader_stop = self._reader_thread = self._writer_thread = None
        self._ownership_confirmed = False

    def release(self):
        with self._state:
            self._epoch += 1
            self._release()

    def cancel(self):
        self.release()

    def close(self):
        with self._state:
            self._closed = True
            self._release()

    def _start(self, epoch):
        with self._state:
            if self._closed or epoch != self._epoch:
                raise PersistentWorkerCancelled("Identity transport is closed")
            if self._process is not None and self._process.poll() is not None:
                self._release()
            if self._process is None:
                self._process = subprocess.Popen(self.command, cwd=str(self.cwd), env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    self._lifetime = self.lifetime_factory(self._process)
                    self._responses = queue.Queue(maxsize=1)
                    self._reader_stop = threading.Event()
                    self._reader_thread = threading.Thread(target=_reader, args=(self._process.stdout, self._responses, MAX_RESPONSE, self._reader_stop), daemon=True)
                    self._reader_thread.start()
                except BaseException:
                    self._release()
                    raise
            return self._process, self._responses

    def _check_wait(self, process, cancelled, deadline, on_poll):
        if cancelled is not None and cancelled.is_set():
            raise PersistentWorkerCancelled("Identity request cancelled")
        if self.process is not process:
            raise PersistentWorkerCancelled("Identity worker released")
        if time.monotonic() >= deadline:
            raise RuntimeError("Identity worker timed out")
        if on_poll is not None:
            on_poll()

    def _confirm_ownership(self, process, responses, cancelled, deadline, on_poll):
        if not self._ownership_handshake or self._ownership_confirmed:
            return
        deadline = min(deadline, time.monotonic() + 15)
        while True:
            self._check_wait(process, cancelled, deadline, on_poll)
            try:
                line = responses.get(timeout=.05)
                break
            except queue.Empty:
                continue
        try:
            if len(line) > 1024 or not line.endswith(b"\n"):
                raise ValueError()
            ready = json.loads(line)
            if (not isinstance(ready, dict) or ready.get("type") != "worker_ready" or
                    type(ready.get("protocol")) is not int or ready["protocol"] != 1 or
                    type(ready.get("pid")) is not int or ready["pid"] <= 0):
                raise ValueError()
        except (ValueError, TypeError):
            raise RuntimeError("Identity worker ownership handshake failed") from None
        with self._state:
            self._check_wait(process, cancelled, deadline, None)
            self._lifetime.confirm_worker(ready["pid"])
            self._ownership_confirmed = True

    def run_batch(self, payload, *, cancelled=None, timeout=900, on_poll=None):
        return self.run_operation('batch', payload, cancelled=cancelled, timeout=timeout, on_poll=on_poll)

    def run_operation(self, operation, payload, *, cancelled=None, timeout=900, on_poll=None):
        if operation not in ('batch', 'refine'):
            raise ValueError('Unsupported worker operation')
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Invalid worker timeout")
        if not self._request.acquire(blocking=False):
            raise RuntimeError("Identity worker is busy")
        try:
            with self._state:
                epoch = self._epoch
            for attempt in range(2):
                if cancelled is not None and cancelled.is_set():
                    raise PersistentWorkerCancelled("Identity request cancelled")
                identifier = uuid.uuid4().hex
                data = _json({"id": identifier, "op": operation, "payload": payload}) + b"\n"
                if len(data) > MAX_REQUEST:
                    raise ValueError("Identity request too large")
                process, responses = self._start(epoch)
                deadline = time.monotonic() + timeout
                self._confirm_ownership(process, responses, cancelled, deadline, on_poll)
                written = threading.Event()
                write_errors = []
                def write_request():
                    try:
                        process.stdin.write(data)
                        process.stdin.flush()
                    except (OSError, ValueError) as exc:
                        write_errors.append(type(exc).__name__)
                    finally:
                        written.set()
                with self._state:
                    self._writer_thread = threading.Thread(target=write_request, daemon=True)
                    self._writer_thread.start()
                while not written.wait(.05):
                    self._check_wait(process, cancelled, deadline, on_poll)
                if write_errors:
                    raise RuntimeError("Identity worker protocol write failed")
                while True:
                    self._check_wait(process, cancelled, deadline, on_poll)
                    try:
                        line = responses.get(timeout=.05)
                        break
                    except queue.Empty:
                        continue
                if cancelled is not None and cancelled.is_set():
                    raise PersistentWorkerCancelled("Identity request cancelled")
                try:
                    if len(line) > MAX_RESPONSE or not line.endswith(b"\n"):
                        raise ValueError()
                    response = json.loads(line)
                    if not isinstance(response, dict) or response.get("id") != identifier or type(response.get("ok")) is not bool:
                        raise ValueError()
                except (ValueError, TypeError):
                    raise RuntimeError("Identity worker protocol failed") from None
                if response["ok"] is False:
                    with self._state:
                        self._release()
                    if response.get("code") == "RESTART_REQUIRED" and attempt == 0:
                        continue  # Child guarantees this is before any render.
                    raise RuntimeError("Identity worker failed")
                result = response.get("result")
                if not isinstance(result, dict) or result.get("ok") is not True:
                    raise RuntimeError("Identity worker protocol failed")
                return result
        except BaseException:
            self.release()
            raise
        finally:
            self._request.release()
