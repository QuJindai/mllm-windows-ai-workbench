"""GUI-02: stale inventory, fake zeroes and unbounded probes must not reach clients."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

import psutil
import pytest
from fastapi.testclient import TestClient

from app import create_app
from errors import DreamApiError
from runtime import DreamRuntime
from test_generation_jobs import make_config


@pytest.fixture
def telemetry(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    inventory = {
        "timestamp": "2026-01-01T00:00:00Z",
        "nvidia": {"name": "Stale GPU", "memory_total_mib": 6141, "memory_free_mib": 5911},
        "ram": {"total_bytes": 64000, "free_bytes": 50000},
        "cpu": {"name": "Inventory CPU", "cores": 20, "logical_processors": 28},
    }
    (config.dream_root / "data" / "hardware.json").write_text(json.dumps(inventory), encoding="utf-8")
    runtime = DreamRuntime(config)
    monkeypatch.setattr(runtime, "_run_core", lambda *args, **kwargs: json.dumps(inventory))
    state = {"now": 10.0, "csv": "Live GPU, 6141, 1506, 80, 57, 32.5, 595.95\n", "error": None, "calls": []}

    def run(command, **kwargs):
        state["calls"].append((command, kwargs))
        if state["error"]:
            raise state["error"]
        return subprocess.CompletedProcess(command, 0, state["csv"], "")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(time, "monotonic", lambda: state["now"])
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(total=64 * 1024**3, available=48 * 1024**3))
    return runtime, state


def test_hardware_api_uses_live_readings_and_preserves_the_full_client_contract(telemetry):
    runtime, state = telemetry
    before = datetime.now(timezone.utc)
    response = TestClient(create_app(config=runtime.config, runtime=runtime)).get("/api/hardware")
    assert response.status_code == 200
    body = response.json()
    assert body["vramUsedMiB"] == 1506  # not the persisted 230 MiB
    assert body["gpuUtil"] == 80
    assert body["gpuName"] == "Live GPU"
    assert body["vramTotalMiB"] == 6141
    assert body["ramTotalBytes"] == 64 * 1024**3
    assert body["ramUsedBytes"] == 16 * 1024**3
    assert body["gpuTempC"] == 57
    assert body["gpuPowerW"] == 32.5  # power.draw, not power.limit
    assert body["driverVersion"] == "595.95"
    assert body["cpuName"] == "Inventory CPU"
    assert body["cpuCores"] == 20 and body["cpuThreads"] == 28
    assert body["cudaReady"] is True and body["isMock"] is False
    assert body["backend"] == "stable-diffusion.cpp + CUDA"
    assert body["backendTruth"] == "derived" and body["truth"] == "observed"
    assert body["dreamRoot"] == str(runtime.config.dream_root)
    assert before <= datetime.fromisoformat(body["sampledAt"]) <= datetime.now(timezone.utc)
    assert body["telemetrySource"] == "nvidia-smi + psutil"
    assert body["eDriveTotalBytes"] > 0 and body["eDriveFreeBytes"] > 0
    command, options = state["calls"][0]
    assert "--id=0" in command
    assert any("utilization.gpu" in arg and "memory.used" in arg and "power.draw" in arg for arg in command)
    assert 0 < options["timeout"] <= 2
    assert not options.get("shell", False)


def test_live_acquisition_does_not_depend_on_the_core_inventory_command(telemetry, monkeypatch):
    runtime, _ = telemetry
    monkeypatch.setattr(runtime, "_run_core", lambda *args: (_ for _ in ()).throw(DreamApiError("STALE_CORE", "not a live probe")))
    assert runtime.hardware()["gpuUtil"] == 80


def test_poll_bursts_share_a_sample_then_refresh_after_cache_expiry(telemetry):
    runtime, state = telemetry
    with ThreadPoolExecutor(max_workers=8) as pool:
        samples = list(pool.map(lambda _: runtime.hardware(), range(8)))
    assert len(state["calls"]) == 1
    assert all(sample["vramUsedMiB"] == 1506 for sample in samples)
    first_time = samples[0]["sampledAt"]
    samples[0]["gpuUtil"] = 99
    state["csv"] = "Live GPU, 6141, 2000, 12, 44, 20.0, 595.95\n"
    state["now"] = 11.0
    assert runtime.hardware()["gpuUtil"] == 80
    assert runtime.hardware()["sampledAt"] == first_time
    state["now"] = 12.1
    assert runtime.hardware()["vramUsedMiB"] == 2000
    assert len(state["calls"]) == 2


@pytest.mark.parametrize("row", [
    "", "bad,row", "Live GPU, 6141, N/A, 80, 57, 32.5, 595.95",
    "Live GPU, 6141, 1506, N/A, 57, 32.5, 595.95",
    "Live GPU, 6141, 1506, NaN, 57, 32.5, 595.95",
    "Live GPU, 6141, 1506, inf, 57, 32.5, 595.95",
    "Live GPU, 6141, 1506, 101, 57, 32.5, 595.95",
    "Live GPU, 6141, -1, 80, 57, 32.5, 595.95",
    "Live GPU, 6141, 7000, 80, 57, 32.5, 595.95",
    "Live GPU, 0, 0, 80, 57, 32.5, 595.95",
])
def test_invalid_required_readings_return_unavailable_not_zero_or_inventory(telemetry, row):
    runtime, state = telemetry
    state["csv"] = row
    response = TestClient(create_app(config=runtime.config, runtime=runtime)).get("/api/hardware")
    assert response.status_code == 503
    assert response.json()["code"] == "HARDWARE_TELEMETRY_UNAVAILABLE"
    assert "gpuUtil" not in response.json()


@pytest.mark.parametrize("error", [FileNotFoundError("missing"), subprocess.TimeoutExpired("nvidia-smi", 1.5)])
def test_failed_probes_invalidate_success_cache_and_recover_without_a_retry_storm(telemetry, error):
    runtime, state = telemetry
    assert runtime.hardware()["gpuUtil"] == 80
    state["now"] = 13.0
    state["error"] = error
    for _ in range(5):
        with pytest.raises(DreamApiError, match="硬件"):
            runtime.hardware()
    assert len(state["calls"]) == 2
    state["now"] = 16.0
    state["error"] = None
    assert runtime.hardware()["gpuUtil"] == 80
    assert len(state["calls"]) == 3


def test_nonzero_driver_exit_is_unavailable_even_with_valid_stdout(telemetry, monkeypatch):
    runtime, state = telemetry
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, state["csv"], "driver failed"))
    with pytest.raises(DreamApiError):
        runtime.hardware()


def test_real_idle_zero_is_valid_and_optional_na_sensors_stay_null(telemetry):
    runtime, state = telemetry
    state["csv"] = "Live GPU, 6141, 0, 0, [N/A], N/A, 595.95\n"
    snapshot = runtime.hardware()
    assert snapshot["gpuUtil"] == 0 and snapshot["vramUsedMiB"] == 0
    assert snapshot["gpuTempC"] is None and snapshot["gpuPowerW"] is None


def test_ram_probe_failure_never_uses_the_persisted_ram_sample(telemetry, monkeypatch):
    runtime, _ = telemetry
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(total=0, available=0))
    with pytest.raises(DreamApiError):
        runtime.hardware()


@pytest.mark.parametrize(("error", "category", "cause", "diagnostic"), [
    (FileNotFoundError(2, "private-path-secret"), "probe_missing", "FileNotFoundError", "errno=2"),
    (PermissionError(13, "private-path-secret"), "probe_denied", "PermissionError", "errno=13"),
    (OSError(5, "private-path-secret"), "os_error", "OSError", "errno=5"),
    (subprocess.TimeoutExpired("private-path-secret", 1.5, stderr="private-path-secret"), "probe_timeout", "TimeoutExpired", "timeout_seconds=1.5"),
    (subprocess.CalledProcessError(9, "private-path-secret", stderr="private-path-secret"), "probe_exit", "CalledProcessError", "returncode=9"),
    (subprocess.SubprocessError("private-path-secret"), "subprocess_error", "SubprocessError", ""),
    (ValueError("private-path-secret" * 1000), "invalid_sample", "ValueError", ""),
    (psutil.AccessDenied(123, "private-path-secret"), "system_probe_error", "AccessDenied", ""),
])
def test_failed_cached_sample_logs_once_with_safe_diagnostics_and_keeps_api_generic(telemetry, caplog, error, category, cause, diagnostic):
    runtime, state = telemetry
    state["error"] = error
    client = TestClient(create_app(config=runtime.config, runtime=runtime))
    with caplog.at_level(logging.WARNING, logger="hardware_telemetry"):
        for _ in range(5):
            response = client.get("/api/hardware")
            assert response.status_code == 503
            assert response.json()["code"] == "HARDWARE_TELEMETRY_UNAVAILABLE"
            assert response.json()["retryable"] is True
            assert "private-path-secret" not in response.text
            assert "gpuUtil" not in response.json()
        records = [record for record in caplog.records if record.name == "hardware_telemetry"]
        assert len(records) == 1
        message = records[0].getMessage()
        assert f"category={category}" in message and f"cause={cause}" in message
        assert diagnostic in message
        assert "private-path-secret" not in message and len(message) < 256
        assert records[0].exc_info is None
        assert len(state["calls"]) == 1
        state["now"] = 13.0
        assert client.get("/api/hardware").status_code == 503
        assert len([record for record in caplog.records if record.name == "hardware_telemetry"]) == 2
        state["now"] = 16.0
        state["error"] = None
        assert client.get("/api/hardware").status_code == 200
        assert len([record for record in caplog.records if record.name == "hardware_telemetry"]) == 2


@pytest.mark.parametrize(("row", "returncode", "cause"), [
    ("bad,row", 0, "invalid_gpu_row"),
    ("Live GPU, 6141, N/A, 80, 57, 32.5, 595.95", 0, "invalid_gpu_values"),
    ("Live GPU, 6141, 1506, 80, 57, 32.5, 595.95", 7, "CalledProcessError"),
])
def test_invalid_driver_result_logs_a_specific_safe_cause(telemetry, monkeypatch, caplog, row, returncode, cause):
    runtime, _ = telemetry
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, returncode, row, "private-stderr\n" * 10000))
    with caplog.at_level(logging.WARNING, logger="hardware_telemetry"), pytest.raises(DreamApiError):
        runtime.hardware()
    records = [record for record in caplog.records if record.name == "hardware_telemetry"]
    assert len(records) == 1
    assert f"cause={cause}" in records[0].getMessage()
    assert "private-stderr" not in records[0].getMessage()
    assert len(records[0].getMessage()) < 256


def test_telemetry_failure_does_not_replace_generation_validation_or_operations_guard(telemetry, monkeypatch):
    runtime, state = telemetry
    submitted = []
    monkeypatch.setattr(runtime.job_runner, "submit", lambda request: submitted.append(request) or {"id": "test-job"})
    state["error"] = FileNotFoundError("missing probe")
    client = TestClient(create_app(config=runtime.config, runtime=runtime))
    assert client.get("/api/hardware").status_code == 503
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=10 * 1024**3))
    missing = client.post("/api/generate", json={"prompt": "mountain lake", "modelId": "missing", "seed": 42})
    assert missing.json()["code"] == "MODEL_NOT_FOUND"
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=1024**3))
    blocked = client.post("/api/generate", json={"prompt": "mountain lake", "modelId": "model", "seed": 42})
    assert blocked.status_code == 507
    assert blocked.json()["code"] == "DISK_SPACE_LOW"
    assert submitted == []
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=10 * 1024**3))
    accepted = client.post("/api/generate", json={"prompt": "mountain lake", "modelId": "model", "seed": 42})
    assert accepted.status_code == 200 and accepted.json()["id"] == "test-job"
    assert len(submitted) == 1 and submitted[0].model_id == "model"


def test_concurrent_failed_reads_share_one_probe_and_one_warning(telemetry, caplog):
    runtime, state = telemetry
    state["error"] = subprocess.TimeoutExpired("nvidia-smi", 1.5)

    def read(_):
        with pytest.raises(DreamApiError) as failure:
            runtime.hardware()
        return failure.value.code

    with caplog.at_level(logging.WARNING, logger="hardware_telemetry"), ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(read, range(8))) == ["HARDWARE_TELEMETRY_UNAVAILABLE"] * 8
    assert len(state["calls"]) == 1
    assert len([record for record in caplog.records if record.name == "hardware_telemetry"]) == 1
