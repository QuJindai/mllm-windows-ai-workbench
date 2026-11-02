"""Real HQ storage/queue/hash/auth behavior; only HTTP and child processes are fake."""
from __future__ import annotations

import hashlib
import io
import json
import queue
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from pydantic import ValidationError

from errors import DreamApiError
from hq_service import HQCreateRequest, HQService, ORIGIN, atomic_json
from identity_service import IdentityService, hq_pixel_fingerprint
from identity_contract import IdentityGenerateRequest
from hq_tryon_pipeline import DIRECTORY_KEYS, FILE_KEYS, required_assets
from job_runner import JobRunner
from test_generation_jobs import make_config


def png(size=(16, 24), color='navy', format='PNG'):
    stream = io.BytesIO()
    Image.new('RGB', size, color).save(stream, format=format)
    return stream.getvalue()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class OwnedR2:
    def __init__(self):
        self.raw = {'person': png(format='JPEG'), 'garment': png(color='red'), 'pose': png(color='white')}
        self.ids = {'person': sha(self.raw['person']), 'garment': 'G001', 'pose': 'P001'}
        self.calls = []
        self.denied = self.bad_hash = self.redirect = False
        self.evil_url = None
        self.timeouts = 0
        self.session = '1' * 64  # Synthetic test credential, never the real config.

    def item(self, kind):
        prefix = ORIGIN + '/assets/20261101-r2-v2/' + kind + '/' + self.ids[kind] + '/'
        return {'id': self.ids[kind], 'label': kind, 'category': 'studio',
                'fullUrl': self.evil_url or prefix + 'original.png', 'thumbUrl': prefix + 'thumb.png',
                'fullSha256': sha(self.raw[kind]), 'thumbSha256': sha(png(color='gray'))}

    def __call__(self, request):
        self.calls.append(request)
        assert request.url.host == 'hq-tryon-picker.qujindai1986.workers.dev'
        path = request.url.path
        if path.startswith('/api/person/'):
            assert request.headers.get('authorization') == 'Bearer ' + self.session
            if self.denied:
                return httpx.Response(401, json={'error': 'private'})
            if self.redirect:
                return httpx.Response(302, headers={'location': 'https://evil.invalid/steal'})
        else:
            assert 'authorization' not in request.headers
        if path == '/api/person/list':
            return httpx.Response(200, json={'items': [{'id': self.ids['person'], 'sha256': self.ids['person'], 'name': 'person.jpg'}], 'hasMore': False, 'nextCursor': None})
        if path == '/api/catalog':
            kind = request.url.params['kind']
            return httpx.Response(200, json={'items': [self.item(kind)], 'total': 1, 'hasMore': False,
                                           'categories': ['studio'], 'release': '20261101-r2-v2'})
        if path == '/api/asset':
            return httpx.Response(200, json={'item': self.item(request.url.params['kind'])})
        if path.startswith('/api/person/image/'):
            if self.timeouts:
                self.timeouts -= 1
                raise httpx.ReadTimeout('synthetic timeout', request=request)
            return httpx.Response(200, content=self.raw['person'], headers={'content-type': 'image/jpeg', 'x-content-sha256': self.ids['person']})
        if path.startswith('/assets/'):
            kind = path.split('/')[3]
            raw = png(color='gray') if path.endswith('/thumb.png') else self.raw[kind]
            if self.bad_hash:
                raw = png(color='green')
            return httpx.Response(200, content=raw, headers={'content-type': 'image/png'})
        raise AssertionError('Unexpected network operation: ' + path)


class Pipe:
    def __init__(self):
        self.data = queue.Queue()
        self.closed = False

    def readline(self, limit):
        return self.data.get(timeout=10)

    def put(self, value):
        self.data.put(value)

    def close(self):
        self.closed = True


