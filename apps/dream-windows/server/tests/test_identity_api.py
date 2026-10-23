"""Real routes/storage/queue, with only the external process boundary controlled."""
from __future__ import annotations

import base64
import asyncio
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import create_app
from job_runner import JobRunner, NativeRunResult
from models import GenerateRequest
from persistent_engine import PersistentEngineClient, PersistentEngineUnavailable
from runtime import DreamRuntime
from test_generation_jobs import make_config

REAL_POPEN = subprocess.Popen


def image_base64(size=(12, 8), orientation=None):
    output = io.BytesIO()
    image = Image.new("RGB", size, "navy")
    if orientation:
        exif = Image.Exif()
        exif[274] = orientation
        image.save(output, format="JPEG", exif=exif)
    else:
        image.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


class WorkerBoundary:
    """Implements the specified file CLI without importing or running face models."""

    def __init__(self):
        self.calls = []
        self.children = []
        self.faces = [{"index": 0, "box": [1, 1, 3, 6]}, {"index": 1, "box": [4, 1, 7, 6]}]
        self.fail = None
        self.hold = None
        self.started = threading.Event()
        self.release = threading.Event()
        self.exit_allowed = threading.Event()
        self.exit_allowed.set()

    def spawn(self, command, **kwargs):
        assert len(command) == 8
        assert Path(command[1]).name == "identity_worker.py"
        assert command[2::2] == ["--operation", "--request", "--result"]
        operation = command[3]
        payload = json.loads(Path(command[5]).read_text(encoding="utf-8"))
        result_path = Path(command[7])
        self.calls.append((command, operation, payload, kwargs))
        boundary = self

        class Child:
            returncode = None
            pid = 432100
            stopped = False

            def poll(self):
                return self.returncode

            def terminate(self):
                self.stopped = True

            kill = terminate

            def wait(self, timeout=None):
                if timeout is None and self.stopped:
                    assert boundary.exit_allowed.wait(5)
                self.communicate(timeout=timeout)
                return self.returncode

            def communicate(self, timeout=None):
                if self.returncode is not None:
                    return "", ""
                if operation == boundary.hold:
                    boundary.started.set()
                    if not self.stopped and not boundary.release.wait(0.01):
                        raise subprocess.TimeoutExpired(command, timeout)
                if self.stopped:
                    if not boundary.exit_allowed.wait(0.01):
                        raise subprocess.TimeoutExpired(command, timeout)
                    self.returncode = -15
                    return "", "cancelled"
                if operation == boundary.fail:
                    self.returncode = 1
                    kwargs["stderr"].write("controlled worker diagnostic 人物\n".encode("utf-8"))
                    kwargs["stderr"].flush()
                    result_path.write_text(json.dumps({"ok": False, "code": "IDENTITY_WORKER_FAILED", "message": "controlled worker failure"}), encoding="utf-8")
                    return "", "controlled worker failure"
                if operation == "status":
                    assert set(payload) == {"configPath"}
                    result = {"ready": True, "modelName": "Realistic Vision V5.1", "message": "ready", "loras": [{"id": "style", "name": "Style"}]}
                elif operation == "inspect":
                    assert set(payload) == {"imagePath"}
                    with Image.open(payload["imagePath"]) as image:
                        assert image.format == "PNG"
                    result = {"faces": boundary.faces}
                else:
                    assert operation == "generate"
                    assert {"imagePath", "outputPath", "metadataPath", "jobId", "dreamRoot", "configPath"} <= payload.keys()
                    output = Path(payload["outputPath"])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    Image.new("RGB", (payload["width"], payload["height"])).save(output)
                    Path(payload["metadataPath"]).write_text(json.dumps({"seed": payload["seed"], "generation_time_ms": 17}), encoding="utf-8")
                    result = {"ok": True}
                result_path.write_text(json.dumps(result), encoding="utf-8")
                self.returncode = 0
                return "", ""

        child = Child()
        self.children.append(child)
        return child


def absent_native(*args):
    import urllib.error

    raise PersistentEngineUnavailable("connection refused") from urllib.error.URLError(ConnectionRefusedError())


@pytest.fixture
def harness(tmp_path, monkeypatch):
    import identity_service

    config = make_config(tmp_path)
    runtime_config = config.dream_root / "data" / "identity" / "runtime.json"
    runtime_config.parent.mkdir(parents=True)
    runtime_config.write_text(json.dumps({"python": sys.executable}), encoding="utf-8")
    monkeypatch.setenv("DREAM_IDENTITY_CONFIG", str(runtime_config))
    boundary = WorkerBoundary()
    monkeypatch.setattr(subprocess, "Popen", boundary.spawn)
    monkeypatch.setattr(identity_service, "WorkerLifetime", lambda process: SimpleNamespace(close=lambda: None))
    runner = JobRunner(config, persistent_engine=PersistentEngineClient(config, transport=absent_native))
    runtime = DreamRuntime(config, job_runner=runner)
    with TestClient(create_app(config, runtime), base_url="http://127.0.0.1:8866") as client:
        try:
            yield client, config, runner, boundary
        finally:
            boundary.release.set()
            boundary.exit_allowed.set()
    runner._executor.shutdown(wait=True, cancel_futures=True)


