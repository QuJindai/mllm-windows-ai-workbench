"""Real refinement storage/queue and pixel boundaries; only model inference is fake."""
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest
from PIL import Image

from test_identity_api import harness, upload, submit, finished
from test_identity_refinements import base, done


@pytest.fixture
def upscaler(tmp_path, monkeypatch):
    model = tmp_path / 'RealESRGAN_x4plus.pth'
    model.write_bytes(b'CPU model boundary fixture')
    control, calls = {}, []

    def status(config):
        path = Path(config.get('upscaleModel') or tmp_path / 'missing')
        return {'ready': path.is_file() and path.stat().st_size > 0,
                'message': '本地清晰增强模型未就绪'}

    def enhance(config, image, stage, *, tile=128):
        assert tile == 128
        assert status(config)['ready']
        calls.append(image.size)
        stage('2倍清晰增强')
        if control.get('started'):
            control['started'].set()
            assert control['cancelled'].wait(5)
        if control.get('fail'):
            raise RuntimeError('upscale model failed')
        result = image.resize((image.width * 2, image.height * 2))
        if control.get('size'):
            result = result.resize(control['size'])
        if control.get('mode'):
            result = result.convert(control['mode'])
        details = {'method': 'RealESRGAN-x4plus-to-2x', 'modelSha256': hashlib.sha256(model.read_bytes()).hexdigest(),
                   'inputWidth': image.width, 'inputHeight': image.height,
                   'outputWidth': result.width, 'outputHeight': result.height,
                   'durationMs': 17, 'tileSize': tile}
        details.update(control.get('details', {}))
        return result, details

    monkeypatch.setitem(sys.modules, 'identity_upscale', SimpleNamespace(enhance=enhance, upscale_status=status))
    return SimpleNamespace(model=model, config={'upscaleModel': str(model)}, calls=calls, control=control,
                           status=status, probes=[])


@pytest.fixture
def stored(harness, upscaler, monkeypatch):
    from identity_service import IdentityService
    from identity_refinement_engine import refine
    client, config, runner, boundary = harness
    source = base(client)
    runtime = config.dream_root / 'data/identity/runtime.json'
    settings = json.loads(runtime.read_text(encoding='utf-8'))
    runtime.write_text(json.dumps({**settings, **upscaler.config}), encoding='utf-8')
    original = IdentityService._worker

    def worker(self, operation, payload, cancelled=None):
        if operation == 'status' and payload.get('capability') == 'upscale':
            upscaler.probes.append(payload)
            return {'upscale': upscaler.status(json.loads(runtime.read_text(encoding='utf-8')))}
        if operation != 'refine':
            return original(self, operation, payload, cancelled)
        upscaler.control['cancelled'] = cancelled
        result = refine(upscaler.config, payload)
        if upscaler.control.get('tamper_output'):
            Image.new('RGB', (512, 768)).save(payload['outputPath'])
        return result

    monkeypatch.setattr(IdentityService, '_worker', worker)
    return SimpleNamespace(client=client, config=config, runner=runner, source=source, runtime=runtime,
                           folder=config.dream_root / 'data/identity/refinements' / source['id'], real_worker=original)


def request(stored, **changes):
    return {'sourceJobId': stored.source['id'], 'mode': 'upscale', 'requestId': 'upscale-request-0001', **changes}


def submit_upscale(stored, **changes):
    response = stored.client.post('/api/identity/refinements', json=request(stored, **changes))
    assert response.status_code == 200, response.text
    return done(stored.client, stored.source['id'], response.json()['id'])


