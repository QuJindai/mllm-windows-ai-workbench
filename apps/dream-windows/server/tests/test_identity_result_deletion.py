from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import threading

import history_transactions

from test_identity_api import harness, upload, submit, finished
from test_identity_profiles import profile_harness
from test_identity_batches import batch_harness, batch_request, submit_batch, wait_batch


def test_temporarily_missing_output_is_not_claimed_deleted(harness):
    client, _, _, _ = harness
    completed = finished(client, submit(client, upload(client))["id"])
    output = Path(completed["result"]["metadata"]["output"])
    temporary = output.with_suffix(".temporarily-unavailable")
    output.rename(temporary)
    try:
        assert not client.get(f"/api/identity/jobs/{completed['id']}").json().get("resultDeleted", False)
    finally:
        temporary.rename(output)


def test_deletion_read_does_not_hide_image_when_commit_fails_and_rolls_back(harness, monkeypatch):
    client, _, _, _ = harness
    completed = finished(client, submit(client, upload(client))["id"])
    moved, release = threading.Event(), threading.Event()
    original = history_transactions._write_record

    def fail_commit(root, destination, record):
        if destination.name == "committed.json":
            moved.set()
            assert release.wait(3)
            raise PermissionError("controlled commit failure")
        return original(root, destination, record)

    monkeypatch.setattr(history_transactions, "_write_record", fail_commit)
    with ThreadPoolExecutor(2) as pool:
        deletion = pool.submit(client.delete, f"/api/history/{completed['id']}")
        try:
            assert moved.wait(3)
            read = pool.submit(client.get, f"/api/identity/jobs/{completed['id']}")
            # Reading before a failed transaction commits must not report deletion.
        finally:
            release.set()
        assert deletion.result().status_code >= 400
        assert not read.result().json().get("resultDeleted", False)
    assert client.get(completed["result"]["imageUrl"]).status_code == 200


def test_deleted_result_is_annotated_on_task_and_list_without_mutating_task_or_reference(harness):
    client, config, _, _ = harness
    reference = upload(client)
    completed = finished(client, submit(client, reference)["id"])
    job_id = completed["id"]
    record = config.dream_root / "data" / "identity" / "jobs" / f"{job_id}.json"
    saved_record = record.read_bytes()
    ref = client.get(reference["imageUrl"]).content
    assert not completed.get("resultDeleted", False)
    response = client.delete(f"/api/history/{job_id}")
    assert response.status_code == 200
    assert not Path(completed["result"]["metadata"]["output"]).exists()
    assert client.get(f"/api/identity/jobs/{job_id}").json().get("resultDeleted") is True
    assert client.get("/api/identity/jobs").json()[0].get("resultDeleted") is True
    assert record.read_bytes() == saved_record
    assert client.get(reference["imageUrl"]).content == ref
    assert client.get("/api/history").json()["total"] == 0


def test_deleting_one_batch_result_preserves_siblings_and_frozen_batch(batch_harness):
    client, config, _, _ = batch_harness
    reference = upload(client)
    completed = wait_batch(client, submit_batch(client, batch_request(reference))["id"])
    first, sibling = completed["items"]
    record = config.dream_root / "data" / "identity" / "batches" / f"{completed['id']}.json"
    frozen_batch = record.read_bytes()
    sibling_image = client.get(sibling["result"]["imageUrl"]).content
    assert client.delete(f"/api/history/{first['id']}").status_code == 200
    for refreshed in [client.get(f"/api/identity/batches/{completed['id']}").json(), client.get("/api/identity/batches").json()[0]]:
        assert refreshed["items"][0].get("resultDeleted") is True
        assert not refreshed["items"][1].get("resultDeleted", False)
    assert record.read_bytes() == frozen_batch
    assert client.get(sibling["result"]["imageUrl"]).content == sibling_image
    assert client.get(reference["imageUrl"]).status_code == 200
    assert client.get("/api/history").json()["total"] == 1
