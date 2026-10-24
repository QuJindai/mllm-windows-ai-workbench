"""Deletion contracts use synthetic files and controlled workers, never real photos."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pytest
from fastapi.testclient import TestClient

from app import create_app
import history_transactions
from runtime import DreamRuntime
from test_identity_api import harness, upload, submit, finished
from test_identity_profiles import profile_harness
from test_identity_batches import batch_harness, batch_request, submit_batch, wait_batch


def receipts(config):
    return list((config.dream_root / 'data/history-trash').glob('*/committed.json'))


def assert_hidden(client, job_id, *, result_deleted=False):
    records = [client.get(f'/api/identity/jobs/{job_id}').json(),
               next(j for j in client.get('/api/identity/jobs').json() if j['id'] == job_id),
               client.post(f'/api/identity/jobs/{job_id}/cancel').json()]
    for record in records:
        assert record.get('historyDeleted') is True, record
        assert record.get('resultDeleted', False) is result_deleted


def test_history_delete_is_idempotent_and_hides_identity_history(harness):
    client, config, _, _ = harness
    job = finished(client, submit(client, upload(client))['id'])
    first = client.delete(f"/api/history/{job['id']}")
    assert first.status_code == 200
    second = client.delete(f"/api/history/{job['id']}")
    assert second.status_code == 200, second.text
    assert second.json() == first.json()
    assert len(receipts(config)) == 1
    assert_hidden(client, job['id'], result_deleted=True)


def test_identity_delete_uses_existing_transaction_and_keeps_frozen_record(harness):
    client, config, _, _ = harness
    reference = upload(client)
    job = finished(client, submit(client, reference)['id'])
    job_path = config.dream_root / 'data/identity/jobs' / f"{job['id']}.json"
    frozen = job_path.read_bytes()
    output = Path(job['result']['metadata']['output'])
    saved_image = output.read_bytes()
    response = client.delete(f"/api/identity/jobs/{job['id']}")
    assert response.status_code == 200, response.text
    assert response.json() == {'deleted': job['id']}
    assert not output.exists()
    assert not output.with_suffix('.json').exists()
    assert job_path.read_bytes() == frozen
    assert client.get(reference['imageUrl']).status_code == 200
    assert_hidden(client, job['id'], result_deleted=True)
    receipt = json.loads(receipts(config)[0].read_text())
    assert saved_image in [(receipts(config)[0].parent / f['staged']).read_bytes() for f in receipt['files']]
    assert client.delete(f"/api/identity/jobs/{job['id']}").json() == response.json()
    assert client.delete(f"/api/history/{job['id']}").status_code == 200
    assert len(receipts(config)) == 1


@pytest.mark.parametrize('state', ['failed', 'cancelled'])
def test_no_result_terminal_deletion_survives_restart(harness, state):
    client, config, runner, worker = harness
    reference = upload(client)
    if state == 'failed':
        worker.fail = 'generate'
    else:
        worker.hold = 'generate'
    job = submit(client, reference)
    if state == 'cancelled':
        assert worker.started.wait(3)
        assert client.post(f"/api/identity/jobs/{job['id']}/cancel").status_code == 200
    job = finished(client, job['id'])
    assert job['state'] == state and job['result'] is None
    path = config.dream_root / 'data/identity/jobs' / f"{job['id']}.json"
    frozen = path.read_bytes()
    response = client.delete(f"/api/identity/jobs/{job['id']}")
    assert response.status_code == 200, response.text
    assert_hidden(client, job['id'])
    assert path.read_bytes() == frozen
    client.__exit__(None, None, None)
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner)), base_url=str(client.base_url)) as restored:
        assert_hidden(restored, job['id'])
        assert restored.delete(f"/api/identity/jobs/{job['id']}").json() == {'deleted': job['id']}
    assert path.read_bytes() == frozen
    assert len(receipts(config)) == 1


@pytest.mark.parametrize('missing', ['image', 'metadata', 'both', 'result'])
def test_partial_artifacts_are_staged_and_only_empty_records_use_tombstones(harness, missing):
    client, config, runner, _ = harness
    job = finished(client, submit(client, upload(client))['id'])
    output = Path(job['result']['metadata']['output'])
    path = config.dream_root / 'data/identity/jobs' / f"{job['id']}.json"
    client.__exit__(None, None, None)
    if missing in {'image', 'both'}:
        output.unlink()
    if missing in {'metadata', 'both'}:
        output.with_suffix('.json').unlink()
    if missing == 'result':
        job['result'] = None
        path.write_text(json.dumps(job), encoding='utf-8')
    frozen = path.read_bytes()
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner)), base_url=str(client.base_url)) as restored:
        response = restored.delete(f"/api/identity/jobs/{job['id']}")
        assert response.status_code == 200, response.text
        assert_hidden(restored, job['id'], result_deleted=missing in {'image', 'metadata'})
        assert restored.get(f"/api/history/{job['id']}/image").status_code == 404
        assert restored.get('/api/history').json()['total'] == 0
    assert path.read_bytes() == frozen
    if missing != 'result':
        assert not output.exists() and not output.with_suffix('.json').exists()


@pytest.mark.parametrize('missing', ['image', 'metadata', 'both'])
def test_partial_complete_deletion_includes_original_and_stages(harness, missing):
    client, config, _, _ = harness
    job = finished(client, submit(client, upload(client))['id'])
    output = Path(job['result']['metadata']['output'])
    original = config.dream_root / 'data/identity/originals' / f"{job['id']}.png"
    stages = [config.dream_root / 'data/identity/stages' / job['id'] / f'{kind}.png'
              for kind in ('anchor', 'harmonize', 'detail')]
    for path in [original, *stages]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'synthetic stage')
    if missing in {'image', 'both'}:
        output.unlink()
    if missing in {'metadata', 'both'}:
        output.with_suffix('.json').unlink()
    response = client.delete(f"/api/identity/jobs/{job['id']}")
    assert response.status_code == 200, response.text
    assert_hidden(client, job['id'], result_deleted=True)
    assert all(not p.exists() for p in [output, output.with_suffix('.json'), original, *stages])
    receipt = json.loads(receipts(config)[0].read_text())
    assert len(receipt['files']) == (4 if missing == 'both' else 5)


def test_history_delete_lookup_does_not_reenter_the_file_lock(harness, monkeypatch):
    from contextlib import contextmanager

    client, _, _, _ = harness
    job = finished(client, submit(client, upload(client))['id'])
    original = history_transactions._locked
    active = False
    acquisitions = 0

    @contextmanager
    def non_reentrant(root, store):
        nonlocal active, acquisitions
        assert not active, 'history lookup attempted to acquire its own OS lock'
        active = True
        acquisitions += 1
        try:
            with original(root, store):
                yield
        finally:
            active = False

    with monkeypatch.context() as locks:
        locks.setattr(history_transactions, '_locked', non_reentrant)
        assert client.delete(f"/api/history/{job['id']}").status_code == 200
    assert acquisitions == 1


def test_active_and_unknown_jobs_cannot_be_hidden(harness):
    client, config, _, worker = harness
    worker.hold = 'generate'
    job = submit(client, upload(client))
    assert worker.started.wait(3)
    response = client.delete(f"/api/identity/jobs/{job['id']}")
    assert response.status_code == 409, response.text
    assert response.json()['code'] == 'IDENTITY_JOB_ACTIVE'
    response = client.delete('/api/identity/jobs/identity-' + 'f' * 24)
    assert response.status_code == 404
    assert receipts(config) == []
    assert not client.get(f"/api/identity/jobs/{job['id']}").json().get('historyDeleted', False)


@pytest.mark.parametrize('terminal_kind', ['complete', 'failed', 'partial'])
def test_commit_failure_never_hides_a_job_and_retry_succeeds(harness, monkeypatch, terminal_kind):
    client, config, _, worker = harness
    reference = upload(client)
    if terminal_kind == 'failed':
        worker.fail = 'generate'
    job = finished(client, submit(client, reference)['id'])
    if terminal_kind == 'partial':
        output = Path(job['result']['metadata']['output'])
        output.unlink()
        partial = output.with_suffix('.json')
        saved_partial = partial.read_bytes()
    original = history_transactions._write_record

    def fail_commit(root, destination, record):
        if destination.name == 'committed.json':
            raise PermissionError('controlled publication failure')
        return original(root, destination, record)

    with monkeypatch.context() as fault:
        fault.setattr(history_transactions, '_write_record', fail_commit)
        response = client.delete(f"/api/identity/jobs/{job['id']}")
    assert response.status_code >= 400
    assert response.json()['code'] == 'HISTORY_DELETE_FAILED', response.text
    assert receipts(config) == []
    assert not client.get(f"/api/identity/jobs/{job['id']}").json().get('historyDeleted', False)
    if terminal_kind == 'complete':
        assert client.get(job['result']['imageUrl']).status_code == 200
    elif terminal_kind == 'partial':
        assert partial.read_bytes() == saved_partial
    assert client.delete(f"/api/identity/jobs/{job['id']}").status_code == 200
    assert_hidden(client, job['id'], result_deleted=terminal_kind != 'failed')


def test_concurrent_history_and_identity_delete_publish_one_receipt(harness, monkeypatch):
    client, config, _, _ = harness
    job = finished(client, submit(client, upload(client))['id'])
    reached, release = threading.Event(), threading.Event()
    original = history_transactions._write_record

    def hold_commit(root, destination, record):
        if destination.name == 'committed.json':
            reached.set()
            assert release.wait(5)
        return original(root, destination, record)

    monkeypatch.setattr(history_transactions, '_write_record', hold_commit)
    with ThreadPoolExecutor(3) as pool:
        first = pool.submit(client.delete, f"/api/identity/jobs/{job['id']}")
        try:
            assert reached.wait(3)
            second = pool.submit(client.delete, f"/api/history/{job['id']}")
            read = pool.submit(client.get, f"/api/identity/jobs/{job['id']}")
        finally:
            release.set()
        assert first.result().status_code == second.result().status_code == 200
        assert read.result().json().get('historyDeleted') is True
    assert len(receipts(config)) == 1


def test_batch_tombstone_survives_child_recovery_and_preserves_retry_lineage(batch_harness):
    client, config, runner, worker = batch_harness
    worker.fail = True
    parent = wait_batch(client, submit_batch(client, batch_request(upload(client)))['id'])
    complete, failed = parent['items']
    batch_path = config.dream_root / 'data/identity/batches' / f"{parent['id']}.json"
    frozen = batch_path.read_bytes()
    for job in (complete, failed):
        response = client.delete(f"/api/identity/jobs/{job['id']}")
        assert response.status_code == 200, response.text
    for response in (client.get(f"/api/identity/batches/{parent['id']}"),
                     client.post(f"/api/identity/batches/{parent['id']}/cancel")):
        assert [j.get('historyDeleted') for j in response.json()['items']] == [True, True]
        assert response.json()['completedItems'] == 1
    assert batch_path.read_bytes() == frozen
    client.__exit__(None, None, None)
    (config.dream_root / 'data/identity/jobs' / f"{failed['id']}.json").unlink()
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner)), base_url=str(client.base_url)) as restored:
        assert_hidden(restored, failed['id'])
        assert restored.delete(f"/api/identity/jobs/{failed['id']}").status_code == 200
        batch = restored.get('/api/identity/batches').json()[0]
        assert [j.get('historyDeleted') for j in batch['items']] == [True, True]
        assert batch['completedItems'] == 1
        worker.fail = False
        body = {'mode': 'failed', 'idempotencyKey': 'hidden-parent-retry'}
        retry = restored.post(f"/api/identity/batches/{parent['id']}/retry", json=body)
        assert retry.status_code == 200, retry.text
        child = wait_batch(restored, retry.json()['id'])
        assert child['parentBatchId'] == parent['id']
        assert child['originalItemIndices'] == [1]
        assert not child['items'][0].get('historyDeleted', False)
        assert restored.post(f"/api/identity/batches/{parent['id']}/retry", json=body).json()['id'] == child['id']
    assert batch_path.read_bytes() == frozen


def test_identity_delete_rejects_cross_origin(harness):
    client, config, _, worker = harness
    worker.fail = 'generate'
    job = finished(client, submit(client, upload(client))['id'])
    response = client.delete(f"/api/identity/jobs/{job['id']}", headers={'origin': 'https://evil.example'})
    assert response.status_code == 403
    assert receipts(config) == []


@pytest.mark.parametrize('damage', ['outside', 'other-job', 'traversal', 'metadata-owner', 'request', 'corrupt-metadata'])
def test_invalid_result_binding_never_falls_back_to_tombstone(harness, damage):
    client, config, runner, _ = harness
    job = finished(client, submit(client, upload(client))['id'])
    output = Path(job['result']['metadata']['output'])
    saved = output.read_bytes()
    job_path = config.dream_root / 'data/identity/jobs' / f"{job['id']}.json"
    client.__exit__(None, None, None)
    metadata = job['result']['metadata']
    if damage == 'outside':
        metadata['output'] = str(config.dream_root.parent / 'outside.png')
    elif damage == 'other-job':
        metadata['output'] = str(output.with_name('identity-' + 'b' * 24 + '.png'))
    elif damage == 'traversal':
        metadata['output'] = str(output.parent / '..' / output.parent.name / output.name)
    elif damage == 'metadata-owner':
        metadata['id'] = 'identity-' + 'c' * 24
    elif damage == 'request':
        metadata['identity'] = {**metadata['identity'], 'prompt': 'different frozen request'}
    else:
        output.with_suffix('.json').write_text('{', encoding='utf-8')
    job_path.write_text(json.dumps(job), encoding='utf-8')
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner)), base_url=str(client.base_url)) as restored:
        response = restored.delete(f"/api/identity/jobs/{job['id']}")
        assert response.status_code == 422, response.text
        assert not restored.get(f"/api/identity/jobs/{job['id']}").json().get('historyDeleted', False)
    assert output.read_bytes() == saved
    assert receipts(config) == []


def test_changed_durable_owner_is_not_deleted_from_stale_memory(harness):
    client, config, _, worker = harness
    worker.fail = 'generate'
    job = finished(client, submit(client, upload(client))['id'])
    path = config.dream_root / 'data/identity/jobs' / f"{job['id']}.json"
    job['state'] = 'sampling'
    path.write_text(json.dumps(job), encoding='utf-8')
    response = client.delete(f"/api/identity/jobs/{job['id']}")
    assert response.status_code == 409, response.text
    assert receipts(config) == []


@pytest.mark.parametrize('target', ['job', 'trash', 'output', 'metadata'])
def test_identity_deletion_rejects_redirects_even_inside_root(harness, target):
    client, config, _, _ = harness
    job = finished(client, submit(client, upload(client))['id'])
    output = Path(job['result']['metadata']['output'])
    paths = {'job': config.dream_root / 'data/identity/jobs' / f"{job['id']}.json",
             'trash': config.dream_root / 'data/history-trash',
             'output': output, 'metadata': output.with_suffix('.json')}
    path = paths[target]
    backup = path.with_name(path.name + '.safe-original')
    if path.exists():
        path.rename(backup)
    else:
        backup.mkdir()
    try:
        try:
            path.symlink_to(backup, target_is_directory=target == 'trash')
        except OSError:
            pytest.skip('symlink privilege unavailable')
        saved = None if target == 'trash' else backup.read_bytes()
        response = client.delete(f"/api/identity/jobs/{job['id']}")
        assert response.status_code == 422, response.text
        if saved is not None:
            assert backup.read_bytes() == saved
        assert not list((backup if target == 'trash' else config.dream_root / 'data/history-trash').glob('*/committed.json'))
    finally:
        if path.is_symlink():
            path.unlink()
        backup.rename(path)


def test_concurrent_empty_record_deletion_commits_once(harness):
    client, config, _, worker = harness
    worker.fail = 'generate'
    job = finished(client, submit(client, upload(client))['id'])
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: client.delete(f"/api/identity/jobs/{job['id']}"), range(4)))
    assert [r.status_code for r in results] == [200] * 4
    assert all(r.json() == {'deleted': job['id']} for r in results)
    assert len(receipts(config)) == 1
    assert_hidden(client, job['id'])


def test_delete_missing_unknown_history_is_not_reported_as_success(harness):
    client, config, _, _ = harness
    response = client.delete('/api/history/identity-' + 'e' * 24)
    assert response.status_code == 404
    assert response.json()['code'] == 'HISTORY_NOT_FOUND'
    assert receipts(config) == []