class ProcessBoundary:
    """Only the existing identity worker process is replaced; its service and queue remain real."""
    def __init__(self):
        self.calls, self.inspections, self.refinements, self.lifetimes = [], [], [], []
        self.started = threading.Event()
        self.release = threading.Event()
        self.hold = False
        self.error = None
        self.bad_audit = False
        self.bad_output_hash = False
        self.late_output = False
        self.confirmed = []
        self.release_allowed = threading.Event()
        self.release_allowed.set()
        self.release_blocked = threading.Event()
        self.faces = [{'index': 0, 'box': [1., 1., 12., 20.]}]

    def spawn(self, command, **kwargs):
        assert Path(command[1]).name == 'identity_worker.py'
        assert command[2:3] == ['--operation']
        operation = command[3]
        request = json.loads(Path(command[5]).read_text(encoding='utf-8'))
        result_path = Path(command[7])
        trusted = bool(request.get('hqConditioning'))
        if trusted:
            assert command[8:] == ['--ownership-handshake']
            assert operation == 'generate'
            assert set(request['hqConditioning']['inputs']) == {'person', 'garment', 'pose'}
        else:
            assert len(command) == 8
        target = self.calls if operation == 'generate' else self.inspections if operation == 'inspect' else self.refinements
        target.append((command, kwargs, request))
        boundary = self

        class Child:
            pid = 7654321
            returncode = None
            stopped = False
            continued = False

            def __init__(self):
                self.stdout = io.BytesIO((json.dumps({'workerReady': True, 'pid': self.pid}) + '\n').encode()) if trusted else None
                self.stdin = SimpleNamespace(write=self.resume, flush=lambda: None, close=lambda: None) if trusted else None

            def resume(self, data):
                assert self.pid in boundary.confirmed
                assert json.loads(data)['workerContinue'] is True
                self.continued = True

            def poll(self):
                return self.returncode

            def terminate(self):
                self.stopped = True

            kill = terminate

            def wait(self, timeout=None):
                self.communicate(timeout=timeout)
                return self.returncode

            def communicate(self, timeout=None):
                if self.returncode is not None:
                    return b'', b''
                if trusted and not self.stopped:
                    assert self.continued
                if operation == 'generate':
                    boundary.started.set()
                    if boundary.hold and not boundary.release.wait(.01) and not self.stopped:
                        raise subprocess.TimeoutExpired(command, timeout)
                if self.stopped and not boundary.late_output:
                    self.returncode = -15
                    return b'', b''
                if operation == 'inspect':
                    result = {'faces': boundary.faces}
                elif operation == 'refine':
                    Path(request['outputPath']).write_bytes(Path(request['sourcePath']).read_bytes())
                    result = {'ok': True, 'restoreStrength': .35}
                elif boundary.error:
                    result = {'ok': False, 'error': {'code': boundary.error, 'message': 'Synthetic worker failure'}}
                    if trusted:
                        condition = request['hqConditioning']
                        atomic_json(Path(condition['auditPath']), {'schemaVersion': 2,
                            'pipeline': 'identity-session-hq-sd15-v1', 'jobId': request['jobId'],
                            'parentJobId': condition['jobId'], 'status': 'failed', 'error': result['error']})
                    result_path.write_text(json.dumps(result), encoding='utf-8')
                    self.returncode = 1
                    return b'', b''
                else:
                    raw = png((request['width'], request['height']))
                    output = Path(request['outputPath'])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(raw)
                    metadata = {'seed': request['seed'], 'generation_time_ms': 17}
                    if request.get('facePolish'):
                        original = Path(request['dreamRoot']) / 'data' / 'identity' / 'originals' / (request['jobId'] + '.png')
                        original.parent.mkdir(parents=True, exist_ok=True)
                        original.write_bytes(raw)
                        metadata['facePolish'] = {'enabled': True, 'status': 'completed',
                            'originalImageUrl': f"/api/identity/jobs/{request['jobId']}/original", 'restoreStrength': request['faceRestoreStrength']}
                    if trusted:
                        condition = request['hqConditioning']
                        audit = {'schemaVersion': 2, 'pipeline': 'identity-session-hq-sd15-v1',
                                 'jobId': request['jobId'], 'parentJobId': condition.get('jobId'), 'status': 'completed',
                                 'parameters': {key: request[key] for key in ('seed', 'width', 'height', 'steps')},
                                 'configuration': {'sha256': sha(Path(condition['configPath']).read_bytes())},
                                 'inputs': {role: dict(item) for role, item in condition['inputs'].items()},
                                 'conditioning': {role: {'actualConditioning': {'sha256': sha(role.encode()), 'observed': True,
                                     'shape': [1, 4, 8], 'dtype': 'float16', 'forwardCalls': request['steps']}}
                                     for role in ('person', 'garment', 'pose')},
                                 'output': {'path': str(output), 'sha256': '0' * 64 if boundary.bad_output_hash else sha(raw),
                                            'width': request['width'], 'height': request['height']}}
                        if boundary.bad_audit:
                            audit['inputs']['person']['sha256'] = '0' * 64
                        Path(condition['auditPath']).write_text(json.dumps(audit), encoding='utf-8')
                        Path(condition['eventPath']).write_text(json.dumps({'jobId': request['jobId'], 'type': 'step', 'step': 1}) + '\n', encoding='utf-8')
                        metadata['hq'] = audit
                    Path(request['metadataPath']).write_text(json.dumps(metadata), encoding='utf-8')
                    result = {'ok': True}
                result_path.write_text(json.dumps(result), encoding='utf-8')
                self.returncode = 0
                return b'', b''

        return Child()

    def lifetime(self, process, *, awaiting_worker=False):
        boundary = self
        class Lifetime:
            def confirm_worker(self, pid):
                assert awaiting_worker and pid == process.pid
                boundary.confirmed.append(pid)
            def close(self):
                if not boundary.release_allowed.is_set():
                    boundary.release_blocked.set()
                    raise RuntimeError('Synthetic owned child release unconfirmed')
                process.terminate()
                process.wait(5)
        result = Lifetime()
        self.lifetimes.append(result)
        return result


