from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hq_routes import create_hq_router
from test_hq_service import complete, hq, sha


@pytest.fixture
def client(hq):
    app = FastAPI()
    app.include_router(create_hq_router(hq.config, hq.service))
    with TestClient(app, base_url='http://127.0.0.1:8766', client=('127.0.0.1', 50000)) as value:
        yield value


@pytest.mark.parametrize('path', [
    '/status', '/catalog?kind=person', '/asset?kind=person&id=' + '0' * 64,
    '/jobs', '/jobs/hq-' + '0' * 64, '/jobs/hq-' + '0' * 64 + '/inputs/person',
    '/jobs/hq-' + '0' * 64 + '/result',
])
@pytest.mark.parametrize('headers', [
    {'origin': 'https://evil.invalid'}, {'sec-fetch-site': 'cross-site'},
    {'host': 'evil.invalid', 'origin': 'http://evil.invalid'}, {'origin': 'null'},
])
def test_every_get_including_private_images_rejects_cross_site_and_dns_rebinding(client, hq, path, headers):
    result = client.get('/api/hq' + path, headers=headers)
    assert result.status_code == 403
    assert result.json()['error']['code'] == 'IDENTITY_ORIGIN_FORBIDDEN'
    assert 'no-store' in result.headers['cache-control']
    assert not hq.r2.calls


def test_loopback_create_read_result_hash_attachment_and_native_queue_binding(client, hq):
    assert client.get('/api/hq/status').json()['modelReady']
    assert client.get('/api/hq/catalog?kind=garment').json()['categories'] == ['studio']
    person = client.get('/api/hq/asset', params={'kind': 'person', 'id': hq.r2.ids['person']})
    assert person.status_code == 200 and person.content == hq.r2.raw['person']
    created = client.post('/api/hq/jobs', json=hq.payload.model_dump())
    assert created.status_code == 201
    job_id = created.json()['id']
    record = complete(hq, job_id)
    assert client.get('/api/hq/jobs').json()['jobs'][0]['id'] == job_id
    assert client.get('/api/hq/jobs/' + job_id).json()['state'] == 'succeeded'
    output = client.get('/api/hq/jobs/' + job_id + '/result?download=1')
    assert output.status_code == 200 and output.headers['content-type'] == 'image/png'
    assert sha(output.content) == record['outputSha256'] == output.headers['x-content-sha256']
    assert 'attachment' in output.headers['content-disposition']
    assert 'no-store' in output.headers['cache-control']
    original = client.get('/api/hq/jobs/' + job_id + '/inputs/person')
    assert original.content == hq.r2.raw['person']
    assert original.headers['content-type'] == 'image/jpeg'
    assert client.post('/api/hq/jobs', json=hq.payload.model_dump()).status_code == 200
    bad = hq.payload.model_dump()
    bad['parameters']['steps'] = 3
    conflict = client.post('/api/hq/jobs', json=bad)
    assert conflict.status_code == 409 and conflict.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'


@pytest.mark.parametrize('change', [
    {'personId': '../credentials/vault-session.json'}, {'python': 'evil.exe'},
    {'parameters': {'width': 768, 'height': 768}}, {'parameters': {'steps': 51}},
    {'parameters': {'width': '512'}}, {'parameters': {'seed': True}},
])
def test_strict_post_rejects_paths_commands_extras_and_invalid_parameters(client, hq, change):
    response = client.post('/api/hq/jobs', json={**hq.payload.model_dump(), **change})
    assert response.status_code == 422
    assert not hq.r2.calls and not hq.boundary.calls
    assert 'evil.exe' not in response.text


def test_post_origin_body_limits_and_cancel_scope(client, hq):
    denied = client.post('/api/hq/jobs', json=hq.payload.model_dump(), headers={'origin': 'http://evil.invalid'})
    assert denied.status_code == 403
    too_large = client.post('/api/hq/jobs', content=b'x' * 16385, headers={'content-type': 'application/json'})
    assert too_large.status_code == 413
    mime = client.post('/api/hq/jobs', content=json.dumps(hq.payload.model_dump()), headers={'content-type': 'text/plain'})
    assert mime.status_code == 415
    hq.boundary.hold = True
    result = client.post('/api/hq/jobs', json=hq.payload.model_dump())
    job_id = result.json()['id']
    assert client.post('/api/hq/jobs/' + job_id + '/cancel', headers={'sec-fetch-site': 'cross-site'}).status_code == 403
    cancelled = client.post('/api/hq/jobs/' + job_id + '/cancel')
    assert cancelled.status_code == 200 and cancelled.json()['cancellationRequested']
    assert client.get('/api/hq/jobs/' + job_id + '/result').status_code == 409


