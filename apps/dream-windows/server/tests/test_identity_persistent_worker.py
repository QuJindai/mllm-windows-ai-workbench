import copy
import importlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


def transport():
    assert importlib.util.find_spec("identity_persistent_worker"), "Persistent transport is missing"
    return importlib.import_module("identity_persistent_worker")


@pytest.fixture
def fixture(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    config = {}
    for key in ("checkpoint", "adapter", "faceLora", "clipVision"):
        path = assets / key
        path.write_bytes(key.encode())
        config[key] = str(path)
    for key in ("pipelineConfig", "insightfaceRoot", "lorasDir"):
        path = assets / key
        path.mkdir()
        (path / "config.json").write_text("{}")
        config[key] = str(path)
    image = tmp_path / "reference.png"
    image.write_bytes(b"reference")
    def payload(index=0, **changes):
        return {"dreamRoot": str(tmp_path), "previewEvery": 0, "items": [{
            "referenceId": "ref-" + "a" * 24, "faceIndex": 0, "prompt": "landscape", "seed": 42 + index,
            "jobId": "identity-" + f"{index:024x}", "imagePath": str(image), "dreamRoot": str(tmp_path),
            "outputPath": str(tmp_path / f"output-{index}.png"), "metadataPath": str(tmp_path / f"output-{index}.json"),
            **changes,
        }]}
    return config, payload


def test_key_allows_only_per_render_changes_and_hashes_reference_bytes(fixture):
    module = transport()
    config, payload = fixture
    original = module.build_compatibility_key(config, payload())
    assert len(original) == 64
    assert module.build_compatibility_key(config, payload(1, prompt="lake", negativePrompt="fog", steps=10)) == original
    image = Path(payload()["items"][0]["imagePath"])
    before = image.stat()
    image.write_bytes(b"Reference")
    os.utime(image, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert module.build_compatibility_key(config, payload()) != original


@pytest.mark.parametrize("change", [
    {"identityStrength": .3}, {"structureStrength": .3}, {"faceLoraStrength": .2},
    {"loraStrength": .2}, {"faceIndex": 1}, {"width": 768}, {"cfg": 4.},
    {"facePolish": True}, {"animeDenoiseStrength": .5}, {"faceRestoreStrength": .5},
    {"visualPolishPrompt": "clean"}, {"visualPolishNegativePrompt": "blur"},
    {"traceLevel": "basic"}, {"researchCoverage": "extended"}, {"futureFixedParameter": 42},
])
def test_key_covers_all_fixed_and_unknown_future_parameters(fixture, change):
    config, payload = fixture
    assert transport().build_compatibility_key(config, payload()) != transport().build_compatibility_key(config, payload(**change))


@pytest.mark.parametrize("asset", ["checkpoint", "adapter", "faceLora", "clipVision", "pipelineConfig", "lorasDir"])
def test_key_invalidates_changed_assets_and_config(fixture, asset):
    config, payload = fixture
    module = transport()
    original = module.build_compatibility_key(config, payload())
    path = Path(config[asset])
    if path.is_dir():
        path = path / "config.json"
    path.write_bytes(b"changed")
    assert module.build_compatibility_key(config, payload()) != original
    assert module.build_compatibility_key({**config, "futureSetting": 1}, payload()) != original


def test_unreadable_asset_directory_fails_closed(fixture, monkeypatch):
    config, payload = fixture
    def denied(*args, **kwargs):
        raise PermissionError("unreadable asset directory")
    monkeypatch.setattr(os, "scandir", denied)
    with pytest.raises(PermissionError):
        transport().build_compatibility_key(config, payload())


class CpuSession:
    """Only the GPU inference boundary is replaced; publication/transport are real."""
    created = []

    def __init__(self, config, first, emit):
        self.started = time.perf_counter()
        self.initial_stages = [{"name": "load", "durationMs": 12}]
        self.created.append(self)

    def render(self, item, index, emit, preview_dir, preview_every):
        Path(item["outputPath"]).write_bytes(b"cpu-test-image")
        metadata = {"jobId": item["jobId"], "stages": list(self.initial_stages), "batchItemIndex": index, "modelReused": index > 0}
        Path(item["metadataPath"]).write_text(json.dumps(metadata))
        return {"jobId": item["jobId"], "metadata": metadata}


def test_real_batch_transport_reuses_one_session_resets_timing_and_keeps_local_indices(fixture, monkeypatch):
    config, payload = fixture
    monkeypatch.setattr(CpuSession, "created", [])
    worker = transport().WarmBatchWorker(lambda request: config, session_factory=CpuSession, reset_metrics=lambda: None)
    first = worker.run_batch(payload())
    original_bytes = Path(payload()["items"][0]["metadataPath"]).read_bytes()
    second = worker.run_batch(payload(1))
    assert len(CpuSession.created) == 1
    assert first["sessionReused"] is False and second["sessionReused"] is True
    assert second["items"][0]["metadata"]["batchItemIndex"] == 0
    assert second["items"][0]["metadata"]["stages"] == []
    assert second["items"][0]["metadata"]["sessionReused"] is True
    assert json.loads(Path(payload(1)["items"][0]["metadataPath"]).read_text())["sessionReused"] is True
    assert Path(payload()["items"][0]["metadataPath"]).read_bytes() == original_bytes


def test_incompatible_session_exits_before_render_and_does_not_create_second_session(fixture, monkeypatch):
    config, payload = fixture
    module = transport()
    monkeypatch.setattr(CpuSession, "created", [])
    worker = module.WarmBatchWorker(lambda request: config, session_factory=CpuSession, reset_metrics=lambda: None)
    worker.run_batch(payload())
    with pytest.raises(module.WorkerRestartRequired):
        worker.run_batch(payload(1, faceIndex=1))
    assert worker.closed
    assert len(CpuSession.created) == 1
    assert not Path(payload(1)["items"][0]["outputPath"]).exists()


def test_render_error_permanently_resets_worker_and_keeps_completed_output(fixture):
    config, payload = fixture
    class Failing(CpuSession):
        def render(self, item, *args):
            if item["seed"] == 43:
                raise RuntimeError("private-path-and-command")
            return super().render(item, *args)
    module = transport()
    worker = module.WarmBatchWorker(lambda request: config, session_factory=Failing, reset_metrics=lambda: None)
    worker.run_batch(payload())
    with pytest.raises(RuntimeError):
        worker.run_batch(payload(1))
    assert worker.closed
    assert Path(payload()["items"][0]["outputPath"]).read_bytes() == b"cpu-test-image"
    with pytest.raises(RuntimeError):
        worker.run_batch(payload(2))


def test_existing_output_and_mixed_fixed_parameters_rejected_before_load(fixture):
    config, payload = fixture
    def forbidden(*args):
        pytest.fail("session loaded before validation")
    module = transport()
    first = payload()
    first["items"] += payload(1, faceRestoreStrength=.2)["items"]
    with pytest.raises(ValueError):
        module.WarmBatchWorker(lambda request: config, session_factory=forbidden).run_batch(first)
    output = Path(payload()["items"][0]["outputPath"])
    output.write_bytes(b"protected")
    with pytest.raises(ValueError):
        module.WarmBatchWorker(lambda request: config, session_factory=forbidden).run_batch(payload())
    assert output.read_bytes() == b"protected"


def test_protocol_error_is_sanitized_exits_and_never_reads_another_request(fixture):
    config, payload = fixture
    module = transport()
    worker = module.WarmBatchWorker(lambda request: (_ for _ in ()).throw(ValueError("secret-private-path")))
    commands = [{"id": "one", "op": "batch", "payload": payload()}, {"id": "two", "op": "batch", "payload": payload(1)}]
    source = io.BytesIO(b"".join(json.dumps(command).encode() + b"\n" for command in commands))
    target = io.BytesIO()
    assert module.serve(worker, source, target) == 1
    result = json.loads(target.getvalue())
    assert result["id"] == "one" and result["ok"] is False
    assert "secret-private-path" not in target.getvalue().decode()
    assert worker.closed


@pytest.mark.parametrize("ending", ["idle", "eof"])
def test_cli_persistent_idle_and_eof_exit_without_importing_models(ending):
    worker = Path(__file__).resolve().parents[1] / "identity_worker.py"
    process = subprocess.Popen([sys.executable, str(worker), "--persistent", "--idle-ttl", "0.1"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        if ending == "eof":
            process.stdin.close()
            process.stdin = None
        code = process.wait(timeout=5)
        assert code == 0, process.stderr.read().decode("utf-8", errors="replace")
        assert process.stdout.read() == b""
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


def cpu_client(module, script, tmp_path, lifecycle=None):
    events = lifecycle if lifecycle is not None else []
    def lifetime(process):
        events.append("owned")
        def close():
            assert process.poll() is not None, "ownership released before process exit"
            events.append("released")
        return SimpleNamespace(close=close)
    return module.PersistentWorkerClient([sys.executable, "-u", "-c", script], cwd=tmp_path, env=os.environ.copy(), lifetime_factory=lifetime)


ECHO_CHILD = '''import sys,json
for line in sys.stdin:
    request=json.loads(line)
    print(json.dumps({"id":request["id"],"ok":True,"result":{"ok":True,"items":[]}}),flush=True)
'''


def test_parent_reuses_only_owned_child_and_release_is_a_wait_barrier(tmp_path):
    events = []
    client = cpu_client(transport(), ECHO_CHILD, tmp_path, events)
    try:
        assert client.run_batch({"items": []})["ok"]
        assert client.run_batch({"items": []})["ok"]
        assert events == ["owned"]
        client.release()
        assert events == ["owned", "released"]
        assert client.run_batch({"items": []})["ok"]
    finally:
        client.close()
    assert events == ["owned", "released", "owned", "released"]
    with pytest.raises(RuntimeError):
        client.run_batch({"items": []})


@pytest.mark.parametrize("action", ["cancel", "close", "timeout", "event"])
def test_parent_cancellation_timeout_and_close_release_owned_child(tmp_path, action):
    module = transport()
    client = cpu_client(module, "import time; time.sleep(20)", tmp_path)
    cancelled = threading.Event()
    errors = []
    def run():
        try:
            client.run_batch({"items": []}, cancelled=cancelled, timeout=.1 if action == "timeout" else 5)
        except RuntimeError as exc:
            errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        deadline = time.monotonic() + 3
        while client.process is None and time.monotonic() < deadline:
            time.sleep(.01)
        owned = client.process
        assert owned is not None
        if action == "event":
            cancelled.set()
        elif action != "timeout":
            getattr(client, action)()
        thread.join(4)
        assert not thread.is_alive()
        assert owned.poll() is not None
        assert errors
    finally:
        client.close()
        thread.join(3)


def test_parent_protocol_failure_never_replays_request(tmp_path):
    events = []
    client = cpu_client(transport(), "import sys; sys.stdin.readline(); print('private invalid response',flush=True)", tmp_path, events)
    with pytest.raises(RuntimeError, match="protocol"):
        client.run_batch({"items": []})
    assert events == ["owned", "released"]
    assert client.process is None


def test_large_request_timeout_cannot_block_on_child_stdin(tmp_path):
    client = cpu_client(transport(), "import time; time.sleep(20)", tmp_path)
    errors = []
    def run():
        try:
            client.run_batch({"items": [], "padding": "x" * 200000}, timeout=.1)
        except RuntimeError as exc:
            errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        thread.join(2)
        assert not thread.is_alive(), "stdin write bypassed the request deadline"
        assert errors
    finally:
        client.close()
        thread.join(3)


def test_release_does_not_leave_blocked_protocol_threads(tmp_path):
    before = set(threading.enumerate())
    script = ECHO_CHILD.replace("flush=True)", "flush=True)\n    print('{}',flush=True)\n    print('{}',flush=True)")
    client = cpu_client(transport(), script, tmp_path)
    try:
        client.run_batch({"items": []})
    finally:
        client.close()
    deadline = time.monotonic() + .5
    while time.monotonic() < deadline and set(threading.enumerate()) - before:
        time.sleep(.01)
    assert not (set(threading.enumerate()) - before), "protocol reader remained blocked after child exit"


def test_cold_session_forces_fresh_feature_fingerprints(fixture):
    config, payload = fixture
    class Session(CpuSession):
        def __init__(self, config, first, emit):
            assert first.get("forceFingerprint") is True
            super().__init__(config, first, emit)
    transport().WarmBatchWorker(lambda request: config, session_factory=Session).run_batch(payload())


def test_reused_batch_resets_peak_metrics_before_render(fixture):
    config, payload = fixture
    resets = []
    class Session(CpuSession):
        def render(self, item, *args):
            assert len(resets) == item["seed"] - 42
            return super().render(item, *args)
    worker = transport().WarmBatchWorker(lambda request: config, session_factory=Session, reset_metrics=lambda: resets.append(True))
    worker.run_batch(payload())
    worker.run_batch(payload(1))


def test_cancel_during_startup_does_not_spawn_a_child_after_cancel_returns(tmp_path, monkeypatch):
    client = cpu_client(transport(), ECHO_CHILD, tmp_path)
    reached, proceed = threading.Event(), threading.Event()
    original = client._start
    def delayed(*args):
        reached.set()
        assert proceed.wait(3)
        return original(*args)
    monkeypatch.setattr(client, "_start", delayed)
    errors = []
    def run():
        try:
            client.run_batch({"items": []})
        except RuntimeError as exc:
            errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert reached.wait(2)
        client.cancel()
        proceed.set()
        thread.join(3)
        assert not thread.is_alive()
        assert errors and client.process is None
    finally:
        proceed.set()
        client.close()
        thread.join(3)


def test_parent_restarts_only_before_render_and_limits_restart_attempts(tmp_path):
    events = []
    script = '''import sys,json
request=json.loads(sys.stdin.readline())
print(json.dumps({"id":request["id"],"ok":False,"code":"RESTART_REQUIRED"}),flush=True)
'''
    client = cpu_client(transport(), script, tmp_path, events)
    with pytest.raises(RuntimeError, match="worker failed"):
        client.run_batch({"items": []})
    assert events == ["owned", "released", "owned", "released"]
    assert client.process is None


def test_process_batch_budget_restarts_before_any_additional_output(fixture, monkeypatch):
    config, payload = fixture
    module = transport()
    monkeypatch.setattr(module, "MAX_BATCHES", 1)
    worker = module.WarmBatchWorker(lambda request: config, session_factory=CpuSession)
    worker.run_batch(payload())
    with pytest.raises(module.WorkerRestartRequired):
        worker.run_batch(payload(1))
    assert worker.closed
    assert not Path(payload(1)["items"][0]["outputPath"]).exists()


def stdin_initialization_client(tmp_path, initialization, python=sys.executable):
    # Windows venv launchers have a second interpreter process. Use the real
    # service ownership mechanism so a failed regression cannot orphan it.
    from identity_service import WorkerLifetime
    script = '''import os,sys
from identity_persistent_worker import serve
class Worker:
    def run_batch(self, request):
        INITIALIZATION
        return {"ok":True,"items":[],"initialized":True}
    def close(self): pass
os._exit(serve(Worker(),sys.stdin.buffer,sys.stdout.buffer,idle_ttl=.5,ownership_handshake=True))
'''.replace("INITIALIZATION", initialization)
    env = os.environ.copy()
    env.update(PYTHONPATH=str(Path(__file__).resolve().parents[1]), CUDA_VISIBLE_DEVICES="-1",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    return transport().PersistentWorkerClient([python, "-u", "-c", script], cwd=tmp_path,
        env=env, lifetime_factory=lambda process: WorkerLifetime(process, awaiting_worker=True), ownership_handshake=True)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows CRT stdin descriptor lock")
def test_request_initialization_can_duplicate_stdin_without_reader_lock(tmp_path):
    client = stdin_initialization_client(tmp_path, "descriptor=os.dup(0); os.close(descriptor)")
    try:
        # Keep stdin open: communicate(input=...) would hide the deadlock by EOF.
        assert client.run_batch({"items": []}, timeout=3)["initialized"]
        assert client.run_batch({"items": []}, timeout=3)["initialized"]
    finally:
        client.close()


@pytest.mark.skipif(not os.environ.get("DREAM_IDENTITY_TEST_PYTHON"), reason="opt-in installed identity runtime; no dependency install")
def test_installed_torch_initializes_on_cpu_with_persistent_stdin_open(tmp_path):
    client = stdin_initialization_client(tmp_path,
        "import torch; assert torch.ones(1,device='cpu').item()==1",
        os.environ["DREAM_IDENTITY_TEST_PYTHON"])
    try:
        assert client.run_batch({"items": []}, timeout=20)["initialized"]
        assert client.run_batch({"items": []}, timeout=3)["initialized"]
    finally:
        client.close()


def test_startup_stages_are_published_before_validation_and_session_initialization(fixture, tmp_path):
    config, payload = fixture
    event_path = tmp_path / "events.ndjson"
    def stages():
        return [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    def loader(request):
        assert stages()[-1]["stage"] == "校验模型与参考文件"
        return config
    class Session(CpuSession):
        def __init__(self, *args):
            assert stages()[-1]["stage"] == "初始化 CUDA 与身份会话"
            super().__init__(*args)
    transport().WarmBatchWorker(loader, session_factory=Session).run_batch({**payload(), "eventPath": str(event_path)})
    events = stages()
    assert events[-1]["type"] == "item_complete"
    assert [event["elapsedMs"] for event in events] == sorted(event["elapsedMs"] for event in events)


def test_component_import_failure_reports_import_stage_without_claiming_cuda(fixture, tmp_path, monkeypatch):
    config, payload = fixture
    event_path = tmp_path / "events.ndjson"
    monkeypatch.setitem(sys.modules, "torch", None)
    worker = transport().WarmBatchWorker(lambda request: config)
    with pytest.raises(ImportError):
        worker.run_batch({**payload(), "eventPath": str(event_path)})
    events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    assert [event["stage"] for event in events] == ["校验模型与参考文件", "导入推理组件"]
    assert worker.closed