def setup_hq(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    root = config.dream_root / 'data' / 'hq'
    root.mkdir()
    pipeline = {'schemaVersion': 1}
    for key in FILE_KEYS:
        pipeline[key] = str(root / 'models' / (key + '.weight'))
    for key in DIRECTORY_KEYS:
        pipeline[key] = str(root / 'models' / key)
    for path in required_assets(pipeline).values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('test asset')
    atomic_json(root / 'pipeline.json', pipeline)
    session_path = root / 'credentials' / 'vault-session.json'
    atomic_json(session_path, {'token': '1' * 64, 'expiresAt': int(time.time() * 1000) + 3600000})
    atomic_json(root / 'config.json', {'origin': ORIGIN, 'sessionFile': str(session_path),
                                     'pipelineConfig': str(root / 'pipeline.json'), 'python': sys.executable})
    r2, boundary, barriers = OwnedR2(), ProcessBoundary(), []
    engine = SimpleNamespace(release_for_identity=lambda: barriers.append('native'))
    runner = JobRunner(config, persistent_engine=engine)
    client = httpx.Client(transport=httpx.MockTransport(r2))
    import identity_service as identity_module
    monkeypatch.setattr(identity_module.subprocess, 'Popen', boundary.spawn)
    monkeypatch.setattr(identity_module, 'WorkerLifetime', boundary.lifetime)
    identity = IdentityService(config, runner)
    identity.config_path = config.dream_root / 'data' / 'identity' / 'runtime.json'
    from hq_tryon_pipeline import BASE_BINDINGS
    atomic_json(identity.config_path, {'python': sys.executable, 'persistentWorker': True,
                **{target: pipeline[source] for source, target in BASE_BINDINGS.items()}})
    service = HQService(config, runner, client=client, identity_service=identity)
    payload = HQCreateRequest(personId=r2.ids['person'], garmentId=r2.ids['garment'], poseId=r2.ids['pose'],
                              idempotencyKey='hq-local-test-12345678', parameters={'seed': 42, 'width': 256, 'height': 256, 'steps': 2})
    return SimpleNamespace(config=config, root=root, service=service, runner=runner, client=client, r2=r2,
                           boundary=boundary, barriers=barriers, payload=payload, session_path=session_path, identity=identity)


@pytest.fixture
def hq(tmp_path, monkeypatch):
    fixture = setup_hq(tmp_path, monkeypatch)
    try:
        yield fixture
    finally:
        fixture.boundary.release_allowed.set()
        fixture.boundary.release.set()
        fixture.service.close()
        fixture.identity.close()
        fixture.runner._executor.shutdown(wait=True)
        fixture.client.close()


def complete(hq, job_id):
    hq.service._futures[job_id].result(timeout=10)
    return hq.service.get_job(job_id)


def test_depth_preset_preserves_upstream_poses_and_routes_unpaired_jobs(hq):
    import hq_paired_depth as depth
    path = hq.root / 'pipeline.json'
    config = json.loads(path.read_text(encoding='utf-8'))
    config.update(poseEstimator=depth.ESTIMATOR,
                  openpose={key: config[key] for key in ('controlnet', 'controlnetConfig')})
    atomic_json(path, config)
    status = hq.service.status()
    assert status['posePipelineReady'] == {depth.PIPELINE: True, depth.LEGACY_PIPELINE: True}
    assert hq.payload.poseId not in status['pairedDepthPoseIds']
    assert [row['id'] for row in hq.service.catalog('pose')['items']] == [hq.payload.poseId]
    created, reused = hq.service.create_job(hq.payload)
    assert not reused and created['pipeline'] == depth.LEGACY_PIPELINE
    assert complete(hq, created['id'])['state'] == 'succeeded'
    assert hq.service.create_job(hq.payload)[1] is True
    # A missing skeleton model must leave the paired depth poses usable.
    config['openpose']['controlnet'] = str(hq.root / 'missing-skeleton.pth')
    atomic_json(path, config)
    assert hq.service.status()['posePipelineReady'] == {depth.PIPELINE: True, depth.LEGACY_PIPELINE: False}


def test_status_is_file_inventory_not_gpu_and_never_returns_token(hq):
    status = hq.service.status()
    assert status['configured'] and status['authorized'] and status['modelReady']
    assert status['pipelineFilesPresent'] and not status['executionValidated']
    assert status['readiness'] == 'files-present'
    assert not hq.boundary.calls and not hq.barriers
    assert hq.r2.session not in json.dumps(status)
    hq.r2.denied = True
    hq.service._auth_cache = None
    assert not hq.service.status()['authorized']


def test_create_downloads_three_originals_preserves_jpeg_and_does_one_inference(hq, monkeypatch):
    import identity_service as identity_module
    real_read = identity_module.read_json
    reads = []
    def read(path, *args, **kwargs):
        if Path(path).name == 'record.json':
            reads.append(path)
            # Only trusted submission may read HQ's mutable journal. Execution
            # must use the input receipt it persisted, avoiding Windows sharing violations.
            assert len(reads) == 1
        return real_read(path, *args, **kwargs)
    monkeypatch.setattr(identity_module, 'read_json', read)
    record, reused = hq.service.create_job(hq.payload)
    result = complete(hq, record['id'])
    assert not reused and result['state'] == 'succeeded', result['error']
    assert hq.barriers == ['native']
    assert len(hq.boundary.inspections) == 1
    assert len(hq.boundary.calls) == 1
    assert result['outputSha256'] == result['output']['sha256'] == result['result']['sha256']
    assert hq.service.status()['executionValidated']
    folder = hq.root / 'jobs' / record['id']
    assert (folder / 'inputs' / 'person.jpg').read_bytes() == hq.r2.raw['person']
    for kind in ('garment', 'pose'):
        assert (folder / 'inputs' / (kind + '.png')).read_bytes() == hq.r2.raw[kind]
    assert not any(request.url.path.endswith('/thumb.png') for request in hq.r2.calls)
    assert len(result['inputs']) == 3
    assert hq.r2.session not in (folder / 'request.json').read_text()
    assert hq.r2.session not in (folder / 'record.json').read_text()
    second, reused = hq.service.create_job(hq.payload)
    assert reused and second['id'] == result['id'] and len(hq.boundary.calls) == 1


def test_concurrent_idempotency_and_changed_parameters_conflict(hq):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: hq.service.create_job(hq.payload), range(8)))
    assert len({row[0]['id'] for row in results}) == 1
    assert sum(not row[1] for row in results) == 1
    complete(hq, results[0][0]['id'])
    assert len(hq.boundary.calls) == 1
    changed = HQCreateRequest.model_validate({**hq.payload.model_dump(), 'parameters': {**hq.payload.parameters.model_dump(), 'seed': 99}})
    with pytest.raises(DreamApiError, match='幂等键') as error:
        hq.service.create_job(changed)
    assert error.value.status_code == 409