def test_invalid_role_ids_and_outside_paths_cannot_read_local_files(client, hq):
    for path in ('/jobs/vault-session', '/jobs/hq-' + '0' * 64 + '/inputs/secret', '/asset?kind=person&id=..%2Fconfig.json'):
        assert client.get('/api/hq' + path).status_code in (404, 422)
    record, _ = hq.service.create_job(hq.payload)
    complete(hq, record['id'])
    folder = hq.root / 'jobs' / record['id']
    original = folder / 'inputs' / 'person.jpg'
    original.write_bytes(b'tampered')
    response = client.get('/api/hq/jobs/' + record['id'] + '/inputs/person')
    assert response.status_code == 422 and response.json()['error']['code'] == 'HQ_HASH_MISMATCH'


def test_app_registration_smoke_shares_existing_runner(hq):
    from app import create_app
    from types import SimpleNamespace
    app = create_app(hq.config, SimpleNamespace(job_runner=hq.runner))
    registered = app.state.hq_service
    assert registered.job_runner is hq.runner
    assert registered.identity.__class__.__name__ == 'IdentityService'
    assert any(route.path == '/api/hq/jobs' for route in app.routes)
    assert any(route.path == '/api/identity/jobs/{job_id}' for route in app.routes)
    registered.close()


@pytest.mark.parametrize('peer', ['192.168.1.30', '10.0.0.8', '::ffff:192.168.1.30'])
def test_lan_peer_cannot_spoof_local_host_and_origin(hq, peer):
    app = FastAPI()
    app.include_router(create_hq_router(hq.config, hq.service))
    with TestClient(app, base_url='http://127.0.0.1:8766', client=(peer, 50000)) as remote:
        response = remote.get('/api/hq/asset?kind=person&id=' + hq.r2.ids['person'],
                              headers={'host': '127.0.0.1:8766', 'origin': 'http://127.0.0.1:8766'})
        assert response.status_code == 403 and response.json()['code'] == 'HQ_PEER_FORBIDDEN'
        assert not hq.r2.calls


def test_nonloopback_bind_disables_hq_even_for_loopback_peer(hq):
    from dataclasses import replace
    config = replace(hq.config, host='0.0.0.0')
    app = FastAPI()
    app.include_router(create_hq_router(config, hq.service))
    with TestClient(app, base_url='http://127.0.0.1:8766', client=('127.0.0.1', 50000)) as local:
        response = local.get('/api/hq/status')
        assert response.status_code == 403 and response.json()['code'] == 'HQ_LOOPBACK_REQUIRED'
        assert not hq.service._started and not hq.r2.calls


def test_trusted_uvicorn_proxy_cannot_rewrite_lan_peer_as_loopback(hq):
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    app = FastAPI()
    app.include_router(create_hq_router(hq.config, hq.service))
    proxy = ProxyHeadersMiddleware(app, trusted_hosts=['*'])
    with TestClient(proxy, base_url='http://127.0.0.1:8766', client=('192.168.1.20', 50000)) as remote:
        response = remote.get('/api/hq/catalog?kind=person', headers={'x-forwarded-for': '127.0.0.1'})
        assert response.status_code == 403 and response.json()['code'] == 'HQ_PEER_FORBIDDEN'
        assert not hq.r2.calls