def upload(client, **changes):
    response = client.post("/api/identity/references", json={"name": "人物.jpg", "imageBase64": image_base64(), **changes})
    assert response.status_code == 200, response.text
    return response.json()


def submit(client, reference, **changes):
    response = client.post("/api/identity/generate", json={"referenceId": reference["id"], "faceIndex": 1, "prompt": "portrait", "seed": 42, **changes})
    assert response.status_code == 200, response.text
    return response.json()


def finished(client, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/identity/jobs/{job_id}")
        assert response.status_code == 200, response.text
        value = response.json()
        if value["state"] in {"complete", "failed", "cancelled"}:
            return value
        time.sleep(0.01)
    pytest.fail("identity job did not become terminal")


def test_status_uses_configured_python_and_returns_loras(harness):
    client, config, _, boundary = harness
    response = client.get("/api/identity/status")
    assert response.status_code == 200
    assert response.json() == {"ready": True, "modelName": "Realistic Vision V5.1", "message": "ready", "loras": [{"id": "style", "name": "Style"}]}
    command, _, payload, options = boundary.calls[-1]
    assert command[0] == sys.executable
    assert payload["configPath"] == str(config.dream_root / "data" / "identity" / "runtime.json")
    assert options["env"]["DREAM_IDENTITY_CONFIG"] == payload["configPath"]
    assert options["env"]["PYTHONIOENCODING"] == "utf-8"
    assert options["env"]["HF_HUB_OFFLINE"] == "1"
    assert options["env"]["HF_HOME"] == str(config.dream_root / "cache" / "identity-hub")
    assert options["env"]["TEMP"] == str(config.dream_root / "temp")
    assert options["env"]["TMP"] == str(config.dream_root / "temp")
    assert Path(options["env"]["TEMP"]).is_dir()


def test_upload_normalizes_exif_and_persists_opaque_reference(harness):
    client, config, _, _ = harness
    reference = upload(client, name="../../portrait.jpg", imageBase64=image_base64(orientation=6))
    assert re.fullmatch(r"ref-[a-f0-9]{24}", reference["id"])
    assert len(reference["faces"]) == 2
    assert set(reference) == {"id", "name", "imageUrl", "faces"}
    response = client.get(reference["imageUrl"])
    assert response.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.size == (8, 12)
        assert not image.getexif()
    assert client.get("/api/identity/references").json() == [reference]
    assert not (config.dream_root / "portrait.jpg").exists()


@pytest.mark.parametrize("encoded", ["not base64", base64.b64encode(b"not an image").decode(), "A" * (14 * 1024 * 1024)], ids=["bad-base64", "bad-image", "too-large"])
def test_malformed_and_oversized_uploads_never_reach_worker(harness, encoded):
    client, config, _, boundary = harness
    response = client.post("/api/identity/references", json={"name": "x", "imageBase64": encoded})
    assert response.status_code in {413, 422}
    assert boundary.calls == []
    assert not list((config.dream_root / "data" / "identity" / "references").glob("*.png"))


def test_upload_rejects_more_than_16_megapixels(harness):
    client, _, _, boundary = harness
    response = client.post("/api/identity/references", json={"name": "big", "imageBase64": image_base64((4001, 4000))})
    assert response.status_code == 413
    assert boundary.calls == []


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"}, {"Origin": "http://testserver.evil"}, {"Host": "evil.example", "Origin": "http://evil.example"}])
def test_cross_site_writes_are_rejected_before_work(harness, headers):
    client, _, _, boundary = harness
    for path, payload in [("references", {"name": "x", "imageBase64": image_base64()}), ("generate", {}), ("jobs/identity-" + "a" * 24 + "/cancel", None)]:
        assert client.post("/api/identity/" + path, json=payload, headers=headers).status_code == 403
    assert boundary.calls == []


def test_same_origin_upload_allowed(harness):
    client, _, _, _ = harness
    response = client.post("/api/identity/references", json={"name": "x", "imageBase64": image_base64()}, headers={"Origin": "http://127.0.0.1:8866", "Sec-Fetch-Site": "same-origin"})
    assert response.status_code == 200


@pytest.mark.parametrize("changes", [{"referenceId": "../../private"}, {"faceIndex": -1}, {"faceIndex": 2}, {"faceIndex": True}, {"faceIndex": None}, {"width": 513}, {"identityStrength": "NaN"}, {"structureStrength": "Infinity"}, {"faceLoraStrength": -1}, {"loraId": "../outside"}, {"imagePath": "E:/private.jpg"}, {"prompt": " "}])
def test_generation_rejects_invalid_input(harness, changes):
    client, _, _, boundary = harness
    reference = upload(client)
    response = client.post("/api/identity/generate", json={"referenceId": reference["id"], "faceIndex": 1, "prompt": "portrait", **changes})
    assert response.status_code == 422, response.text
    assert all(call[1] != "generate" for call in boundary.calls)


def test_rejects_unknown_reference_and_invalid_ids(harness):
    client, _, _, boundary = harness
    response = client.post("/api/identity/generate", json={"referenceId": "ref-" + "a" * 24, "faceIndex": 0, "prompt": "portrait"})
    assert response.status_code == 404
    assert response.json().get("code") == "IDENTITY_REFERENCE_NOT_FOUND"
    for path in ["references/not-valid/image", "jobs/not-valid", "jobs/identity-" + "b" * 24]:
        assert client.get("/api/identity/" + path).status_code in {404, 422}
    assert boundary.calls == []


def test_generation_persists_real_seed_and_is_discovered_by_ordinary_history(harness):
    client, config, _, boundary = harness
    reference = upload(client)
    job = submit(client, reference, seed="random", loraId="style", loraStrength=0.4)
    assert re.fullmatch(r"identity-[a-f0-9]{24}", job["id"])
    completed = finished(client, job["id"])
    assert completed["state"] == "complete", completed
    assert set(completed) == {"id", "state", "progress", "message", "request", "result", "error"}
    assert isinstance(completed["request"]["seed"], int)
    assert completed["request"]["faceIndex"] == 1
    assert completed["result"]["metadata"]["identity"] == completed["request"]
    assert completed["result"]["metadata"]["model_id"] == "realistic-vision-v5.1-faceid"
    assert client.get(completed["result"]["imageUrl"]).status_code == 200
    history = client.get("/api/history").json()
    assert history["items"][0]["id"] == job["id"]
    assert history["items"][0]["seed"] == completed["request"]["seed"]
    assert len(list((config.dream_root / "outputs").glob(f"*/{job['id']}.json"))) == 1
    persisted = config.dream_root / "data" / "identity" / "jobs" / f"{job['id']}.json"
    assert json.loads(persisted.read_text(encoding="utf-8")) == completed
    assert client.get("/api/identity/jobs").json() == [completed]
    assert next(call[2] for call in boundary.calls if call[1] == "generate")["faceIndex"] == 1


@pytest.mark.parametrize("operation", ["inspect", "generate"])
def test_worker_failure_is_terminal_and_partial_assets_are_removed(harness, operation):
    client, config, _, boundary = harness
    boundary.fail = operation
    if operation == "inspect":
        response = client.post("/api/identity/references", json={"name": "x", "imageBase64": image_base64()})
        assert response.status_code == 503
        assert client.get("/api/identity/references").json() == []
        assert not list((config.dream_root / "data" / "identity" / "references").glob("*.png"))
    else:
        job = submit(client, upload(client))
        value = finished(client, job["id"])
        assert value["state"] == "failed"
        assert "controlled worker failure" in value["error"]
        assert client.post(f"/api/identity/jobs/{job['id']}/cancel").json() == value


def test_no_faces_does_not_publish_reference(harness):
    client, _, _, boundary = harness
    boundary.faces = []
    response = client.post("/api/identity/references", json={"name": "x", "imageBase64": image_base64()})
    assert response.status_code == 422
    assert client.get("/api/identity/references").json() == []


def test_native_and_identity_share_one_executor_and_queued_cancel_skips_worker(harness):
    client, _, runner, boundary = harness
    reference = upload(client)
    native_started, native_release = threading.Event(), threading.Event()

    def native(command, *args):
        native_started.set()
        assert native_release.wait(5)
        return NativeRunResult(1, "", "controlled native failure")

    runner.command_runner = native
    try:
        native_job = runner.submit(GenerateRequest(prompt="native", modelId="model"))
        assert native_started.wait(2)
        cancelled = submit(client, reference)
        assert cancelled["state"] == "queued"
        assert client.post(f"/api/identity/jobs/{cancelled['id']}/cancel").json()["state"] == "cancelled"
        live = submit(client, reference)
        assert live["state"] == "queued"
        assert all(call[1] != "generate" for call in boundary.calls)
    finally:
        native_release.set()
    assert finished(client, live["id"])["state"] == "complete"
    assert runner.get(native_job["id"])["state"] == "failed"
    assert len([call for call in boundary.calls if call[1] == "generate"]) == 1


def test_cancel_waits_for_owned_child_exit_before_native_can_start(harness):
    client, _, runner, boundary = harness
    reference = upload(client)
    boundary.hold = "generate"
    boundary.exit_allowed.clear()
    job = submit(client, reference)
    assert boundary.started.wait(2)
    native_started = threading.Event()

    def native(*args):
        native_started.set()
        return NativeRunResult(1, "", "controlled")

    runner.command_runner = native
    native_job = runner.submit(GenerateRequest(prompt="after", modelId="model"))
    with ThreadPoolExecutor(max_workers=1) as pool:
        cancellation = pool.submit(client.post, f"/api/identity/jobs/{job['id']}/cancel")
        try:
            time.sleep(0.1)
            assert not cancellation.done()
            assert not native_started.is_set()
        finally:
            boundary.exit_allowed.set()
        assert cancellation.result(timeout=3).json()["state"] == "cancelled"
    assert boundary.children[-1].poll() is not None
    assert native_started.wait(2)
    assert finished(client, job["id"])["result"] is None
    assert runner.get(native_job["id"])["state"] == "failed"
    assert client.get("/api/history").json()["total"] == 0


@pytest.mark.parametrize("state", ["queued", "preparing", "sampling", "complete", "cancelled", "failed"])
def test_restart_recovers_inflight_jobs_without_changing_get_contract(harness, state):
    client, config, runner, _ = harness
    folder = config.dream_root / "data" / "identity" / "jobs"
    folder.mkdir(parents=True, exist_ok=True)
    job_id = "identity-" + "c" * 24
    record = {"id": job_id, "state": state, "progress": 24, "message": "before", "request": {}, "result": None, "error": None}
    (folder / f"{job_id}.json").write_text(json.dumps(record), encoding="utf-8")
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as restored:
        response = restored.get(f"/api/identity/jobs/{job_id}")
        assert response.status_code == 200
        value = response.json()
        assert set(value) == set(record)
        if state in {"queued", "preparing", "sampling"}:
            assert value["state"] == "failed"
            assert value["error"]
        else:
            assert value == record
        assert restored.get("/api/identity/jobs").json() == [value]
        assert json.loads((folder / f"{job_id}.json").read_text(encoding="utf-8")) == value


def test_unknown_native_resident_fails_closed(harness):
    client, _, runner, boundary = harness
    runner.persistent_engine._transport = lambda *args: {"model": {"path": "unowned.gguf"}, "supported_modes": ["img_gen"]}
    job = submit(client, upload(client))
    value = finished(client, job["id"])
    assert value["state"] == "failed"
    assert "归属" in value["error"]
    assert all(call[1] != "generate" for call in boundary.calls)


def test_release_terminates_only_owned_native_child_and_waits(tmp_path):
    config = make_config(tmp_path)

    class OwnedChild:
        returncode = None
        waited = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def wait(self, timeout=None):
            self.waited = True
            return self.returncode

    child = OwnedChild()
    client = PersistentEngineClient(config, transport=absent_native)
    client._process = child
    assert callable(getattr(client, "release_for_identity", None)), "native release boundary is missing"
    client.release_for_identity()
    assert child.waited
    assert client._process is None


def test_constructing_app_does_not_recover_other_running_service_jobs(harness):
    _, config, runner, _ = harness
    folder = config.dream_root / "data" / "identity" / "jobs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ("identity-" + "d" * 24 + ".json")
    before = {"id": path.stem, "state": "sampling", "progress": 20, "message": "active elsewhere", "request": {}, "result": None, "error": None}
    path.write_text(json.dumps(before), encoding="utf-8")
    create_app(config, DreamRuntime(config, job_runner=runner))
    assert json.loads(path.read_text(encoding="utf-8")) == before


@pytest.mark.parametrize("faces", [[{"index": 0, "box": [1, 2]}], [{"index": 0, "box": [1, 1, 1000, 2000]}], "invalid"])
def test_malformed_inspection_is_structured_and_never_stores_reference(harness, faces):
    client, _, _, boundary = harness
    boundary.faces = faces
    response = client.post("/api/identity/references", json={"name": "x", "imageBase64": image_base64()})
    assert response.status_code == 503
    assert response.json()["code"] == "IDENTITY_WORKER_FAILED"
    assert client.get("/api/identity/references").json() == []


def test_worker_diagnostics_survive_failed_job_cleanup(harness):
    client, config, _, boundary = harness
    boundary.fail = "generate"
    job = submit(client, upload(client))
    assert finished(client, job["id"])["state"] == "failed"
    logs = list((config.dream_root / "logs" / "identity").glob("*.err.log"))
    assert any("controlled worker diagnostic 人物" in path.read_text(encoding="utf-8") for path in logs)


def test_newest_first_order_survives_cancel_then_restart(harness):
    client, config, runner, boundary = harness
    reference = upload(client)
    boundary.hold = "generate"
    older = submit(client, reference)
    assert boundary.started.wait(2)
    newer = submit(client, reference)
    assert client.post(f"/api/identity/jobs/{newer['id']}/cancel").json()["state"] == "cancelled"
    boundary.release.set()
    assert finished(client, older["id"])["state"] == "complete"
    client.__exit__(None, None, None)
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as restored:
        assert [job["id"] for job in restored.get("/api/identity/jobs").json()] == [newer["id"], older["id"]]


@pytest.mark.skipif(os.name != "nt", reason="Windows process lifetime containment")
def test_worker_job_object_kills_owned_child_when_handle_closes():
    import identity_service

    assert callable(getattr(identity_service, "WorkerLifetime", None)), "parent-exit worker containment is missing"
    process = REAL_POPEN([sys.executable, "-c", "import time; time.sleep(20)"], creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        lifetime = identity_service.WorkerLifetime(process)
        lifetime.close()
        # Windows job termination may report zero; the deadline proves that
        # the 20-second child was stopped when its owning handle closed.
        assert process.wait(timeout=3) is not None
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()


def test_unresponsive_unknown_native_listener_fails_closed(tmp_path):
    import urllib.error

    def unavailable(*args):
        raise PersistentEngineUnavailable("bad response from an unknown listener") from urllib.error.HTTPError("http://localhost", 500, "error", {}, None)

    client = PersistentEngineClient(make_config(tmp_path), transport=unavailable)
    client._transport_injected = False
    with pytest.raises(PersistentEngineUnavailable, match="归属"):
        client.release_for_identity()


def test_restart_removes_interrupted_outputs_from_ordinary_history(harness):
    _, config, runner, _ = harness
    job_id = "identity-" + "e" * 24
    folder = config.dream_root / "data" / "identity" / "jobs"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{job_id}.json").write_text(json.dumps({"id": job_id, "state": "sampling", "progress": 20, "message": "interrupted", "request": {}, "result": None, "error": None}), encoding="utf-8")
    outputs = config.dream_root / "outputs" / "2026-09-20"
    outputs.mkdir(parents=True)
    Image.new("RGB", (8, 8)).save(outputs / f"{job_id}.png")
    (outputs / f"{job_id}.json").write_text(json.dumps({"id": job_id}), encoding="utf-8")
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as restored:
        assert restored.get(f"/api/identity/jobs/{job_id}").json()["state"] == "failed"
        assert restored.get("/api/history").json()["items"] == []


def test_disconnected_upload_stops_inspection_and_removes_unpublished_reference(harness):
    client, config, _, boundary = harness
    boundary.hold = "inspect"
    body = json.dumps({"name": "x", "imageBase64": image_base64()}).encode()
    replies = []

    async def exercise():
        remaining = [{"type": "http.request", "body": body, "more_body": False}]

        async def receive():
            if remaining:
                return remaining.pop(0)
            if boundary.started.is_set():
                return {"type": "http.disconnect"}
            await asyncio.sleep(0.01)
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            replies.append(message)

        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http", "path": "/api/identity/references", "raw_path": b"/api/identity/references", "query_string": b"", "root_path": "", "server": ("127.0.0.1", 8866), "client": ("127.0.0.1", 4000), "headers": [(b"host", b"127.0.0.1:8866"), (b"content-type", b"application/json")]}
        await asyncio.wait_for(client.app(scope, receive, send), timeout=5)

    asyncio.run(exercise())
    assert boundary.children[-1].poll() is not None
    assert client.get("/api/identity/references").json() == []
    assert not list((config.dream_root / "data" / "identity" / "references").glob("*.png"))
    assert next(message["status"] for message in replies if message["type"] == "http.response.start") == 499


def test_atomic_job_write_preserves_previous_record_if_replace_fails(tmp_path, monkeypatch):
    import identity_service

    path = tmp_path / "job.json"
    previous = {"state": "queued", "prompt": "人物"}
    identity_service.atomic_json(path, previous)

    def fail_replace(*args):
        raise OSError("controlled disk replacement failure")

    monkeypatch.setattr(identity_service.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replacement"):
        identity_service.atomic_json(path, {"state": "sampling"})
    assert json.loads(path.read_text(encoding="utf-8")) == previous
    assert not list(tmp_path.glob("*.tmp"))


@pytest.fixture
def inherited_native(tmp_path, monkeypatch):
    """Only psutil/process IO and the native HTTP endpoint are controlled."""
    import psutil

    config = make_config(tmp_path)
    model = config.dream_root / "models" / "windows" / "gguf" / "model.gguf"

    class ProcessIdentity:
        pid = 765432
        started = time.time() - 100
        executable = str(config.persistent_engine_exe)
        command = [executable, "-m", str(model), "--backend", "cuda", "--listen-ip", "127.0.0.1", "--listen-port", "12444"]
        port = 12444
        stopped = False
        waited = False
        missing = False
        reused = False
        denied = False
        lookup_denied = False
        other_listener = False
        probe_action = None
        advertised_model = str(model)

        def exe(self):
            if self.denied:
                raise psutil.AccessDenied(self.pid)
            return self.executable

        def cmdline(self):
            return self.command

        def create_time(self):
            return self.started

        def net_connections(self, kind):
            assert kind == "tcp"
            return [SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(ip="127.0.0.1", port=self.port))]

        def is_running(self):
            return not (self.reused or self.missing or self.stopped)

        def terminate(self):
            # Mirror psutil's PID reuse guard; never dispatch to the OS.
            if self.reused:
                raise psutil.NoSuchProcess(self.pid)
            self.stopped = True

        kill = terminate

        def wait(self, timeout=None):
            assert self.stopped
            self.waited = True
            return 0

        def transport(self, *args):
            if self.probe_action:
                action, self.probe_action = self.probe_action, None
                action()
            if (self.stopped or self.missing) and not self.other_listener:
                return absent_native()
            return {"model": {"path": self.advertised_model}, "supported_modes": ["img_gen"]}

    process = ProcessIdentity()

    def lookup(pid):
        assert pid == process.pid, "Only the recorded, controlled PID may be inspected"
        if process.lookup_denied:
            raise psutil.AccessDenied(pid)
        if process.missing:
            raise psutil.NoSuchProcess(pid)
        return process

    monkeypatch.setattr(psutil, "Process", lookup)
    client = PersistentEngineClient(config, transport=process.transport)
    state = {"pid": process.pid, "base_url": client.base_url, "model_path": str(model), "flash_attention": True, "executable": process.executable, "startTime": process.started}
    client._state_path.parent.mkdir(parents=True, exist_ok=True)
    client._state_path.write_text(json.dumps(state), encoding="utf-8")
    return client, process, state


@pytest.mark.parametrize("legacy", [False, True], ids=["timestamped", "legacy"])
def test_adopts_verified_inherited_native_and_waits_for_release(inherited_native, legacy):
    client, process, state = inherited_native
    if legacy:
        state.pop("startTime")
        state.pop("executable")
        client._state_path.write_text(json.dumps(state), encoding="utf-8")
    client.release_for_identity()
    assert process.stopped and process.waited
    assert not client._state_path.exists()


def test_persists_native_start_time_and_exact_executable(inherited_native):
    client, process, state = inherited_native
    client._process = SimpleNamespace(pid=process.pid)
    client._persist_state(Path(state["model_path"]))
    saved = json.loads(client._state_path.read_text(encoding="utf-8"))
    assert saved["startTime"] == process.started
    assert saved["executable"] == process.executable


@pytest.mark.parametrize("mismatch", ["exe", "command-exe", "model", "port", "listen-ip", "base-url", "stored-exe", "start-time", "legacy-new-process", "advertised-model", "listener", "duplicate-model", "denied", "lookup-denied", "reused-before-kill", "state-replaced"])
def test_inherited_native_mismatch_never_terminates_or_deletes_state(inherited_native, mismatch):
    client, process, state = inherited_native
    if mismatch == "exe":
        process.executable += ".other.exe"
    elif mismatch == "command-exe":
        process.command[0] += ".other.exe"
    elif mismatch == "model":
        process.command[2] = str(Path(state["model_path"]).with_name("another.gguf"))
    elif mismatch == "port":
        process.command[-1] = "12445"
    elif mismatch == "listen-ip":
        process.command[-3] = "0.0.0.0"
    elif mismatch == "base-url":
        state["base_url"] = "http://127.0.0.1:12445"
    elif mismatch == "stored-exe":
        state["executable"] += ".other.exe"
    elif mismatch == "start-time":
        state["startTime"] -= 100
    elif mismatch == "legacy-new-process":
        state.pop("startTime")
        process.started = time.time() + 100
    elif mismatch == "advertised-model":
        process.advertised_model += ".other.gguf"
    elif mismatch == "listener":
        process.port = 12445
    elif mismatch == "duplicate-model":
        process.command += ["--model", state["model_path"]]
    elif mismatch == "denied":
        process.denied = True
    elif mismatch == "lookup-denied":
        process.lookup_denied = True
    elif mismatch == "reused-before-kill":
        process.probe_action = lambda: setattr(process, "reused", True)
    elif mismatch == "state-replaced":
        process.probe_action = lambda: client._state_path.write_text('{"another":"owner"}', encoding="utf-8")
    client._state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(PersistentEngineUnavailable, match="归属|身份|启动时间|状态|校验"):
        client.release_for_identity()
    assert not process.stopped
    assert client._state_path.exists()
    if mismatch == "state-replaced":
        assert json.loads(client._state_path.read_text(encoding="utf-8")) == {"another": "owner"}


def test_nonexistent_native_and_refused_endpoint_clear_only_stale_state(inherited_native):
    client, process, _ = inherited_native
    process.missing = True
    unrelated = client._state_path.parent / "keep.json"
    unrelated.write_text('{"keep":true}', encoding="utf-8")
    client.release_for_identity()
    assert not client._state_path.exists()
    assert unrelated.read_text(encoding="utf-8") == '{"keep":true}'
    assert not process.stopped


def test_nonexistent_recorded_pid_with_live_endpoint_preserves_state(inherited_native):
    client, process, _ = inherited_native
    process.missing = True
    process.other_listener = True
    with pytest.raises(PersistentEngineUnavailable, match="归属"):
        client.release_for_identity()
    assert client._state_path.exists()
    assert not process.stopped


def test_owned_child_does_not_delete_another_process_state(inherited_native):
    client, process, state = inherited_native
    state["pid"] += 1
    client._state_path.write_text(json.dumps(state), encoding="utf-8")

    class Owned:
        pid = process.pid

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    client._process = Owned()
    process.stopped = True
    with pytest.raises(PersistentEngineUnavailable, match="状态|归属"):
        client.release_for_identity()
    assert json.loads(client._state_path.read_text(encoding="utf-8")) == state


def test_identity_validation_errors_are_chinese(harness):
    client, _, _, _ = harness
    invalid = client.post("/api/identity/generate", json={})
    assert "人物" in invalid.json()["message"]
    bad_image = client.post("/api/identity/references", json={"name": "x", "imageBase64": "invalid"})
    assert "图片" in bad_image.json()["message"]


def test_second_app_cannot_recover_live_job_or_delete_its_outputs(harness):
    client, config, runner, boundary = harness
    reference = upload(client)
    boundary.hold = "generate"
    job = submit(client, reference)
    assert boundary.started.wait(2)
    job_path = config.dream_root / "data" / "identity" / "jobs" / f"{job['id']}.json"
    original = job_path.read_bytes()
    request = next(call[2] for call in boundary.calls if call[1] == "generate")
    output, metadata = Path(request["outputPath"]), Path(request["metadataPath"])
    output.write_bytes(b"live partial image")
    metadata.write_text('{"live":true}', encoding="utf-8")
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner)), base_url="http://127.0.0.1:8866") as competing:
        blocked = competing.get("/api/identity/jobs")
        assert blocked.status_code == 503
        assert "占用" in blocked.json()["message"]
        assert competing.get(f"/api/identity/jobs/{job['id']}").status_code == 503
        assert competing.post("/api/identity/references", json={"name": "other", "imageBase64": image_base64()}).status_code == 503
        assert competing.post("/api/identity/generate", json={"referenceId": reference["id"], "faceIndex": 1, "prompt": "other"}).status_code == 503
        assert competing.post(f"/api/identity/jobs/{job['id']}/cancel").status_code == 503
        assert job_path.read_bytes() == original
        assert output.read_bytes() == b"live partial image"
        assert metadata.read_text(encoding="utf-8") == '{"live":true}'
        assert client.get(f"/api/identity/jobs/{job['id']}").json()["state"] == "sampling"
    boundary.release.set()
    assert finished(client, job["id"])["state"] == "complete"