def test_shared_gpu_queue_expired_session_does_not_invalidate_copied_inputs(hq):
    release = threading.Event()
    first = hq.runner.submit_serial(lambda: release.wait(5))
    try:
        record, _ = hq.service.create_job(hq.payload)
        assert record['state'] == 'queued' and record['phase'] == 'queued'
        assert not hq.boundary.calls
        wait_until(lambda: len(hq.service.get_job(record['id'])['inputs']) == 3)
        atomic_json(hq.session_path, {'token': hq.r2.session, 'expiresAt': 1})
        hq.r2.denied = True
        call_count = len(hq.r2.calls)
        release.set()
        first.result(5)
        result = complete(hq, record['id'])
        assert result['state'] == 'succeeded' and len(hq.r2.calls) == call_count
        replay, reused = hq.service.create_job(hq.payload)
        assert reused and replay['id'] == record['id']
    finally:
        release.set()


def test_bad_input_hash_persists_failure_and_never_queues(hq):
    hq.r2.bad_hash = True
    created, _ = hq.service.create_job(hq.payload)
    record = complete(hq, created['id'])
    assert record['error']['code'] == 'HQ_HASH_MISMATCH'
    assert record['state'] == 'failed' and not hq.boundary.calls
    hq.r2.bad_hash = False
    replay, reused = hq.service.create_job(hq.payload)
    assert reused and replay['state'] == 'failed'


@pytest.mark.parametrize('change,code', [('bad_audit', 'HQ_AUDIT_INVALID'), ('bad_output_hash', 'HQ_HASH_MISMATCH')])
def test_output_requires_matching_three_input_audit_and_actual_hash(hq, change, code):
    setattr(hq.boundary, change, True)
    record, _ = hq.service.create_job(hq.payload)
    result = complete(hq, record['id'])
    assert result['state'] == 'failed' and result['error']['code'] == code
    with pytest.raises(DreamApiError):
        hq.service.image_path(record['id'])


def test_cancel_running_fences_late_output_without_deleting_artifacts(hq):
    hq.boundary.hold = hq.boundary.late_output = True
    record, _ = hq.service.create_job(hq.payload)
    assert hq.boundary.started.wait(5)
    cancelled = hq.service.cancel(record['id'])
    assert cancelled['state'] not in {'succeeded', 'failed'} and cancelled['cancellationRequested']
    result = complete(hq, record['id'])
    assert result['state'] == 'cancelled' and result['result'] is None
    assert (hq.root / 'jobs' / record['id'] / 'cancel.flag').is_file()
    assert (hq.root / 'jobs' / record['id'] / 'inputs' / 'person.jpg').is_file()
    assert not (hq.root / 'jobs' / record['id'] / 'result.png').exists()  # Only existing identity owns outputs.


def test_cancel_queued_job_never_spawns(hq):
    release = threading.Event()
    first = hq.runner.submit_serial(lambda: release.wait(5))
    try:
        record, _ = hq.service.create_job(hq.payload)
        assert hq.service.cancel(record['id'])['cancellationRequested']
        release.set()
        first.result(5)
        assert not hq.boundary.calls
    finally:
        release.set()


def test_oom_is_explicit_and_is_not_retried(hq):
    hq.boundary.error = 'VRAM_OOM'
    record, _ = hq.service.create_job(hq.payload)
    result = complete(hq, record['id'])
    assert result['error']['code'] == 'VRAM_OOM' and result['state'] == 'failed'
    assert result['audit']['error']['code'] == 'VRAM_OOM'
    assert len(hq.boundary.calls) == 1


def test_restart_reconciles_completed_child_without_regeneration_and_exclusive_storage(hq):
    record, _ = hq.service.create_job(hq.payload)
    complete(hq, record['id'])
    other = HQService(hq.config, hq.runner, client=hq.client, identity_service=hq.identity)
    with pytest.raises(DreamApiError) as error:
        other.start()
    assert error.value.code == 'HQ_STORAGE_BUSY'
    hq.service.close()
    path = hq.root / 'jobs' / record['id'] / 'record.json'
    saved = json.loads(path.read_text(encoding='utf-8'))
    saved.update(state='running', phase='infer_started')
    atomic_json(path, saved)
    try:
        other.start()
        recovered = other.get_job(record['id'])
        assert recovered['state'] == 'succeeded' and recovered['outputSha256']
        replay, reused = other.create_job(hq.payload)
        assert reused and replay['id'] == record['id'] and replay['state'] == 'succeeded'
        assert not (path.parent / 'result.png').exists()
    finally:
        other.close()


