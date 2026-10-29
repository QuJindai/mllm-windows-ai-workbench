"""Restore reuse through real CPU image publication and bounded transport."""
import copy
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest


def adapter():
    return importlib.import_module('identity_warm_refine')


@pytest.fixture
def case(tmp_path, monkeypatch):
    import identity_pipeline
    from types import SimpleNamespace
    calls = []
    monkeypatch.setattr(identity_pipeline, 'configure_cuda', lambda: calls.append('cuda'))
    monkeypatch.setattr(identity_pipeline, 'IdentitySession', lambda *a: pytest.fail('generation session loaded'))
    config = {}
    for key in ('faceSwapModel', 'faceRestoreModel'):
        path = tmp_path / key
        path.write_bytes(b'weight-one')
        config[key] = str(path)
    for key, relative in [('faceDetectionRoot', 'detection_Resnet50_Final.pth'),
                          ('faceDetectionRoot', 'parsing_parsenet.pth'),
                          ('insightfaceRoot', 'models/buffalo_l/det_10g.onnx'),
                          ('insightfaceRoot', 'models/buffalo_l/w600k_r50.onnx')]:
        root = tmp_path / key
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'weight-one')
        config[key] = str(root)
    source, reference = tmp_path / 'source.png', tmp_path / 'reference.png'
    Image.new('RGB', (256, 256), (20, 40, 60)).save(source)
    Image.new('RGB', (256, 256), (60, 40, 20)).save(reference)
    def payload(index=0, **changes):
        return dict(modelId='realistic-vision-v5.1-faceid', referenceId='ref-' + 'a'*24, faceIndex=0,
                    prompt='original scene', negativePrompt='', seed=12, width=256, height=256,
                    sourcePath=str(source), outputPath=str(tmp_path / f'edit-{index}.png'),
                    imagePath=str(reference), dreamRoot=str(tmp_path), jobId='identity-' + f'{index:024x}',
                    editSettings=dict(mode='restore', strength=.3, seed=42, prompt='', negativePrompt=''), **changes)
    control = {'fail': False}
    class Processor:
        def __init__(self, selected_config, item):
            calls.append(('load', item['referenceId'], item['faceIndex']))
        def apply(self, image, item, strength, stage):
            calls.append(('apply', item['jobId'], strength))
            if control['fail']:
                raise RuntimeError('restore failed')
            result = image.copy()
            result.putpixel((10, 12), (200, 40, 60))
            return result, {'method': 'cpu-boundary'}
    return SimpleNamespace(config=config, payload=payload, calls=calls, factory=Processor, control=control)


def test_second_restore_reuses_only_processor_and_reports_current_timings(case):
    worker = adapter().WarmRestoreWorker(lambda request: case.config, processor_factory=case.factory)
    first_request, second_request = case.payload(), case.payload(1)
    second_request['editSettings'].update(strength=.5, seed=77, prompt='new edit')
    original = copy.deepcopy(second_request)
    first = worker.run_refine(first_request)
    second = worker.run_refine(second_request)
    assert first['processorReused'] is False and second['processorReused'] is True
    assert first['sessionReused'] is False and second['sessionReused'] is True
    assert len([row for row in case.calls if isinstance(row, tuple) and row[0] == 'load']) == 1
    assert case.calls.count('cuda') == 2  # each operation still performs admission/reset
    assert case.calls[-1] == ('apply', second_request['jobId'], .5)
    assert second_request == original
    assert second['diagnostics']['retention']['whole']['changedPixels'] == 1
    assert second['phasesMs']['compatibility'] >= 0
    assert sum(second['phasesMs'].values()) <= second['durationMs'] + 1
    assert Path(first_request['outputPath']).read_bytes() == Path(second_request['outputPath']).read_bytes()
    worker.close()
    assert worker.processor is None
    with pytest.raises(RuntimeError, match='closed'):
        worker.run_refine(case.payload(2))


@pytest.mark.parametrize('change', ['faceIndex', 'referenceBytes', 'modelBytes', 'config', 'limit'])
def test_incompatible_restore_exits_before_work_and_never_loads_a_second_processor(case, change, monkeypatch):
    from identity_persistent_worker import WorkerRestartRequired
    module = adapter()
    worker = module.WarmRestoreWorker(lambda request: case.config, processor_factory=case.factory)
    worker.run_refine(case.payload())
    next_request = case.payload(1)
    if change == 'faceIndex':
        next_request['faceIndex'] = 1
    elif change == 'referenceBytes':
        path = Path(next_request['imagePath'])
        before = path.stat()
        content = bytearray(path.read_bytes())
        content[-1] ^= 1  # the content hash must invalidate before decode
        path.write_bytes(content)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    elif change == 'modelBytes':
        path = Path(case.config['faceRestoreModel'])
        before = path.stat()
        path.write_bytes(b'weight-two')
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    elif change == 'config':
        case.config['newSetting'] = True
    else:
        monkeypatch.setattr(module, 'MAX_RESTORES', 1)
    with pytest.raises(WorkerRestartRequired):
        worker.run_refine(next_request)
    assert worker.closed and worker.processor is None
    assert len([row for row in case.calls if isinstance(row, tuple) and row[0] == 'load']) == 1
    assert not Path(next_request['outputPath']).exists()


