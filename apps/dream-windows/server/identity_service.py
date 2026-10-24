"""Identity storage and subprocess boundary; deliberately no inference imports."""
from __future__ import annotations

import base64
import binascii
import copy
import io
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import CancelledError, Future
from contextlib import contextmanager
from datetime import date, datetime
from functools import wraps
from pathlib import Path
from typing import Annotated, Any, Literal

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from config import DreamServerConfig
from errors import DreamApiError
from identity_contract import IdentityGenerateRequest
from identity_models import (is_visual_model_id, visual_restore_model,
                             ILLUSTRIOUS_VISUAL_MODEL_ID, require_identity_model_enabled)
from identity_persistent_worker import PersistentWorkerClient, PersistentWorkerCancelled
from identity_stage_artifacts import cleanup_visual_stages, validate_visual_stage, visual_stage_url
from job_runner import JobRunner


MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
MAX_BASE64 = 4 * ((MAX_IMAGE_BYTES + 2) // 3)
REFERENCE_PATTERN = r"ref-[0-9a-f]{24}"
JOB_PATTERN = r"identity-[0-9a-f]{24}"
TERMINAL = {"complete", "failed", "cancelled"}


def request_reference_kind(request: IdentityGenerateRequest) -> Literal["faceid", "visual"]:
    return "visual" if is_visual_model_id(request.modelId) else "faceid"


class ReferenceUpload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=255)
    imageBase64: str
    referenceKind: Literal["faceid", "visual"] = "faceid"


