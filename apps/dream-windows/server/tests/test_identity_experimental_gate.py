"""Experimental model policy: real resolver/storage, no inference or GPU work."""
import copy
import json

import pytest

from errors import DreamApiError
from identity_batches import BatchRequest, BatchRetryRequest
from identity_contract import IdentityGenerateRequest
from identity_models import identity_model_catalog, resolve_identity_model
from identity_service import atomic_json
from test_identity_models import assets
from test_identity_visual_service import visual_service, reference, assert_no_jobs


ILLUSTRIOUS = 'illustrious-xl-v2.0-plus-face'
FACEID = 'illustrious-xl-v2.0-faceid'
CYBER = 'cyberrealistic-xl-plus-face'
MESSAGE = '实验性：本机画质验收未通过，默认禁用，请使用Cyber视觉路线'
DISABLED = [{}, *[{'allowExperimentalVisualModels': value}
                 for value in (False, None, 0, 1, 'true', 'false', [], {})]]


def installed(tmp_path, settings):
    config = assets(tmp_path)
    config['models'][CYBER] = dict(config['models'][FACEID])
    config.update(settings)
    return config


def params(ref, model=ILLUSTRIOUS):
    return IdentityGenerateRequest(referenceId=ref['id'], faceIndex=0, prompt='portrait',
        seed=9, modelId=model, structureStrength=0., faceLoraStrength=0.)


@pytest.mark.parametrize('settings', DISABLED)
def test_only_literal_true_enables_resolver_and_catalog(tmp_path, settings):
    config = installed(tmp_path, settings)
    before = copy.deepcopy(config)
    with pytest.raises(ValueError, match=MESSAGE):
        resolve_identity_model(config, ILLUSTRIOUS)
    rows = {row['id']: row for row in identity_model_catalog(config)}
    assert rows[ILLUSTRIOUS]['ready'] is False
    assert rows[ILLUSTRIOUS]['message'] == MESSAGE
    assert rows[ILLUSTRIOUS]['experimental'] is True
    assert rows[ILLUSTRIOUS]['qualityStatus'] == 'failed'
    for model in (CYBER, FACEID, 'realistic-vision-v5.1-faceid'):
        assert rows[model]['ready'] is True
        assert not rows[model].get('experimental', False)
        assert resolve_identity_model(config, model)['modelId'] == model
    assert config == before


def test_opt_in_enables_assets_not_quality_approval_or_fallback(tmp_path):
    config = installed(tmp_path, {'allowExperimentalVisualModels': True})
    selected = resolve_identity_model(config, ILLUSTRIOUS)
    assert selected['checkpoint'] == config['models'][FACEID]['checkpoint']
    assert selected['adapter'] == config['models'][CYBER]['adapter']
    row = next(row for row in identity_model_catalog(config) if row['id'] == ILLUSTRIOUS)
    assert row['ready'] is True and row['experimental'] is True
    assert row['qualityStatus'] == 'failed'
    assert '实验性' in row['message'] and '画质验收未通过' in row['message']
    del config['models'][CYBER]['adapter']
    with pytest.raises(ValueError, match='adapter'):
        resolve_identity_model(config, ILLUSTRIOUS)
    assert next(row for row in identity_model_catalog(config) if row['id'] == ILLUSTRIOUS)['ready'] is False


@pytest.mark.parametrize('operation', ['generate', 'batch'])
def test_worker_config_gate_cannot_be_enabled_by_request(tmp_path, operation):
    from identity_worker import load_config
    config = installed(tmp_path, {})
    path = tmp_path/'runtime.json'
    atomic_json(path, config)
    item = {'modelId': ILLUSTRIOUS, 'allowExperimentalVisualModels': True}
    payload = {'configPath': str(path), **({'items': [item]} if operation == 'batch' else item)}
    with pytest.raises(ValueError, match=MESSAGE):
        load_config(payload, operation=operation)
    atomic_json(path, {**config, 'allowExperimentalVisualModels': True})
    assert load_config(payload, operation=operation)['modelId'] == ILLUSTRIOUS


@pytest.mark.parametrize('settings', DISABLED)
@pytest.mark.parametrize('batch', [False, True])
def test_disabled_submission_rejected_before_persisting_or_dispatch(visual_service, tmp_path, settings, batch):
    service, boundary = visual_service
    service.config_path = tmp_path/'runtime.json'
    atomic_json(service.config_path, settings)
    ref = reference(service, 'visual')
    request = params(ref)
    before = request.model_dump()
    with pytest.raises(DreamApiError) as error:
        if batch:
            service.batch_operation('submit', BatchRequest(request=request, count=1))
        else:
            service.submit(request)
    assert error.value.code == 'IDENTITY_EXPERIMENTAL_MODEL_DISABLED'
    assert error.value.status_code == 422 and str(error.value) == MESSAGE
    assert_no_jobs(service)
    assert [op for op, _ in boundary.calls] == ['inspect']
    assert request.model_dump() == before


@pytest.mark.parametrize('contents', [None, '{', '[]'])
def test_unreadable_runtime_fails_closed(visual_service, tmp_path, contents):
    service, _ = visual_service
    service.config_path = tmp_path/'runtime.json'
    if contents is not None:
        service.config_path.write_text(contents)
    with pytest.raises(DreamApiError) as error:
        service.submit(params(reference(service, 'visual')))
    assert error.value.code == 'IDENTITY_EXPERIMENTAL_MODEL_DISABLED'
    assert_no_jobs(service)