@pytest.mark.parametrize('updates', [
    {'modelId': 'cyberrealistic-xl-plus-face'},
    {'modelId': 'illustrious-xl-v2.0-faceid', 'animeProfileId': 'anime-' + 'b'*24},
    {'modelId': 'unknown'}, {'editSettings': {'mode': 'redraw'}}, {'editSettings': {'mode': 'edge-lighting'}},
])
def test_only_plain_faceid_restore_is_eligible_and_unsupported_requests_never_start(case, updates):
    module = adapter()
    payload = {**case.payload(), **updates}
    assert module.is_restore_only(payload) is False
    worker = module.WarmRestoreWorker(lambda request: case.config, processor_factory=case.factory)
    with pytest.raises(ValueError):
        worker.run_refine(payload)
    assert not case.calls and worker.closed


def test_restore_failure_invalidates_cached_processor_and_preserves_prior_output(case):
    worker = adapter().WarmRestoreWorker(lambda request: case.config, processor_factory=case.factory)
    worker.run_refine(case.payload())
    saved = Path(case.payload()['outputPath']).read_bytes()
    case.control['fail'] = True
    with pytest.raises(RuntimeError, match='restore failed'):
        worker.run_refine(case.payload(1))
    assert worker.closed and worker.processor is None
    assert Path(case.payload()['outputPath']).read_bytes() == saved
    assert not Path(case.payload(1)['outputPath']).exists()


def test_restore_key_does_not_scan_unused_generation_weights(case, monkeypatch):
    case.config['checkpoint'] = 'unused-do-not-read.safetensors'
    module = adapter()
    original = module._asset
    def check(path):
        assert 'unused-do-not-read' not in str(path)
        return original(path)
    monkeypatch.setattr(module, '_asset', check)
    worker = module.WarmRestoreWorker(lambda request: case.config, processor_factory=case.factory)
    assert worker.run_refine(case.payload())['ok'] is True


def test_restore_protocol_dispatches_two_edits_and_rejects_batch(case):
    from identity_persistent_worker import serve
    worker = adapter().WarmRestoreWorker(lambda request: case.config, processor_factory=case.factory)
    commands = [{'id': str(i), 'op': 'refine', 'payload': case.payload(i)} for i in range(2)]
    commands.append({'id': 'wrong', 'op': 'batch', 'payload': {}})
    source = io.BytesIO(b''.join(json.dumps(row).encode() + b'\n' for row in commands))
    target = io.BytesIO()
    assert serve(worker, source, target, operation='refine') == 1
    replies = [json.loads(line) for line in target.getvalue().splitlines()]
    assert [row['ok'] for row in replies] == [True, True, False]
    assert replies[1]['result']['processorReused'] is True
    assert worker.closed


def test_generic_client_uses_existing_owned_process_and_refine_operation(tmp_path):
    from identity_persistent_worker import PersistentWorkerClient
    child = tmp_path / 'child.py'
    child.write_text('import json,sys\nfor line in sys.stdin.buffer:\n m=json.loads(line)\n print(json.dumps({"id":m["id"],"ok":True,"result":{"ok":True,"operation":m["op"]}}),flush=True)\n', encoding='utf-8')
    class Lifetime:
        def __init__(self, process): self.process = process
        def close(self): pass
    client = PersistentWorkerClient([sys.executable, str(child)], cwd=tmp_path, env=os.environ.copy(), lifetime_factory=Lifetime)
    try:
        assert client.run_operation('refine', {}, timeout=5)['operation'] == 'refine'
        child_process = client.process
        assert client.run_operation('refine', {}, timeout=5)['operation'] == 'refine'
        assert client.process is child_process
        with pytest.raises(ValueError, match='operation'):
            client.run_operation('unsupported', {}, timeout=5)
    finally:
        client.close()
    assert child_process.poll() is not None


def test_restore_adapter_cli_exits_idle_without_loading_inference(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'identity_warm_refine.py'
    process = subprocess.Popen([sys.executable, str(script), '--idle-ttl', '.1', '--ownership-handshake'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert process.wait(timeout=5) == 0, process.stderr.read().decode('utf-8', errors='replace')
        ready = json.loads(process.stdout.read())
        assert ready['type'] == 'worker_ready' and ready['protocol'] == 1
        assert ready['pid'] == process.pid
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
