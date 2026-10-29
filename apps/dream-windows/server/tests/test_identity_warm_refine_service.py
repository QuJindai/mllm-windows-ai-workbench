"""Service routing/ownership with real transport and CPU-only child processes."""
import json
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from job_runner import JobRunner, NativeRunResult
from models import GenerateRequest
from test_generation_jobs import make_config


CPU_WORKER = '''import sys,json,pathlib,os,time
print(json.dumps({"type":"worker_ready","protocol":1,"pid":os.getpid()}),flush=True)
completed=0
for line in sys.stdin:
    message=json.loads(line)
    assert message["op"]==os.environ["EXPECTED_OPERATION"]
    payload=message["payload"]
    if payload.get("waitMarker"):
        pathlib.Path(payload["waitMarker"]).write_text("running")
        time.sleep(30)
    result={"ok":True,"sessionReused":completed>0,"operation":message["op"]}
    if message["op"]=="batch":
        result["items"]=[]
        for item in payload["items"]:
            for key in ("outputPath","metadataPath"):
                path=pathlib.Path(item[key]);path.parent.mkdir(parents=True,exist_ok=True);path.write_text("{}")
            result["items"].append({"jobId":item["jobId"],"metadata":{}})
    completed+=1
    print(json.dumps({"id":message["id"],"ok":True,"result":result}),flush=True)
'''


@pytest.fixture
def service_case(tmp_path, monkeypatch):
    import identity_service
    from identity_persistent_worker import PersistentWorkerClient
    config = make_config(tmp_path)
    settings = config.dream_root / 'data/identity/runtime.json'
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({'python': sys.executable, 'persistentWorker': True}), encoding='utf-8')
    monkeypatch.setenv('DREAM_IDENTITY_CONFIG', str(settings))
    clients, commands, children = [], [], []
    def factory(command, **kwargs):
        assert '--ownership-handshake' in command and kwargs['ownership_handshake'] is True
        assert all(client.process is None or client.process.poll() is not None for client in clients), 'two warm children overlap'
        family = 'refine' if Path(command[1]).name == 'identity_warm_refine.py' else 'batch'
        kwargs['env'] = {**kwargs['env'], 'EXPECTED_OPERATION': family}
        client = PersistentWorkerClient([sys.executable, '-u', '-c', CPU_WORKER], **kwargs)
        clients.append(client)
        commands.append(family)
        return client
    monkeypatch.setattr(identity_service, 'PersistentWorkerClient', factory)
    def native(command, env, cwd, stdout_log, stderr_log):
        assert all(child.poll() is not None for child in children)
        Path(command[command.index('--output') + 1]).write_bytes(b'png')
        Path(command[command.index('--metadata') + 1]).write_text('{}')
        return NativeRunResult(0, '', '')
    runner = JobRunner(config, command_runner=native)
    service = identity_service.IdentityService(config, runner)
    def payload(index=0):
        return {'modelId': 'realistic-vision-v5.1-faceid', 'referenceId': 'ref-'+'a'*24, 'faceIndex': 0,
                'sourcePath': str(tmp_path / 'source.png'), 'imagePath': str(tmp_path / 'reference.png'),
                'jobId': 'identity-'+f'{index:024x}', 'outputPath': str(tmp_path / f'edit-{index}.png'),
                'editSettings': {'mode': 'restore', 'strength': .3, 'prompt': '', 'negativePrompt': '', 'seed': 42},
                'dreamRoot': str(config.dream_root), 'configPath': str(settings)}
    def batch(index=0):
        item = payload(index)
        item['metadataPath'] = str(tmp_path / f'batch-{index}.json')
        return {'items': [item], 'dreamRoot': str(config.dream_root), 'configPath': str(settings)}
    try:
        yield SimpleNamespace(service=service, runner=runner, payload=payload, batch=batch, settings=settings,
                              clients=clients, commands=commands, children=children)
    finally:
        service.close()
        runner._executor.shutdown(wait=True, cancel_futures=True)