def test_app_shutdown_keeps_lease_until_owned_worker_exits(harness):
    client, config, runner, boundary = harness
    reference = upload(client)
    boundary.hold = "generate"
    boundary.exit_allowed.clear()
    job = submit(client, reference)
    assert boundary.started.wait(2)
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as competing:
        with ThreadPoolExecutor(max_workers=1) as pool:
            closing = pool.submit(client.__exit__, None, None, None)
            try:
                time.sleep(0.15)
                assert not closing.done(), "shutdown must wait for the owned child to release"
                assert competing.get("/api/identity/jobs").status_code == 503
            finally:
                boundary.exit_allowed.set()
                boundary.release.set()
            closing.result(timeout=5)
        assert boundary.children[-1].poll() is not None
        restored = competing.get(f"/api/identity/jobs/{job['id']}")
        assert restored.status_code == 200
        assert restored.json()["state"] == "cancelled"
        assert competing.get("/api/identity/jobs").json() == [restored.json()]


@pytest.mark.parametrize("fail_running_write", [False, True], ids=["queued-write", "queued-and-running-writes"])
def test_close_disk_failure_drains_children_releases_lease_and_reports_unpersisted_jobs(harness, monkeypatch, caplog, fail_running_write):
    import identity_service
    from errors import DreamApiError

    _, config, runner, boundary = harness
    service = identity_service.IdentityService(config, runner)
    contender = identity_service.IdentityService(config, runner)
    reference = service.upload(identity_service.ReferenceUpload(name="人物", imageBase64=image_base64()))
    request = identity_service.IdentityGenerateRequest(referenceId=reference["id"], faceIndex=1, prompt="portrait", seed=42)
    boundary.hold = "generate"
    boundary.exit_allowed.clear()
    running = service.submit(request)
    assert boundary.started.wait(2)
    queued, following = service.submit(request), service.submit(request)
    failed_ids = {queued["id"]}
    if fail_running_write:
        failed_ids.add(running["id"])
    folder = config.dream_root / "data" / "identity" / "jobs"
    preserved = {job_id: (folder / f"{job_id}.json").read_bytes() for job_id in failed_ids}
    write_failed = threading.Event()
    real_atomic_json = identity_service.atomic_json

    def disk_full(path, value):
        if value.get("id") in failed_ids and value.get("state") == "cancelled":
            write_failed.set()
            raise OSError(28, "controlled disk full")
        return real_atomic_json(path, value)

    try:
        with monkeypatch.context() as disk:
            disk.setattr(identity_service, "atomic_json", disk_full)
            with ThreadPoolExecutor(max_workers=2) as pool:
                closing = pool.submit(service.close)
                try:
                    assert write_failed.wait(2)
                    assert not closing.done(), "a failed write must not bypass the child-exit barrier"
                    repeated = pool.submit(service.close)
                    with pytest.raises(DreamApiError) as error:
                        contender.jobs()
                    assert error.value.status_code == 503
                    assert not repeated.done()
                    boundary.exit_allowed.set()
                    boundary.release.set()
                    closing.result(timeout=5)
                    repeated.result(timeout=5)
                    pool.submit(service.close).result(timeout=2)
                    assert boundary.children[-1].poll() is not None
                    for job_id, original in preserved.items():
                        assert (folder / f"{job_id}.json").read_bytes() == original
                        assert job_id in caplog.text
                    assert "controlled disk full" in caplog.text
                    assert "人物" in caplog.text
                    assert json.loads((folder / f"{following['id']}.json").read_text(encoding="utf-8"))["state"] == "cancelled"
                    # Take over before test cleanup can release any lease.
                    recovered = {job["id"]: job for job in contender.jobs()}
                    assert set(recovered) == {running["id"], queued["id"], following["id"]}
                    for job_id in failed_ids:
                        assert recovered[job_id]["state"] == "failed"
                finally:
                    boundary.exit_allowed.set()
                    boundary.release.set()
                    runner.submit_serial(lambda: None).result(timeout=5)
                    # Keep the RED test bounded even when broken close strands
                    # its condition/lease; only after all owned work has exited.
                    with service._condition:
                        service._lease.close()
                        service._closed = True
                        service._condition.notify_all()
    finally:
        contender.close()


