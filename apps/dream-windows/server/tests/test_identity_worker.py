import json
import subprocess
import sys
from pathlib import Path

import pytest


def test_contract_rejects_invalid_strength_and_faces():
    from identity_contract import IdentityGenerateRequest
    request = IdentityGenerateRequest(referenceId='ref-' + 'a' * 24, faceIndex=0, prompt='portrait', seed=42)
    assert (request.width, request.height, request.steps, request.seed) == (512, 768, 28, 42)
    for change in ({'faceIndex': -1}, {'identityStrength': float('nan')}, {'cfg': float('inf')}, {'width': 257}, {'width': 2048}, {'prompt': ' '}, {'referenceId': '../bad'}):
        with pytest.raises(ValueError):
            IdentityGenerateRequest(**({'referenceId': 'ref-' + 'a' * 24, 'faceIndex': 0, 'prompt': 'portrait'} | change))


def test_worker_missing_config_has_structured_failure(tmp_path):
    worker = Path(__file__).resolve().parents[1] / 'identity_worker.py'
    request, result = tmp_path / 'request.json', tmp_path / 'result.json'
    request.write_text(json.dumps({'configPath': str(tmp_path / 'missing.json')}))
    completed = subprocess.run([sys.executable, str(worker), '--operation', 'status', '--request', str(request), '--result', str(result)], capture_output=True, text=True, encoding='utf-8')
    assert result.exists(), completed.stderr
    body = json.loads(result.read_text(encoding='utf-8'))
    assert body['ready'] is False
    assert '配置' in body['message']


def test_worker_does_not_leak_exception_paths(tmp_path):
    worker = Path(__file__).resolve().parents[1] / 'identity_worker.py'
    request, result = tmp_path / 'request.json', tmp_path / 'result.json'
    request.write_text('{}')
    run = subprocess.run([sys.executable, str(worker), '--operation', 'inspect', '--request', str(request), '--result', str(result)], capture_output=True, text=True, encoding='utf-8')
    assert run.returncode != 0
    assert result.exists(), run.stderr
    body = json.loads(result.read_text(encoding='utf-8'))
    assert body['ok'] is False and body['code'] == 'IDENTITY_WORKER_FAILED'


def test_select_face_is_sorted_and_checks_range():
    from identity_pipeline import select_face
    faces = [{'bbox': [30, 0, 40, 20]}, {'bbox': [1, 0, 11, 20]}]
    assert select_face(faces, 0)['bbox'][0] == 1
    with pytest.raises(ValueError, match='人脸'):
        select_face(faces, 2)
    with pytest.raises(ValueError, match='人脸'):
        select_face([], 0)


def test_cuda_required_no_fallback():
    from identity_pipeline import require_cuda
    with pytest.raises(RuntimeError, match='CUDA'):
        require_cuda(False, 0, 0)
    with pytest.raises(RuntimeError, match='显存'):
        require_cuda(True, 512 * 1024**2, 6 * 1024**3)
    require_cuda(True, 5 * 1024**3, 6 * 1024**3)


def test_companion_lora_uses_explicit_offline_filename(tmp_path):
    from identity_pipeline import load_companion_lora
    class Pipeline:
        def load_lora_weights(self, folder, **kwargs):
            assert folder == str(tmp_path)
            assert kwargs == {'weight_name': 'face.safetensors', 'local_files_only': True, 'adapter_name': 'identity'}
            return 'loaded'
    assert load_companion_lora(Pipeline(), tmp_path / 'face.safetensors') == 'loaded'


def test_reference_face_boxes_are_clipped_without_renumbering():
    from identity_pipeline import reference_boxes
    class Face:
        def __init__(self, box):
            self.bbox = box
    assert reference_boxes([Face([-2, -3, 30, 40]), Face([90, 1, 110, 20])], 100, 80) == [
        {'index': 0, 'box': [0, 0, 30, 40]}, {'index': 1, 'box': [90, 1, 100, 20]}]


def test_registered_loras_reject_architecture_and_path_escape(tmp_path):
    from identity_pipeline import registered_loras
    folder = tmp_path / 'loras'
    folder.mkdir()
    (tmp_path / 'outside.safetensors').write_bytes(b'asset')
    (folder / 'good.safetensors').write_bytes(b'asset')
    for name, architecture, filename in [('ok', 'SD1.5', 'good.safetensors'), ('xl', 'SDXL', 'good.safetensors'), ('escape', 'SD1.5', '../outside.safetensors')]:
        (folder / (name + '.json')).write_text(json.dumps({'architecture': architecture, 'file': filename}))
    assert [item['id'] for item in registered_loras({'lorasDir': str(folder)})] == ['ok']


def test_preflight_requires_local_face_models(tmp_path):
    from identity_worker import load_config
    asset = tmp_path / 'weight'
    asset.write_bytes(b'asset')
    config = {key: str(asset) for key in ('checkpoint', 'adapter', 'faceLora', 'clipVision')}
    config.update(pipelineConfig=str(tmp_path), insightfaceRoot=str(tmp_path / 'missing'))
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match='InsightFace'):
        load_config({'configPath': str(path)})


def test_worker_preflight_reports_missing_dependency():
    from identity_worker import require_dependencies
    with pytest.raises(ValueError, match='diffusers'):
        require_dependencies(lambda name: None if name == 'diffusers' else object())
