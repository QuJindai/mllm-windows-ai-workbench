"""P0 diagnostics: no inference, no live service, and no archive mutations."""
import importlib
import importlib.util
import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import create_app
from config import DreamServerConfig
from errors import DreamApiError


GIB = 1024 ** 3


def operations():
    assert importlib.util.find_spec("operations") is not None, "P0 operations module is missing"
    return importlib.import_module("operations")


@pytest.fixture
def config(tmp_path):
    return replace(
        DreamServerConfig.for_testing(), dream_root=tmp_path,
        frontend_dist=tmp_path / "frontend", core_exe=tmp_path / "core.exe",
        engine_exe=tmp_path / "engine.exe", wrapper=tmp_path / "wrapper.cmd",
        registry_path=tmp_path / "registry.json",
    )


def disk(monkeypatch, free):
    monkeypatch.setattr(shutil, "disk_usage", lambda path: SimpleNamespace(free=free))


@pytest.mark.parametrize("free,status,allowed", [
    (0, "blocked", False), (2 * GIB - 1, "blocked", False),
    (2 * GIB, "warning", True), (10 * GIB - 1, "warning", True),
    (10 * GIB, "ok", True), (20 * GIB, "ok", True),
])
def test_capacity_boundaries_preserve_exact_bytes(config, monkeypatch, free, status, allowed):
    disk(monkeypatch, free)
    result = operations().get_operations(config)["disk"]
    assert (result["status"], result["freeBytes"], result["generationAllowed"]) == (status, free, allowed)
    if allowed:
        assert operations().ensure_generation_capacity(config) == result
    else:
        with pytest.raises(DreamApiError) as caught:
            operations().ensure_generation_capacity(config)
        assert caught.value.status_code == 507
        assert caught.value.code == "DISK_SPACE_LOW"
        assert caught.value.detail["freeBytes"] == free


@pytest.mark.parametrize("free", [None, -1, True, float("nan"), "0"])
def test_invalid_measurement_is_unknown_not_zero(config, monkeypatch, free):
    disk(monkeypatch, free)
    result = operations().ensure_generation_capacity(config)
    assert result["status"] == "unknown"
    assert result["freeBytes"] is None
    assert result["generationAllowed"] is None


def test_unreadable_disk_does_not_create_paths_or_leak_errors(config, monkeypatch):
    def unavailable(path):
        raise OSError(r"C:\Users\Private\token=secret; powershell private-command")
    monkeypatch.setattr(shutil, "disk_usage", unavailable)
    config = replace(config, dream_root=config.dream_root / "not-created")
    result = operations().ensure_generation_capacity(config)
    assert result["status"] == "unknown"
    assert result["freeBytes"] is None
    assert not config.dream_root.exists()
    assert "Private" not in json.dumps(result)
    assert "secret" not in json.dumps(result)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_snapshot_is_allowlisted_read_only_and_counts_records(config, monkeypatch):
    disk(monkeypatch, 8 * GIB)
    for path in [config.core_exe, config.engine_exe, config.wrapper, config.registry_path]:
        path.write_text("fixture", encoding="utf-8")
    write_json(config.frontend_dist / "release.json", {
        "release": "p0-test-20261023", "commit": "a" * 40,
        "path": r"C:\Users\Private", "command": "private-command", "token": "secret",
    })
    (config.frontend_dist / "index.html").write_text("<html></html>")
    for folder, prefix in [("jobs", "job"), ("identity/jobs", "identity"), ("identity/batches", "batch")]:
        for index, state in enumerate(["queued", "sampling", "complete", "failed", "cancelled"]):
            write_json(config.dream_root / "data" / folder / f"{prefix}-{index}.json", {
                "state": state, "request": {"prompt": "private-prompt"}, "command": "private-command",
            })
    # index is metadata, never another pending job.
    write_json(config.dream_root / "data/identity/jobs/index.json", {"ids": ["private-id"]})
    before = {p.relative_to(config.dream_root): p.read_bytes() for p in config.dream_root.rglob("*") if p.is_file()}
    result = operations().get_operations(config)
    after = {p.relative_to(config.dream_root): p.read_bytes() for p in config.dream_root.rglob("*") if p.is_file()}
    assert before == after
    assert result["release"]["release"] == "p0-test-20261023"
    assert result["release"]["commit"] == "a" * 40
    for source in ("ordinary", "identity", "batches"):
        assert result["pendingWork"][source] == {"status": "known", "pendingCount": 2}
    checks = {check["id"]: check["status"] for check in result["checks"]}
    assert checks["frontend"] == checks["core"] == checks["engine"] == "ok"
    serialized = json.dumps(result)
    for private in ("Private", "private-command", "secret", "private-prompt", "private-id", str(config.dream_root)):
        assert private not in serialized


@pytest.mark.parametrize("release", [r"C:\Users\Private", "/home/private", "pwsh -Command secret", "sk-private-token"])
def test_release_identity_cannot_be_a_path_command_or_secret(config, release):
    write_json(config.frontend_dist / "release.json", {"release": release})
    result = operations().get_operations(config)["release"]
    assert result["release"] is None
    assert result["status"] == "unknown"


def test_missing_corrupt_and_empty_job_records_are_distinct(config):
    assert operations().get_operations(config)["pendingWork"]["ordinary"] == {"status": "unknown", "pendingCount": None}
    folder = config.dream_root / "data/jobs"
    folder.mkdir(parents=True)
    assert operations().get_operations(config)["pendingWork"]["ordinary"] == {"status": "known", "pendingCount": 0}
    (folder / "job-broken.json").write_text("{private-invalid-json")
    assert operations().get_operations(config)["pendingWork"]["ordinary"] == {"status": "unknown", "pendingCount": None}


