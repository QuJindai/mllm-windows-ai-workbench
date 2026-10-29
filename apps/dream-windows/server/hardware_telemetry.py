"""Bounded, read-only telemetry. Persisted hardware.json is inventory, not load."""
from __future__ import annotations

import csv
import logging
import math
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any

import psutil

from config import DreamServerConfig
from errors import DreamApiError
from research_traces import InvalidArtifact, read_bounded_json


logger = logging.getLogger(__name__)


class _InvalidSample(ValueError):
    """Only fixed, non-sensitive validation codes are used as messages."""


def _log_sample_failure(error: Exception) -> None:
    # Never format the exception: OS paths, commands and driver stderr can be private.
    cause = type(error).__name__[:64]
    if isinstance(error, subprocess.TimeoutExpired):
        category = "probe_timeout"
    elif isinstance(error, FileNotFoundError):
        category = "probe_missing"
    elif isinstance(error, PermissionError):
        category = "probe_denied"
    elif isinstance(error, subprocess.CalledProcessError):
        category = "probe_exit"
    elif isinstance(error, subprocess.SubprocessError):
        category = "subprocess_error"
    elif isinstance(error, OSError):
        category = "os_error"
    elif isinstance(error, psutil.Error):
        category = "system_probe_error"
    else:
        category = "invalid_sample"
        if isinstance(error, _InvalidSample):
            cause = str(error)
    diagnostics = []
    for attribute, label in (("errno", "errno"), ("returncode", "returncode"), ("timeout", "timeout_seconds")):
        value = getattr(error, attribute, None)
        if type(value) in (int, float) and -1e9 < value < 1e9:
            diagnostics.append(f"{label}={value:g}")
    logger.warning("Hardware telemetry failed: category=%s cause=%s %s", category, cause, " ".join(diagnostics))


def _number(value: str) -> float | None:
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) and number >= 0 else None


class HardwareTelemetry:
    # One driver query per process per window, including on failure. No GPU work.
    CACHE_SECONDS = 2.0
    PROBE_TIMEOUT_SECONDS = 3.0
    FAILURE_RETRY_SECONDS = (3.0, 6.0, 12.0, 30.0)

    def __init__(self, config: DreamServerConfig):
        self.config = config
        self._lock = threading.Lock()
        self._expires_at = 0.0
        self._failures = 0
        self._snapshot: dict[str, Any] | None = None
        self._cpu: dict[str, Any] | None = None

    def read(self) -> dict[str, Any]:
        with self._lock:
            if time.monotonic() >= self._expires_at:
                # Never reuse a successful reading after a failed refresh.
                self._snapshot = None
                try:
                    self._snapshot = self._sample()
                    self._failures = 0
                except (OSError, subprocess.SubprocessError, ValueError, psutil.Error) as error:
                    # Log once for this failed cached sample, not once per API caller.
                    self._failures = min(self._failures + 1, len(self.FAILURE_RETRY_SECONDS))
                    _log_sample_failure(error)
                delay = self.FAILURE_RETRY_SECONDS[self._failures - 1] if self._failures else self.CACHE_SECONDS
                self._expires_at = time.monotonic() + delay
            if self._snapshot is None:
                raise DreamApiError(
                    "HARDWARE_TELEMETRY_UNAVAILABLE",
                    "当前硬件采样不可用，请检查 NVIDIA 驱动或稍后重试。",
                    retryable=True,
                )
            return dict(self._snapshot)

    def _sample(self) -> dict[str, Any]:
        result = subprocess.run(
            ["nvidia-smi", "--id=0",
             "--query-gpu=name,memory.total,memory.used,utilization.gpu,temperature.gpu,power.draw,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=self.PROBE_TIMEOUT_SECONDS, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, "nvidia-smi")
        rows = list(csv.reader(result.stdout.strip().splitlines()))
        if len(rows) != 1 or len(rows[0]) != 7:
            raise _InvalidSample("invalid_gpu_row")
        name, total, used, util, temperature, power, driver = (cell.strip() for cell in rows[0])
        total_vram, used_vram, gpu_util = _number(total), _number(used), _number(util)
        if (not name or name in {"N/A", "[N/A]"} or total_vram is None or total_vram <= 0
                or used_vram is None or used_vram > total_vram or gpu_util is None or gpu_util > 100):
            raise _InvalidSample("invalid_gpu_values")
        ram = psutil.virtual_memory()
        if not (0 <= ram.available <= ram.total and ram.total > 0):
            raise _InvalidSample("invalid_ram_values")

        if self._cpu is None:
            try:
                inventory = read_bounded_json(self.config.dream_root / "data" / "hardware.json", 64 * 1024)
                self._cpu = inventory.get("cpu") if isinstance(inventory.get("cpu"), dict) else {}
            except InvalidArtifact:
                self._cpu = {}
        try:
            drive = psutil.disk_usage(str(self.config.dream_root))
        except OSError:
            drive = None
        native_ready = all(path.exists() for path in (
            self.config.core_exe, self.config.engine_exe, self.config.wrapper, self.config.registry_path,
        ))
        return {
            "gpuName": name,
            "vramTotalMiB": total_vram,
            "vramUsedMiB": used_vram,
            "gpuUtil": gpu_util,
            "gpuTempC": _number(temperature),
            "gpuPowerW": _number(power),
            "ramTotalBytes": ram.total,
            "ramUsedBytes": ram.total - ram.available,
            "cudaReady": True,
            "backend": "stable-diffusion.cpp + CUDA" if native_ready else "Unavailable",
            "backendTruth": "derived",
            "dreamRoot": str(self.config.dream_root),
            "truth": "observed",
            "isMock": False,
            "cpuName": self._cpu.get("name"),
            "cpuCores": self._cpu.get("cores"),
            "cpuThreads": self._cpu.get("logical_processors"),
            "driverVersion": driver if driver not in {"N/A", "[N/A]", ""} else None,
            "eDriveTotalBytes": drive.total if drive else None,
            "eDriveFreeBytes": drive.free if drive else None,
            "sampledAt": datetime.now(timezone.utc).isoformat(),
            "telemetrySource": "nvidia-smi + psutil",
        }