def test_shutdown_terminates_owned_child_and_preserves_failure(hq):
    hq.boundary.hold = True
    record, _ = hq.service.create_job(hq.payload)
    assert hq.boundary.started.wait(5)
    hq.service.close()
    saved = json.loads((hq.root / 'jobs' / record['id'] / 'record.json').read_text(encoding='utf-8'))
    assert saved['state'] == 'failed' and saved['error']['code'] == 'EXECUTOR_INTERRUPTED'
    assert not hq.identity.gpu_release_blocked


def test_get_timeout_retries_once_and_redirect_never_forwards_bearer(hq):
    hq.r2.timeouts = 1
    raw, info = hq.service.asset('person', hq.r2.ids['person'])
    assert sha(raw) == info['sha256']
    assert len(hq.r2.calls) == 2
    hq.r2.timeouts = 5
    before = len(hq.r2.calls)
    with pytest.raises(DreamApiError):
        hq.service.asset('person', hq.r2.ids['person'])
    assert len(hq.r2.calls) == before + 2
    hq.r2.timeouts = 0
    hq.r2.redirect = True
    with pytest.raises(DreamApiError) as error:
        hq.service.asset('person', hq.r2.ids['person'])
    assert error.value.code == 'HQ_UPSTREAM_REDIRECT'


def test_foreign_catalog_url_and_config_origin_fail_closed(hq):
    hq.r2.evil_url = 'https://evil.invalid/original.png'
    with pytest.raises(DreamApiError) as error:
        hq.service.asset('garment', 'G001')
    assert error.value.code == 'HQ_UPSTREAM_ORIGIN'
    settings = json.loads((hq.root / 'config.json').read_text())
    settings['origin'] = ORIGIN + '.evil.invalid'
    atomic_json(hq.root / 'config.json', settings)
    assert hq.service.status()['configured'] is False


def test_person_cache_is_bounded_and_invalidated_by_session_expiry(hq):
    first = hq.service.catalog('person')
    count = len(hq.r2.calls)
    assert first['total'] == 1 and first['items'][0]['id'] == hq.r2.ids['person']
    assert hq.service.catalog('person', q='PERSON')['total'] == 1
    assert len(hq.r2.calls) == count
    atomic_json(hq.session_path, {'token': hq.r2.session, 'expiresAt': 1})
    with pytest.raises(DreamApiError) as error:
        hq.service.catalog('person')
    assert error.value.code == 'HQ_AUTH_EXPIRED'


@pytest.mark.parametrize('value', [True, '42', 1.5, -1, 4294967296])
def test_strict_parameter_validation(hq, value):
    body = hq.payload.model_dump()
    body['parameters']['seed'] = value
    with pytest.raises(ValidationError):
        HQCreateRequest.model_validate(body)



def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('Condition did not become true')


def installed_profile(hq, *, defaults=None, different_person=False):
    """An already-recognized profile with the same normalized pixels, encoded as PNG."""
    hq.identity._ensure_recovered()
    reference_id, profile_id = 'ref-' + 'a' * 24, 'person-' + 'b' * 24
    path = hq.identity._asset(reference_id, '.png')
    path.parent.mkdir(parents=True, exist_ok=True)
    if different_person:
        path.write_bytes(png(color='green'))
    else:
        with Image.open(io.BytesIO(hq.r2.raw['person'])) as original:
            original.convert('RGB').save(path)
    atomic_json(hq.identity._asset(reference_id, '.json'), {'id': reference_id, 'name': 'Existing person',
        'referenceKind': 'faceid', 'faces': hq.boundary.faces})
    hq.identity.profiles._save({'id': profile_id, 'name': 'Existing person', 'referenceId': reference_id,
        'faceIndex': 0, 'referenceKind': 'faceid', 'state': 'ready', 'defaults': defaults or {},
        'error': None, 'createdAt': '2026-11-02T00:00:00Z'})
    return HQCreateRequest.model_validate({**hq.payload.model_dump(), 'profileId': profile_id})


def test_profile_reuses_identity_only_and_freezes_neutral_full_body_prompt(hq):
    payload = installed_profile(hq, defaults={'prompt': 'blue shirt portrait', 'negativePrompt': 'full body',
        'loraId': 'legacy-style-lora', 'modelId': 'realistic-vision-v5.1-faceid', 'seed': 100,
        'width': 768, 'height': 512, 'facePolish': True, 'faceRestoreStrength': 1.,
        'cfg': 6.5, 'identityStrength': .85, 'structureStrength': .2, 'faceLoraStrength': .7})
    created, _ = hq.service.create_job(payload)
    job = complete(hq, created['id'])
    assert job['state'] == 'succeeded', job['error']
    assert not hq.boundary.inspections
    request = hq.boundary.calls[0][2]
    assert 'full body fashion' in request['prompt'] and 'blue shirt' not in request['prompt']
    assert request['negativePrompt'] != 'full body' and request['loraId'] is None
    assert request['identityStrength'] == .85 and request['structureStrength'] == .2
    assert request['faceLoraStrength'] == .7 and request['cfg'] == 6.5
    assert request['width'] == request['height'] == 256 and request['seed'] == 42
    assert request['facePolish'] is False and request['faceRestoreStrength'] == .35
    assert job['profileId'] == payload.profileId and job['referenceId'] == request['referenceId']
    original = Path(request['hqConditioning']['inputs']['person']['path'])
    reference = Path(request['imagePath'])
    assert sha(original.read_bytes()) != sha(reference.read_bytes())
    assert hq_pixel_fingerprint(original) == hq_pixel_fingerprint(reference)