def test_unknown_job_state_and_oversized_release_stay_unknown(config):
    write_json(config.dream_root / "data/jobs/job-invalid.json", {"state": "future-state"})
    write_json(config.frontend_dist / "release.json", {"release": "x" * 70000})
    result = operations().get_operations(config)
    assert result["pendingWork"]["ordinary"]["pendingCount"] is None
    assert result["release"]["status"] == "unknown"


def test_missing_assets_dependencies_and_access_failure_are_distinct(config, monkeypatch):
    module = operations()
    def missing(package):
        raise module.metadata.PackageNotFoundError(package)
    monkeypatch.setattr(module.metadata, "version", missing)
    original_stat = Path.stat
    def denied(path, *args, **kwargs):
        if path == config.engine_exe:
            raise PermissionError("private-secret-path")
        return original_stat(path, *args, **kwargs)
    monkeypatch.setattr(Path, "stat", denied)
    result = module.get_operations(config)
    checks = {check["id"]: check["status"] for check in result["checks"]}
    assert checks["frontend"] == checks["assets"] == checks["dependencies"] == "missing"
    assert checks["engine"] == "unknown"
    assert "private-secret-path" not in json.dumps(result)


def test_asset_presence_and_bounded_pending_scan(config, monkeypatch):
    assets = config.frontend_dist / "assets"
    assets.mkdir(parents=True)
    (assets / "index-fixture.js").write_text("fixture")
    for index in range(3):
        write_json(config.dream_root / f"data/jobs/job-{index}.json", {"state": "queued"})
    module = operations()
    monkeypatch.setattr(module, "MAX_RECORDS", 2)
    result = module.get_operations(config)
    assert next(check for check in result["checks"] if check["id"] == "assets")["status"] == "ok"
    assert result["pendingWork"]["ordinary"] == {"status": "unknown", "pendingCount": None}


class SubmissionRuntime:
    def __init__(self):
        self.submitted = []

    def generate(self, payload):
        self.submitted.append(payload)
        return {"id": "new-job"}

    def run_experiment(self, payload):
        return self.generate(payload)

    def history(self, query):
        return {"items": [], "total": 0}

    def get_job(self, job_id):
        return {"id": job_id, "state": "queued"}

    def cancel_job(self, job_id):
        return {"id": job_id, "state": "cancelled"}


@pytest.mark.parametrize("endpoint", ["/api/generate", "/api/experiments"])
def test_guard_runs_before_submission_and_preserves_reads_and_cancel(config, monkeypatch, endpoint):
    disk(monkeypatch, GIB)
    runtime = SubmissionRuntime()
    client = TestClient(create_app(config=config, runtime=runtime))
    response = client.post(endpoint, json={"modelId": "fixture", "prompt": "mountain lake", "seed": 42})
    assert response.status_code == 507
    assert response.json()["code"] == "DISK_SPACE_LOW"
    assert runtime.submitted == []
    assert client.get("/api/history").status_code == 200
    assert client.get("/api/jobs/existing").status_code == 200
    assert client.post("/api/jobs/existing/cancel").json()["state"] == "cancelled"


@pytest.mark.parametrize("free", [2 * GIB, 10 * GIB, None])
def test_allowed_or_unknown_capacity_keeps_ordinary_submission_working(config, monkeypatch, free):
    disk(monkeypatch, free)
    runtime = SubmissionRuntime()
    client = TestClient(create_app(config=config, runtime=runtime))
    assert client.post("/api/generate", json={"modelId": "fixture", "prompt": "lake"}).status_code == 200
    assert len(runtime.submitted) == 1


def test_operations_route_is_read_only_no_store_and_works_without_runtime(config, monkeypatch):
    disk(monkeypatch, 0)
    client = TestClient(create_app(config=config, runtime=object()))
    response = client.get("/api/operations")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["service"] == "dream-web"
    assert response.json()["schemaVersion"] == 1
    assert response.json()["disk"]["freeBytes"] == 0
    assert list(config.dream_root.iterdir()) == []


@pytest.mark.parametrize("listener,health,want", [
    (False, "throw 'private-secret-path'", "not-running"),
    (True, "throw 'private-secret-path'", "health-failed"),
    (True, "return @{ StatusCode=200; Content='{" + '"service":"other"' + "}' }", "port-conflict"),
    (True, "return @{ StatusCode=200; Content='{" + '"service":"dream-web","ok":true' + "}' }", "ready"),
])
def test_diagnostic_script_uses_mocked_probes_and_never_exposes_raw_data(listener, health, want):
    script = Path(__file__).resolve().parents[4] / "scripts/diagnose_dream_web.ps1"
    assert script.is_file(), "Read-only diagnostic script is missing"
    assert shutil.which("pwsh"), "PowerShell 7 is required for the diagnostic script tests"
    command = """
function Get-NetTCPConnection { %s }
function Invoke-WebRequest {
    param($Uri)
    if ($Uri -like '*/api/health') { %s }
    return @{ StatusCode=200; Content='{"schemaVersion":1,"service":"dream-web","disk":{"status":"warning","freeBytes":2147483648},"command":"private-secret-path"}' }
}
function Stop-Process { throw 'destructive action attempted' }
function Start-Process { throw 'service start attempted' }
& '%s' -Json
""" % ("@{OwningProcess=123; LocalPort=8766}" if listener else "return $null", health, script.as_posix())
    result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == want
    assert "private-secret-path" not in result.stdout + result.stderr
    if want == "ready":
        assert report["diskStatus"] == "warning"
        assert report["freeBytes"] == 2147483648