def test_disabling_after_opt_in_preserves_history_and_rejects_replay(visual_service, tmp_path):
    service, boundary = visual_service
    service.config_path = tmp_path/'runtime.json'
    atomic_json(service.config_path, {'allowExperimentalVisualModels': True})
    request = params(reference(service, 'visual'))
    job = service.submit(request)
    service._futures[job['id']].result(timeout=5)
    completed = service.get(job['id'])
    assert completed['state'] == 'complete', completed['error']
    path = service._job_path(job['id'])
    original = path.read_bytes()
    calls = copy.deepcopy(boundary.calls)
    atomic_json(service.config_path, {'allowExperimentalVisualModels': False})
    # Read the durable job through recovery too, not just the in-memory copy.
    service._jobs.clear()
    service._recover()
    assert service.get(job['id']) == completed
    assert service.jobs() == [completed]
    assert IdentityGenerateRequest.model_validate(completed['request']) == request
    with pytest.raises(DreamApiError, match=MESSAGE):
        service.submit(request)
    assert path.read_bytes() == original and boundary.calls == calls


@pytest.mark.parametrize('model', [FACEID, CYBER])
def test_stable_routes_still_submit_without_experimental_runtime(visual_service, tmp_path, model):
    service, boundary = visual_service
    service.config_path = tmp_path/'missing-runtime.json'
    ref = reference(service, 'visual' if model == CYBER else 'faceid')
    job = service.submit(params(ref, model))
    service._futures[job['id']].result(timeout=5)
    completed = service.get(job['id'])
    assert completed['state'] == 'complete', completed['error']
    assert completed['request']['modelId'] == model
    assert next(payload for op, payload in boundary.calls if op == 'generate')['modelId'] == model


@pytest.mark.parametrize('batch', [False, True])
def test_http_disabled_request_returns_policy_error_without_creating_jobs(tmp_path, monkeypatch, batch):
    from fastapi.testclient import TestClient
    from app import create_app
    from identity_service import IdentityService
    from job_runner import JobRunner
    from persistent_engine import PersistentEngineClient
    from runtime import DreamRuntime
    from test_generation_jobs import make_config
    from test_identity_api import absent_native, image_base64
    from test_identity_visual_service import InferenceBoundary
    runtime_path = tmp_path/'runtime.json'
    atomic_json(runtime_path, {})
    monkeypatch.setenv('DREAM_IDENTITY_CONFIG', str(runtime_path))
    config = make_config(tmp_path)
    boundary = InferenceBoundary()
    monkeypatch.setattr(IdentityService, '_worker', lambda self, *args: boundary.run(*args))
    runner = JobRunner(config, persistent_engine=PersistentEngineClient(config, transport=absent_native))
    try:
        with TestClient(create_app(config, DreamRuntime(config, job_runner=runner)),
                        base_url='http://127.0.0.1:8866') as client:
            ref = client.post('/api/identity/references', json={'name': 'art',
                'imageBase64': image_base64(), 'referenceKind': 'visual'}).json()
            payload = params(ref).model_dump()
            response = (client.post('/api/identity/batches', json={'request': payload, 'count': 1})
                        if batch else client.post('/api/identity/generate', json=payload))
            assert response.status_code == 422, response.text
            assert response.json()['code'] == 'IDENTITY_EXPERIMENTAL_MODEL_DISABLED'
            assert response.json()['message'] == MESSAGE
            assert client.get('/api/identity/jobs').json() == []
            assert client.get('/api/identity/batches').json() == []
            assert [op for op, _ in boundary.calls] == ['inspect']
    finally:
        runner._executor.shutdown(wait=True, cancel_futures=True)


def test_disabled_retry_preserves_frozen_batch(visual_service, tmp_path):
    service, boundary = visual_service
    service.config_path = tmp_path/'runtime.json'
    atomic_json(service.config_path, {'allowExperimentalVisualModels': True})
    job = service.batch_operation('submit', BatchRequest(request=params(reference(service, 'visual')), count=1))
    service._background[job['id']][0].result(timeout=5)
    completed = service.batch_operation('get', job['id'])
    # The inference boundary deliberately emits no batch images: this is a failed item.
    assert completed['state'] == 'failed'
    path = service.batches.path(job['id'])
    original = path.read_bytes()
    calls = copy.deepcopy(boundary.calls)
    atomic_json(service.config_path, {})
    with pytest.raises(DreamApiError, match=MESSAGE):
        service.batch_operation('retry', job['id'], BatchRetryRequest(mode='failed', idempotencyKey='gate-retry'))
    assert service.batch_operation('get', job['id']) == completed
    assert path.read_bytes() == original and boundary.calls == calls
    assert len(service.batch_operation('list')) == 1


def test_public_status_preserves_experimental_warning_without_asset_paths(visual_service, tmp_path):
    service, boundary = visual_service
    config = installed(tmp_path, {})
    boundary.models = identity_model_catalog(config)
    row = next(row for row in service.status()['models'] if row['id'] == ILLUSTRIOUS)
    assert row['ready'] is False and row['experimental'] is True
    assert row['qualityStatus'] == 'failed' and row['message'] == MESSAGE
    assert str(tmp_path) not in json.dumps(row)
