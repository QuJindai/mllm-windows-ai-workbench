"""Exercise the real routes/storage/serial queue with an inference boundary."""
import io
import json
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from test_identity_api import harness, upload, submit, finished
from test_identity_profiles import profile_harness
from test_identity_anime_profiles import anime_harness, source_pair, create_anime, wait_anime


def base(client):
    return finished(client, submit(client, upload(client))['id'])


def done(client, source, edit):
    for _ in range(300):
        response = client.get(f'/api/identity/jobs/{source}/refinements')
        assert response.status_code == 200, response.text
        row = next(row for row in response.json()['versions'] if row['id'] == edit)
        if row['state'] in ('complete', 'failed', 'cancelled'):
            return row
        time.sleep(.01)
    pytest.fail('Refinement did not terminate')


@pytest.fixture
def inference(monkeypatch):
    from identity_service import IdentityService
    original = IdentityService._worker
    calls = []
    def worker(self, operation, payload, cancelled=None):
        if operation != 'refine':
            return original(self, operation, payload, cancelled)
        calls.append(payload)
        image = Image.open(payload['sourcePath']).convert('RGB')
        image.putpixel((0, 0), (255, 0, 0))
        image.save(payload['outputPath'])
        return {'durationMs': 20, 'operation': 'restore'}
    monkeypatch.setattr(IdentityService, '_worker', worker)
    return calls


def test_refinement_preserves_original_and_selects_completed_version(harness, inference):
    client, _, _, _ = harness
    source = base(client)
    original = client.get(source['result']['imageUrl']).content
    data = {'sourceJobId': source['id'], 'mode': 'restore', 'strength': .3, 'seed': 42}
    response = client.post('/api/identity/refinements', json=data)
    assert response.status_code == 200, response.text
    row = done(client, source['id'], response.json()['id'])
    assert row['state'] == 'complete', row
    assert client.get(row['imageUrl']).content != original
    assert client.get(source['result']['imageUrl']).content == original
    workspace = client.get(f"/api/identity/jobs/{source['id']}/refinements").json()
    assert workspace['selectedVersionId'] == 'result'
    selected = client.post(f"/api/identity/jobs/{source['id']}/refinements/select", json={'versionId': row['id']})
    assert selected.status_code == 200
    assert selected.json()['selectedVersionId'] == row['id']
    assert client.post(f"/api/identity/jobs/{source['id']}/refinements/select", json={'versionId': 'original'}).json()['selectedVersionId'] == 'original'
    assert len(inference) == 1


def test_repeated_request_is_idempotent_and_changed_payload_conflicts(harness, inference):
    client, _, _, _ = harness
    source = base(client)
    data = {'sourceJobId': source['id'], 'mode': 'restore', 'requestId': 'request-1234567890', 'seed': 1}
    a = client.post('/api/identity/refinements', json=data)
    assert a.status_code == 200, a.text
    b = client.post('/api/identity/refinements', json=data)
    assert b.status_code == 200 and b.json()['id'] == a.json()['id']
    assert client.post('/api/identity/refinements', json={**data, 'seed': 2}).status_code == 409
    assert done(client, source['id'], a.json()['id'])['state'] == 'complete'
    assert len(inference) == 1


@pytest.mark.parametrize('route', ['/api/identity/jobs', '/api/history'])
def test_source_delete_removes_versions_and_stale_image_access(harness, inference, route):
    client, config, _, _ = harness
    source = base(client)
    response = client.post('/api/identity/refinements', json={'sourceJobId':source['id'],'mode':'restore'})
    assert response.status_code == 200, response.text
    row = done(client,source['id'],response.json()['id'])
    assert client.delete(f"{route}/{source['id']}").status_code == 200
    assert client.get(row['imageUrl']).status_code == 404
    assert client.get(f"/api/identity/jobs/{source['id']}/refinements").status_code == 404
    assert not list((config.dream_root/'data/identity/refinements'/source['id']).glob('*.png'))


def test_cross_source_parent_and_unsupported_mode_are_rejected(harness, inference):
    client, _, _, _ = harness
    one, two = base(client), base(client)
    response = client.post('/api/identity/refinements',json={'sourceJobId':one['id'],'mode':'restore'})
    assert response.status_code == 200, response.text
    edit = done(client,one['id'],response.json()['id'])
    assert client.post('/api/identity/refinements',json={'sourceJobId':two['id'],'parentVersionId':edit['id'],'mode':'restore'}).status_code == 422
    assert client.post('/api/identity/refinements',json={'sourceJobId':one['id'],'mode':'reference-anchor'}).status_code == 422
    assert client.post('/api/identity/refinements',json={'sourceJobId':one['id'],'sourcePath':'E:/private.png'}).status_code == 422