def test_upscale_is_immutable_selectable_double_size_and_terminal_edit(stored, upscaler):
    client, source = stored.client, stored.source
    original = client.get(source['result']['imageUrl']).content
    job_path = stored.config.dream_root / 'data/identity/jobs' / (source['id'] + '.json')
    frozen = job_path.read_bytes()
    row = submit_upscale(stored)
    assert row['state'] == 'complete', row
    assert (row['width'], row['height'], row['canRefine']) == (1024, 1536, False)
    with Image.open(io.BytesIO(client.get(row['imageUrl']).content)) as image:
        assert image.size == (1024, 1536) and image.mode == 'RGB'
    assert client.get(source['result']['imageUrl']).content == original and job_path.read_bytes() == frozen
    workspace = client.get(f"/api/identity/jobs/{source['id']}/refinements").json()
    assert 'upscale' in workspace['modes'] and workspace['selectedVersionId'] == 'result'
    assert [(x['width'], x['height'], x['canRefine']) for x in workspace['versions'][:2]] == [(512, 768, True)] * 2
    selected = client.post(f"/api/identity/jobs/{source['id']}/refinements/select", json={'versionId': row['id']})
    assert selected.status_code == 200 and selected.json()['selectedVersionId'] == row['id']
    for mode in ('upscale', 'restore', 'edge-lighting', 'redraw', 'reference-anchor'):
        denied = client.post('/api/identity/refinements', json=request(stored, mode=mode, parentVersionId=row['id'], requestId='another-request-0001'))
        assert denied.status_code == 409, denied.text
        assert '增强前' in denied.text
    assert upscaler.calls == [(512, 768)]


def test_upscale_replay_survives_missing_model_and_changed_payload_conflicts(stored, upscaler):
    row = submit_upscale(stored)
    assert row['state'] == 'complete', row
    upscaler.model.unlink()
    replay = stored.client.post('/api/identity/refinements', json=request(stored))
    assert replay.status_code == 200 and replay.json()['id'] == row['id']
    assert stored.client.post('/api/identity/refinements', json=request(stored, seed=43)).status_code == 409
    assert upscaler.calls == [(512, 768)]


@pytest.mark.parametrize('width,height,expected', [(640, 960, (1280, 1920)), (768, 1152, (1536, 2304)),
                                                 (1152, 768, (2304, 1536))])
def test_upscale_storage_publishes_double_actual_hd_task_size(stored, width, height, expected):
    created = submit(stored.client, upload(stored.client), width=width, height=height)
    stored.source = finished(stored.client, created['id'])
    row = submit_upscale(stored)
    assert row['state'] == 'complete', row
    assert (row['width'], row['height']) == expected and row['canRefine'] is False
    with Image.open(io.BytesIO(stored.client.get(row['imageUrl']).content)) as image:
        assert image.size == expected


def legacy_version(stored, *, size=(512, 768)):
    version = 'refine-' + stored.source['id'].removeprefix('identity-') + '-' + 'e' * 24
    stored.folder.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', size, 'blue').save(stored.folder / (version + '.png'))
    row = {'id': version, 'sourceJobId': stored.source['id'], 'parentVersionId': 'result', 'state': 'complete',
           'createdAt': '2026-01-01T00:00:00+00:00', 'imageUrl': f'/api/identity/refinements/{version}/image',
           'settings': {'sourceJobId': stored.source['id'], 'parentVersionId': 'result', 'mode': 'restore',
                        'strength': .3, 'prompt': '', 'negativePrompt': '', 'seed': 42, 'requestId': None}}
    (stored.folder / (version + '.json')).write_text(json.dumps(row), encoding='utf-8')
    return version


def test_legacy_same_size_refinement_remains_editable_and_is_actual_upscale_source(stored):
    version = legacy_version(stored)
    path = stored.folder / (version + '.json')
    frozen = path.read_bytes()
    workspace = stored.client.get(f"/api/identity/jobs/{stored.source['id']}/refinements").json()
    prior = next(row for row in workspace['versions'] if row['id'] == version)
    assert (prior['width'], prior['height'], prior['canRefine']) == (512, 768, True)
    row = submit_upscale(stored, parentVersionId=version)
    assert row['state'] == 'complete', row
    with Image.open(io.BytesIO(stored.client.get(row['imageUrl']).content)) as image:
        assert image.getpixel((0, 0)) == (0, 0, 255)
    assert path.read_bytes() == frozen


