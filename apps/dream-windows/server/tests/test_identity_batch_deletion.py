"""Whole-batch deletion uses real routes and transactions with synthetic outputs."""
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient

from app import create_app
import history_transactions as transactions
from runtime import DreamRuntime
from test_identity_api import harness, upload
from test_identity_profiles import profile_harness
from test_identity_batches import batch_harness, batch_request, submit_batch, wait_batch


def delete(client, batch):
    return client.delete(f"/api/identity/batches/{batch['id']}")


def test_whole_batch_deletion_is_durable_idempotent_and_preserves_other_results(batch_harness):
    client, config, runner, _ = batch_harness
    reference = upload(client)
    batch = wait_batch(client, submit_batch(client, batch_request(reference))['id'])
    other = wait_batch(client, submit_batch(client, batch_request(reference))['id'])
    record = config.dream_root / 'data/identity/batches' / f"{batch['id']}.json"
    frozen = record.read_bytes()
    ref = client.get(reference['imageUrl']).content
    expected = {'deleted': batch['id'], 'deletedJobIds': [item['id'] for item in batch['items']]}
    response = delete(client, batch)
    assert response.status_code == 200, response.text
    assert response.json() == expected
    assert delete(client, batch).json() == expected
    assert client.get('/api/history').json()['total'] == len(other['items'])
    assert record.read_bytes() == frozen
    assert client.get(reference['imageUrl']).content == ref
    for item in batch['items']:
        assert client.get(item['result']['imageUrl']).status_code == 404
        assert client.get(f"/api/identity/jobs/{item['id']}").json()['historyDeleted']
        assert client.delete(f"/api/history/{item['id']}").status_code == 200
    for item in other['items']:
        assert client.get(item['result']['imageUrl']).status_code == 200
    client.__exit__(None, None, None)
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner)), base_url=str(client.base_url)) as restored:
        saved = restored.get(f"/api/identity/batches/{batch['id']}").json()
        assert saved['historyDeleted'] and all(item['historyDeleted'] for item in saved['items'])
        assert saved['completedItems'] == batch['completedItems']
        assert delete(restored, batch).json() == expected
    assert record.read_bytes() == frozen


def test_batch_commit_failure_restores_all_members_without_any_deletion_receipt(batch_harness, monkeypatch):
    client, config, _, _ = batch_harness
    batch = wait_batch(client, submit_batch(client, batch_request(upload(client)))['id'])
    originals = {Path(item['result']['metadata']['output']): client.get(item['result']['imageUrl']).content for item in batch['items']}
    write = transactions._write_record
    def fail_commit(root, path, record):
        if path.name == 'committed.json':
            raise PermissionError('synthetic commit failure')
        return write(root, path, record)
    monkeypatch.setattr(transactions, '_write_record', fail_commit)
    assert delete(client, batch).status_code >= 400
    assert transactions.history_deletion_flags(config.dream_root) == {}
    assert all(path.read_bytes() == data for path, data in originals.items())
    assert not client.get(f"/api/identity/batches/{batch['id']}").json().get('historyDeleted')
    monkeypatch.setattr(transactions, '_write_record', write)
    assert delete(client, batch).status_code == 200


def test_batch_delete_includes_already_deleted_and_failed_members(batch_harness):
    client, config, _, worker = batch_harness
    worker.fail = True
    batch = wait_batch(client, submit_batch(client, batch_request(upload(client)))['id'])
    assert batch['state'] == 'failed'
    complete = batch['items'][0]
    assert client.delete(f"/api/identity/jobs/{complete['id']}").status_code == 200
    assert delete(client, batch).status_code == 200
    response = client.get(f"/api/identity/batches/{batch['id']}").json()
    assert response['historyDeleted']
    assert all(item['historyDeleted'] for item in response['items'])
    assert client.get('/api/history').json()['total'] == 0
    assert len(list((config.dream_root / 'data/history-trash').glob('*/committed.json'))) == 2


def test_active_batch_cannot_be_deleted_and_cancelled_batch_can(batch_harness):
    client, _, _, worker = batch_harness
    worker.hold = True
    batch = submit_batch(client, batch_request(upload(client), previewEvery=5))
    running = wait_batch(client, batch['id'], lambda value: value['step'] == 5)
    assert delete(client, batch).status_code == 409
    assert client.get(running['items'][0]['result']['imageUrl']).status_code == 200
    client.post(f"/api/identity/batches/{batch['id']}/cancel")
    assert delete(client, batch).status_code == 200
    assert client.get(running['previewUrl']).status_code == 404
    assert client.post(f"/api/identity/batches/{batch['id']}/cancel").json()['historyDeleted']