def test_receipt_and_cancel_available_while_original_download_is_blocked(client, hq):
    import httpx
    import threading
    entered, release = threading.Event(), threading.Event()
    class SlowOriginal(httpx.SyncByteStream):
        def __iter__(self):
            entered.set()
            assert release.wait(5)
            yield hq.r2.raw['person']
    def remote(request):
        if request.url.path.startswith('/api/person/image/'):
            return httpx.Response(200, stream=SlowOriginal(), headers={'content-type': 'image/jpeg'})
        return hq.r2(request)
    temporary = httpx.Client(transport=httpx.MockTransport(remote))
    hq.service.client = temporary
    try:
        response = client.post('/api/hq/jobs', json=hq.payload.model_dump())
        assert response.status_code == 201
        job = response.json()
        assert job['identityJobId'] and job['requestedInputIds'] == hq.r2.ids
        assert entered.wait(5)
        assert client.get('/api/hq/jobs/' + job['id']).json()['phase'] == 'downloading'
        cancelled = client.post('/api/hq/jobs/' + job['id'] + '/cancel')
        assert cancelled.status_code == 200 and cancelled.json()['cancellationRequested']
        assert cancelled.json()['state'] == 'queued' and cancelled.json()['phase'] == 'cancelling'
        release.set()
        assert complete(hq, job['id'])['state'] == 'cancelled'
        assert not hq.boundary.inspections and not hq.boundary.calls
    finally:
        release.set()
        temporary.close()
        hq.service.client = hq.client


def test_identity_history_deletion_hides_hq_result_and_refinements_immediately(client, hq):
    from errors import DreamApiError
    created, _ = hq.service.create_job(hq.payload)
    job = complete(hq, created['id'])
    result_path, _ = hq.service.image_path(job['id'])
    assert result_path == Path(job['identityResult']['metadata']['output'])
    assert client.get('/api/hq/jobs/' + job['id'] + '/result').status_code == 200
    hq.identity.delete_history(job['identityJobId'])
    assert not result_path.exists()
    for row in (client.get('/api/hq/jobs/' + job['id']).json(), client.get('/api/hq/jobs').json()['jobs'][0]):
        assert row['historyDeleted'] and row['resultDeleted']
        assert row['result'] is row['output'] is row['identityResult'] is row['outputSha256'] is None
        assert row['refinementsAvailable'] is False and row['audit']
    response = client.get('/api/hq/jobs/' + job['id'] + '/result?download=1')
    assert response.status_code == 404 and response.json()['code'] == 'HQ_RESULT_DELETED'
    assert client.get('/api/hq/jobs/' + job['id'] + '/inputs/person').status_code == 200
    with pytest.raises(DreamApiError) as error:
        hq.identity.refinement_operation('workspace', job['identityJobId'])
    assert error.value.status_code == 404


@pytest.mark.parametrize('path', [
    '/api/identity/references/ref-' + 'a' * 24 + '/image', '/api/identity/jobs',
    '/api/identity/jobs/identity-' + 'a' * 24 + '/original',
    '/api/identity/jobs/identity-' + 'a' * 24 + '/refinements',
    '/api/history', '/api/history/identity-' + 'a' * 24,
    '/api/history/identity-' + 'a' * 24 + '/image',
])
@pytest.mark.parametrize('case', ['lan', 'proxy', 'cross-site', 'nonloopback-bind'])
def test_private_hq_identity_and_history_aliases_share_transport_boundary(hq, path, case):
    from app import create_app
    from dataclasses import replace
    from runtime import DreamRuntime
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    config = replace(hq.config, host='0.0.0.0') if case == 'nonloopback-bind' else hq.config
    app = create_app(config, DreamRuntime(config, job_runner=hq.runner))
    wrapped = ProxyHeadersMiddleware(app, trusted_hosts=['*']) if case == 'proxy' else app
    peer = '192.168.1.20' if case in {'lan', 'proxy'} else '127.0.0.1'
    headers = {'host': '127.0.0.1:8766'}
    if case == 'proxy':
        headers['x-forwarded-for'] = '127.0.0.1'
    if case == 'cross-site':
        headers['origin'] = 'https://evil.invalid'
    try:
        with TestClient(wrapped, base_url='http://127.0.0.1:8766', client=(peer, 50000)) as remote:
            for method in ('get', 'post'):
                response = getattr(remote, method)(path, headers=headers)
                assert response.status_code == 403
                assert 'no-store' in response.headers['cache-control']
            assert not hq.r2.calls and not hq.boundary.calls
    finally:
        app.state.hq_service.close()