def test_changed_parent_size_is_rejected_before_dispatch(stored, upscaler):
    version = legacy_version(stored, size=(1024, 1536))
    response = stored.client.post('/api/identity/refinements', json=request(stored, parentVersionId=version))
    assert response.status_code == 409 and '增强前' in response.text
    assert not upscaler.calls


@pytest.mark.parametrize('invalid', ['missing', 'empty', 'directory'])
def test_workspace_hides_unready_upscale_and_new_submit_does_not_enqueue(stored, upscaler, invalid):
    upscaler.model.unlink()
    if invalid == 'empty':
        upscaler.model.touch()
    if invalid == 'directory':
        upscaler.model.mkdir()
    workspace = stored.client.get(f"/api/identity/jobs/{stored.source['id']}/refinements").json()
    assert 'upscale' not in workspace['modes']
    response = stored.client.post('/api/identity/refinements', json=request(stored))
    assert response.status_code == 409, response.text
    assert not upscaler.calls and not list(stored.folder.glob('refine-*.json'))


def test_upscale_skips_disabled_base_reference_and_anime_resolution(stored, monkeypatch):
    import identity_service
    import identity_anime_profiles
    monkeypatch.setattr(identity_service.IdentityService, '_require_model_enabled', lambda *a: pytest.fail('unused base model gate'))
    monkeypatch.setattr(identity_service.IdentityService, 'reference_image', lambda *a: pytest.fail('unused person reference'))
    monkeypatch.setattr(identity_anime_profiles.AnimeProfiles, 'resolve_request', lambda *a: pytest.fail('unused anime archive'))
    row = submit_upscale(stored)
    assert row['state'] == 'complete', row


@pytest.mark.parametrize('route', ['/api/identity/jobs', '/api/history'])
def test_upscale_deletion_removes_versions_and_stale_access(stored, route):
    row = submit_upscale(stored)
    assert row['state'] == 'complete', row
    assert stored.client.delete(f"{route}/{stored.source['id']}").status_code == 200
    assert stored.client.get(row['imageUrl']).status_code == 404
    assert not list(stored.folder.glob('refine-*'))