def test_batch_deletion_rejects_cross_origin_and_changed_owner(batch_harness):
    client, config, _, _ = batch_harness
    batch = wait_batch(client, submit_batch(client, batch_request(upload(client)))['id'])
    assert client.delete(f"/api/identity/batches/{batch['id']}", headers={'origin': 'https://evil.invalid'}).status_code == 403
    path = config.dream_root / 'data/identity/batches' / f"{batch['id']}.json"
    record = json.loads(path.read_text())
    record['items'][0]['request']['prompt'] = 'changed'
    path.write_text(json.dumps(record))
    assert delete(client, batch).status_code == 409
    assert transactions.history_deletion_flags(config.dream_root) == {}


def test_deleting_last_individual_also_hides_empty_batch(batch_harness):
    client, _, _, _ = batch_harness
    batch = wait_batch(client, submit_batch(client, batch_request(upload(client)))['id'])
    for item in batch['items']:
        assert client.delete(f"/api/identity/jobs/{item['id']}").status_code == 200
    assert client.get(f"/api/identity/batches/{batch['id']}").json()['historyDeleted']
    assert client.get('/api/identity/batches').json()[0]['historyDeleted']


def test_concurrent_batch_and_member_delete_have_complete_receipts(batch_harness):
    client, config, _, _ = batch_harness
    batch = wait_batch(client, submit_batch(client, batch_request(upload(client)))['id'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        whole = pool.submit(delete, client, batch)
        single = pool.submit(client.delete, f"/api/identity/jobs/{batch['items'][0]['id']}")
        assert whole.result().status_code == single.result().status_code == 200
    flags = transactions.history_deletion_flags(config.dream_root)
    assert flags[batch['id']]['historyDeleted']
    assert all(flags[item['id']]['resultDeleted'] for item in batch['items'])


def test_staging_failure_after_first_member_restores_entire_batch(batch_harness, monkeypatch):
    client, config, _, _ = batch_harness
    batch = wait_batch(client, submit_batch(client, batch_request(upload(client)))['id'])
    original = transactions._move
    second = batch['items'][1]['id']
    def fail(root, source, destination):
        if source.name == f'{second}.png' and destination.suffix == '.bin':
            raise PermissionError('second member locked')
        return original(root, source, destination)
    monkeypatch.setattr(transactions, '_move', fail)
    assert delete(client, batch).status_code >= 400
    assert transactions.history_deletion_flags(config.dream_root) == {}
    assert all(client.get(item['result']['imageUrl']).status_code == 200 for item in batch['items'])


def test_batch_journal_recovers_after_process_interruption(tmp_path, monkeypatch):
    batch_id = 'batch-' + 'a' * 24
    members = {}
    originals = {}
    for index in range(2):
        job_id = 'identity-' + f'{index:024x}'
        path = tmp_path / 'outputs' / '2026-10-25' / f'{job_id}.png'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f'original-{index}'.encode())
        originals[path] = path.read_bytes()
        members[job_id] = lambda path=path: [path]
    move = transactions._move
    def interrupt(root, source, target):
        move(root, source, target)
        if target.name == '1.bin':
            raise SystemExit('simulated abrupt exit')
    monkeypatch.setattr(transactions, '_move', interrupt)
    with pytest.raises(SystemExit):
        transactions.delete_history_files(tmp_path, batch_id, [], allow_empty=True, batch_members=members)
    monkeypatch.setattr(transactions, '_move', move)
    transactions.recover_history_transactions(tmp_path)
    assert transactions.history_deletion_flags(tmp_path) == {}
    assert all(path.read_bytes() == data for path, data in originals.items())


def test_maximum_batch_with_all_stage_files_round_trips_receipt(tmp_path):
    members = {}
    for index in range(16):
        job_id = 'identity-' + f'{index:024x}'
        paths = [tmp_path / 'outputs/2026-10-25' / f'{job_id}.{ext}' for ext in ('png', 'json')]
        paths.append(tmp_path / 'data/identity/originals' / f'{job_id}.png')
        stages = [tmp_path / 'data/identity/stages' / job_id / f'{kind}.png' for kind in ('anchor', 'harmonize', 'detail')]
        for path in paths + stages:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'synthetic')
        members[job_id] = lambda paths=paths: paths
    transactions.delete_history_files(tmp_path, 'batch-' + 'b' * 24, [], allow_empty=True, batch_members=members)
    transactions.recover_history_transactions(tmp_path)
    assert len(list((tmp_path / 'data/history-trash').glob('*/*.bin'))) == 96
    flags = transactions.history_deletion_flags(tmp_path)
    assert len(flags) == 17 and all(flags[member]['resultDeleted'] for member in members)