@pytest.mark.parametrize('different_person,defaults,code', [
    (True, {}, 'HQ_PERSON_MISMATCH'),
    (False, {'modelId': 'illustrious-xl-v2.0-faceid'}, 'HQ_PROFILE_MODEL_UNSUPPORTED'),
])
def test_incompatible_profile_never_changes_person_or_ports_sdxl(hq, different_person, defaults, code):
    payload = installed_profile(hq, defaults=defaults, different_person=different_person)
    created, _ = hq.service.create_job(payload)
    job = complete(hq, created['id'])
    assert job['state'] == 'failed' and job['error']['code'] == code
    assert not hq.boundary.inspections and not hq.boundary.calls


def test_ambiguous_import_is_not_silently_assigned_to_first_face(hq):
    hq.boundary.faces.append({'index': 1, 'box': [2., 2., 10., 18.]})
    created, _ = hq.service.create_job(hq.payload)
    job = complete(hq, created['id'])
    assert job['error']['code'] == 'HQ_PERSON_AMBIGUOUS'
    assert len(hq.boundary.inspections) == 1 and not hq.boundary.calls


def test_release_failure_holds_shared_queue_until_owned_tree_exit(hq):
    payload = installed_profile(hq)
    hq.boundary.hold = True
    created, _ = hq.service.create_job(payload)
    assert hq.boundary.started.wait(5)
    hq.boundary.release_allowed.clear()
    hq.boundary.release.set()
    assert hq.boundary.release_blocked.wait(5)
    # The launcher has already returned; the owned child's lifetime still fails exit verification.
    later = [hq.runner.submit_serial(lambda name=name: name) for name in ('identity', 'native', 'hq')]
    try:
        time.sleep(.3)
        assert hq.identity.gpu_release_blocked
        assert all(not task.done() for task in later)
        assert not hq.identity._futures[created['identityJobId']].done()
        assert hq.service.status()['gpuReleaseBlocked']
        hq.boundary.release_allowed.set()
        assert [task.result(5) for task in later] == ['identity', 'native', 'hq']
        assert complete(hq, created['id'])['state'] == 'succeeded'
        assert not hq.identity.gpu_release_blocked
    finally:
        hq.boundary.release_allowed.set()


@pytest.mark.parametrize('interrupted', [False, True])
def test_submit_hq_first_call_after_restart_recovers_prior_child_before_dispatch(hq, interrupted):
    created, _ = hq.service.create_job(hq.payload)
    result = complete(hq, created['id'])
    child = hq.identity.get(result['identityJobId'])
    config_path = hq.identity.config_path
    hq.service.close()
    hq.identity.close()
    if interrupted:
        child.update(state='sampling', result=None)
        atomic_json(hq.identity._job_path(child['id']), child)
    restarted = IdentityService(hq.config, hq.runner)
    restarted.config_path = config_path
    try:
        assert not restarted._recovered
        replay = restarted.submit_hq(hq_job_id=created['id'], request_digest=child['hqBinding']['requestDigest'],
            request=IdentityGenerateRequest.model_validate(child['request']), conditioning=child['hqConditioning'])
        assert restarted._recovered and replay['id'] == child['id']
        assert replay['state'] == ('failed' if interrupted else 'complete')
        if interrupted:
            assert replay['errorCode'] == 'EXECUTOR_INTERRUPTED'
        assert not restarted._futures and len(hq.boundary.calls) == 1
        if interrupted:
            assert Path(hq.boundary.calls[0][2]['outputPath']).exists()
        else:
            assert Path(replay['result']['metadata']['output']).exists()
        changed = {**child['request'], 'steps': 3}
        with pytest.raises(DreamApiError) as error:
            restarted.submit_hq(hq_job_id=created['id'], request_digest=child['hqBinding']['requestDigest'],
                request=IdentityGenerateRequest.model_validate(changed), conditioning=child['hqConditioning'])
        assert error.value.code == 'IDEMPOTENCY_CONFLICT'
    finally:
        restarted.close()


def test_optional_polish_uses_existing_original_and_refinement_history(hq):
    payload = HQCreateRequest.model_validate({**hq.payload.model_dump(), 'facePolish': True, 'faceRestoreStrength': .35})
    created, _ = hq.service.create_job(payload)
    job = complete(hq, created['id'])
    assert job['state'] == 'succeeded', job['error']
    assert job['facePolish'] is True
    assert job['result']['metadata']['facePolish']['originalImageUrl'].startswith('/api/identity/jobs/')
    assert job['identityResult'] == hq.identity.get(job['identityJobId'])['result']
    assert hq.identity.original_image(job['identityJobId']).exists()
    workspace = hq.identity.refinement_operation('workspace', job['identityJobId'])
    assert workspace['selectedVersionId'] == 'result'
    assert any(row['id'] == 'original' for row in workspace['versions'])
    assert not (hq.root / 'jobs' / job['id'] / 'result.png').exists()


