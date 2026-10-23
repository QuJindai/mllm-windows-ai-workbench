from types import SimpleNamespace

import pytest
from PIL import Image


def request(tmp_path, **values):
    return {'dreamRoot': str(tmp_path), 'jobId': 'identity-' + 'a' * 24,
            'imagePath': str(tmp_path / 'reference.png'), 'faceIndex': 0, **values}


def params(enabled=False, strength=1.0):
    return SimpleNamespace(facePolish=enabled, faceRestoreStrength=strength)


def test_disabled_does_not_load_models_or_create_original(tmp_path):
    from identity_face_polish import optional_face_polish
    original = Image.new('RGB', (64, 80), 'green')
    def forbidden():
        pytest.fail('disabled polish must not load any optional model')
    final, info = optional_face_polish(original, params(), request(tmp_path), forbidden, [].append)
    assert final is original
    assert info == {'enabled': False, 'status': 'disabled'}
    assert not (tmp_path / 'data').exists()


def test_enabled_keeps_original_and_returns_processed_image_and_real_stages(tmp_path):
    from identity_face_polish import optional_face_polish
    original = Image.new('RGB', (64, 80), 'green')
    changed = Image.new('RGB', original.size, 'blue')
    events, calls = [], []
    class Processor:
        def apply(self, image, item, strength, stage):
            calls.append((image, item, strength))
            assert (tmp_path / 'data/identity/originals' / (item['jobId'] + '.png')).is_file()
            stage('身份回贴')
            stage('面部细节修复')
            return changed, {'swapModel': 'inswapper_128.onnx'}
    item = request(tmp_path, faceIndex=2)
    final, info = optional_face_polish(original, params(True, .6), item, Processor, events.append)
    assert final is changed and calls == [(original, item, .6)]
    assert info['status'] == 'completed' and info['restoreStrength'] == .6
    assert info['originalImageUrl'] == '/api/identity/jobs/' + item['jobId'] + '/original'
    saved = Image.open(tmp_path / 'data/identity/originals' / (item['jobId'] + '.png'))
    assert saved.tobytes() == original.tobytes()
    assert events == ['身份回贴', '面部细节修复']


@pytest.mark.parametrize('failure', ['load', 'process', 'wrong_size'])
def test_failure_preserves_base_and_never_claims_polished(tmp_path, failure):
    from identity_face_polish import optional_face_polish
    original = Image.new('RGB', (64, 80), 'green')
    class Broken:
        def __init__(self):
            if failure == 'load':
                raise RuntimeError('GPU internal error')
        def apply(self, image, item, strength, stage):
            if failure == 'wrong_size':
                return Image.new('RGB', (3, 3)), {}
            raise RuntimeError('restore failed')
    final, info = optional_face_polish(original, params(True), request(tmp_path), Broken, [].append)
    assert final is original and info['status'] == 'failed'
    assert '原图' in info['message']
    assert len(list((tmp_path / 'data/identity/originals').glob('*.png'))) == 1


def test_status_optional_assets_do_not_import_inference_or_download(tmp_path):
    from identity_face_polish import face_polish_status
    assert not face_polish_status({}, find_spec=lambda name: object())['ready']
    weights = tmp_path / 'faces'
    weights.mkdir()
    for filename in ('inswapper_128.onnx', 'GFPGANv1.4.pth', 'detection_Resnet50_Final.pth', 'parsing_parsenet.pth'):
        (weights / filename).write_bytes(b'local')
    config = {'faceSwapModel': str(weights / 'inswapper_128.onnx'),
              'faceRestoreModel': str(weights / 'GFPGANv1.4.pth'), 'faceDetectionRoot': str(weights)}
    assert face_polish_status(config, find_spec=lambda name: object())['ready']
    assert not face_polish_status(config, find_spec=lambda name: None if name == 'spandrel' else object())['ready']
    (weights / 'parsing_parsenet.pth').unlink()
    assert not face_polish_status(config, find_spec=lambda name: object())['ready']


@pytest.mark.parametrize('count', [0, 2])
def test_no_face_or_ambiguous_target_is_not_silently_swapped(count):
    from identity_face_polish import single_target
    with pytest.raises(ValueError, match='人脸'):
        single_target([object()] * count)