class Face(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    index: int = Field(ge=0)
    box: list[float] = Field(min_length=4, max_length=4)

    @field_validator("box")
    @classmethod
    def valid_box(cls, box: list[float]) -> list[float]:
        if min(box) < 0 or box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError("Invalid face box")
        return box


class WorkerCancelled(Exception):
    pass


class AnimeBinding(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    id: str = Field(pattern=r'^anime-[a-f0-9]{24}$')
    name: str = Field(min_length=1,max_length=120)
    featureKey: str = Field(pattern=r'^[a-f0-9]{64}$')


class VisualPolishPass(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    kind: Literal['harmonize', 'detail']
    denoiseStrength: float = Field(ge=.15, le=.65)
    steps: int = Field(ge=1)
    durationMs: int = Field(ge=0)


class VisualPolishSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal['anchor', 'harmonize', 'detail']
    imageUrl: str


class FacePolishMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    enabled: bool
    status: Literal["disabled", "completed", "failed"]
    originalImageUrl: str | None = None
    message: str | None = None
    restoreStrength: float | None = Field(default=None, ge=0, le=1)
    # Optional on older saved results; validate and retain current engine details.
    durationMs: int | None = Field(default=None, ge=0)
    swapModel: str | None = None
    restoreModel: str | None = None
    swapDevice: str | None = None
    restoreDevice: str | None = None
    assetHashes: dict[str, Annotated[str, Field(pattern=r"^[0-9a-fA-F]+$")]] | None = None
    method: Literal['anime-reference-local-redraw', 'visual-reference-local-redraw'] | None = None
    referenceId: str | None = Field(default=None, pattern=rf'^{REFERENCE_PATTERN}$')
    faceIndex: int | None = Field(default=None, ge=0, le=19)
    profileId: str | None = Field(default=None, pattern=r'^anime-[a-f0-9]{24}$')
    profileName: str | None = None
    featureKey: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    faceBox: list[float] | None = Field(default=None,min_length=4,max_length=4)
    cropBox: list[int] | None = Field(default=None,min_length=4,max_length=4)
    denoiseStrength: float | None = Field(default=None,ge=.15,le=.65)
    outsideMaskUnchanged: bool | None = None
    detailerVersion: Literal['masked-face-v1', 'staged-face-v2', 'protected-face-v3'] | None = None
    featureProtection: Literal['central-features-v1'] | None = None
    polishMode: Literal['redraw', 'reference-anchor'] | None = None
    passes: list[VisualPolishPass] | None = Field(default=None, min_length=1, max_length=2)
    anchorStrength: float | None = Field(default=None, ge=.3, le=1)
    # Geometric fit normalized by eye distance, never identity similarity.
    alignmentError: float | None = Field(default=None, ge=0, le=.18)
    snapshots: list[VisualPolishSnapshot] | None = Field(default=None, min_length=1, max_length=3)
    processingSize: list[Annotated[int, Field(ge=128, le=768, multiple_of=8)]] | None = Field(default=None, min_length=2, max_length=2)
    detailPrompt: str | None = Field(default=None, max_length=2000)
    detailNegativePrompt: str | None = Field(default=None, max_length=2000)


class StorageOwnerLease:
    """Process-lifetime OS lock; never unlink the file or inherit its handle."""

    def __init__(self, path: Path):
        self.path = path
        self._fd: int | None = None

    def acquire(self) -> None:
        if self._fd is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.set_inheritable(fd, False)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            raise DreamApiError("IDENTITY_STORAGE_BUSY", "人物数据正在被另一个服务实例占用，请关闭该实例后重试", status_code=503) from exc
        self._fd = fd

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


def owned_operation(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._operation():
            return method(self, *args, **kwargs)
    return guarded


class WorkerLifetime:
    """Bind owned Windows children to a non-inherited kill-on-close Job Object.

    Windows closes this handle even if the web process crashes, so a face
    worker cannot continue holding CUDA after restart. A startup PID is accepted
    only after checking its live handle, parent and creation time against the
    owned launcher. No process-name lookup or external-process termination.
    """

    def __init__(self, process: subprocess.Popen, *, awaiting_worker=False):
        self.handle = None
        self.process = process
        self._confirmed = {}
        self._tree_handles = {}
        self._awaiting_worker = awaiting_worker
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong), ("flags", wintypes.DWORD), ("min_working", ctypes.c_size_t), ("max_working", ctypes.c_size_t), ("active", wintypes.DWORD), ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("basic", BasicLimits), ("io", ctypes.c_ulonglong * 6), ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        for name, arguments, result in (
            ('TerminateJobObject', [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            ('QueryInformationJobObject', [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
            ('OpenProcess', [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            ('IsProcessInJob', [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)], wintypes.BOOL),
            ('GetProcessTimes', [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4, wintypes.BOOL),
            ('WaitForSingleObject', [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            ('TerminateProcess', [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        ):
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = arguments, result
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not awaiting_worker and not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
                error = ctypes.get_last_error()
                if process.poll() is None:
                    raise ctypes.WinError(error)
        except BaseException:
            self.close()
            raise

    def _parent_pid(self, pid):
        import ctypes
        from ctypes import wintypes
        class Entry(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD),
                        ('pid', wintypes.DWORD), ('heap', ctypes.c_size_t),
                        ('module', wintypes.DWORD), ('threads', wintypes.DWORD),
                        ('parent', wintypes.DWORD), ('priority', wintypes.LONG),
                        ('flags', wintypes.DWORD), ('exe', wintypes.WCHAR * 260)]
        self.kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        for name in ('Process32FirstW', 'Process32NextW'):
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = [wintypes.HANDLE, ctypes.POINTER(Entry)], wintypes.BOOL
        snapshot = self.kernel.CreateToolhelp32Snapshot(2, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = Entry()
            entry.size = ctypes.sizeof(entry)
            available = self.kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            while available:
                if entry.pid == pid:
                    return entry.parent
                available = self.kernel.Process32NextW(snapshot, ctypes.byref(entry))
            raise RuntimeError('Worker is not a live owned child')
        finally:
            self.kernel.CloseHandle(snapshot)

    def _created(self, handle):
        import ctypes
        from ctypes import wintypes
        times = [wintypes.FILETIME() for _ in range(4)]
        if not self.kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
            raise ctypes.WinError(ctypes.get_last_error())
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime

    def _in_job(self, handle):
        import ctypes
        from ctypes import wintypes
        member = wintypes.BOOL()
        if not self.kernel.IsProcessInJob(handle, self.handle, ctypes.byref(member)):
            raise ctypes.WinError(ctypes.get_last_error())
        return bool(member.value)

    def confirm_worker(self, pid):
        """Pin and bind the actual interpreter before it receives any batch."""
        if type(pid) is not int or pid <= 0 or self.process.poll() is not None:
            raise ValueError('Invalid worker ownership handshake')
        if os.name != 'nt':
            if pid != self.process.pid:
                raise ValueError('Worker PID is not owned')
            return
        import ctypes
        if self.handle is None:
            raise RuntimeError('Worker ownership is closed')
        if pid == self.process.pid:
            if self._awaiting_worker:
                if not self.kernel.AssignProcessToJobObject(self.handle, int(self.process._handle)):
                    raise ctypes.WinError(ctypes.get_last_error())
            if not self._in_job(int(self.process._handle)):
                raise RuntimeError('Launcher is not in the owned job')
            self._awaiting_worker = False
            return
        # PROCESS_SET_QUOTA | TERMINATE | QUERY_LIMITED_INFORMATION | SYNCHRONIZE.
        handle = self.kernel.OpenProcess(0x101101, False, pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        owned = False
        try:
            if (self._parent_pid(pid) != self.process.pid or
                    self._created(handle) < self._created(int(self.process._handle)) or
                    self.kernel.WaitForSingleObject(handle, 0) != 258 or self.process.poll() is not None):
                raise ValueError('Worker PID is not an owned live interpreter')
            # Retain the verified handle even if assignment fails, so cleanup
            # can safely reap this child without rediscovering/reusing its PID.
            self._confirmed[pid] = handle
            owned = True
            if not self._in_job(handle):
                if not self.kernel.AssignProcessToJobObject(self.handle, handle):
                    raise ctypes.WinError(ctypes.get_last_error())
            if not self._in_job(handle):
                raise RuntimeError('Worker job assignment was not confirmed')
            self._awaiting_worker = False
        finally:
            if not owned:
                self.kernel.CloseHandle(handle)

    def active_processes(self):
        import ctypes
        from ctypes import wintypes
        class Accounting(ctypes.Structure):
            _fields_ = [('times', ctypes.c_longlong * 4), ('faults', wintypes.DWORD),
                        ('total', wintypes.DWORD), ('active', wintypes.DWORD), ('terminated', wintypes.DWORD)]
        info = Accounting()
        if not self.kernel.QueryInformationJobObject(self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return info.active

    def _pin_job_processes(self):
        """Hold process objects through termination (ActiveProcesses can reach
        zero before every terminating process object becomes signalled)."""
        import ctypes
        from ctypes import wintypes
        capacity = 16
        while capacity <= 16384:
            class ProcessList(ctypes.Structure):
                _fields_ = [('assigned', wintypes.DWORD), ('count', wintypes.DWORD),
                            ('pids', ctypes.c_size_t * capacity)]
            listing = ProcessList()
            if self.kernel.QueryInformationJobObject(self.handle, 3, ctypes.byref(listing), ctypes.sizeof(listing), None):
                break
            if ctypes.get_last_error() != 234:  # ERROR_MORE_DATA
                raise ctypes.WinError(ctypes.get_last_error())
            capacity *= 2
        else:
            raise RuntimeError('Owned worker process tree exceeds release bound')
        for pid in listing.pids[:listing.count]:
            if pid in self._tree_handles:
                continue
            handle = self.kernel.OpenProcess(0x101001, False, pid)
            if not handle:
                if ctypes.get_last_error() == 87:  # Process already gone.
                    continue
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not self._in_job(handle):
                    # A concurrent exit/PID reuse must never authorize killing
                    # the new process. A still-live unknown handle fails closed.
                    if self.kernel.WaitForSingleObject(handle, 0) != 0:
                        raise RuntimeError('Owned process changed during release')
                    continue
                self._tree_handles[pid] = handle
                handle = None
            finally:
                if handle is not None:
                    self.kernel.CloseHandle(handle)

    def close(self, *, timeout=5.) -> None:
        if self.handle is None:
            return
        import ctypes
        import math
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Invalid worker release timeout')
        self._pin_job_processes()
        unbound = [handle for handle in self._confirmed.values()
                   if self.kernel.WaitForSingleObject(handle, 0) == 258 and not self._in_job(handle)]
        # Keep every handle on error. Native before_run must fail closed and a
        # later release may retry, even if the launcher has already exited.
        if not self.kernel.TerminateJobObject(self.handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())
        # The persistent venv launcher is deliberately outside the worker job.
        # Pin its descendants first, then reap this owned launcher as well.
        if self.process.poll() is None and not self._in_job(int(self.process._handle)):
            self.process.terminate()
        for handle in unbound:
            if not self.kernel.TerminateProcess(handle, 1):
                error = ctypes.get_last_error()
                # A venv launcher's own kill-on-close job can already be
                # terminating this pinned child. Still require observed exit.
                if error != 5 or self.kernel.WaitForSingleObject(handle, max(1, int(timeout * 1000))) != 0:
                    raise ctypes.WinError(error)
        deadline = time.monotonic() + timeout
        while True:
            active = self.active_processes()
            states = [self.kernel.WaitForSingleObject(handle, 0)
                      for handle in [int(self.process._handle), *self._confirmed.values(), *self._tree_handles.values()]]
            if any(state not in (0, 258) for state in states):
                raise RuntimeError('Cannot confirm owned interpreter exit')
            if active == 0 and all(state == 0 for state in states):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('Owned worker process tree did not exit')
            time.sleep(.01)
        if not self.kernel.CloseHandle(self.handle):
            raise ctypes.WinError(ctypes.get_last_error())
        self.handle = None
        for handle in [*self._confirmed.values(), *self._tree_handles.values()]:
            self.kernel.CloseHandle(handle)
        self._confirmed.clear()
        self._tree_handles.clear()

    def terminate_and_wait(self):
        """Transport release barrier, before terminating a venv launcher."""
        self.close()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_json(path: Path, limit: int = 2 * 1024 * 1024) -> dict[str, Any]:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("人物任务 JSON 超过大小限制")
    value = json.loads(data.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("人物任务 JSON 必须包含对象")
    return value


class IdentityService:
    def __init__(self, config: DreamServerConfig, job_runner: JobRunner):
        self.config = config
        self.job_runner = job_runner
        self.root = config.dream_root / "data" / "identity"
        self.config_path = Path(os.environ.get("DREAM_IDENTITY_CONFIG") or "E:/Dream/data/identity/runtime.json")
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._futures: dict[str, Future] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._recovered = False
        self._lease = StorageOwnerLease(self.root / "owner.lock")
        self._condition = threading.Condition(self._lock)
        self._active_operations = 0
        self._worker_events: set[threading.Event] = set()
        self._inspect_futures: set[Future] = set()
        self._closing = False
        self._closed = False
        self._background: dict[str, tuple[Future, threading.Event, Any]] = {}
        from identity_profiles import IdentityProfiles
        self.profiles = IdentityProfiles(self)
        from identity_anime_profiles import AnimeProfiles
        self.anime_profiles = AnimeProfiles(self)
        from identity_batches import IdentityBatches
        self.batches = IdentityBatches(self)
        self._event_callbacks = {}
        self._persistent_lock = threading.RLock()
        self._persistent_worker = None
        self._persistent_settings = None
        self._persistent_log = None
        self._has_native_barrier = hasattr(job_runner, "add_before_run")
        if self._has_native_barrier:
            job_runner.add_before_run(self.release_warm_worker)

    def release_warm_worker(self) -> None:
        """Release barrier used by native generation, extraction, and shutdown."""
        with self._persistent_lock:
            if self._persistent_worker is not None:
                self._persistent_worker.close()
                self._persistent_worker = None
            self._persistent_settings = None
            if self._persistent_log is not None:
                self._persistent_log.close()
                self._persistent_log = None

    def _persistent_batch(self, settings, payload, cancelled, consume_events):
        if not self._has_native_barrier:
            raise RuntimeError("Persistent identity requires a native release barrier")
        signature = json.dumps(settings, sort_keys=True, allow_nan=False)
        with self._persistent_lock:
            self._require_open()
            if self._persistent_worker is not None and signature != self._persistent_settings:
                self.release_warm_worker()
            if self._persistent_worker is None:
                python = settings.get("python") or sys.executable
                hub = self._safe(self.config.dream_root / "cache/identity-hub")
                temporary = self._safe(self.config.dream_root / "temp")
                logs = self._safe(self.config.dream_root / "logs/identity")
                for folder in (hub, temporary, logs):
                    folder.mkdir(parents=True, exist_ok=True)
                env = os.environ.copy()
                env.update(DREAM_IDENTITY_CONFIG=str(self.config_path), PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HOME=str(hub), TEMP=str(temporary), TMP=str(temporary))
                self._persistent_log = (logs / f"persistent-{secrets.token_hex(8)}.err.log").open("ab")
                self._persistent_worker = PersistentWorkerClient(
                    [python, str(Path(__file__).with_name("identity_worker.py")), "--ownership-handshake", "--persistent"],
                    # Leave this job empty until the actual interpreter's hello.
                    # A venv launcher may already own a nested job for its child;
                    # an empty job can join that hierarchy without a bind race.
                    cwd=self.config.dream_root, env=env,
                    lifetime_factory=lambda process: WorkerLifetime(process, awaiting_worker=True),
                    stderr=self._persistent_log,
                    ownership_handshake=True,
                )
                self._persistent_settings = signature
            worker = self._persistent_worker
        return worker.run_batch(payload, cancelled=cancelled, timeout=900 * len(payload["items"]), on_poll=consume_events)

    def _submit_background(self, task_id, execute, cancel_queued):
        # Called under the same lock as the entity's initial persistence.
        self._require_open()
        cancelled = threading.Event()
        future = self.job_runner.submit_serial(execute, cancelled)
        self._background[task_id] = (future, cancelled, cancel_queued)
        return future

    def _validate_face(self, reference_id, face_index, reference_kind="faceid"):
        reference = self.reference(reference_id)
        if reference_kind == "faceid" and reference.get("referenceKind", "faceid") == "visual":
            raise DreamApiError("IDENTITY_REFERENCE_KIND_CONFLICT", "视觉参考图不能用于 FaceID，请选择视觉参考模型或重新上传真人参考图", status_code=422)
        if face_index not in {face["index"] for face in reference["faces"]}:
            raise DreamApiError("IDENTITY_FACE_INVALID", "所选人脸不在当前参考图中，请重新选择人脸", status_code=422)
        return reference

    @owned_operation
    def profile_operation(self, method, *args):
        with self._lock:
            self._require_open()
            return getattr(self.profiles, method)(*args)

    @owned_operation
    def anime_profile_operation(self, method, *args):
        with self._lock:
            self._require_open()
            return getattr(self.anime_profiles, method)(*args)

    def bind_anime_dispatch(self, job_id, payload):
        profile = payload.get('animeProfile')
        if profile is not None:
            binding = AnimeBinding.model_validate({k:profile[k] for k in AnimeBinding.model_fields}).model_dump()
            self._update(job_id,animeBinding=binding)

    @owned_operation
    def batch_operation(self, method, *args):
        if method == 'submit':
            self._require_model_enabled(args[0].request.modelId)
            self._require_visual_polish_ready(args[0].request.model_dump())
        elif method == 'retry':
            request = self.batches.get(args[0])['request']['request']
            self._require_model_enabled(request['modelId'])
        # Batch cancellation waits outside the lock for worker finalization.
        return getattr(self.batches, method)(*args)

    def _require_visual_polish_ready(self, request):
        if not request.get('facePolish') or request.get('visualPolishMode', 'redraw') != 'reference-anchor':
            return
        # Status uses the configured worker Python, which may have different
        # packages from the controller. It checks files/specs without GPU work.
        status = self.status()
        visual = status.get('visualPolish', {})
        if visual.get('referenceAnchorReady') is not True:
            message = visual.get('referenceAnchorMessage') or status.get('message') or '参考脸对齐组件未就绪'
            raise DreamApiError('IDENTITY_REFERENCE_ANCHOR_NOT_READY', message, status_code=422)

    def _require_model_enabled(self, model_id):
        if model_id != ILLUSTRIOUS_VISUAL_MODEL_ID:
            return
        try:
            settings = read_json(self.config_path, 64 * 1024)
        except (OSError, ValueError):
            settings = {}  # Missing or unreadable runtime cannot grant an opt-in.
        try:
            require_identity_model_enabled(settings, model_id)
        except ValueError as exc:
            raise DreamApiError('IDENTITY_EXPERIMENTAL_MODEL_DISABLED', str(exc), status_code=422) from exc

    def _require_open(self) -> None:
        if self._closing or self._closed:
            raise DreamApiError("IDENTITY_SERVICE_CLOSED", "人物服务正在关闭，请稍后重试", status_code=503)

    @contextmanager
    def _operation(self):
        with self._condition:
            self._ensure_recovered()
            self._active_operations += 1
        try:
            yield
        finally:
            with self._condition:
                self._active_operations -= 1
                self._condition.notify_all()

    def close(self) -> None:
        import logging

        # Retain ownership through cancellation, child exit and final writes.
        # This does not shut down the shared native executor or resident engine.
        errors: list[tuple[str, Exception]] = []
        with self._condition:
            if self._closing:
                self._condition.wait_for(lambda: self._closed)
                return
            self._closing = True
            futures = list(self._futures.items())
            background = list(self._background.items())
        try:
            with self._condition:
                for event in [*self._cancel.values(), *self._worker_events]:
                    event.set()
                for _, (_, event, _) in background:
                    event.set()
                for task_id, (future, _, cancel_queued) in background:
                    if future.cancel():
                        try:
                            cancel_queued()
                        except Exception as exc:
                            errors.append((task_id, exc))
                for job_id, future in futures:
                    if future.cancel():
                        try:
                            cleanup_error = self._cleanup_incomplete(job_id)
                            self._update(job_id, state="cancelled", progress=0, message="已取消生成", result=None, error=cleanup_error)
                        except Exception as exc:
                            # Atomic writes retain the prior record for recovery.
                            # Disk failure must not strand the remaining work.
                            errors.append((job_id, exc))
                for future in self._inspect_futures:
                    future.cancel()
        finally:
            try:
                self.release_warm_worker()
                for job_id, future in [*futures, *((task_id, entry[0]) for task_id, entry in background)]:
                    try:
                        future.result()
                    except CancelledError:
                        pass
                    except Exception as exc:
                        # Includes a running job's final persistence failure,
                        # after its worker boundary has waited for child exit.
                        errors.append((job_id, exc))
                with self._condition:
                    self._condition.wait_for(lambda: not self._active_operations and not self._worker_events)
            finally:
                with self._condition:
                    try:
                        # If process exit could not be confirmed, retain both
                        # ownership and the native barrier: fail closed.
                        if self._persistent_worker is None:
                            self._lease.close()
                            if self._has_native_barrier:
                                self.job_runner.remove_before_run(self.release_warm_worker)
                    finally:
                        self._closed = True
                        self._condition.notify_all()
                for job_id, exc in errors:
                    logging.getLogger(__name__).error(
                        "人物服务关闭时任务 %s 无法确认最终状态已保存，请检查磁盘；保留的任务记录将在重启后恢复",
                        job_id, exc_info=(type(exc), exc, exc.__traceback__),
                    )

    def _ensure_recovered(self) -> None:
        # create_app is also used by tools/tests while another server is live.
        # Construction alone must not rewrite that server's job records.
        with self._lock:
            self._require_open()
            self._safe(self._lease.path)
            self._lease.acquire()
            if not self._recovered:
                # Batch completion events may be durable before the child job
                # update. Validate membership before legacy orphan cleanup.
                batch_members = self.batches.load_for_recovery()
                self._recover(batch_members)
                self.profiles.recover()
                self.anime_profiles.recover()
                self.batches.recover()
                self._recovered = True

    def _safe(self, path: Path) -> Path:
        if not self.config.path_under_dream(path):
            raise DreamApiError("IDENTITY_PATH_INVALID", "人物数据存储路径超出 Dream 目录", status_code=422)
        return path

    def _asset(self, reference_id: str, suffix: str) -> Path:
        self._validate_id(reference_id, REFERENCE_PATTERN)
        return self._safe(self.root / "references" / f"{reference_id}{suffix}")

    def _job_path(self, job_id: str) -> Path:
        self._validate_id(job_id, JOB_PATTERN)
        return self._safe(self.root / "jobs" / f"{job_id}.json")

    def _original_path(self, job_id: str) -> Path:
        self._validate_id(job_id, JOB_PATTERN)
        path = self._safe(self.root / "originals" / f"{job_id}.png")
        expected = self.config.dream_root.resolve() / "data" / "identity" / "originals" / path.name
        # Reject redirects even to another location inside this Dream root.
        if path.resolve() != expected:
            raise DreamApiError("IDENTITY_PATH_INVALID", "人物原图存储路径无效", status_code=422)
        return path

    def _remove_original(self, job_id: str) -> str | None:
        try:
            self._original_path(job_id).unlink(missing_ok=True)
        except DreamApiError:
            # A forged link is never authority to remove its target.
            import logging
            logging.getLogger(__name__).warning("人物任务 %s 原图路径无效，未清理重定向路径", job_id)
            return "原图路径无效，未清理重定向路径，请检查存储目录"
        except OSError:
            import logging
            logging.getLogger(__name__).exception("人物任务 %s 原图清理失败，残留文件尚未删除", job_id)
            return "原图清理失败，文件可能仍存在，请检查文件占用或权限"
        return None

    def _cleanup_incomplete(self, job_id: str, *paths: Path | None) -> str | None:
        """Attempt each owned artifact independently; never block terminal writes."""
        errors = []
        original_error = self._remove_original(job_id)
        if original_error:
            errors.append(original_error)
        stage_error = self._remove_stages(job_id)
        if stage_error:
            errors.append(stage_error)
        for path in paths:
            if path is None:
                continue
            try:
                self._safe(path).unlink(missing_ok=True)
            except (OSError, DreamApiError):
                import logging
                logging.getLogger(__name__).exception("人物任务 %s 未完成输出清理失败，继续保存终态", job_id)
                errors.append("未完成输出清理失败，文件可能仍存在，请检查文件占用、路径或权限")
        return "；".join(dict.fromkeys(errors)) or None

    def _remove_stages(self, job_id: str) -> str | None:
        try:
            cleanup_visual_stages({'dreamRoot': str(self.config.dream_root), 'jobId': job_id})
        except (OSError, ValueError):
            import logging
            logging.getLogger(__name__).exception("人物任务 %s 阶段图片清理失败", job_id)
            return "阶段图片清理失败，请检查存储路径、占用或权限"
        return None

    def _validate_original(self, job_id: str, request: dict[str, Any]) -> Path:
        path = self._original_path(job_id)
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("人物原图超过大小限制")
        with Image.open(path) as image:
            if image.format != "PNG" or image.size != (request["width"], request["height"]):
                raise ValueError("人物原图格式或尺寸无效")
            image.verify()
        return path

    def _validate_face_polish(self, job_id: str, request: dict[str, Any], metadata: dict[str, Any],
                              *, validate_artifacts: bool = True) -> None:
        """Always bind the receipt to its request; publication also checks every file.

        Read endpoints validate their requested file separately, so loss of an
        unrelated stage cannot hide an intact original or another saved stage.
        """
        value = metadata.get("facePolish")
        if value is None and not request.get("facePolish", False):
            # Old workers/results did not have postprocessing metadata.
            metadata["facePolish"] = {"enabled": False, "status": "disabled"}
            return
        polish = FacePolishMetadata.model_validate(value)
        protected = polish.detailerVersion == 'protected-face-v3'
        if protected or polish.featureProtection is not None:
            if (not protected or polish.featureProtection != 'central-features-v1'
                    or not polish.enabled or not is_visual_model_id(request.get('modelId'))
                    or request.get('visualPolishMode', 'redraw') != 'reference-anchor'
                    or polish.polishMode != 'reference-anchor'):
                raise ValueError('受保护修脸凭据必须匹配参考脸对齐模式与中心五官保护版本')
        if polish.enabled != request.get("facePolish", False) or (polish.status == "disabled") == polish.enabled:
            raise ValueError("人物修复状态与请求不一致")
        if polish.status == "failed" and not (polish.message and polish.message.strip()):
            raise ValueError("人物修复失败缺少原因")
        if polish.status != 'completed' and (polish.passes is not None or polish.snapshots is not None):
            raise ValueError('未完成修脸不能宣称部分阶段成功')
        if polish.originalImageUrl is not None:
            if not polish.enabled or polish.originalImageUrl != f"/api/identity/jobs/{job_id}/original":
                raise ValueError("人物原图地址与任务不一致")
        if polish.enabled and validate_artifacts:
            # A completed repair needs its base original. A failed optional
            # repair may fail before saving one, and must still keep the base.
            if polish.status == "completed" or polish.originalImageUrl is not None:
                self._validate_original(job_id, request)
        if is_visual_model_id(request.get('modelId')) and polish.enabled:
            mode = request.get('visualPolishMode', 'redraw')
            pass_count = request.get('visualPolishPasses', 1)
            staged = mode == 'reference-anchor' or pass_count == 2
            staged_fields = {'polishMode', 'passes', 'anchorStrength', 'alignmentError'}
            if polish.polishMode is not None and polish.polishMode != mode:
                raise ValueError('修脸模式与请求不一致')
            if mode != 'reference-anchor' and {'anchorStrength', 'alignmentError'}.intersection(polish.model_fields_set):
                raise ValueError('局部重绘不能返回参考脸对齐证据')
            if polish.anchorStrength is not None and polish.anchorStrength != request.get('visualAnchorStrength', .95):
                raise ValueError('参考脸对齐强度与请求不一致')
            if (polish.method not in (None, 'visual-reference-local-redraw')
                or any(value is not None for value in (polish.profileId, polish.profileName, polish.swapModel, polish.swapDevice))
                or (polish.restoreModel is not None and polish.restoreModel != visual_restore_model(request['modelId']))
                or metadata.get('referenceKind', 'visual') != 'visual'
                or metadata.get('model_id', request['modelId']) != request['modelId']):
                raise ValueError('视觉修脸不能使用真人换脸或混合动漫档案')
            # Failed optional redraws may have no success evidence. Any supplied
            # binding must still agree with the immutable generation request.
            if ((polish.referenceId is not None and polish.referenceId != request['referenceId'])
                or (polish.faceIndex is not None and polish.faceIndex != request['faceIndex'])
                or (polish.featureKey is not None and polish.featureKey != metadata.get('featureKey'))):
                raise ValueError('视觉修脸结果与已派发参考图或特征版本不一致')
            if polish.status == 'completed':
                if (polish.method != 'visual-reference-local-redraw'
                    or polish.referenceId != request['referenceId'] or polish.faceIndex != request['faceIndex']
                    or not polish.featureKey or polish.featureKey != metadata.get('featureKey')
                    or polish.denoiseStrength != request.get('animeDenoiseStrength', .35)
                    or polish.outsideMaskUnchanged is not True or not polish.originalImageUrl
                    or not polish.restoreModel or not (polish.restoreDevice and polish.restoreDevice.strip())
                    or polish.faceBox is None or polish.cropBox is None):
                    raise ValueError('视觉修脸成功结果缺少与请求一致的重绘证据')
                for box in (polish.faceBox, polish.cropBox):
                    Face.model_validate({'index': 0, 'box': box})
                    if box[2] > request['width'] or box[3] > request['height']:
                        raise ValueError('视觉修脸区域超出图片')
                face, crop = polish.faceBox, polish.cropBox
                if not (crop[0] <= face[0] and crop[1] <= face[1] and crop[2] >= face[2] and crop[3] >= face[3]):
                    raise ValueError('视觉重绘裁剪区域未包含人脸')
                detail_fields = {'detailerVersion', 'processingSize', 'detailPrompt', 'detailNegativePrompt'}
                if staged or detail_fields.intersection(polish.model_fields_set):
                    from identity_visual_polish import detail_prompts, detail_size
                    # Keep historical anchor v2 receipts valid without relabeling
                    # them as protected. Redraw retains its existing v1/v2 rules.
                    versions = (('staged-face-v2', 'protected-face-v3') if mode == 'reference-anchor'
                                else ('staged-face-v2',) if staged else ('masked-face-v1',))
                    if (polish.detailerVersion not in versions
                        or polish.processingSize != list(detail_size(crop, face))
                        or (polish.detailPrompt, polish.detailNegativePrompt) != detail_prompts(request)):
                        raise ValueError('蒙版细化参数与请求不一致')
                if staged:
                    if polish.polishMode != mode or polish.passes is None or len(polish.passes) != pass_count:
                        raise ValueError('分阶段修脸缺少完整轮次证据')
                    expected = [('harmonize', request.get('animeDenoiseStrength', .35)), ('detail', .15)][:pass_count]
                    for actual, (kind, strength) in zip(polish.passes, expected):
                        if (actual.kind, actual.denoiseStrength, actual.steps) != (kind, strength, int(30 * strength)):
                            raise ValueError('分阶段修脸轮次参数与请求不一致')
                    if mode == 'reference-anchor' and (polish.anchorStrength != request.get('visualAnchorStrength', .95)
                                                      or polish.alignmentError is None):
                        raise ValueError('参考脸对齐缺少几何拟合证据')
                elif staged_fields.intersection(polish.model_fields_set):
                    raise ValueError('旧单轮重绘不能返回分阶段凭据')
                if staged or polish.snapshots is not None:
                    expected_kinds = (['anchor'] if mode == 'reference-anchor' else []) + ['harmonize'] + (['detail'] if pass_count == 2 else [])
                    if polish.snapshots is None or [snapshot.kind for snapshot in polish.snapshots] != expected_kinds:
                        raise ValueError('分阶段修脸缺少按顺序保存的图片')
                    item = {**request, 'jobId': job_id, 'dreamRoot': str(self.config.dream_root)}
                    for snapshot in polish.snapshots:
                        if snapshot.imageUrl != visual_stage_url(job_id, snapshot.kind):
                            raise ValueError('人物阶段图片地址与任务不一致')
                        if validate_artifacts:
                            validate_visual_stage(item, snapshot.kind)
        elif (polish.method == 'visual-reference-local-redraw' or polish.referenceId is not None or polish.faceIndex is not None
              or polish.detailerVersion == 'staged-face-v2' or any(value is not None for value in
                  (polish.polishMode, polish.passes, polish.anchorStrength, polish.alignmentError, polish.snapshots))):
            raise ValueError('未请求视觉修脸却返回视觉修脸结果')
        elif polish.status == 'completed' and request.get('animeProfileId'):
            binding = AnimeBinding.model_validate(self._jobs.get(job_id,{}).get('animeBinding'))
            if (polish.method != 'anime-reference-local-redraw' or polish.profileId != request['animeProfileId']
                or polish.denoiseStrength != request.get('animeDenoiseStrength',.35) or polish.outsideMaskUnchanged is not True
                or not polish.featureKey or not polish.profileName or polish.faceBox is None or polish.cropBox is None):
                raise ValueError('动漫修脸结果与请求不一致')
            if (polish.profileId,polish.profileName,polish.featureKey)!=(binding.id,binding.name,binding.featureKey):
                raise ValueError('动漫修脸结果与已派发档案版本不一致')
            for box in (polish.faceBox, polish.cropBox):
                Face.model_validate({'index':0,'box':box})
                if box[2]>request['width'] or box[3]>request['height']: raise ValueError('动漫修脸区域超出图片')
        elif polish.method or polish.profileId:
            raise ValueError('未请求动漫修脸却返回动漫修脸结果')
        metadata["facePolish"] = polish.model_dump(exclude_none=True)

    @staticmethod
    def _validate_id(value: str, pattern: str) -> None:
        if re.fullmatch(pattern, value) is None:
            raise DreamApiError("IDENTITY_ID_INVALID", "人物参考图或任务编号无效", status_code=422)

    def _recover(self, batch_members: set[str] | None = None) -> None:
        folder = self._safe(self.root / "jobs")
        if not folder.exists():
            return
        for path in sorted(folder.glob("identity-*.json"), key=lambda p: p.stat().st_mtime_ns):
            if re.fullmatch(JOB_PATTERN, path.stem) is None:
                continue
            try:
                record = read_json(self._safe(path))
                if record.get("id") != path.stem or record.get("state") not in TERMINAL | {"queued", "preparing", "sampling"}:
                    continue
                if record.get("request"):
                    record["request"] = IdentityGenerateRequest.model_validate(record["request"]).model_dump()
                if record["state"] not in TERMINAL and path.stem not in (batch_members or set()):
                    # Only opaque IDs discovered in this service's job store
                    # can identify incomplete output; never trust saved paths.
                    output_root = self._safe(self.config.dream_root / "outputs")
                    partials = [partial for partial in output_root.glob(f"*/{path.stem}.*") if partial.suffix in {".png", ".json"} and re.fullmatch(r"\d{4}-\d{2}-\d{2}", partial.parent.name)]
                    cleanup_error = self._cleanup_incomplete(path.stem, *partials)
                    error = "；".join(filter(None, ("人物任务被服务重启中断，请重新提交", cleanup_error)))
                    record.update(state="failed", progress=0, message="任务被服务重启中断", error=error, result=None)
                    atomic_json(path, record)
                elif record["state"] in {"failed", "cancelled"}:
                    cleanup_error = self._cleanup_incomplete(path.stem)
                    if cleanup_error and cleanup_error not in (record.get("error") or ""):
                        record["error"] = "；".join(filter(None, (record.get("error"), cleanup_error)))
                        atomic_json(path, record)
                self._jobs[path.stem] = record
            except (OSError, ValueError):
                continue
        try:
            order = read_json(self._safe(folder / "index.json")).get("ids", [])
            if not isinstance(order, list) or not all(isinstance(item, str) for item in order):
                order = []
        except (OSError, ValueError):
            order = []
        ordered_ids = dict.fromkeys([*order, *self._jobs])
        self._jobs = {job_id: self._jobs[job_id] for job_id in ordered_ids if job_id in self._jobs}

    def _update(self, job_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            updated = {**self._jobs[job_id], **changes}
            atomic_json(self._job_path(job_id), updated)
            self._jobs[job_id] = updated
            return copy.deepcopy(updated)

    @staticmethod
    def _stop_owned(process: subprocess.Popen) -> None:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def _worker(self, operation: str, payload: dict[str, Any], cancelled: threading.Event | None = None) -> dict[str, Any]:
        cancelled = cancelled if cancelled is not None else threading.Event()
        with self._condition:
            if self._closing:
                raise WorkerCancelled()
            self._worker_events.add(cancelled)
        try:
            return self._run_worker(operation, payload, cancelled)
        finally:
            with self._condition:
                self._worker_events.discard(cancelled)
                self._condition.notify_all()

    def _run_worker(self, operation: str, payload: dict[str, Any], cancelled: threading.Event) -> dict[str, Any]:
        callback = self._event_callbacks.get(payload.get("eventPath"))
        offset = 0

        def consume_events(drain=False):
            nonlocal offset
            if callback is None:
                return
            from identity_events import read_events
            path = self._safe(Path(payload["eventPath"]))
            for _ in range(65 if drain else 1):
                if path.exists() and path.stat().st_size > 4 * 1024 * 1024:
                    raise ValueError("人物批次事件超过大小限制")
                events, next_offset = read_events(path, offset)
                for event in events:
                    callback(event)
                if next_offset == offset:
                    if drain and path.exists() and path.stat().st_size != offset:
                        raise ValueError("人物批次事件尾行未完成")
                    return
                offset = next_offset

        try:
            settings = read_json(self.config_path, 64 * 1024)
            python = settings.get("python") or sys.executable
            if not isinstance(python, str) or not python.strip():
                raise ValueError("人物运行配置中的 python 必须是解释器路径")
            # Explicit deployment opt-in until real CUDA performance acceptance.
            # Both dispatch modes use the same serialized queue and journal.
            if operation in {"generate", "batch"} and settings.get("persistentWorker") is True:
                batch = payload if operation == "batch" else {
                    "items": [payload], "configPath": str(self.config_path),
                    "dreamRoot": str(self.config.dream_root), "previewEvery": 0,
                }
                try:
                    value = self._persistent_batch(settings, batch, cancelled, consume_events)
                    if operation == "generate":
                        return {"ok": True, **value["items"][0], "sessionReused": value.get("sessionReused", False)}
                    return value
                finally:
                    consume_events(drain=True)
            if operation != "status":
                self.release_warm_worker()
            work = self._safe(self.root / "work")
            work.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="worker-", dir=work) as directory:
                folder = Path(directory)
                request_path, result_path = folder / "request.json", folder / "result.json"
                atomic_json(request_path, payload)
                command = [python, str(Path(__file__).with_name("identity_worker.py")), "--operation", operation, "--request", str(request_path), "--result", str(result_path)]
                env = os.environ.copy()
                env["DREAM_IDENTITY_CONFIG"] = str(self.config_path)
                env["PYTHONIOENCODING"] = "utf-8"
                hub_cache = self._safe(self.config.dream_root / "cache" / "identity-hub")
                temporary_root = self._safe(self.config.dream_root / "temp")
                hub_cache.mkdir(parents=True, exist_ok=True)
                temporary_root.mkdir(parents=True, exist_ok=True)
                env.update(HF_HUB_OFFLINE="1", HF_HOME=str(hub_cache), TEMP=str(temporary_root), TMP=str(temporary_root))
                if cancelled is not None and cancelled.is_set():
                    raise WorkerCancelled()
                process = None
                lifetime = None
                # Worker logs stay on disk; neither images nor unbounded output
                # are retained in the web process's memory.
                logs = self._safe(self.config.dream_root / "logs" / "identity")
                logs.mkdir(parents=True, exist_ok=True)
                with (logs / f"{folder.name}.err.log").open("w+b") as error_log:
                    try:
                        process = subprocess.Popen(command, cwd=str(self.config.dream_root), env=env, stdout=subprocess.DEVNULL, stderr=error_log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                        lifetime = WorkerLifetime(process)
                        deadline = time.monotonic() + (900 * len(payload["items"]) if operation == "batch" else 900 if operation == "generate" else 120)
                        while True:
                            consume_events()
                            if cancelled is not None and cancelled.is_set():
                                raise WorkerCancelled()
                            if time.monotonic() >= deadline:
                                raise RuntimeError("人物工作进程运行超时，请查看本地任务日志")
                            try:
                                process.communicate(timeout=0.1)
                                break
                            except subprocess.TimeoutExpired:
                                continue
                        consume_events(drain=True)
                        if cancelled is not None and cancelled.is_set():
                            raise WorkerCancelled()
                        if process.returncode != 0:
                            try:
                                failure = read_json(result_path)
                                detail = failure.get("message") or failure.get("error")
                            except (OSError, ValueError):
                                detail = None
                            error_log.seek(0, 2)
                            error_log.seek(max(0, error_log.tell() - 8192))
                            raise RuntimeError(str(detail or error_log.read().decode("utf-8", errors="replace") or "人物工作进程运行失败"))
                        return read_json(result_path)
                    finally:
                        try:
                            if process is not None:
                                self._stop_owned(process)
                            # The child may finish one atomic output just before
                            # cancellation; consume its completion before cleanup.
                            consume_events(drain=True)
                        finally:
                            if lifetime is not None:
                                lifetime.close()
        except PersistentWorkerCancelled as exc:
            raise WorkerCancelled() from exc
        except WorkerCancelled:
            raise
        except (OSError, ValueError, RuntimeError) as exc:
            raise DreamApiError("IDENTITY_WORKER_FAILED", f"人物处理失败：{exc}") from exc

    @owned_operation
    def status(self) -> dict[str, Any]:
        try:
            value = self._worker("status", {"configPath": str(self.config_path)})
            loras = value.get("loras", [])
            if not isinstance(value.get("ready"), bool) or not isinstance(loras, list):
                raise ValueError("人物工作进程返回了无效的状态信息")
            if any(not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("name"), str) for item in loras):
                raise ValueError("人物工作进程返回了无效的 LoRA 列表")
            result = {"ready": value["ready"], "modelName": str(value.get("modelName") or "Realistic Vision V5.1"), "message": str(value.get("message") or ""), "loras": [{"id": item["id"], "name": item["name"]} for item in loras]}
            if isinstance(value.get('models'), list):
                from identity_models import MODEL_SPECS
                result['models'] = []
                for row in value['models']:
                    if not isinstance(row, dict) or row.get('id') not in MODEL_SPECS or type(row.get('ready')) is not bool:
                        raise ValueError('人物工作进程返回了无效的模型列表')
                    result['models'].append({key: row[key] for key in ('id', 'name', 'architecture', 'ready', 'message')})
                    result['models'][-1]['loras'] = [{key: entry[key] for key in ('id', 'name')} for entry in row.get('loras', [])]
                    if 'referenceKind' in row:
                        if row['referenceKind'] not in ('faceid', 'visual'):
                            raise ValueError('人物工作进程返回了无效的参考图类型')
                        result['models'][-1]['referenceKind'] = row['referenceKind']
                    if 'experimental' in row:
                        if type(row['experimental']) is not bool:
                            raise ValueError('人物工作进程返回了无效的实验模型标记')
                        result['models'][-1]['experimental'] = row['experimental']
                    if 'qualityStatus' in row:
                        if row['qualityStatus'] not in ('failed', 'unverified', 'passed'):
                            raise ValueError('人物工作进程返回了无效的画质验收状态')
                        result['models'][-1]['qualityStatus'] = row['qualityStatus']
            polish = value.get("facePolish")
            if isinstance(polish, dict) and type(polish.get("ready")) is bool and isinstance(polish.get("message"), str):
                result["facePolish"] = {"ready": polish["ready"], "message": polish["message"]}
            anime = value.get('animePolish')
            if isinstance(anime, dict) and type(anime.get('ready')) is bool and isinstance(anime.get('message'), str):
                result['animePolish'] = {'ready':anime['ready'],'message':anime['message']}
            visual = value.get('visualPolish')
            if isinstance(visual, dict) and type(visual.get('ready')) is bool and isinstance(visual.get('message'), str):
                result['visualPolish'] = {'ready': visual['ready'], 'message': visual['message']}
                if type(visual.get('referenceAnchorReady')) is bool and isinstance(visual.get('referenceAnchorMessage'), str):
                    result['visualPolish'].update(referenceAnchorReady=visual['referenceAnchorReady'],
                                                 referenceAnchorMessage=visual['referenceAnchorMessage'])
            return result
        except WorkerCancelled as exc:
            raise DreamApiError("IDENTITY_SERVICE_CLOSED", "人物服务正在关闭，请稍后重试", status_code=503) from exc
        except (DreamApiError, ValueError) as exc:
            return {"ready": False, "modelName": "Realistic Vision V5.1", "message": str(exc), "loras": []}

    @owned_operation
    def upload(self, payload: ReferenceUpload, cancelled: threading.Event | None = None) -> dict[str, Any]:
        encoded = payload.imageBase64
        if len(encoded) > MAX_BASE64:
            raise DreamApiError("IDENTITY_IMAGE_TOO_LARGE", "参考图片不能超过 10 MiB", status_code=413)
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise DreamApiError("IDENTITY_IMAGE_INVALID", "参考图片编码无效，请重新选择图片", status_code=422) from exc
        if len(raw) > MAX_IMAGE_BYTES:
            raise DreamApiError("IDENTITY_IMAGE_TOO_LARGE", "参考图片不能超过 10 MiB", status_code=413)
        try:
            with Image.open(io.BytesIO(raw)) as source:
                if source.width * source.height > MAX_IMAGE_PIXELS:
                    raise DreamApiError("IDENTITY_IMAGE_TOO_LARGE", "参考图片不能超过 1600 万像素", status_code=413)
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.info.clear()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
            raise DreamApiError("IDENTITY_IMAGE_INVALID", "参考图片格式不受支持或图片已损坏", status_code=422) from exc
        reference_id = "ref-" + secrets.token_hex(12)
        image_path = self._asset(reference_id, ".png")
        metadata_path = self._asset(reference_id, ".json")
        image_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with image_path.open("xb") as stream:
                image.save(stream, format="PNG")
            with self._lock:
                self._require_open()
                inspect_payload = {"imagePath": str(image_path)}
                # The omitted kind retains the original FaceID worker contract.
                if "referenceKind" in payload.model_fields_set:
                    inspect_payload["referenceKind"] = payload.referenceKind
                future = self.job_runner.submit_serial(self._worker, "inspect", inspect_payload, cancelled)
                self._inspect_futures.add(future)
            try:
                result = future.result()
            except CancelledError as exc:
                raise WorkerCancelled() from exc
            finally:
                with self._lock:
                    self._inspect_futures.discard(future)
            try:
                raw_faces = result.get("faces")
                if not isinstance(raw_faces, list) or len(raw_faces) > 20:
                    raise ValueError("Invalid face list")
                faces = [Face.model_validate(value).model_dump() for value in raw_faces]
                if any(face["box"][2] > image.width or face["box"][3] > image.height for face in faces):
                    raise ValueError("Face box lies outside the reference")
            except (ValueError, ValidationError) as exc:
                raise DreamApiError("IDENTITY_WORKER_FAILED", "人脸检测返回了无效结果，请重新选择参考图片") from exc
            if not faces or len(faces) > 100 or len({face["index"] for face in faces}) != len(faces):
                raise DreamApiError("IDENTITY_FACE_INVALID", "参考图片中未检测到可用人脸，请选择清晰的人物照片", status_code=422)
            record = {"id": reference_id, "name": payload.name, "imageUrl": f"/api/identity/references/{reference_id}/image", "faces": faces}
            if "referenceKind" in payload.model_fields_set:
                record["referenceKind"] = payload.referenceKind
            atomic_json(metadata_path, record)
            return record
        except BaseException:
            image_path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            raise

    def reference(self, reference_id: str) -> dict[str, Any]:
        path = self._asset(reference_id, ".json")
        try:
            return read_json(path)
        except FileNotFoundError as exc:
            raise DreamApiError("IDENTITY_REFERENCE_NOT_FOUND", "人物参考图不存在，请重新选择", status_code=404) from exc

    @owned_operation
    def references(self) -> list[dict[str, Any]]:
        folder = self._safe(self.root / "references")
        return [self.reference(path.stem) for path in sorted(folder.glob("ref-*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True) if re.fullmatch(REFERENCE_PATTERN, path.stem)]

    @owned_operation
    def reference_image(self, reference_id: str) -> Path:
        self.reference(reference_id)
        path = self._asset(reference_id, ".png")
        if not path.is_file():
            raise DreamApiError("IDENTITY_REFERENCE_NOT_FOUND", "人物参考图片文件不存在，请重新上传", status_code=404)
        return path

    @owned_operation
    def submit(self, request: IdentityGenerateRequest) -> dict[str, Any]:
        self._ensure_recovered()
        self._require_model_enabled(request.modelId)
        self._validate_face(request.referenceId, request.faceIndex, request_reference_kind(request))
        data = request.model_dump()
        self._require_visual_polish_ready(data)
        self.anime_profiles.resolve_request(data)
        if data["seed"] == "random":
            data["seed"] = secrets.randbelow(2147483648)
        job_id = "identity-" + secrets.token_hex(12)
        record = {"id": job_id, "state": "queued", "progress": 0, "message": "等待本地生成队列", "request": data, "result": None, "error": None}
        with self._lock:
            self._require_open()
            atomic_json(self._job_path(job_id), record)
            self._jobs[job_id] = record
            atomic_json(self._safe(self.root / "jobs" / "index.json"), {"ids": list(self._jobs)})
            self._cancel[job_id] = threading.Event()
            self._futures[job_id] = self.job_runner.submit_serial(self._execute, job_id)
            return copy.deepcopy(record)

    @owned_operation
    def get(self, job_id: str) -> dict[str, Any]:
        self._ensure_recovered()
        self._validate_id(job_id, JOB_PATTERN)
        with self._lock:
            if job_id not in self._jobs:
                raise DreamApiError("IDENTITY_JOB_NOT_FOUND", "人物生成任务不存在", status_code=404)
            return copy.deepcopy(self._jobs[job_id])

    @owned_operation
    def jobs(self) -> list[dict[str, Any]]:
        self._ensure_recovered()
        with self._lock:
            return copy.deepcopy(list(reversed(self._jobs.values())))

    @owned_operation
    def stage_image(self, job_id: str, kind: str) -> Path:
        try:
            visual_stage_url(job_id, kind)
            record = self.get(job_id)
            from history_transactions import committed_history_deletions
            if job_id in committed_history_deletions(self.config.dream_root):
                raise ValueError('人物结果已删除')
            with self._lock:
                durable = read_json(self._job_path(job_id))
                if (record['state'] != 'complete' or durable.get('id') != job_id or durable.get('state') != 'complete'
                        or durable.get('result') != record.get('result')):
                    raise ValueError('人物阶段结果尚未持久保存')
                request = IdentityGenerateRequest.model_validate(record['request']).model_dump()
                if IdentityGenerateRequest.model_validate(durable['request']).model_dump() != request:
                    raise ValueError('人物阶段请求与记录不一致')
                metadata = copy.deepcopy(record['result']['metadata'])
                if metadata.get('id') != job_id:
                    raise ValueError('人物阶段结果编号无效')
                self._validate_face_polish(job_id, request, metadata, validate_artifacts=False)
                polish = metadata['facePolish']
                if polish['status'] != 'completed' or kind not in [snapshot['kind'] for snapshot in polish.get('snapshots', [])]:
                    raise ValueError('人物阶段图片未登记')
                return validate_visual_stage({**request, 'jobId': job_id, 'dreamRoot': str(self.config.dream_root)}, kind)
        except (OSError, ValueError, TypeError, KeyError, DreamApiError) as exc:
            raise DreamApiError('IDENTITY_STAGE_NOT_FOUND', '人物阶段图片不存在或尚未完成', status_code=404) from exc

    @owned_operation
    def original_image(self, job_id: str) -> Path:
        record = self.get(job_id)
        try:
            with self._lock:
                # In-memory pending completions are not durable registrations.
                durable = read_json(self._job_path(job_id))
                if record["state"] != "complete" or durable.get("id") != job_id or durable.get("state") != "complete":
                    raise ValueError("人物任务尚未完成")
                request = IdentityGenerateRequest.model_validate(record["request"]).model_dump()
                metadata = copy.deepcopy(record["result"]["metadata"])
                if not isinstance(metadata, dict) or metadata.get("id") != job_id:
                    raise ValueError("人物结果元数据无效")
                self._validate_face_polish(job_id, request, metadata, validate_artifacts=False)
                if metadata["facePolish"]["enabled"] is not True:
                    raise ValueError("人物任务未启用修复")
                return self._validate_original(job_id, request)
        except (OSError, ValueError, TypeError, KeyError, DreamApiError) as exc:
            raise DreamApiError("IDENTITY_ORIGINAL_NOT_FOUND", "人物原图不存在或尚未完成", status_code=404) from exc

    @owned_operation
    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            record = self.get(job_id)
            if record["state"] in TERMINAL:
                return record
            if job_id in self.batches.item_owners:
                raise DreamApiError("IDENTITY_BATCH_CANCEL_REQUIRED", "该图片属于批次，请通过批次取消剩余生成", status_code=409)
            self._cancel[job_id].set()
            future = self._futures[job_id]
            if future.cancel():
                cleanup_error = self._cleanup_incomplete(job_id)
                return self._update(job_id, state="cancelled", progress=0, message="已取消生成", result=None, error=cleanup_error)
        # A cancellation response is a release barrier: the child's exit and
        # cleanup must finish before this shared queue can start another job.
        future.result()
        return self.get(job_id)

    def _execute(self, job_id: str) -> None:
        output = metadata = None
        cancelled = self._cancel[job_id]
        try:
            if cancelled.is_set():
                raise WorkerCancelled()
            request = self._update(job_id, state="preparing", progress=10, message="准备人物生成")["request"]
            self.job_runner.release_native_for_identity()
            if cancelled.is_set():
                raise WorkerCancelled()
            folder = self._safe(self.config.dream_root / "outputs" / date.today().isoformat())
            output = self._safe(folder / f"{job_id}.png")
            metadata = self._safe(folder / f"{job_id}.json")
            folder.mkdir(parents=True, exist_ok=True)
            payload = {**request, "imagePath": str(self.reference_image(request["referenceId"])), "outputPath": str(output), "metadataPath": str(metadata), "jobId": job_id, "dreamRoot": str(self.config.dream_root), "configPath": str(self.config_path)}
            payload.update(self.anime_profiles.resolve_request(request))
            self.bind_anime_dispatch(job_id,payload)
            self._update(job_id, state="sampling", progress=20, message="正在运行人物工作进程")
            self._worker("generate", payload, cancelled)
            with Image.open(output) as image:
                if image.format != "PNG" or image.size != (request["width"], request["height"]):
                    raise ValueError("人物工作进程返回的图片格式或尺寸不符合请求")
                image.verify()
            value = read_json(metadata)
            self._validate_face_polish(job_id, request, value)
            value.update({"id": job_id, "model_id": request.get('modelId', 'realistic-vision-v5.1-faceid'), "identity": request, "output": str(output), "prompt": request["prompt"], "negative_prompt": request["negativePrompt"], "seed": request["seed"], "width": request["width"], "height": request["height"], "steps": request["steps"], "cfg": request["cfg"], "generated_at": datetime.now().astimezone().isoformat()})
            with self._lock:
                if cancelled.is_set():
                    raise WorkerCancelled()
                atomic_json(metadata, value)
                self._update(job_id, state="complete", progress=100, message="生成完成", result={"imageUrl": f"/api/history/{job_id}/image", "metadata": value})
        except Exception as exc:
            cleanup_error = self._cleanup_incomplete(job_id, metadata, output)
            is_cancelled = cancelled.is_set() or isinstance(exc, WorkerCancelled)
            error = "；".join(filter(None, (None if is_cancelled else f"人物生成失败：{exc}", cleanup_error))) or None
            self._update(job_id, state="cancelled" if is_cancelled else "failed", progress=0, message="已取消生成" if is_cancelled else "人物生成失败", result=None, error=error)