def test_corrupt_persisted_child_is_never_overwritten_or_redispatched(hq):
    created, _ = hq.service.create_job(hq.payload)
    result = complete(hq, created['id'])
    child = hq.identity.get(result['identityJobId'])
    config_path = hq.identity.config_path
    hq.service.close()
    hq.identity.close()
    journal = hq.identity._job_path(child['id'])
    journal.write_text('{broken prior attempt', encoding='utf-8')
    restarted = IdentityService(hq.config, hq.runner)
    restarted.config_path = config_path
    try:
        with pytest.raises(DreamApiError) as error:
            restarted.submit_hq(hq_job_id=created['id'], request_digest=child['hqBinding']['requestDigest'],
                request=IdentityGenerateRequest.model_validate(child['request']), conditioning=child['hqConditioning'])
        assert error.value.code == 'HQ_CHILD_RECORD_INVALID'
        assert journal.read_text() == '{broken prior attempt'
        assert not restarted._futures and len(hq.boundary.calls) == 1
    finally:
        restarted.close()


def test_hq_refinement_reuses_existing_version_storage_and_delete_transaction(hq):
    from identity_refinements import RefinementRequest, VersionSelection
    created, _ = hq.service.create_job(hq.payload)
    job = complete(hq, created['id'])
    output, _ = hq.service.image_path(job['id'])
    before = output.read_bytes()
    settings = json.loads(hq.identity.config_path.read_text())
    settings['persistentWorker'] = False  # Exercise the existing file CLI boundary for the version too.
    atomic_json(hq.identity.config_path, settings)
    version = hq.identity.refinement_operation('submit', RefinementRequest(sourceJobId=job['identityJobId'], strength=.35))
    hq.identity._background[version['id']][0].result(5)
    workspace = hq.identity.refinement_operation('workspace', job['identityJobId'])
    version = next(row for row in workspace['versions'] if row['id'] == version['id'])
    assert version['state'] == 'complete', version
    assert len(hq.boundary.refinements) == 1 and not hq.boundary.refinements[0][2].get('hqConditioning')
    selected = hq.identity.refinement_operation('select', job['identityJobId'], VersionSelection(versionId=version['id']))
    assert selected['selectedVersionId'] == version['id']
    assert output.read_bytes() == before
    assert hq.service.get_job(job['id'])['refinementsAvailable']
    hq.identity.delete_history(job['identityJobId'])
    with pytest.raises(DreamApiError) as error:
        hq.identity.refinement_operation('image', version['id'])
    assert error.value.status_code == 404
    with pytest.raises(DreamApiError):
        hq.service.image_path(job['id'])


def test_public_identity_request_cannot_accept_internal_conditioning_paths(hq):
    payload = installed_profile(hq)
    with pytest.raises(ValidationError):
        IdentityGenerateRequest.model_validate({'referenceId': 'ref-' + 'a' * 24, 'faceIndex': 0,
            'prompt': 'full body', 'hqConditioning': {'configPath': 'E:/private.json'}})


@pytest.mark.parametrize('field,value', [('facePolish', True), ('faceRestoreStrength', .5), ('profileId', 'person-' + 'c' * 24)])
def test_changed_identity_options_with_same_key_are_conflicts(hq, field, value):
    created, _ = hq.service.create_job(hq.payload)
    complete(hq, created['id'])
    changed = HQCreateRequest.model_validate({**hq.payload.model_dump(), field: value})
    with pytest.raises(DreamApiError) as error:
        hq.service.create_job(changed)
    assert error.value.code == 'IDEMPOTENCY_CONFLICT'
    assert len(hq.boundary.calls) == 1


@pytest.mark.parametrize('reason', ['audit', 'hash', 'cancel'])
def test_rejected_or_cancelled_worker_artifacts_never_become_runtime_history(hq, reason):
    from runtime import DreamRuntime
    if reason == 'audit':
        hq.boundary.bad_audit = True
    elif reason == 'hash':
        hq.boundary.bad_output_hash = True
    else:
        hq.boundary.hold = hq.boundary.late_output = True
    created, _ = hq.service.create_job(hq.payload)
    if reason == 'cancel':
        assert hq.boundary.started.wait(5)
        hq.service.cancel(created['id'])
    result = complete(hq, created['id'])
    assert result['state'] == ('cancelled' if reason == 'cancel' else 'failed')
    folder = hq.root / 'jobs' / created['id'] / 'unpublished'
    assert (folder / (created['identityJobId'] + '.png')).is_file()
    assert (folder / (created['identityJobId'] + '.json')).is_file()
    assert not list((hq.config.dream_root / 'outputs').glob('*/' + created['identityJobId'] + '.*'))
    runtime = DreamRuntime(hq.config, job_runner=hq.runner)
    assert runtime.history({})['total'] == 0
    with pytest.raises(DreamApiError) as error:
        runtime.history_image(created['identityJobId'])
    assert error.value.status_code == 404


def test_cancel_remains_pending_until_owned_child_release_is_verified(hq):
    hq.boundary.hold = hq.boundary.late_output = True
    created, _ = hq.service.create_job(installed_profile(hq))
    assert hq.boundary.started.wait(5)
    hq.boundary.release_allowed.clear()
    receipt = hq.service.cancel(created['id'])
    try:
        assert receipt['cancellationRequested'] and receipt['state'] in {'queued', 'running'}
        assert receipt['phase'] == 'cancelling'
        assert hq.boundary.release_blocked.wait(5)
        during = hq.service.get_job(created['id'])
        assert during['state'] in {'queued', 'running'} and during['phase'] == 'cancelling'
        assert not hq.service._futures[created['id']].done()
        later = hq.runner.submit_serial(lambda: 'native-next')
        assert not later.done()
        hq.boundary.release_allowed.set()
        assert complete(hq, created['id'])['state'] == 'cancelled'
        assert later.result(5) == 'native-next'
    finally:
        hq.boundary.release_allowed.set()


