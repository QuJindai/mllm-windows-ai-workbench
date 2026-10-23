"""Real service + serial executor + CPU child, with no GPU or live service."""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from job_runner import JobRunner, NativeRunResult
from models import GenerateRequest
from test_generation_jobs import make_config


CPU_WORKER = '''import sys,json,pathlib,os
print(json.dumps({"type":"worker_ready","protocol":1,"pid":os.getpid()}),flush=True)
for line in sys.stdin:
    request=json.loads(line)
    items=request["payload"]["items"]
    results=[]
    for item in items:
        for field in ("outputPath","metadataPath"):
            path=pathlib.Path(item[field]);path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text("{}")
        results.append({"jobId":item["jobId"],"metadata":{}})
    print(json.dumps({"id":request["id"],"ok":True,"result":{"ok":True,"items":results,"sessionReused":False}}),flush=True)
'''


@pytest.fixture
def service_case(tmp_path, monkeypatch):
    import identity_service
    from identity_persistent_worker import PersistentWorkerClient
    config = make_config(tmp_path)
    settings = config.dream_root / "data/identity/runtime.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"python": sys.executable, "persistentWorker": True}))
    monkeypatch.setenv("DREAM_IDENTITY_CONFIG", str(settings))
    def factory(command, **kwargs):
        assert command[-1] == "--persistent"
        assert "--ownership-handshake" in command and kwargs["ownership_handshake"] is True
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        return PersistentWorkerClient([sys.executable, "-u", "-c", CPU_WORKER], **kwargs)
    assert hasattr(identity_service, "PersistentWorkerClient"), "Service transport integration missing"
    monkeypatch.setattr(identity_service, "PersistentWorkerClient", factory)
    native_calls = []
    def native(command, env, cwd, stdout_log, stderr_log):
        assert all(child.poll() is not None for child in children), "native overlapped warm identity process"
        native_calls.append(command)
        Path(command[command.index("--output") + 1]).write_bytes(b"png")
        Path(command[command.index("--metadata") + 1]).write_text("{}")
        return NativeRunResult(0, "", "")
    children = []
    runner = JobRunner(config, command_runner=native)
    service = identity_service.IdentityService(config, runner)
    def payload(index):
        return {"items": [{"jobId": f"cpu-{index}", "outputPath": str(tmp_path / f"{index}.png"), "metadataPath": str(tmp_path / f"{index}.json")}], "dreamRoot": str(config.dream_root), "configPath": str(settings)}
    try:
        yield service, runner, payload, children, native_calls
    finally:
        service.close()
        runner._executor.shutdown(wait=True, cancel_futures=True)


def test_service_dispatch_reuses_child_then_native_barrier_releases_it(service_case):
    service, runner, payload, children, native_calls = service_case
    assert runner.submit_serial(service._worker, "batch", payload(0)).result(5)["ok"]
    child = service._persistent_worker.process
    children.append(child)
    assert runner.submit_serial(service._worker, "batch", payload(1)).result(5)["ok"]
    assert service._persistent_worker.process is child
    job = runner.submit(GenerateRequest(modelId="model", prompt="lake", seed=42, traceLevel="off"))
    runner.submit_serial(lambda: None).result(5)
    assert runner.get(job["id"])["state"] == "complete"
    assert len(native_calls) == 1
    assert child.poll() is not None


def test_service_close_waits_for_warm_child_exit(service_case):
    service, runner, payload, children, _ = service_case
    runner.submit_serial(service._worker, "batch", payload(0)).result(5)
    children.append(service._persistent_worker.process)
    service.close()
    assert children[0].poll() is not None