def test_storage_owner_lease_is_os_backed_and_released_on_process_death(tmp_path):
    import identity_service
    from errors import DreamApiError

    assert callable(getattr(identity_service, "StorageOwnerLease", None)), "OS-backed storage ownership is missing"
    lock_path = tmp_path / "owner.lock"
    script = (
        "import os,sys; from pathlib import Path; from identity_service import StorageOwnerLease; "
        "lease=StorageOwnerLease(Path(sys.argv[1])); lease.acquire(); "
        "print('ready',flush=True); sys.stdin.readline(); os._exit(0)"
    )
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "PYTHONIOENCODING": "utf-8"}
    process = REAL_POPEN([sys.executable, "-c", script, str(lock_path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", env=environment, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    contender = identity_service.StorageOwnerLease(lock_path)
    try:
        assert process.stdout.readline().strip() == "ready"
        with pytest.raises(DreamApiError) as error:
            contender.acquire()
        assert error.value.status_code == 503
        process.communicate("exit\n", timeout=5)
        assert process.returncode == 0
        contender.acquire()
    finally:
        contender.close()
        if process.poll() is None:
            process.kill()
        process.wait()


def test_native_loopback_http_explicitly_bypasses_inherited_system_proxy(tmp_path, monkeypatch):
    import urllib.request

    def proxied_urlopen(*args, **kwargs):
        raise TimeoutError("controlled inherited Windows proxy timeout")

    direct_calls = []

    class DirectLoopbackOpener:
        def open(self, request, timeout):
            assert request.full_url == "http://127.0.0.1:12444/sdcpp/v1/capabilities"
            direct_calls.append(request.get_method())
            return io.BytesIO(b'{"supported_modes":["img_gen"]}')

    def build_direct_opener(handler):
        assert isinstance(handler, urllib.request.ProxyHandler)
        assert handler.proxies == {}, "The native loopback transport must disable system proxies"
        return DirectLoopbackOpener()

    monkeypatch.setattr(urllib.request, "urlopen", proxied_urlopen)
    monkeypatch.setattr(urllib.request, "build_opener", build_direct_opener)
    client = PersistentEngineClient(make_config(tmp_path))
    assert client._http_json("GET", "/sdcpp/v1/capabilities", None, 2) == {"supported_modes": ["img_gen"]}
    assert direct_calls == ["GET"]


def test_direct_refused_native_endpoint_clears_stale_state_despite_system_proxy(inherited_native, monkeypatch):
    import urllib.error
    import urllib.request

    client, process, _ = inherited_native
    process.missing = True
    client._transport = client._http_json
    client._transport_injected = False
    environment = dict(os.environ)
    requests = []

    def direct_refusal(handler, request):
        assert request.host == "127.0.0.1:12444"
        assert request.selector == "/sdcpp/v1/capabilities"
        assert not request.has_proxy()
        requests.append(request.full_url)
        raise urllib.error.URLError(ConnectionRefusedError("controlled loopback refusal"))

    # Exercise the real opener, replacing only system discovery and socket IO.
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {"http": "http://unreachable-proxy.invalid:8080"})
    monkeypatch.setattr(urllib.request.HTTPHandler, "http_open", direct_refusal)
    client.release_for_identity()
    assert requests
    assert not client._state_path.exists()
    assert not process.stopped
    assert dict(os.environ) == environment
