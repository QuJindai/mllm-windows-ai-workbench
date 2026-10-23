"""Service-side execution time, independent of worker events and queue delay."""
import hashlib
import json
from pathlib import Path
import threading

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from app import create_app
import identity_batches
from identity_service import IdentityService, WorkerCancelled
from runtime import DreamRuntime
from test_identity_api import harness, upload
from test_identity_profiles import profile_harness
from test_identity_batches import batch_harness, batch_request, submit_batch, wait_batch


@pytest.fixture
def clock(monkeypatch):
    value = [100.0]
    # Only the batch clock is controlled; queue waits and test deadlines stay real.
    monkeypatch.setattr(identity_batches, "monotonic", lambda: value[0], raising=False)
    return value


def files_digest(paths):
    return {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def write_image(item):
    Image.new("RGB", (item["width"], item["height"]), "navy").save(item["outputPath"])
    Path(item["metadataPath"]).write_text(json.dumps({"seed": item["seed"]}), encoding="utf-8")


@pytest.mark.parametrize("outcome", ["failed", "cancelled", "complete"])
def test_execution_clock_excludes_queue_and_freezes_at_terminal_even_without_events(batch_harness, monkeypatch, clock, outcome):
    client, config, runner, _ = batch_harness
    reference = upload(client)
    started, finish, dequeue = threading.Event(), threading.Event(), threading.Event()
    blocker = runner.submit_serial(dequeue.wait)
    original = IdentityService._worker

    def controlled(service, operation, payload, cancelled=None):
        if operation != "batch":
            return original(service, operation, payload, cancelled)
        started.set()
        assert finish.wait(5)
        if outcome == "failed":
            raise TimeoutError("controlled 15 minute timeout before the first event")
        if outcome == "cancelled":
            raise WorkerCancelled()
        for item in payload["items"]:
            write_image(item)
        return {"ok": True, "items": [{"jobId": item["jobId"]} for item in payload["items"]]}

    monkeypatch.setattr(IdentityService, "_worker", controlled)
    try:
        batch = submit_batch(client, batch_request(reference))
        clock[0] += 600
        assert client.get(f"/api/identity/batches/{batch['id']}").json()["elapsedMs"] == 0
        dequeue.set()
        blocker.result(timeout=5)
        assert started.wait(5)
        record_path = config.dream_root / "data/identity/batches" / f"{batch['id']}.json"
        saved_before_reads = record_path.read_bytes()
        clock[0] += 900
        running = client.get(f"/api/identity/batches/{batch['id']}").json()
        assert running["state"] == "preparing"
        assert running["elapsedMs"] == 900_000
        assert client.get("/api/identity/batches").json()[0]["elapsedMs"] == 900_000
        assert record_path.read_bytes() == saved_before_reads  # GET is not a write.
    finally:
        dequeue.set()
        finish.set()
    terminal = wait_batch(client, batch["id"])
    assert terminal["state"] == outcome, terminal
    assert terminal["elapsedMs"] == 900_000
    assert json.loads(record_path.read_text(encoding="utf-8"))["elapsedMs"] == 900_000
    saved_terminal = record_path.read_bytes()
    clock[0] += 10_000
    assert client.get(f"/api/identity/batches/{batch['id']}").json() == terminal
    assert client.get("/api/identity/batches").json()[0] == terminal
    assert record_path.read_bytes() == saved_terminal
    client.__exit__(None, None, None)
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner)), base_url="http://127.0.0.1") as restored:
        assert restored.get(f"/api/identity/batches/{batch['id']}").json()["elapsedMs"] == 900_000
        clock[0] += 10_000
        assert restored.get("/api/identity/batches").json()[0]["elapsedMs"] == 900_000
        assert record_path.read_bytes() == saved_terminal


def test_execution_clock_includes_pre_dispatch_preparation_failure(batch_harness, monkeypatch, clock):
    client, _, runner, boundary = batch_harness
    reference = upload(client)
    entered, finish = threading.Event(), threading.Event()

    def failed_preparation():
        entered.set()
        assert finish.wait(5)
        raise TimeoutError("controlled native ownership preparation timeout")

    monkeypatch.setattr(runner, "release_native_for_identity", failed_preparation)
    try:
        batch = submit_batch(client, batch_request(reference))
        assert entered.wait(5)
        clock[0] += 42
        assert client.get(f"/api/identity/batches/{batch['id']}").json()["elapsedMs"] == 42_000
    finally:
        finish.set()
    failed = wait_batch(client, batch["id"])
    assert failed["state"] == "failed" and failed["elapsedMs"] == 42_000
    assert boundary.calls == []


@pytest.mark.parametrize("outcome", ["failed", "cancelled"])
def test_late_worker_events_use_their_own_clock_and_completed_files_stay_unchanged(batch_harness, monkeypatch, clock, outcome):
    client, config, _, _ = batch_harness
    reference = upload(client)
    observed, finish = threading.Event(), threading.Event()
    protected = {}
    original = IdentityService._worker

    def controlled(service, operation, payload, cancelled=None):
        if operation != "batch":
            return original(service, operation, payload, cancelled)
        batch_id = Path(payload["eventPath"]).parent.name
        clock[0] += 10  # Startup precedes the worker's own time origin.
        assert service.batches.get(batch_id)["elapsedMs"] == 10_000
        service.batches.consume(batch_id, {"type": "stage", "stage": "sampling", "elapsedMs": 0})
        service.batches.consume(batch_id, {"type": "step", "itemIndex": 0, "step": 1, "totalSteps": 10, "elapsedMs": 100})
        with pytest.raises(ValueError, match="时间不能倒退"):
            service.batches.consume(batch_id, {"type": "stage", "stage": "bad timestamp", "elapsedMs": 99})
        item = payload["items"][0]
        write_image(item)
        service.batches.consume(batch_id, {"type": "item_complete", "itemIndex": 0, "jobId": item["jobId"], "elapsedMs": 200})
        protected.update(files_digest([Path(item["outputPath"]), Path(item["metadataPath"]),
                                      config.dream_root / "data/identity/jobs" / f"{item['jobId']}.json"]))
        observed.set()
        assert finish.wait(5)
        if outcome == "cancelled":
            raise WorkerCancelled()
        raise TimeoutError("controlled failure after one completed item")

    monkeypatch.setattr(IdentityService, "_worker", controlled)
    try:
        batch = submit_batch(client, batch_request(reference))
        assert observed.wait(5)
        clock[0] += 20
        running = client.get(f"/api/identity/batches/{batch['id']}").json()
        assert running["elapsedMs"] == 30_000 and running["completedItems"] == 1
    finally:
        finish.set()
    terminal = wait_batch(client, batch["id"])
    assert terminal["state"] == outcome and terminal["elapsedMs"] == 30_000
    assert terminal["items"][0] == running["items"][0]
    assert files_digest(protected) == protected
    clock[0] += 5000
    assert client.get(f"/api/identity/batches/{batch['id']}").json() == terminal
    assert files_digest(protected) == protected