def test_upscale_cancel_fences_late_output_and_delete_waits(stored, upscaler):
    upscaler.control['started'] = threading.Event()
    response = stored.client.post('/api/identity/refinements', json=request(stored))
    assert response.status_code == 200, response.text
    assert upscaler.control['started'].wait(5)
    assert stored.client.delete(f"/api/history/{stored.source['id']}").status_code == 409
    cancelled = stored.client.post(f"/api/identity/refinements/{response.json()['id']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()['state'] == 'cancelled'
    assert not list(stored.folder.glob('*.png'))


def test_upscale_queued_cancellation_uses_existing_serial_queue(stored, upscaler):
    blocked, release = threading.Event(), threading.Event()
    def occupied():
        blocked.set()
        assert release.wait(5)
    future = stored.runner.submit_serial(occupied)
    try:
        assert blocked.wait(5)
        response = stored.client.post('/api/identity/refinements', json=request(stored))
        assert response.status_code == 200, response.text
        cancelled = stored.client.post(f"/api/identity/refinements/{response.json()['id']}/cancel")
        assert cancelled.status_code == 200 and cancelled.json()['state'] == 'cancelled'
        assert not upscaler.calls
    finally:
        release.set()
        future.result(timeout=5)


@pytest.mark.parametrize('failure', ['fail', 'tamper_output'])
def test_failed_upscale_never_publishes_or_changes_selection(stored, upscaler, failure):
    upscaler.control[failure] = True
    row = submit_upscale(stored)
    assert row['state'] == 'failed' and row['imageUrl'] is None
    workspace = stored.client.get(f"/api/identity/jobs/{stored.source['id']}/refinements").json()
    assert workspace['selectedVersionId'] == 'result' and not list(stored.folder.glob('*.png'))


def test_upscale_interrupted_record_is_not_resubmitted(stored, upscaler):
    row = submit_upscale(stored)
    assert row['state'] == 'complete', row
    path = stored.folder / (row['id'] + '.json')
    saved = json.loads(path.read_text(encoding='utf-8'))
    saved.update(state='running', imageUrl=None)
    path.write_text(json.dumps(saved), encoding='utf-8')
    replay = stored.client.post('/api/identity/refinements', json=request(stored)).json()
    assert replay['id'] == row['id'] and replay['state'] == 'failed' and replay['error'] == 'INTERRUPTED'
    assert upscaler.calls == [(512, 768)]


@pytest.fixture
def engine_case(tmp_path):
    source = tmp_path / 'source.png'
    Image.new('RGB', (512, 768), (20, 60, 100)).save(source)
    return dict(modelId='realistic-vision-v5.1-faceid', sourcePath=str(source), outputPath=str(tmp_path / 'edit.png'),
                width=512, height=768, editSettings=dict(mode='upscale', strength=.3, seed=0, prompt='', negativePrompt=''))


@pytest.mark.parametrize('model,anime', [('realistic-vision-v5.1-faceid', None), ('illustrious-xl-v2.0-faceid', 'anime-' + 'd' * 24),
                                      ('cyberrealistic-xl-plus-face', None)])
def test_upscale_engine_uses_only_helper_and_no_cross_size_pixel_metrics(engine_case, upscaler, monkeypatch, model, anime):
    import identity_refinement_engine as engine
    engine_case.update(modelId=model, animeProfileId=anime)
    monkeypatch.setitem(sys.modules, 'identity_pipeline', None)
    monkeypatch.setitem(sys.modules, 'identity_face_polish', None)
    monkeypatch.setitem(sys.modules, 'identity_anime', None)
    monkeypatch.setattr(engine, 'compare_images', lambda *a, **kw: pytest.fail('cross-size retention'))
    original = copy.deepcopy(engine_case)
    result = engine.refine(upscaler.config, engine_case)
    assert result['ok'] and engine_case == original
    assert (result['polish']['inputWidth'], result['polish']['inputHeight']) == (512, 768)
    assert (result['polish']['outputWidth'], result['polish']['outputHeight']) == (1024, 1536)
    assert result['polish']['modelSha256'] == hashlib.sha256(upscaler.model.read_bytes()).hexdigest()
    assert result['polish']['sourceSha256'] == hashlib.sha256(Path(engine_case['sourcePath']).read_bytes()).hexdigest()
    assert result['polish']['outputSha256'] == hashlib.sha256(Path(engine_case['outputPath']).read_bytes()).hexdigest()
    assert result['polish']['durationMs'] == 17 and result['polish']['tileSize'] == 128
    assert 'retention' not in result.get('diagnostics', {})
    with Image.open(engine_case['outputPath']) as output:
        assert output.mode == 'RGB' and output.size == (1024, 1536)


@pytest.mark.parametrize('size,allowed', [((768, 1152), True), ((1152, 768), True), ((1152, 1152), False), ((1160, 256), False)])
def test_upscale_engine_bounds_follow_base_dimensions(engine_case, upscaler, size, allowed):
    from identity_refinement_engine import refine
    Image.new('RGB', size).save(engine_case['sourcePath'])
    engine_case.update(width=size[0], height=size[1])
    if not allowed:
        with pytest.raises(ValueError, match='尺寸|像素'):
            refine(upscaler.config, engine_case)
        assert not upscaler.calls and not Path(engine_case['outputPath']).exists()
    else:
        refine(upscaler.config, engine_case)
        with Image.open(engine_case['outputPath']) as image:
            assert image.size == ((1536, 2304) if size == (768, 1152) else (2304, 1536))


@pytest.mark.parametrize('change', [{'size': (512, 768)}, {'mode': 'RGBA'}, {'details': {'modelSha256': 'bad'}},
                                  {'details': {'inputWidth': 1}}, {'details': {'outputWidth': 1}},
                                  {'details': {'durationMs': float('nan')}}, {'details': {'tileSize': 256}}])
def test_upscale_invalid_output_or_audit_never_publishes(engine_case, upscaler, change):
    from identity_refinement_engine import refine
    upscaler.control.update(change)
    before = Path(engine_case['sourcePath']).read_bytes()
    with pytest.raises(ValueError):
        refine(upscaler.config, engine_case)
    assert upscaler.calls == [(512, 768)]
    assert not Path(engine_case['outputPath']).exists() and Path(engine_case['sourcePath']).read_bytes() == before


@pytest.mark.parametrize('model,profile', [('realistic-vision-v5.1-faceid', None), ('cyberrealistic-xl-plus-face', None),
                                        ('illustrious-xl-v2.0-faceid', 'anime-' + 'd' * 24)])
def test_upscale_worker_config_skips_base_assets_and_anime_gate(engine_case, upscaler, monkeypatch, tmp_path, model, profile):
    import identity_models
    from identity_worker import load_config
    path = tmp_path / 'runtime.json'
    path.write_text(json.dumps(upscaler.config))
    monkeypatch.setattr(identity_models, 'resolve_identity_model', lambda *a: pytest.fail('unused base model resolution'))
    assert load_config({**engine_case, 'configPath': str(path), 'modelId': model, 'animeProfileId': profile}, operation='refine') == upscaler.config


def test_upscale_worker_dispatches_real_engine_without_generation_or_face_imports(engine_case, upscaler, monkeypatch, tmp_path):
    import identity_worker
    config_path, request_path, result_path = [tmp_path / name for name in ('runtime.json', 'request.json', 'result.json')]
    config_path.write_text(json.dumps(upscaler.config))
    request_path.write_text(json.dumps({**engine_case, 'configPath': str(config_path)}))
    for module in ('identity_pipeline', 'identity_face_polish', 'identity_anime'):
        monkeypatch.setitem(sys.modules, module, None)
    monkeypatch.setattr(sys.stdout, 'reconfigure', lambda **kw: None, raising=False)
    monkeypatch.setattr(sys.stderr, 'reconfigure', lambda **kw: None, raising=False)
    monkeypatch.setattr(sys, 'argv', ['worker', '--operation', 'refine', '--request', str(request_path), '--result', str(result_path)])
    assert identity_worker.main() == 0
    result = json.loads(result_path.read_text(encoding='utf-8'))
    assert result['ok'] and result['mode'] == 'upscale'
    with Image.open(engine_case['outputPath']) as image:
        assert image.size == (1024, 1536)


def test_workspace_probes_configured_python_when_controller_lacks_spandrel(stored, monkeypatch, tmp_path):
    """Use a real isolated interpreter, not the controller's import visibility."""
    import os
    import subprocess
    import venv
    from identity_service import IdentityService
    from test_identity_api import REAL_POPEN
    worker_env = tmp_path / 'worker-env'
    venv.EnvBuilder(with_pip=False).create(worker_env)
    python = worker_env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    packages = worker_env / ('Lib/site-packages' if os.name == 'nt' else f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages')
    for name in ('torch', 'spandrel', 'PIL'):
        (packages / (name + '.py')).write_text("raise RuntimeError('capability probe must not import model libraries')\n")
    settings = json.loads(stored.runtime.read_text(encoding='utf-8'))
    stored.runtime.write_text(json.dumps({**settings, 'python': str(python)}), encoding='utf-8')
    monkeypatch.setitem(sys.modules, 'identity_upscale', SimpleNamespace(upscale_status=lambda _: {
        'ready': False, 'message': 'controller has no spandrel'}))
    monkeypatch.setattr(IdentityService, '_worker', stored.real_worker)
    release_warm_worker = IdentityService.release_warm_worker
    monkeypatch.setattr(IdentityService, 'release_warm_worker', lambda *_: pytest.fail('probe released GPU worker'))
    commands = []
    def spawn(command, **kwargs):
        assert command[0] == str(python)
        commands.append(command)
        return REAL_POPEN(command, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', spawn)
    url = f"/api/identity/jobs/{stored.source['id']}/refinements"
    try:
        assert 'upscale' in stored.client.get(url).json()['modes']
        assert 'upscale' in stored.client.get(url).json()['modes']
        assert len(commands) == 1
    finally:
        # Allow the normal service shutdown to run its unrelated release path.
        monkeypatch.setattr(IdentityService, 'release_warm_worker', release_warm_worker)


@pytest.fixture
def probe_store(tmp_path, upscaler, monkeypatch):
    from identity_refinements import IdentityRefinements
    import identity_refinements
    config_path = tmp_path / 'runtime.json'
    config_path.write_text(json.dumps({**upscaler.config, 'python': sys.executable}))
    clock = [10.]
    monkeypatch.setattr(identity_refinements, 'perf_counter', lambda: clock[0])
    calls, results = [], [{'upscale': {'ready': True, 'message': 'worker ready'}}]
    def worker(operation, payload, cancelled=None):
        assert operation == 'status' and payload == {'configPath': str(config_path), 'capability': 'upscale'}
        calls.append(payload)
        result = results[0]
        if isinstance(result, Exception):
            raise result
        return copy.deepcopy(result)
    store = IdentityRefinements(SimpleNamespace(config_path=config_path, _worker=worker))
    return SimpleNamespace(store=store, config_path=config_path, calls=calls, results=results, clock=clock)


def test_worker_capability_cache_refreshes_after_ttl_config_and_model_changes(probe_store, upscaler):
    case = probe_store
    first = case.store.upscale_status()
    assert first['ready']
    first['ready'] = False
    assert case.store.upscale_status()['ready'] and len(case.calls) == 1
    case.clock[0] += 61
    assert case.store.upscale_status()['ready'] and len(case.calls) == 2
    settings = json.loads(case.config_path.read_text())
    case.config_path.write_text(json.dumps({**settings, 'python': sys.executable + '.other'}))
    assert case.store.upscale_status()['ready'] and len(case.calls) == 3
    upscaler.model.write_bytes(b'replaced model with a different signature')
    assert case.store.upscale_status()['ready'] and len(case.calls) == 4
    upscaler.model.unlink()
    assert not case.store.upscale_status()['ready'] and len(case.calls) == 4


@pytest.mark.parametrize('reply', [{'upscale': {'ready': False, 'message': 'worker lacks spandrel'}},
                                  {'upscale': {'ready': 'yes', 'message': 'invalid'}}, {}, RuntimeError('worker probe failed')])
def test_worker_probe_failures_are_cached_briefly_and_fail_closed(probe_store, reply):
    case = probe_store
    case.results[0] = reply
    assert not case.store.upscale_status()['ready']
    assert not case.store.upscale_status()['ready'] and len(case.calls) == 1
    case.results[0] = {'upscale': {'ready': True, 'message': 'worker repaired'}}
    case.clock[0] += 11
    assert case.store.upscale_status()['ready'] and len(case.calls) == 2


@pytest.fixture
def held_probe(stored, monkeypatch):
    from identity_service import IdentityService
    entered, release = threading.Event(), threading.Event()
    previous = IdentityService._worker
    calls = []

    def worker(service, operation, payload, cancelled=None):
        if operation == 'status' and payload.get('capability') == 'upscale':
            calls.append(payload)
            entered.set()
            assert release.wait(8), 'test did not release the blocked probe'
            return {'upscale': {'ready': True, 'message': 'ready'}}
        return previous(service, operation, payload, cancelled)

    return SimpleNamespace(enter=entered, release=release, calls=calls,
                           install=lambda: monkeypatch.setattr(IdentityService, '_worker', worker))


@pytest.mark.parametrize('entry', ['workspace', 'submit'])
def test_hung_probe_allows_running_edit_cancel_before_probe_returns(stored, upscaler, held_probe, entry):
    client = stored.client
    other = base(client)
    upscaler.control['started'] = threading.Event()
    active = client.post('/api/identity/refinements', json=request(stored))
    assert active.status_code == 200 and upscaler.control['started'].wait(5)
    cancelled = upscaler.control['cancelled']
    upscaler.model.write_bytes(b'new model invalidates the initial probe')
    held_probe.install()
    with ThreadPoolExecutor(max_workers=2) as pool:
        if entry == 'workspace':
            probe = pool.submit(client.get, f"/api/identity/jobs/{other['id']}/refinements")
        else:
            probe = pool.submit(client.post, '/api/identity/refinements', json=request(stored, sourceJobId=other['id']))
        try:
            assert held_probe.enter.wait(3)
            stop = pool.submit(client.post, f"/api/identity/refinements/{active.json()['id']}/cancel")
            assert cancelled.wait(2), 'the capability probe held the service lock during cancellation'
            assert stop.result(timeout=2).json()['state'] == 'cancelled'
            assert not probe.done()
        finally:
            upscaler.control.pop('started', None)
            held_probe.release.set()
        assert probe.result(timeout=4).status_code == 200


@pytest.mark.parametrize('entry', ['workspace', 'submit'])
def test_hung_probe_rechecks_deleted_source_before_return_or_dispatch(stored, upscaler, held_probe, entry):
    client, source = stored.client, stored.source['id']
    held_probe.install()
    with ThreadPoolExecutor(max_workers=2) as pool:
        probe = (pool.submit(client.get, f'/api/identity/jobs/{source}/refinements') if entry == 'workspace'
                 else pool.submit(client.post, '/api/identity/refinements', json=request(stored)))
        try:
            assert held_probe.enter.wait(3)
            remove = pool.submit(client.delete, f'/api/history/{source}')
            assert remove.result(timeout=2).status_code == 200
        finally:
            held_probe.release.set()
        assert probe.result(timeout=4).status_code == 404
    assert not upscaler.calls and not list(stored.folder.glob('refine-*.json'))


def test_probe_rechecks_chosen_parent_before_dispatch(stored, upscaler, held_probe):
    parent = legacy_version(stored)
    held_probe.install()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(stored.client.post, '/api/identity/refinements', json=request(stored, parentVersionId=parent))
        try:
            assert held_probe.enter.wait(3)
            (stored.folder / (parent + '.png')).unlink()
        finally:
            held_probe.release.set()
        assert pending.result(timeout=4).status_code == 404
    assert not upscaler.calls and len(list(stored.folder.glob('refine-*.json'))) == 1


def test_concurrent_submitters_share_probe_and_one_durable_edit(stored, upscaler, held_probe):
    held_probe.install()
    start = threading.Barrier(3)
    def send():
        start.wait(timeout=4)
        return stored.client.post('/api/identity/refinements', json=request(stored))
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(send) for _ in range(2)]
        try:
            start.wait(timeout=4)
            assert held_probe.enter.wait(3)
        finally:
            held_probe.release.set()
        replies = [future.result(timeout=4) for future in pending]
    assert all(reply.status_code == 200 for reply in replies)
    assert replies[0].json()['id'] == replies[1].json()['id']
    assert done(stored.client, stored.source['id'], replies[0].json()['id'])['state'] == 'complete'
    assert len(held_probe.calls) == len(upscaler.calls) == 1


def test_slow_upscale_probe_receives_its_own_cancellation_deadline(probe_store, monkeypatch):
    import identity_refinements
    from identity_service import WorkerCancelled
    case = probe_store
    def slow_probe(operation, payload, cancelled=None):
        assert cancelled is not None and cancelled.wait(1), 'missing bounded capability probe'
        raise WorkerCancelled()
    monkeypatch.setattr(identity_refinements, 'UPSCALE_PROBE_TIMEOUT_SECONDS', .05, raising=False)
    monkeypatch.setattr(case.store.service, '_worker', slow_probe)
    assert not case.store.upscale_status()['ready']