def test_public_history_metadata_appears_only_after_complete_identity_ledger(hq, monkeypatch):
    import identity_service as identity_module
    from runtime import DreamRuntime
    runtime = DreamRuntime(hq.config, job_runner=hq.runner)
    real_replace = identity_module.os.replace
    observed = []
    def replace(source, target):
        target = Path(target)
        if target.suffix == '.json' and target.parent.parent == hq.config.dream_root / 'outputs':
            child = hq.identity.get(target.stem)
            assert child['state'] == 'complete'
            assert runtime.history({})['total'] == 0
            observed.append(child['id'])
        return real_replace(source, target)
    monkeypatch.setattr(identity_module.os, 'replace', replace)
    created, _ = hq.service.create_job(hq.payload)
    result = complete(hq, created['id'])
    assert result['state'] == 'succeeded' and observed == [created['identityJobId']]
    assert runtime.history({})['items'][0]['id'] == created['identityJobId']


@pytest.mark.parametrize('deleted', [False, True])
def test_cold_restart_recovers_completed_child_even_if_hq_receipt_was_not_mirrored(hq, deleted):
    created, _ = hq.service.create_job(hq.payload)
    completed = complete(hq, created['id'])
    if deleted:
        hq.identity.delete_history(created['identityJobId'])
    config_path = hq.identity.config_path
    hq.service.close()
    hq.identity.close()
    if not deleted:
        # Crash after the complete child ledger, before the final scanner sidecar rename.
        Path(completed['identityResult']['metadata']['output']).with_suffix('.json').unlink()
    journal = hq.root / 'jobs' / created['id'] / 'record.json'
    record = json.loads(journal.read_text(encoding='utf-8'))
    record.update(state='running', phase='sampling', result=None, output=None, identityResult=None)
    atomic_json(journal, record)
    identity = IdentityService(hq.config, hq.runner)
    identity.config_path = config_path
    service = HQService(hq.config, hq.runner, identity_service=identity, client=hq.client)
    try:
        recovered = service.get_job(created['id'])
        assert recovered['state'] == 'succeeded'
        if deleted:
            assert recovered['historyDeleted'] and recovered['resultDeleted'] and recovered['result'] is None
        else:
            assert recovered['outputSha256']
            from runtime import DreamRuntime
            assert DreamRuntime(hq.config, job_runner=hq.runner).history({})['total'] == 1
        assert not identity._futures and len(hq.boundary.calls) == 1
        replay, reused = service.create_job(hq.payload)
        assert reused and replay['state'] == 'succeeded'
    finally:
        service.close()
        identity.close()


def test_legacy_standalone_key_cannot_alias_new_identity_execution_basis(hq):
    legacy_id = 'hq-' + sha(('local-hq-v1\0' + hq.payload.idempotencyKey).encode())
    atomic_json(hq.root / 'jobs' / legacy_id / 'record.json', {'id': legacy_id, 'requestDigest': 'f' * 64,
        'state': 'succeeded', 'idempotencyKey': hq.payload.idempotencyKey, 'createdAt': '2026-11-01',
        'audit': {'pipeline': 'standalone-prototype'}, 'inputs': [], 'result': None})
    created, reused = hq.service.create_job(hq.payload)
    assert not reused and created['id'] != legacy_id
    assert created['pipeline'] == 'identity-session-hq-sd15-v1'
    assert hq.service.get_job(legacy_id)['pipeline'] == 'standalone-prototype'
    assert complete(hq, created['id'])['state'] == 'succeeded'


def test_startup_quarantines_old_interrupted_child_even_when_hq_record_is_terminal(hq):
    from runtime import DreamRuntime
    created, _ = hq.service.create_job(hq.payload)
    complete(hq, created['id'])
    child = hq.identity.get(created['identityJobId'])
    original_output = Path(child['result']['metadata']['output'])
    config_path = hq.identity.config_path
    hq.service.close()
    hq.identity.close()
    child.update(state='sampling', result=None)
    atomic_json(hq.identity._job_path(child['id']), child)
    journal = hq.root / 'jobs' / created['id'] / 'record.json'
    record = json.loads(journal.read_text(encoding='utf-8'))
    record.update(state='failed', result=None, identityResult=None)
    atomic_json(journal, record)
    identity = IdentityService(hq.config, hq.runner)
    identity.config_path = config_path
    service = HQService(hq.config, hq.runner, identity_service=identity, client=hq.client)
    try:
        service.start()
        assert identity.get(child['id'])['errorCode'] == 'EXECUTOR_INTERRUPTED'
        assert not original_output.exists() and not original_output.with_suffix('.json').exists()
        folder = hq.root / 'jobs' / created['id'] / 'unpublished'
        assert (folder / (child['id'] + '.png')).is_file()
        assert (folder / (child['id'] + '.json')).is_file()
        assert DreamRuntime(hq.config, job_runner=hq.runner).history({})['total'] == 0
        assert len(hq.boundary.calls) == 1 and not identity._futures
    finally:
        service.close()
        identity.close()