def test_recovered_interrupted_version_is_failed_and_cannot_be_selected(harness, inference):
    client, config, _, _ = harness
    source = base(client)
    response=client.post('/api/identity/refinements',json={'sourceJobId':source['id'],'mode':'restore'})
    assert response.status_code == 200, response.text
    row=done(client,source['id'],response.json()['id'])
    path=config.dream_root/'data/identity/refinements'/source['id']/(row['id']+'.json')
    saved=json.loads(path.read_text(encoding='utf-8'));saved.update(state='running',imageUrl=None)
    path.write_text(json.dumps(saved),encoding='utf-8')
    workspace=client.get(f"/api/identity/jobs/{source['id']}/refinements").json()
    recovered=next(x for x in workspace['versions'] if x['id']==row['id'])
    assert recovered['state']=='failed'
    assert client.post(f"/api/identity/jobs/{source['id']}/refinements/select",json={'versionId':row['id']}).status_code==409


def test_active_edit_blocks_delete_and_cancellation_prevents_late_publication(harness, monkeypatch):
    from identity_service import IdentityService
    client, config, _, _ = harness
    source = base(client)
    before = client.get(source['result']['imageUrl']).content
    started = threading.Event()
    original = IdentityService._worker
    def worker(self, operation, payload, cancelled=None):
        if operation != 'refine':
            return original(self, operation, payload, cancelled)
        started.set()
        assert cancelled.wait(5)
        # A worker that finishes just as cancellation arrives cannot publish.
        Image.new('RGB', (payload['width'], payload['height']), 'red').save(payload['outputPath'])
        return {'durationMs': 1}
    monkeypatch.setattr(IdentityService, '_worker', worker)
    response = client.post('/api/identity/refinements', json={'sourceJobId': source['id']})
    edit = response.json()['id']
    assert started.wait(5)
    assert client.delete(f"/api/identity/jobs/{source['id']}").status_code == 409
    assert client.delete(f"/api/history/{source['id']}").status_code == 409
    cancelled = client.post(f'/api/identity/refinements/{edit}/cancel')
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()['state'] == 'cancelled'
    assert client.get(source['result']['imageUrl']).content == before
    assert client.get(f'/api/identity/refinements/{edit}/image').status_code == 409
    assert not list((config.dream_root/'data/identity/refinements'/source['id']).glob('*.png'))
    assert client.delete(f"/api/identity/jobs/{source['id']}").status_code == 200


def test_version_branch_uses_selected_parent_and_delete_covers_multiple_versions(harness, inference):
    client, config, _, _ = harness
    source = base(client)
    parent = 'result'
    for _ in range(4):
        response = client.post('/api/identity/refinements', json={'sourceJobId': source['id'], 'parentVersionId': parent})
        assert response.status_code == 200, response.text
        row = done(client, source['id'], response.json()['id'])
        assert row['state'] == 'complete', row
        assert row['parentVersionId'] == parent
        if parent != 'result':
            assert Path(inference[-1]['sourcePath']).stem == parent
        parent = row['id']
    response = client.delete(f"/api/identity/jobs/{source['id']}")
    assert response.status_code == 200, response.text
    assert not list((config.dream_root/'data/identity/refinements'/source['id']).glob('refine-*'))


def test_refinement_rejects_cross_origin_and_malformed_selection(harness):
    client, _, _, _ = harness
    source = base(client)
    assert client.post('/api/identity/refinements', json={'sourceJobId': source['id']}, headers={'origin': 'https://example.com'}).status_code == 403
    assert client.post(f"/api/identity/jobs/{source['id']}/refinements/select", json={'versionId': '../../private'}).status_code == 422


def test_independent_anime_refinement_resolves_archive_when_initial_polish_was_off(anime_harness, monkeypatch):
    from identity_service import IdentityService
    client, config, _, _ = anime_harness
    parent, seed_job = source_pair(client)
    archive = wait_anime(client, create_anime(client, parent, seed_job).json()['id'])
    assert archive['state'] == 'ready'
    original = IdentityService._worker
    calls = []
    def worker(self, operation, payload, cancelled=None):
        if operation == 'generate' and payload.get('animeProfileId') and not payload['facePolish']:
            Image.new('RGB', (payload['width'],payload['height']), 'navy').save(payload['outputPath'])
            Path(payload['metadataPath']).write_text('{}',encoding='utf-8')
            return {'ok':True}
        if operation == 'refine':
            calls.append(payload)
            assert payload['animeProfile']['id'] == archive['id']
            assert Path(payload['animeImagePath']).is_file()
            assert Path(payload['animeFeaturesPath']).is_file()
            Image.new('RGB',(payload['width'],payload['height']),'red').save(payload['outputPath'])
            return {'ok':True}
        return original(self,operation,payload,cancelled)
    monkeypatch.setattr(IdentityService,'_worker',worker)
    response=client.post('/api/identity/generate',json={**seed_job['request'],'animeProfileId':archive['id'],'facePolish':False})
    assert response.status_code==200,response.text
    source=finished(client,response.json()['id'])
    assert source['state']=='complete',source
    frozen=(config.dream_root/'data/identity/jobs'/f"{source['id']}.json").read_bytes()
    edit=client.post('/api/identity/refinements',json={'sourceJobId':source['id'],'mode':'restore'})
    row=done(client,source['id'],edit.json()['id'])
    assert row['state']=='complete',row
    assert len(calls)==1
    assert (config.dream_root/'data/identity/jobs'/f"{source['id']}.json").read_bytes()==frozen