def test_only_one_target_is_allowed():
    from identity_face_polish import single_target
    face = object()
    assert single_target([face]) is face


def test_zero_strength_does_not_claim_cuda_restoration_was_executed():
    from identity_face_polish import FacePolisher
    processor = FacePolisher.__new__(FacePolisher)
    processor.hashes = {}
    assert processor.details(restore=False)['restoreDevice'] == 'not-run (strength=0)'


@pytest.mark.parametrize('boundary', ['mkdir', 'save', 'replace'])
def test_original_storage_failure_returns_valid_base_without_broken_original_link(tmp_path, monkeypatch, boundary):
    import identity_face_polish
    from pathlib import Path
    image = Image.new('RGB', (64, 80), 'green')
    def broken(*args, **kwargs):
        raise PermissionError('original storage denied')
    if boundary == 'mkdir':
        monkeypatch.setattr(Path, 'mkdir', broken)
    elif boundary == 'save':
        monkeypatch.setattr(Image.Image, 'save', broken)
    else:
        monkeypatch.setattr(identity_face_polish.os, 'replace', broken)
    def forbidden():
        pytest.fail('must not process without original retention')
    final, info = identity_face_polish.optional_face_polish(image, params(True), request(tmp_path), forbidden, [].append)
    assert final is image and info['status'] == 'failed'
    assert 'originalImageUrl' not in info


def test_redirected_originals_directory_is_not_written(tmp_path):
    from identity_face_polish import optional_face_polish
    outside = tmp_path / 'unrelated'
    outside.mkdir()
    parent = tmp_path / 'data/identity'
    parent.mkdir(parents=True)
    try:
        (parent/'originals').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('directory symlink unavailable')
    image = Image.new('RGB', (64, 80), 'green')
    final, info = optional_face_polish(image, params(True), request(tmp_path), lambda: pytest.fail('redirect accepted'), [].append)
    assert final is image and info['status'] == 'failed'
    assert not list(outside.iterdir())


def test_render_applies_optional_stage_and_persists_truthful_metadata(tmp_path, monkeypatch):
    import json
    import torch
    import identity_face_polish
    from identity_pipeline import IdentitySession
    image = Image.linear_gradient('L').resize((512, 768)).convert('RGB')
    moves, events = [], []
    class Pipe:
        scheduler = object()
        def to(self, device):
            moves.append(device)
        def __call__(self, **kwargs):
            return SimpleNamespace(images=[image])
    class Processor:
        def __init__(self, config, item):
            assert moves[-1] == 'cpu'
        def apply(self, base, item, strength, stage):
            stage('身份回贴')
            stage('面部细节修复')
            return base.transpose(Image.Transpose.FLIP_TOP_BOTTOM), {}
    monkeypatch.setattr(identity_face_polish, 'FacePolisher', Processor)
    monkeypatch.setattr(torch.cuda, 'max_memory_allocated', lambda: 0)
    monkeypatch.setattr(torch.cuda, 'max_memory_reserved', lambda: 0)
    monkeypatch.setattr(torch.cuda, 'empty_cache', lambda: None)
    session = IdentitySession.__new__(IdentitySession)
    session.config, session.pipe, session.projected = {}, Pipe(), None
    session.initial_stages, session.hashes, session.started = [], {}, 0
    session.feature_info = {'cacheHit': True, 'featureKey': 'cached'}
    item = request(tmp_path, referenceId='ref-'+'a'*24, prompt='portrait', seed=42, facePolish=True,
                   outputPath=str(tmp_path/'out.png'), metadataPath=str(tmp_path/'out.json'))
    result = session.render(item, 0, events.append, None, 0)
    metadata = json.loads((tmp_path/'out.json').read_text(encoding='utf-8'))
    assert result['metadata'] == metadata
    assert metadata['facePolish']['status'] == 'completed'
    assert metadata['identity']['facePolish'] is True
    assert {'cpu', 'cuda'} <= set(moves)
    assert any(event.get('stage') == '面部细节修复' for event in events)
    assert Image.open(tmp_path/'out.png').tobytes() != image.tobytes()