@pytest.mark.parametrize("operation", ["inspect", "prepare", "anime_prepare", "status"])
def test_other_worker_operations_release_warm_session_except_cpu_status(service_case, monkeypatch, operation):
    import identity_service
    from types import SimpleNamespace
    service, runner, payload, children, _ = service_case
    runner.submit_serial(service._worker, "batch", payload(0)).result(5)
    child = service._persistent_worker.process
    children.append(child)
    def legacy(command, **kwargs):
        assert (child.poll() is None) == (operation == "status")
        Path(command[command.index("--result") + 1]).write_text('{"ok":true}')
        return SimpleNamespace(returncode=0, poll=lambda: 0, communicate=lambda **kwargs: ("", ""), wait=lambda **kwargs: 0)
    monkeypatch.setattr(identity_service.subprocess, "Popen", legacy)
    monkeypatch.setattr(identity_service, "WorkerLifetime", lambda process: SimpleNamespace(close=lambda: None))
    assert runner.submit_serial(service._worker, operation, {}).result(5)["ok"]


def test_native_before_run_failure_blocks_all_inference(tmp_path):
    config = make_config(tmp_path)
    def forbidden(*args):
        pytest.fail("native inference crossed failed release barrier")
    runner = JobRunner(config, command_runner=forbidden)
    def barrier():
        raise RuntimeError("owned child could not be reaped")
    assert hasattr(runner, "add_before_run"), "Native release callback is missing"
    runner.add_before_run(barrier)
    try:
        job = runner.submit(GenerateRequest(modelId="model", prompt="lake", traceLevel="off"))
        runner.submit_serial(lambda: None).result(5)
        assert runner.get(job["id"])["state"] == "failed"
        assert "GPU" in runner.get(job["id"])["error"]
    finally:
        runner._executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.skipif(sys.platform != "win32", reason="Real Windows release failure")
def test_real_job_query_failure_keeps_owner_and_blocks_native_until_release_retry(service_case, monkeypatch):
    import ctypes
    service, runner, payload, children, native_calls = service_case
    runner.submit_serial(service._worker, "batch", payload(0)).result(5)
    client = service._persistent_worker
    owner = client._lifetime
    handle = owner.handle
    children.append(client.process)
    with monkeypatch.context() as patch:
        def denied(*args):
            ctypes.set_last_error(5)
            return 0
        patch.setattr(owner.kernel, "QueryInformationJobObject", denied)
        job = runner.submit(GenerateRequest(modelId="model", prompt="lake", traceLevel="off"))
        runner.submit_serial(lambda: None).result(5)
        assert runner.get(job["id"])["state"] == "failed"
        assert not native_calls
        assert service._persistent_worker is client and owner.handle == handle
        assert client.process is not None
    # Retry through the same actual native barrier, not a test-only cleanup.
    next_job = runner.submit(GenerateRequest(modelId="model", prompt="lake", traceLevel="off"))
    runner.submit_serial(lambda: None).result(5)
    assert runner.get(next_job["id"])["state"] == "complete"
    assert len(native_calls) == 1 and owner.handle is None


def test_worker_status_recognizes_illustrious_visual_readiness(tmp_path, monkeypatch):
    import identity_worker
    import identity_models
    import identity_face_polish
    import identity_anime
    import identity_visual_polish
    request, result = tmp_path / "request.json", tmp_path / "result.json"
    request.write_text("{}")
    monkeypatch.setattr(identity_worker, "load_config", lambda *args, **kwargs: {})
    monkeypatch.setattr(identity_worker, "require_dependencies", lambda: None)
    monkeypatch.setattr(identity_models, "identity_model_catalog", lambda config: [{"id": "illustrious-xl-v2.0-plus-face", "name": "fixture", "ready": True, "loras": []}])
    monkeypatch.setattr(identity_face_polish, "face_polish_status", lambda config: {"ready": False})
    monkeypatch.setattr(identity_anime, "anime_status", lambda config: {"ready": False})
    monkeypatch.setattr(identity_visual_polish, "visual_polish_status", lambda config: {"ready": True, "message": "ready"})
    monkeypatch.setattr(sys.stdout, "reconfigure", lambda **kwargs: None, raising=False)
    monkeypatch.setattr(sys.stderr, "reconfigure", lambda **kwargs: None, raising=False)
    monkeypatch.setattr(sys, "argv", ["worker", "--operation", "status", "--request", str(request), "--result", str(result)])
    assert identity_worker.main() == 0
    assert json.loads(result.read_text(encoding="utf-8"))["visualPolish"]["ready"] is True
