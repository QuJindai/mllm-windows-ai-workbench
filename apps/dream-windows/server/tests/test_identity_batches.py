"""Batch API integration, with controlled subprocesses and real event files."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import threading
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import create_app
from runtime import DreamRuntime
from test_identity_profiles import profile_harness, create_profile, wait_profile
from test_identity_api import harness, upload


class BatchWorkerBoundary:
    def __init__(self, profiles):
        self.profiles = profiles
        self.calls = []
        self.children = []
        self.hold = False
        self.fail = False
        self.started = threading.Event()
        self.release = threading.Event()
        self.exit_allowed = threading.Event()
        self.exit_allowed.set()
        self.custom_events = None

    @staticmethod
    def emit(payload, event):
        from identity_events import emit_event
        emit_event(payload["eventPath"], event)

    def complete_item(self, payload, index):
        item = payload["items"][index]
        output = Path(item["outputPath"])
        output.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (item["width"], item["height"]), "navy").save(output)
        Path(item["metadataPath"]).write_text(json.dumps({"id": item["jobId"], "seed": item["seed"]}), encoding="utf-8")
        self.emit(payload, {"type": "item_complete", "itemIndex": index, "jobId": item["jobId"], "elapsedMs": 100 * (index + 1)})

    def spawn(self, command, **options):
        if command[3] != "batch":
            return self.profiles.spawn(command, **options)
        assert command[2::2] == ["--operation", "--request", "--result"]
        payload = json.loads(Path(command[5]).read_text(encoding="utf-8"))
        assert set(payload) == {"items", "dreamRoot", "configPath", "eventPath", "previewDir", "previewEvery"}
        for item in payload["items"]:
            assert {"imagePath", "outputPath", "metadataPath", "jobId", "dreamRoot", "configPath", "referenceId", "faceIndex", "seed", "steps"} <= item.keys()
        self.calls.append(payload)
        boundary = self

        class Child:
            returncode = None
            stopped = False
            initialized = False

            def poll(self):
                return self.returncode

            def terminate(self):
                self.stopped = True

            kill = terminate

            def communicate(self, timeout=None):
                if self.returncode is not None:
                    return "", ""
                if self.stopped:
                    if not boundary.exit_allowed.wait(.01):
                        raise subprocess.TimeoutExpired(command, timeout)
                    self.returncode = -15
                    return "", ""
                if not self.initialized:
                    self.initialized = True
                    if boundary.custom_events:
                        boundary.custom_events(payload)
                    elif boundary.hold or boundary.fail:
                        boundary.complete_item(payload, 0)
                        if len(payload["items"]) > 1:
                            boundary.emit(payload, {"type": "stage", "stage": "sampling", "itemIndex": 1, "elapsedMs": 100})
                            boundary.emit(payload, {"type": "step", "itemIndex": 1, "step": 1, "totalSteps": payload["items"][1]["steps"], "elapsedMs": 110})
                            event = {"type": "step", "itemIndex": 1, "step": 5, "totalSteps": payload["items"][1]["steps"], "elapsedMs": 150}
                            if payload["previewEvery"]:
                                name = payload["items"][1]["jobId"] + "-step-005.png"
                                preview = Path(payload["previewDir"]) / name
                                preview.parent.mkdir(parents=True, exist_ok=True)
                                Image.new("RGB", (128, 128), "blue").save(preview)
                                event["previewFile"] = name
                            boundary.emit(payload, event)
                    boundary.started.set()
                if boundary.hold and not boundary.release.wait(.01):
                    raise subprocess.TimeoutExpired(command, timeout)
                if not boundary.fail:
                    start = 1 if (boundary.hold and not boundary.custom_events) else 0
                    for index in range(start, len(payload["items"])):
                        boundary.complete_item(payload, index)
                    result = {"ok": True, "items": [{"jobId": item["jobId"], "imageUrl": "/ignored", "metadata": {}} for item in payload["items"]]}
                else:
                    result = {"ok": False, "message": "受控批次失败"}
                Path(command[7]).write_text(json.dumps(result), encoding="utf-8")
                self.returncode = 1 if boundary.fail else 0
                return "", ""

            def wait(self, timeout=None):
                if timeout is None:
                    assert boundary.exit_allowed.wait(5)
                self.communicate(timeout)
                return self.returncode

        child = Child()
        self.children.append(child)
        return child


@pytest.fixture
def batch_harness(profile_harness, monkeypatch):
    client, config, runner, profiles = profile_harness
    boundary = BatchWorkerBoundary(profiles)
    monkeypatch.setattr(subprocess, "Popen", boundary.spawn)
    try:
        yield client, config, runner, boundary
    finally:
        boundary.release.set()
        boundary.exit_allowed.set()


def batch_request(reference, **changes):
    return {"request": {"referenceId": reference["id"], "faceIndex": 1, "prompt": "portrait", "seed": 42, "steps": 10, "width": 256, "height": 256}, "count": 2, "previewEvery": 0, **changes}


def submit_batch(client, request):
    response = client.post("/api/identity/batches", json=request)
    assert response.status_code == 200, response.text
    return response.json()


def wait_batch(client, batch_id, predicate=lambda b: b["state"] in {"complete", "failed", "cancelled"}):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/identity/batches/{batch_id}")
        assert response.status_code == 200, response.text
        if predicate(response.json()):
            return response.json()
        time.sleep(.01)
    pytest.fail(f"batch did not reach expected state: {response.text}")


def test_calibration_pairs_seeds_and_finishes_items_in_one_worker(batch_harness):
    client, _, _, boundary = batch_harness
    batch = submit_batch(client, batch_request(upload(client), stepValues=[20, 28, 20]))
    assert [(j["request"]["seed"], j["request"]["steps"]) for j in batch["items"]] == [(42, 20), (42, 28), (43, 20), (43, 28)]
    assert batch["request"]["stepValues"] == [20, 28]
    assert batch["currentItem"] == 0 and batch["progress"] == 0 and batch["etaMs"] is None
    result = wait_batch(client, batch["id"])
    assert result["state"] == "complete", result
    assert result["completedItems"] == result["totalItems"] == 4
    assert result["progress"] == 100
    assert len(boundary.calls) == 1
    for item in result["items"]:
        assert item["state"] == "complete"
        assert client.get(f"/api/identity/jobs/{item['id']}").json() == item
        assert client.get(item["result"]["imageUrl"]).status_code == 200
    assert client.get("/api/history").json()["total"] == 4


@pytest.mark.parametrize("changes", [{"count": 0}, {"count": 9}, {"count": True}, {"stepValues": []}, {"stepValues": [0]}, {"stepValues": [51]}, {"stepValues": [1, 2, 3, 4, 5]}, {"stepValues": [True]}, {"count": 8, "stepValues": [10, 20, 30]}, {"previewEvery": 1}, {"previewEvery": True}, {"profileId": "../person"}, {"eventPath": "C:/secret"}])
def test_batch_bounds_before_enqueue(batch_harness, changes):
    client, _, _, boundary = batch_harness
    response = client.post("/api/identity/batches", json=batch_request(upload(client), **changes))
    assert response.status_code == 422
    assert not boundary.calls
    assert client.get("/api/identity/batches").json() == []


def test_batch_rejects_mismatched_and_archived_profile(batch_harness):
    client, _, _, _ = batch_harness
    reference = upload(client)
    profile = wait_profile(client, create_profile(client, reference)["id"])
    request = batch_request(reference, profileId=profile["id"])
    request["request"]["faceIndex"] = 0
    assert client.post("/api/identity/batches", json=request).status_code == 409
    request["request"]["faceIndex"] = 1
    assert client.post(f"/api/identity/profiles/{profile['id']}/archive").status_code == 200
    assert client.post("/api/identity/batches", json=request).status_code == 409


def test_progress_preview_and_cancel_preserve_first_completed_original(batch_harness):
    client, _, _, boundary = batch_harness
    boundary.hold = True
    batch = submit_batch(client, batch_request(upload(client), previewEvery=5))
    partial = wait_batch(client, batch["id"], lambda b: b["step"] == 5)
    assert partial["state"] == "sampling"
    assert (partial["currentItem"], partial["completedItems"], partial["totalItems"], partial["totalSteps"]) == (2, 1, 2, 10)
    assert partial["progress"] == 75 and partial["elapsedMs"] >= 150
    assert partial["etaMs"] is not None and partial["etaMs"] >= 0
    preview = client.get(partial["previewUrl"])
    assert preview.status_code == 200 and preview.headers["content-type"] == "image/png"
    first = partial["items"][0]
    original = client.get(first["result"]["imageUrl"]).content
    response = client.post(f"/api/identity/batches/{batch['id']}/cancel")
    assert response.status_code == 200
    cancelled = response.json()
    assert cancelled["state"] == "cancelled" and cancelled["completedItems"] == 1
    assert [item["state"] for item in cancelled["items"]] == ["complete", "cancelled"]
    assert boundary.children[-1].poll() is not None
    assert client.get(first["result"]["imageUrl"]).content == original
    assert client.get("/api/history").json()["total"] == 1


def test_failed_batch_keeps_completed_item(batch_harness):
    client, _, _, boundary = batch_harness
    boundary.fail = True
    result = wait_batch(client, submit_batch(client, batch_request(upload(client)))["id"])
    assert result["state"] == "failed" and result["completedItems"] == 1
    assert result["items"][0]["state"] == "complete"
    assert client.get(result["items"][0]["result"]["imageUrl"]).status_code == 200


@pytest.mark.parametrize("event", [
    {"type": "step", "itemIndex": -1, "step": 1, "totalSteps": 10, "elapsedMs": 1},
    {"type": "step", "itemIndex": 0, "step": 11, "totalSteps": 10, "elapsedMs": 1},
    {"type": "step", "itemIndex": 0, "step": 1, "totalSteps": 9, "elapsedMs": 1},
    {"type": "step", "itemIndex": 0, "step": 1, "totalSteps": 10, "elapsedMs": True},
    {"type": "step", "itemIndex": 0, "step": 5, "totalSteps": 10, "elapsedMs": 1, "previewFile": "../../secret.png"},
    {"type": "item_complete", "itemIndex": 0, "jobId": "identity-" + "f" * 24, "elapsedMs": 1},
])
def test_invalid_events_fail_closed_without_publishing_images(batch_harness, event):
    client, _, _, boundary = batch_harness
    boundary.hold = True
    boundary.custom_events = lambda payload: boundary.emit(payload, event)
    result = wait_batch(client, submit_batch(client, batch_request(upload(client), previewEvery=5))["id"])
    assert result["state"] == "failed" and result["completedItems"] == 0
    assert result["previewUrl"] is None
    assert client.get("/api/history").json()["total"] == 0


def test_batches_reject_cross_origin_and_preview_traversal(batch_harness):
    client, _, _, _ = batch_harness
    request = batch_request(upload(client))
    assert client.post("/api/identity/batches", json=request, headers={"origin": "https://evil.invalid"}).status_code == 403
    batch = submit_batch(client, request)
    assert client.post(f"/api/identity/batches/{batch['id']}/cancel", headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert client.get(f"/api/identity/batches/{batch['id']}/previews/secret.png").status_code in {404, 422}
    assert client.get(f"/api/identity/batches/{batch['id']}/previews/..%5csecret.png").status_code in {404, 422}


def test_batch_item_cancel_uses_explicit_batch_endpoint(batch_harness):
    client, _, _, boundary = batch_harness
    boundary.hold = True
    batch = submit_batch(client, batch_request(upload(client)))
    wait_batch(client, batch["id"], lambda b: b["step"] == 5)
    response = client.post(f"/api/identity/jobs/{batch['items'][1]['id']}/cancel")
    assert response.status_code == 409
    assert "批次" in response.json()["message"]
    assert client.post(f"/api/identity/batches/{batch['id']}/cancel").status_code == 200


@pytest.mark.parametrize("image_kind", ["incomplete", "oversized"])
def test_preview_endpoint_rejects_unfinished_or_oversized_png_with_structured_error(batch_harness, image_kind):
    client, config, _, _ = batch_harness
    batch = submit_batch(client, batch_request(upload(client), previewEvery=5))
    wait_batch(client, batch["id"])
    name = batch["items"][0]["id"] + "-step-005.png"
    path = config.dream_root / "data" / "identity" / "batches" / batch["id"] / "previews" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if image_kind == "incomplete":
        path.write_bytes(b"\x89PNG\r\n\x1a\nunfinished")
    else:
        Image.new("RGB", (257, 128)).save(path)
    response = client.get(f"/api/identity/batches/{batch['id']}/previews/{name}")
    assert response.status_code in {404, 422}
    assert "预览" in response.json()["message"]


def test_random_batch_seed_is_frozen_and_wraps_across_paired_steps(batch_harness, monkeypatch):
    client, config, runner, _ = batch_harness
    reference = upload(client)
    monkeypatch.setattr("identity_batches.secrets.randbelow", lambda bound: 2147483647)
    request = batch_request(reference, stepValues=[5, 10])
    request["request"]["seed"] = "random"
    batch = submit_batch(client, request)
    assert batch["request"]["request"]["seed"] == 2147483647
    assert [(j["request"]["seed"], j["request"]["steps"]) for j in batch["items"]] == [(2147483647, 5), (2147483647, 10), (0, 5), (0, 10)]
    result = wait_batch(client, batch["id"])
    client.__exit__(None, None, None)
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as restored:
        assert restored.get(f"/api/identity/batches/{batch['id']}").json() == result


def test_profile_binding_cannot_be_archived_while_batch_is_queued(batch_harness):
    client, _, runner, boundary = batch_harness
    reference = upload(client)
    profile = wait_profile(client, create_profile(client, reference)["id"])
    release = threading.Event()
    blocker = runner.submit_serial(lambda: release.wait(5))
    try:
        batch = submit_batch(client, batch_request(reference, profileId=profile["id"]))
        assert not boundary.calls
        assert client.post(f"/api/identity/profiles/{profile['id']}/archive").status_code == 409
        renamed = client.post(f"/api/identity/profiles/{profile['id']}/rename", json={"name": "另一个名称"}).json()
        assert renamed["referenceId"] == profile["referenceId"]
        cancelled = client.post(f"/api/identity/batches/{batch['id']}/cancel").json()
        assert cancelled["state"] == "cancelled"
        assert all(j["state"] == "cancelled" for j in cancelled["items"])
        assert client.post(f"/api/identity/profiles/{profile['id']}/archive").status_code == 200
    finally:
        release.set()
        blocker.result(timeout=5)
    assert not boundary.calls


def test_restart_with_lagging_batch_record_preserves_complete_job_and_history(batch_harness):
    client, config, runner, boundary = batch_harness
    boundary.hold = True
    batch = submit_batch(client, batch_request(upload(client)))
    partial = wait_batch(client, batch["id"], lambda b: b["completedItems"] == 1 and b["step"] == 5)
    first = partial["items"][0]
    original = client.get(first["result"]["imageUrl"]).content
    payload = boundary.calls[0]
    client.__exit__(None, None, None)
    # Simulate a crash after the child job commit but before the batch commit.
    lagging = {**partial, "items": [batch["items"][0], partial["items"][1]], "completedItems": 0}
    batch_path = config.dream_root / "data" / "identity" / "batches" / f"{batch['id']}.json"
    batch_path.write_text(json.dumps(lagging), encoding="utf-8")
    pending = partial["items"][1]
    (config.dream_root / "data" / "identity" / "jobs" / f"{pending['id']}.json").write_text(json.dumps(pending), encoding="utf-8")
    Path(payload["items"][1]["outputPath"]).write_bytes(b"unfinished second image")
    Path(payload["items"][1]["metadataPath"]).write_text("{}", encoding="utf-8")
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as restored:
        recovered = restored.get(f"/api/identity/batches/{batch['id']}").json()
        assert recovered["state"] == "failed", recovered
        assert recovered["completedItems"] == 1
        assert [j["state"] for j in recovered["items"]] == ["complete", "failed"]
        assert recovered["request"] == batch["request"]
        assert restored.get(first["result"]["imageUrl"]).content == original
        assert restored.get("/api/history").json()["total"] == 1
        assert not Path(payload["items"][1]["outputPath"]).exists()
        assert not Path(payload["items"][1]["metadataPath"]).exists()


def test_partial_event_is_invisible_until_newline_then_progress_is_real(batch_harness):
    client, _, _, boundary = batch_harness
    boundary.hold = True
    def initial(payload):
        path = Path(payload["eventPath"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'{"type":"step","itemIndex":0,"step":3,')
    boundary.custom_events = initial
    batch = submit_batch(client, batch_request(upload(client)))
    assert boundary.started.wait(2)
    before = client.get(f"/api/identity/batches/{batch['id']}").json()
    assert before["step"] == before["progress"] == 0
    assert before["elapsedMs"] >= 0  # Execution time does not depend on a complete worker event.
    assert before["previewUrl"] is None and before["etaMs"] is None
    path = Path(boundary.calls[0]["eventPath"])
    with path.open("ab") as stream:
        stream.write(b'"totalSteps":10,"elapsedMs":60}\n')
    observed = wait_batch(client, batch["id"], lambda b: b["step"] == 3)
    assert observed["currentItem"] == 1 and observed["progress"] == 15
    assert observed["elapsedMs"] >= max(60, before["elapsedMs"])
    assert client.post(f"/api/identity/batches/{batch['id']}/cancel").status_code == 200


@pytest.mark.parametrize("raw", [b'{bad json}\n', b'{"type":"stage","stage":"x","elapsedMs":NaN}\n', b'{"type":"stage","stage":"x","elapsedMs":1e999}\n', b'x' * (16 * 1024 + 1)])
def test_dirty_bounded_event_stream_stops_owned_worker(batch_harness, raw):
    client, _, _, boundary = batch_harness
    boundary.hold = True
    def write_dirty(payload):
        path = Path(payload["eventPath"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    boundary.custom_events = write_dirty
    batch = submit_batch(client, batch_request(upload(client)))
    failed = wait_batch(client, batch["id"])
    assert failed["state"] == "failed"
    assert failed["progress"] == 0 and failed["previewUrl"] is None
    assert boundary.children[-1].poll() is not None


def test_preview_error_is_nonfatal_and_cross_batch_preview_is_not_served(batch_harness):
    client, _, _, boundary = batch_harness
    boundary.custom_events = lambda p: boundary.emit(p, {"type": "preview_error", "itemIndex": 0, "elapsedMs": 0, "message": "无法预览，继续生成"})
    first = wait_batch(client, submit_batch(client, batch_request(upload(client), previewEvery=5))["id"])
    assert first["state"] == "complete"
    second = wait_batch(client, submit_batch(client, batch_request(upload(client), previewEvery=5))["id"])
    filename = first["items"][0]["id"] + "-step-005.png"
    assert client.get(f"/api/identity/batches/{second['id']}/previews/{filename}").status_code == 422


def test_shutdown_batch_waits_for_child_and_keeps_completed_output(batch_harness):
    client, config, runner, boundary = batch_harness
    boundary.hold = True
    boundary.exit_allowed.clear()
    batch = submit_batch(client, batch_request(upload(client)))
    partial = wait_batch(client, batch["id"], lambda b: b["step"] == 5)
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as contender:
        with ThreadPoolExecutor(max_workers=1) as pool:
            closing = pool.submit(client.__exit__, None, None, None)
            try:
                time.sleep(.1)
                assert not closing.done()
                assert contender.get("/api/identity/batches").status_code == 503
            finally:
                boundary.exit_allowed.set()
                boundary.release.set()
            closing.result(timeout=5)
        result = contender.get(f"/api/identity/batches/{batch['id']}").json()
        assert result["state"] == "cancelled" and result["completedItems"] == 1
        assert contender.get(partial["items"][0]["result"]["imageUrl"]).status_code == 200


def test_shutdown_batch_disk_failure_logs_and_releases_for_recovery(batch_harness, monkeypatch, caplog):
    import identity_batches
    client, config, runner, _ = batch_harness
    reference = upload(client)
    release = threading.Event()
    blocker = runner.submit_serial(lambda: release.wait(5))
    batch = submit_batch(client, batch_request(reference))
    original_write = identity_batches.atomic_json
    def fail_cancel(path, value):
        if value.get("id") == batch["id"] and value.get("state") == "cancelled":
            raise OSError(28, "controlled batch disk full")
        return original_write(path, value)
    try:
        with monkeypatch.context() as disk:
            disk.setattr(identity_batches, "atomic_json", fail_cancel)
            client.__exit__(None, None, None)
        assert batch["id"] in caplog.text and "disk full" in caplog.text
    finally:
        release.set()
        blocker.result(timeout=5)
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as restored:
        value = restored.get(f"/api/identity/batches/{batch['id']}").json()
        assert value["state"] == "failed" and len(value["items"]) == 2


def test_step_values_limit_applies_after_deduplication(batch_harness):
    client, _, _, _ = batch_harness
    batch = submit_batch(client, batch_request(upload(client), stepValues=[10] * 20))
    assert batch["request"]["stepValues"] == [10]
    assert batch["totalItems"] == 2
    assert wait_batch(client, batch["id"])["state"] == "complete"


def test_running_batch_persistence_failure_reports_terminal_memory_state_and_keeps_original(batch_harness, monkeypatch, caplog):
    import identity_batches
    client, _, _, boundary = batch_harness
    boundary.hold = True
    batch = submit_batch(client, batch_request(upload(client)))
    partial = wait_batch(client, batch["id"], lambda b: b["step"] == 5)
    original_url = partial["items"][0]["result"]["imageUrl"]
    original = client.get(original_url).content
    original_write = identity_batches.atomic_json
    def disk_full(path, value):
        if value.get("id") == batch["id"]:
            raise OSError(28, "controlled runtime disk full")
        return original_write(path, value)
    with monkeypatch.context() as disk:
        disk.setattr(identity_batches, "atomic_json", disk_full)
        boundary.release.set()
        result = wait_batch(client, batch["id"])
        assert result["state"] == "failed"
        assert "保存" in result["error"]
        assert batch["id"] in caplog.text and "disk full" in caplog.text
        assert client.get(original_url).content == original
        assert boundary.children[-1].poll() is not None


def test_step_accepts_optional_preview_source_without_changing_progress(batch_harness):
    client, _, _, boundary = batch_harness
    boundary.hold = True
    boundary.custom_events = lambda p: boundary.emit(p, {"type": "step", "itemIndex": 0, "step": 1, "totalSteps": 10, "elapsedMs": 20, "previewSource": "predicted_original_sample"})
    batch = submit_batch(client, batch_request(upload(client)))
    observed = wait_batch(client, batch["id"], lambda b: b["step"] == 1 or b["state"] == "failed")
    assert observed["state"] == "sampling", observed
    assert observed["step"] == 1 and observed["progress"] == 5 and observed["elapsedMs"] >= 20
    assert client.post(f"/api/identity/batches/{batch['id']}/cancel").status_code == 200


def crash_before_completion_consumed(batch_harness):
    """Real persisted outputs/events, but neither job nor batch saw completion."""
    client, config, runner, boundary = batch_harness
    batch = submit_batch(client, batch_request(upload(client)))
    assert wait_batch(client, batch["id"])["state"] == "complete"
    payload = boundary.calls[0]
    original = Path(payload["items"][0]["outputPath"]).read_bytes()
    client.__exit__(None, None, None)
    root = config.dream_root / "data" / "identity"
    for item in batch["items"]:
        item.update(state="sampling", progress=90, message="正在采样")
        (root / "jobs" / f"{item['id']}.json").write_text(json.dumps(item), encoding="utf-8")
    # A later saved observation must not reject earlier events during replay.
    batch.update(state="sampling", currentItem=1, step=9, totalSteps=10, elapsedMs=90)
    (root / "batches" / f"{batch['id']}.json").write_text(json.dumps(batch), encoding="utf-8")
    events = [
        {"type": "step", "itemIndex": 0, "step": 1, "totalSteps": 10, "elapsedMs": 10},
        {"type": "item_complete", "itemIndex": 0, "jobId": batch["items"][0]["id"], "elapsedMs": 100},
    ]
    Path(payload["eventPath"]).write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    Path(payload["items"][1]["outputPath"]).write_bytes(b"unfinished second image")
    Path(payload["items"][1]["metadataPath"]).write_text("{}", encoding="utf-8")
    return batch, payload, original, root


@pytest.mark.parametrize("tail", [b"", b"{bad JSON}\n", b"[]\n", b"x" * 16385 + b"\n", b'{"type":', b'{"type":"item_complete","itemIndex":1,"jobId":"identity-ffffffffffffffffffffffff","elapsedMs":110}\n'], ids=["clean", "bad-json", "array", "oversized", "partial-tail", "wrong-job"])
def test_restart_replays_durable_completion_prefix_before_unfinished_cleanup(batch_harness, tail):
    _, config, runner, _ = batch_harness
    batch, payload, original, root = crash_before_completion_consumed(batch_harness)
    with Path(payload["eventPath"]).open("ab") as stream:
        stream.write(tail)
    orphan = {**batch["items"][1], "id": "identity-" + "e" * 24}
    (root / "jobs" / f"{orphan['id']}.json").write_text(json.dumps(orphan), encoding="utf-8")
    orphan_paths = [Path(payload["items"][1]["outputPath"]).with_name(orphan["id"] + suffix) for suffix in (".png", ".json")]
    for path in orphan_paths:
        path.write_bytes(b"orphan unfinished output")
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner)), base_url="http://127.0.0.1") as restored:
        recovered = restored.get(f"/api/identity/batches/{batch['id']}").json()
        assert recovered["state"] == "failed", recovered
        assert recovered["completedItems"] == 1
        assert [j["state"] for j in recovered["items"]] == ["complete", "failed"]
        first = recovered["items"][0]
        assert restored.get(first["result"]["imageUrl"]).content == original
        assert restored.get(f"/api/identity/jobs/{first['id']}").json() == first
        assert restored.get("/api/history").json()["total"] == 1
        assert restored.get(f"/api/identity/jobs/{orphan['id']}").json()["state"] == "failed"
        assert all(not path.exists() for path in orphan_paths)
        assert not Path(payload["items"][1]["outputPath"]).exists()
        assert not Path(payload["items"][1]["metadataPath"]).exists()
        assert restored.post(f"/api/identity/batches/{batch['id']}/cancel").json() == recovered


@pytest.mark.parametrize("damage", ["png", "metadata", "job_id", "member_request"])
def test_restart_does_not_protect_unvalidated_batch_output(batch_harness, damage):
    _, config, runner, _ = batch_harness
    batch, payload, _, root = crash_before_completion_consumed(batch_harness)
    if damage == "png":
        Path(payload["items"][0]["outputPath"]).write_bytes(b"not a PNG")
    elif damage == "metadata":
        Path(payload["items"][0]["metadataPath"]).write_text("[]", encoding="utf-8")
    elif damage == "job_id":
        Path(payload["eventPath"]).write_text(json.dumps({"type": "item_complete", "itemIndex": 0, "jobId": batch["items"][1]["id"], "elapsedMs": 100}) + "\n", encoding="utf-8")
    else:
        batch["items"][0]["request"]["seed"] += 1
        (root / "batches" / f"{batch['id']}.json").write_text(json.dumps(batch), encoding="utf-8")
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as restored:
        for item in batch["items"]:
            assert restored.get(f"/api/identity/jobs/{item['id']}").json()["state"] == "failed"
        assert restored.get("/api/history").json()["total"] == 0
        for item in payload["items"]:
            assert not Path(item["outputPath"]).exists()
            assert not Path(item["metadataPath"]).exists()


@pytest.mark.parametrize("point", ["metadata", "complete_job"])
@pytest.mark.parametrize("persistent", [False, True], ids=["transient", "repeated-restart"])
@pytest.mark.parametrize("completed_count", [1, 2], ids=["one-complete", "two-complete-bad-tail"])
def test_recovery_commit_failure_preserves_valid_output_and_retries_next_restart(batch_harness, monkeypatch, caplog, point, persistent, completed_count):
    import identity_batches
    import identity_service
    _, config, runner, worker = batch_harness
    batch, payload, original, root = crash_before_completion_consumed(batch_harness)
    if completed_count == 2:
        worker.complete_item(payload, 1)
        with Path(payload["eventPath"]).open("ab") as stream:
            stream.write(b"{bad JSON}\n")
    first = batch["items"][0]
    image_path = Path(payload["items"][0]["outputPath"])
    metadata_path = Path(payload["items"][0]["metadataPath"])
    job_path = root / "jobs" / f"{first['id']}.json"
    event_path = Path(payload["eventPath"])
    journal = event_path.read_bytes()
    boundary = identity_batches if point == "metadata" else identity_service
    original_write = boundary.atomic_json
    failures = []

    def fail_completion_commit(path, value):
        matches = path == metadata_path if point == "metadata" else path == job_path and value.get("state") == "complete"
        if matches and (persistent or not failures):
            failures.append(path)
            raise OSError(28, "controlled recovery completion disk full")
        return original_write(path, value)

    with monkeypatch.context() as disk:
        disk.setattr(boundary, "atomic_json", fail_completion_commit)
        for _ in range(2 if persistent else 1):
            with TestClient(create_app(config, DreamRuntime(config, job_runner=runner)), base_url="http://127.0.0.1") as restored:
                response = restored.get(f"/api/identity/batches/{batch['id']}")
                assert response.status_code == 200, response.text
                recovered = response.json()
                assert image_path.is_file(), "validated PNG was deleted after a commit error"
                assert image_path.read_bytes() == original
                assert json.loads(metadata_path.read_text(encoding="utf-8"))["id"] == first["id"]
                assert event_path.read_bytes() == journal
                assert recovered["state"] == "failed" and recovered["completedItems"] == completed_count
                assert "保存" in recovered["error"]
                assert "保存" in recovered["items"][0]["error"]
                assert restored.get(recovered["items"][0]["result"]["imageUrl"]).content == original
                assert restored.get(f"/api/identity/jobs/{first['id']}").json() == recovered["items"][0]
                assert json.loads(job_path.read_text(encoding="utf-8"))["state"] == "sampling"
                assert Path(payload["items"][1]["outputPath"]).exists() == (completed_count == 2)
                assert Path(payload["items"][1]["metadataPath"]).exists() == (completed_count == 2)
                assert restored.post(f"/api/identity/batches/{batch['id']}/cancel").status_code == 200
    assert failures and "controlled recovery completion disk full" in caplog.text
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as retried:
        recovered = retried.get(f"/api/identity/batches/{batch['id']}").json()
        assert recovered["state"] == "failed" and recovered["completedItems"] == completed_count
        assert [j["state"] for j in recovered["items"]] == ["complete"] * completed_count + ["failed"] * (2 - completed_count)
        assert recovered["items"][0]["error"] is None
        assert json.loads(job_path.read_text(encoding="utf-8"))["state"] == "complete"
        assert retried.get(recovered["items"][0]["result"]["imageUrl"]).content == original
        assert retried.get("/api/history").json()["total"] == completed_count
        assert event_path.read_bytes() == journal


@pytest.mark.parametrize("point", ["first_child", "second_child", "index", "batch"])
def test_submission_write_failure_rolls_back_children_ownership_and_index(batch_harness, monkeypatch, point):
    import identity_batches
    client, config, runner, boundary = batch_harness
    reference = upload(client)
    profile = wait_profile(client, create_profile(client, reference)["id"])
    existing = wait_batch(client, submit_batch(client, batch_request(reference))["id"])
    root = config.dream_root / "data" / "identity"
    index_before = (root / "jobs" / "index.json").read_bytes()
    jobs_before = client.get("/api/identity/jobs").json()
    paths_before = set((root / "jobs").glob("*.json"))
    original_write = identity_batches.atomic_json
    attempted = []

    def fail_write(path, value):
        if path.parent.name == "jobs" and path.name != "index.json":
            attempted.append(value["id"])
        matched = ((point == "first_child" and len(attempted) == 1) or
                   (point == "second_child" and len(attempted) == 2) or
                   (point == "index" and path.name == "index.json") or
                   (point == "batch" and path.parent.name == "batches"))
        if matched:
            raise OSError(28, "controlled initial submission disk full")
        return original_write(path, value)

    with monkeypatch.context() as disk:
        disk.setattr(identity_batches, "atomic_json", fail_write)
        response = client.post("/api/identity/batches", json=batch_request(reference, profileId=profile["id"]))
    assert response.status_code == 503, response.text
    assert "保存" in response.json()["message"]
    assert len(boundary.calls) == 1  # Failed submission must never launch a worker.
    assert client.get("/api/identity/jobs").json() == jobs_before
    assert client.get("/api/identity/batches").json() == [existing]
    assert set((root / "jobs").glob("*.json")) == paths_before
    assert (root / "jobs" / "index.json").read_bytes() == index_before
    for job_id in attempted:
        assert client.post(f"/api/identity/jobs/{job_id}/cancel").status_code == 404
    assert client.post(f"/api/identity/profiles/{profile['id']}/archive").status_code == 200
    client.__exit__(None, None, None)
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner)), base_url="http://127.0.0.1") as restored:
        assert restored.get("/api/identity/jobs").json() == jobs_before
        assert restored.get("/api/identity/batches").json() == [existing]
        assert wait_batch(restored, submit_batch(restored, batch_request(reference))["id"])["state"] == "complete"


@pytest.mark.parametrize("exit_mode", ["failed", "cancelled"])
def test_worker_final_drain_keeps_completion_before_bad_json(batch_harness, exit_mode):
    client, _, _, boundary = batch_harness
    # For cancellation, write the event only after termination was requested:
    # it must be picked up by the post-exit drain, not a prior progress poll.
    if exit_mode == "failed":
        boundary.fail = True
        def completion_then_bad_json(payload):
            boundary.complete_item(payload, 0)
            with Path(payload["eventPath"]).open("ab") as stream:
                stream.write(b"{bad JSON}\n")
        boundary.custom_events = completion_then_bad_json
    else:
        boundary.hold = True
        boundary.custom_events = lambda payload: None
    batch = submit_batch(client, batch_request(upload(client)))
    assert boundary.started.wait(2)
    if exit_mode == "cancelled":
        child = boundary.children[-1]
        original_terminate = child.terminate
        def terminate_with_final_event():
            payload = boundary.calls[-1]
            boundary.complete_item(payload, 0)
            with Path(payload["eventPath"]).open("ab") as stream:
                stream.write(b"{bad JSON}\n")
            original_terminate()
        child.terminate = terminate_with_final_event
        assert client.post(f"/api/identity/batches/{batch['id']}/cancel").status_code == 200
    result = wait_batch(client, batch["id"])
    assert result["state"] == exit_mode
    assert result["completedItems"] == 1
    assert result["items"][0]["state"] == "complete"
    assert client.get(result["items"][0]["result"]["imageUrl"]).status_code == 200
    assert client.get("/api/history").json()["total"] == 1
    assert boundary.children[-1].poll() is not None
