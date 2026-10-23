"""Retry contracts use real storage/routes/queue and a controlled worker only."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import create_app
from runtime import DreamRuntime
from identity_service import IdentityService
from identity_batches import BatchRetryRequest
from test_identity_api import harness, upload
from test_identity_profiles import profile_harness, create_profile, wait_profile
from test_identity_batches import batch_harness, batch_request, submit_batch, wait_batch


def retry(client, parent, mode="failed", key="retry-1"):
    return client.post(f"/api/identity/batches/{parent['id']}/retry", json={"mode": mode, "idempotencyKey": key})


def partial(batch_harness, *, cancelled=False, profile=False, random=False):
    client, _, _, worker = batch_harness
    reference = upload(client)
    person = wait_profile(client, create_profile(client, reference)["id"]) if profile else None
    request = batch_request(reference, count=2, stepValues=[10, 20], previewEvery=5,
                            profileId=person["id"] if person else None)
    request["request"]["seed"] = "random" if random else 2147483647
    worker.hold, worker.fail = cancelled, not cancelled
    parent = submit_batch(client, request)
    if cancelled:
        wait_batch(client, parent["id"], lambda value: value["step"] == 5)
        assert client.post(f"/api/identity/batches/{parent['id']}/cancel").status_code == 200
    parent = wait_batch(client, parent["id"])
    worker.hold = worker.fail = False
    return parent, reference, person


def digest(paths):
    return {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


@pytest.mark.parametrize("random", [False, True])
def test_retry_preserves_frozen_matrix_profile_and_completed_files(batch_harness, random):
    client, config, _, worker = batch_harness
    parent, _, profile = partial(batch_harness, profile=True, random=random)
    root = config.dream_root / "data" / "identity"
    first = parent["items"][0]
    output = Path(first["result"]["metadata"]["output"])
    protected = [root / "batches" / f"{parent['id']}.json", root / "jobs" / f"{first['id']}.json", output, output.with_suffix(".json")]
    before = digest(protected)
    assert client.post(f"/api/identity/profiles/{profile['id']}/preset", json={"jobId": first["id"]}).status_code == 200
    response = retry(client, parent)
    assert response.status_code == 200, response.text
    child = response.json()
    assert child["parentBatchId"] == parent["id"]
    assert child["originalItemIndices"] == [1, 2, 3]
    assert child["request"] == parent["request"]
    assert [item["request"] for item in child["items"]] == [item["request"] for item in parent["items"][1:]]
    if not random:
        assert [(item["request"]["seed"], item["request"]["steps"]) for item in child["items"]] == [(2147483647, 20), (0, 10), (0, 20)]
    assert not {item["id"] for item in parent["items"]} & {item["id"] for item in child["items"]}
    completed = wait_batch(client, child["id"])
    assert completed["state"] == "complete", completed
    assert completed["completedItems"] == 3
    assert worker.calls[-1]["previewEvery"] == 5
    assert digest(protected) == before
    assert client.get(f"/api/identity/batches/{parent['id']}").json() == parent
    assert client.get("/api/history").json()["total"] == 4


def test_cancelled_only_selected_by_unfinished(batch_harness):
    client, _, _, _ = batch_harness
    parent, _, _ = partial(batch_harness, cancelled=True)
    response = retry(client, parent)
    assert response.status_code == 409 and response.json()["code"] == "IDENTITY_BATCH_RETRY_EMPTY"
    response = retry(client, parent, "unfinished")
    assert response.status_code == 200, response.text
    assert response.json()["originalItemIndices"] == [1, 2, 3]
    assert wait_batch(client, response.json()["id"])["state"] == "complete"


def test_retry_rejects_active_parent_without_child(batch_harness):
    client, _, _, worker = batch_harness
    worker.hold = True
    parent = submit_batch(client, batch_request(upload(client)))
    wait_batch(client, parent["id"], lambda value: value["step"] == 5)
    response = retry(client, parent, "unfinished")
    assert response.status_code == 409 and response.json()["code"] == "IDENTITY_BATCH_ACTIVE"
    assert len(client.get("/api/identity/batches").json()) == 1


def test_deleted_complete_result_is_never_a_retry_candidate(batch_harness):
    client, _, _, worker = batch_harness
    parent = wait_batch(client, submit_batch(client, batch_request(upload(client)))["id"])
    assert client.delete(f"/api/history/{parent['items'][0]['id']}").status_code == 200
    response = retry(client, parent, "unfinished")
    assert response.status_code == 409 and response.json()["code"] == "IDENTITY_BATCH_RETRY_EMPTY"
    assert len(worker.calls) == 1


@pytest.mark.parametrize("body", [{}, {"mode": "all", "idempotencyKey": "k"}, {"mode": "failed", "idempotencyKey": ""}, {"mode": "failed", "idempotencyKey": "   "}, {"mode": "failed", "idempotencyKey": 1}, {"mode": "failed", "idempotencyKey": "x" * 129}, {"mode": "failed", "idempotencyKey": "k", "seed": 7}])
def test_retry_validates_body_without_persistence(batch_harness, body):
    client, _, _, worker = batch_harness
    response = client.post('/api/identity/batches/batch-' + 'a' * 24 + '/retry', json=body)
    assert response.status_code == 422
    assert client.get('/api/identity/batches').json() == [] and worker.calls == []


@pytest.mark.parametrize("damage", ["reference", "profile"])
def test_retry_rejects_missing_or_incompatible_input_before_writes(batch_harness, damage):
    client, config, _, worker = batch_harness
    parent, reference, person = partial(batch_harness, profile=True)
    before = set((config.dream_root / 'data' / 'identity' / 'jobs').glob('*.json'))
    if damage == "reference":
        (config.dream_root / 'data' / 'identity' / 'references' / f"{reference['id']}.png").unlink()
    else:
        assert client.post(f"/api/identity/profiles/{person['id']}/archive").status_code == 200
    response = retry(client, parent)
    assert response.status_code in {404, 409, 422}, response.text
    assert response.json()["code"] == ("IDENTITY_REFERENCE_NOT_FOUND" if damage == "reference" else "IDENTITY_PROFILE_CONFLICT")
    assert set((config.dream_root / 'data' / 'identity' / 'jobs').glob('*.json')) == before
    assert len(worker.calls) == 1


def test_duplicate_requests_and_normal_submit_share_serial_queue(batch_harness):
    client, _, runner, worker = batch_harness
    parent, reference, _ = partial(batch_harness)
    release = threading.Event()
    blocker = runner.submit_serial(lambda: release.wait(5))
    try:
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(retry, client, parent) for _ in range(4)]
            normal = pool.submit(submit_batch, client, batch_request(reference))
            responses = [future.result() for future in futures]
            ordinary = normal.result()
        assert all(response.status_code == 200 for response in responses)
        ids = {response.json()["id"] for response in responses}
        assert len(ids) == 1 and ordinary["id"] not in ids
        conflict = retry(client, parent, "unfinished")
        assert conflict.status_code == 409 and conflict.json()["code"] == "IDENTITY_BATCH_RETRY_CONFLICT"
    finally:
        release.set()
        blocker.result(timeout=5)
    assert wait_batch(client, ids.pop())["state"] == "complete"
    assert wait_batch(client, ordinary["id"])["state"] == "complete"
    assert len(worker.calls) == 3


def test_idempotency_survives_restart_and_retry_of_child_preserves_root_indices(batch_harness):
    client, config, runner, worker = batch_harness
    parent, _, _ = partial(batch_harness)
    worker.fail = True
    response = retry(client, parent)
    assert response.status_code == 200, response.text
    child = wait_batch(client, response.json()["id"])
    assert child["state"] == "failed"
    worker.fail = False
    client.__exit__(None, None, None)
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner)), base_url="http://127.0.0.1") as restored:
        replay = retry(restored, parent)
        assert replay.status_code == 200 and replay.json()["id"] == child["id"]
        assert len(worker.calls) == 2
        response = retry(restored, child, key="child-retry")
        assert response.status_code == 200, response.text
        assert response.json()["originalItemIndices"] == [2, 3]
        assert response.json()["parentBatchId"] == child["id"]
        assert wait_batch(restored, response.json()["id"])["state"] == "complete"


def test_committed_retry_interrupted_before_enqueue_is_not_resubmitted(batch_harness, monkeypatch):
    client, config, runner, worker = batch_harness
    parent, _, _ = partial(batch_harness)
    client.__exit__(None, None, None)
    service = IdentityService(config, runner)
    class PowerLoss(BaseException):
        pass
    try:
        with monkeypatch.context() as crash:
            def interrupt(*args):
                raise PowerLoss()
            crash.setattr(IdentityService, "_submit_background", interrupt)
            with pytest.raises(PowerLoss):
                service.batch_operation("retry", parent['id'], BatchRetryRequest(mode="failed", idempotencyKey="retry-1"))
    finally:
        service.close()
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner)), base_url="http://127.0.0.1") as restored:
        response = retry(restored, parent)
        assert response.status_code == 200, response.text
        assert response.json()["state"] == "failed"
        assert len(restored.get('/api/identity/batches').json()) == 2
        assert len(worker.calls) == 1


@pytest.mark.parametrize("damage", ["cycle", "indices", "request"])
def test_malformed_child_ancestry_blocks_key_reuse_after_restart(batch_harness, damage):
    client, config, runner, worker = batch_harness
    parent, _, _ = partial(batch_harness)
    response = retry(client, parent)
    assert response.status_code == 200, response.text
    child = wait_batch(client, response.json()["id"])
    client.__exit__(None, None, None)
    path = config.dream_root / 'data' / 'identity' / 'batches' / f"{child['id']}.json"
    record = json.loads(path.read_text(encoding='utf-8'))
    if damage == "cycle":
        record['parentBatchId'] = record['id']
    elif damage == "indices":
        record['originalItemIndices'] = [0, 0, 0]
    else:
        record['request']['request']['seed'] = 17
    path.write_text(json.dumps(record), encoding='utf-8')
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner)), base_url="http://127.0.0.1") as restored:
        response = retry(restored, parent)
        assert response.status_code == 409, response.text
        assert len(worker.calls) == 2


@pytest.mark.parametrize("point", ["job", "index", "batch"])
def test_retry_save_failure_does_not_reserve_key_or_change_parent(batch_harness, monkeypatch, point):
    import identity_batches
    client, config, _, worker = batch_harness
    parent, _, _ = partial(batch_harness)
    root = config.dream_root / 'data' / 'identity'
    paths = [*root.joinpath('jobs').glob('*.json'), *root.joinpath('batches').glob('*.json')]
    before = digest(paths)
    original = identity_batches.atomic_json
    def fail_write(path, value):
        if ((point == 'job' and path.parent.name == 'jobs' and path.name != 'index.json')
                or (point == 'index' and path.name == 'index.json')
                or (point == 'batch' and path.parent.name == 'batches')):
            raise OSError(28, 'controlled retry write failure')
        original(path, value)
    with monkeypatch.context() as disk:
        disk.setattr(identity_batches, 'atomic_json', fail_write)
        response = retry(client, parent)
    assert response.status_code == 503 and response.json()['code'] == 'IDENTITY_BATCH_SAVE_FAILED'
    assert digest(paths) == before
    assert set(root.joinpath('jobs').glob('*.json')) | set(root.joinpath('batches').glob('*.json')) == set(paths)
    assert len(worker.calls) == 1
    accepted = retry(client, parent)
    assert accepted.status_code == 200, accepted.text
    assert wait_batch(client, accepted.json()['id'])['state'] == 'complete'


def test_enqueue_failure_keeps_durable_key_and_child_for_explicit_retry(batch_harness, monkeypatch):
    client, config, runner, worker = batch_harness
    parent, _, _ = partial(batch_harness)
    with monkeypatch.context() as queue:
        def unavailable(*args):
            raise RuntimeError('controlled queue rejection')
        queue.setattr(IdentityService, '_submit_background', unavailable)
        response = retry(client, parent)
    assert response.status_code == 200, response.text
    child = response.json()
    assert child['state'] == 'failed'
    client.__exit__(None, None, None)
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner)), base_url='http://127.0.0.1') as restored:
        same = retry(restored, parent)
        assert same.status_code == 200 and same.json()['id'] == child['id']
        assert len(worker.calls) == 1
        continuation = retry(restored, child, key='new-attempt')
        assert continuation.status_code == 200, continuation.text
        assert wait_batch(restored, continuation.json()['id'])['state'] == 'complete'


@pytest.mark.parametrize('mode, expected', [('failed', [1]), ('unfinished', [1, 2, 3])])
def test_retry_selection_excludes_queued_and_cancelled_from_failed_only(batch_harness, mode, expected):
    client, config, runner, worker = batch_harness
    parent, _, _ = partial(batch_harness)
    client.__exit__(None, None, None)
    service = IdentityService(config, runner)
    try:
        service.batch_operation('get', parent['id'])
        # A terminal snapshot can include queued work after an interrupted
        # persistence operation. Exercise selection before restart normalizes it.
        record = service.batches.records[parent['id']]
        record['items'][2]['state'] = 'cancelled'
        record['items'][3]['state'] = 'queued'
        service.batches._save(record)
        child = service.batch_operation('retry', parent['id'], BatchRetryRequest(mode=mode, idempotencyKey='mixed'))
        assert child['originalItemIndices'] == expected
    finally:
        service.close()


def test_retry_rejects_parent_whose_terminal_state_was_not_saved(batch_harness, monkeypatch):
    import identity_batches
    client, config, _, worker = batch_harness
    original = identity_batches.atomic_json
    def fail_terminal(path, value):
        if path.parent.name == 'batches' and value.get('state') == 'failed':
            raise OSError(28, 'controlled terminal parent write failure')
        original(path, value)
    with monkeypatch.context() as disk:
        disk.setattr(identity_batches, 'atomic_json', fail_terminal)
        parent, _, _ = partial(batch_harness)
    root = config.dream_root / 'data' / 'identity'
    assert json.loads((root / 'batches' / f"{parent['id']}.json").read_text(encoding='utf-8'))['state'] == 'sampling'
    before = digest([*root.joinpath('jobs').glob('*.json'), *root.joinpath('batches').glob('*.json')])
    response = retry(client, parent)
    assert response.status_code == 409 and response.json()['code'] == 'IDENTITY_BATCH_RETRY_INVALID', response.text
    assert digest(before) == before
    assert len(worker.calls) == 1


@pytest.mark.parametrize('operation', ['generate', 'batch', 'retry'])
@pytest.mark.parametrize('free', [0, 2 * 1024 ** 3 - 1])
def test_identity_capacity_blocks_new_work_without_records_or_dispatch(batch_harness, monkeypatch, operation, free):
    client, config, _, worker = batch_harness
    if operation == 'retry':
        parent, reference, _ = partial(batch_harness)
    else:
        reference = upload(client)
    root = config.dream_root / 'data' / 'identity'
    before = digest([*root.joinpath('jobs').glob('*.json'), *root.joinpath('batches').glob('*.json')])
    calls = len(worker.calls)
    monkeypatch.setattr(shutil, 'disk_usage', lambda path: SimpleNamespace(free=free))
    if operation == 'retry':
        response = retry(client, parent)
    else:
        payload = batch_request(reference)
        endpoint = '/api/identity/batches' if operation == 'batch' else '/api/identity/generate'
        response = client.post(endpoint, json=payload if operation == 'batch' else payload['request'])
    assert response.status_code == 507, response.text
    assert response.json()['code'] == 'DISK_SPACE_LOW'
    assert response.json()['detail']['freeBytes'] == free
    assert response.json()['retryable'] is True
    after = digest([*root.joinpath('jobs').glob('*.json'), *root.joinpath('batches').glob('*.json')])
    assert after == before
    assert len(worker.calls) == calls


@pytest.mark.parametrize('operation', ['generate', 'batch', 'retry'])
@pytest.mark.parametrize('free', [2 * 1024 ** 3, None], ids=['threshold', 'unknown'])
def test_identity_capacity_warning_or_unknown_allows_new_work(batch_harness, monkeypatch, operation, free):
    from test_identity_api import finished
    client, _, _, _ = batch_harness
    if operation == 'retry':
        parent, reference, _ = partial(batch_harness)
    else:
        reference = upload(client)
    def measure(path):
        if free is None:
            raise OSError('controlled unavailable disk measurement')
        return SimpleNamespace(free=free)
    monkeypatch.setattr(shutil, 'disk_usage', measure)
    if operation == 'retry':
        response = retry(client, parent)
    else:
        payload = batch_request(reference)
        endpoint = '/api/identity/batches' if operation == 'batch' else '/api/identity/generate'
        response = client.post(endpoint, json=payload if operation == 'batch' else payload['request'])
    assert response.status_code == 200, response.text
    result = (finished if operation == 'generate' else wait_batch)(client, response.json()['id'])
    assert result['state'] == 'complete', result


@pytest.mark.parametrize('mode', ['failed', 'unfinished'])
def test_low_disk_allows_idempotent_retry_reads_and_cancel_even_after_restart(batch_harness, monkeypatch, mode):
    client, config, runner, worker = batch_harness
    parent, reference, _ = partial(batch_harness)
    release = threading.Event()
    blocker = runner.submit_serial(release.wait)
    try:
        accepted = retry(client, parent, mode)
        assert accepted.status_code == 200, accepted.text
        child = accepted.json()
        ordinary = client.post('/api/identity/generate', json=batch_request(reference)['request'])
        assert ordinary.status_code == 200, ordinary.text
        monkeypatch.setattr(shutil, 'disk_usage', lambda path: SimpleNamespace(free=0))
        replay = retry(client, parent, mode)
        assert replay.status_code == 200 and replay.json()['id'] == child['id']
        assert replay.json()['state'] == 'queued'
        for url in ['/api/identity/batches', '/api/identity/jobs', f"/api/identity/batches/{parent['id']}",
                    f"/api/identity/batches/{child['id']}", f"/api/identity/jobs/{ordinary.json()['id']}",
                    parent['items'][0]['result']['imageUrl']]:
            assert client.get(url).status_code == 200, url
        assert client.post(f"/api/identity/batches/{child['id']}/cancel").json()['state'] == 'cancelled'
        assert client.post(f"/api/identity/jobs/{ordinary.json()['id']}/cancel").json()['state'] == 'cancelled'
        assert len(worker.calls) == 1
    finally:
        release.set()
        blocker.result(timeout=5)
    client.__exit__(None, None, None)
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner)), base_url='http://127.0.0.1') as restored:
        replay = retry(restored, parent, mode)
        assert replay.status_code == 200 and replay.json()['id'] == child['id']
        assert replay.json()['state'] == 'cancelled'
        fresh = retry(restored, parent, mode, key='new-request')
        assert fresh.status_code == 507 and fresh.json()['code'] == 'DISK_SPACE_LOW', fresh.text
        assert len(restored.get('/api/identity/batches').json()) == 2
        assert len(worker.calls) == 1