def test_service_reuses_restore_child_but_never_crosses_batch_family(service_case):
    c = service_case
    first = c.runner.submit_serial(c.service._worker, 'refine', c.payload()).result(8)
    child = c.service._persistent_worker.process
    c.children.append(child)
    second = c.runner.submit_serial(c.service._worker, 'refine', c.payload(1)).result(8)
    assert first['sessionReused'] is False and second['sessionReused'] is True
    assert c.service._persistent_worker.process is child and not c.service._worker_events
    assert c.runner.submit_serial(c.service._worker, 'batch', c.batch(2)).result(8)['operation'] == 'batch'
    assert child.poll() is not None
    batch_child = c.service._persistent_worker.process
    c.children.append(batch_child)
    result = c.runner.submit_serial(c.service._worker, 'refine', c.payload(3)).result(8)
    assert batch_child.poll() is not None and result['sessionReused'] is False
    assert c.commands == ['refine', 'batch', 'refine']
    c.children.append(c.service._persistent_worker.process)
    job = c.runner.submit(GenerateRequest(modelId='model', prompt='lake', seed=42, traceLevel='off'))
    c.runner.submit_serial(lambda: None).result(8)
    assert c.runner.get(job['id'])['state'] == 'complete'
    assert all(child.poll() is not None for child in c.children)


def test_refine_cancel_uses_worker_events_and_reaps_owned_process(service_case, tmp_path):
    from identity_service import WorkerCancelled
    c, cancelled = service_case, threading.Event()
    marker = tmp_path / 'started'
    payload = {**c.payload(), 'waitMarker': str(marker)}
    future = c.runner.submit_serial(c.service._worker, 'refine', payload, cancelled)
    deadline = time.monotonic() + 8
    while not marker.exists() and time.monotonic() < deadline:
        if future.done():
            future.result()
        time.sleep(.02)
    assert marker.exists() and cancelled in c.service._worker_events
    child = c.service._persistent_worker.process
    cancelled.set()
    with pytest.raises(WorkerCancelled):
        future.result(8)
    assert child.poll() is not None and not c.service._worker_events


def test_family_switch_fails_closed_when_previous_owner_cannot_release(service_case, monkeypatch):
    from errors import DreamApiError
    c = service_case
    c.runner.submit_serial(c.service._worker, 'batch', c.batch()).result(8)
    owner = c.service._persistent_worker
    with monkeypatch.context() as patch:
        patch.setattr(owner, 'close', lambda: (_ for _ in ()).throw(RuntimeError('release failed')))
        with pytest.raises(DreamApiError, match='release failed'):
            c.runner.submit_serial(c.service._worker, 'refine', c.payload(1)).result(8)
        assert c.service._persistent_worker is owner and c.commands == ['batch']
        assert owner.process.poll() is None and not c.service._worker_events


@pytest.mark.parametrize('kind', ['visual', 'anime', 'edge-lighting', 'disabled'])
def test_ineligible_or_disabled_refine_releases_warm_child_and_uses_one_shot(service_case, monkeypatch, kind):
    import identity_service
    c = service_case
    initial_operation = 'refine' if kind == 'edge-lighting' else 'batch'
    initial_payload = c.payload() if initial_operation == 'refine' else c.batch()
    c.runner.submit_serial(c.service._worker, initial_operation, initial_payload).result(8)
    child = c.service._persistent_worker.process
    payload = c.payload(1)
    if kind == 'visual':
        payload['modelId'] = 'cyberrealistic-xl-plus-face'
        payload['editSettings']['mode'] = 'redraw'
    elif kind == 'anime':
        payload.update(modelId='illustrious-xl-v2.0-faceid', animeProfileId='anime-'+'b'*24)
    elif kind == 'edge-lighting':
        payload['editSettings']['mode'] = 'edge-lighting'
    else:
        c.settings.write_text(json.dumps({'python': sys.executable, 'persistentWorker': False}), encoding='utf-8')
    def one_shot(command, **kwargs):
        assert child.poll() is not None and command[command.index('--operation') + 1] == 'refine'
        Path(command[command.index('--result') + 1]).write_text('{"ok":true,"oneShot":true}')
        return SimpleNamespace(returncode=0, poll=lambda: 0, communicate=lambda **kw: ('', ''), wait=lambda **kw: 0)
    monkeypatch.setattr(identity_service.subprocess, 'Popen', one_shot)
    monkeypatch.setattr(identity_service, 'WorkerLifetime', lambda process: SimpleNamespace(close=lambda: None))
    assert c.runner.submit_serial(c.service._worker, 'refine', payload).result(8)['oneShot'] is True
    assert c.commands == [initial_operation] and c.service._persistent_worker is None and not c.service._worker_events
