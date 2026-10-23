"""Visual conditioning must never become a synthetic biometric enrollment."""
import hashlib
import json
from pathlib import Path

import pytest
from test_identity_pipeline_publication import render_case

VISUAL = 'cyberrealistic-xl-plus-face'


def request(**extra):
    return dict(referenceId='ref-'+'a'*24, faceIndex=0, prompt='anime portrait',
                modelId=VISUAL, structureStrength=0., faceLoraStrength=0., **extra)


def test_visual_request_accepts_research_and_polish_but_rejects_hybrid_controls():
    from identity_contract import IdentityGenerateRequest
    assert IdentityGenerateRequest(**request(traceLevel='basic')).modelId == VISUAL
    for extra in ({'facePolish': True}, {'traceLevel': 'h7'}, {'traceLevel': 'h6'}):
        assert IdentityGenerateRequest(**request(**extra)).modelId == VISUAL
    for extra in ({'animeProfileId': 'anime-'+'b'*24},):
        with pytest.raises(ValueError, match='视觉参考'):
            IdentityGenerateRequest(**request(**extra))
    for key in ('structureStrength', 'faceLoraStrength'):
        with pytest.raises(ValueError, match='视觉参考'):
            IdentityGenerateRequest(**{**request(), key: .5})


def test_visual_bundle_needs_no_recognition_or_companion_lora(tmp_path):
    from identity_models import resolve_identity_model
    from test_identity_models import assets
    config = assets(tmp_path)
    bundle = dict(config['models']['illustrious-xl-v2.0-faceid'])
    del bundle['faceLora']
    config['models'][VISUAL] = bundle
    (tmp_path/'models/buffalo_l/w600k_r50.onnx').unlink()
    selected = resolve_identity_model(config, VISUAL)
    assert selected['referenceKind'] == 'visual'
    assert selected['adapter'] == bundle['adapter']
    assert not selected.get('faceLora')
    with pytest.raises(ValueError, match='InsightFace'):
        resolve_identity_model(config)


def test_clip_encoder_uses_exact_gelu_not_quick_approximation():
    import torch
    from transformers.activations import ACT2FN
    import identity_pipeline
    config = identity_pipeline.clip_vision_config()
    values = torch.tensor([-2., -1., 0., 1., 2.])
    observed = ACT2FN[config.hidden_act](values)
    assert torch.allclose(observed, torch.nn.functional.gelu(values), atol=1e-7)
    assert not torch.allclose(observed, values * torch.sigmoid(1.702 * values), atol=1e-5)


def cache_assets(tmp_path):
    root = tmp_path/'assets'
    (root/'models/buffalo_l').mkdir(parents=True)
    for name in ('det_10g.onnx', 'w600k_r50.onnx'):
        (root/'models/buffalo_l'/name).write_bytes(name.encode())
    (root/'clip').write_bytes(b'clip')
    (root/'image').write_bytes(b'image')
    return {'clipVision': str(root/'clip'), 'insightfaceRoot': str(root)}, {
        'dreamRoot': str(tmp_path), 'imagePath': str(root/'image'), 'faceIndex': 0}


def tensors(visual=False):
    import torch
    value = {key: torch.ones(1, 257, 1280) for key in ('clip', 'negative_clip')}
    if not visual:
        value['id'] = torch.ones(1, 512)
    return value


def test_gelu_upgrade_leaves_v2_bytes_and_writes_new_key(tmp_path):
    from identity_features import reference_features
    from safetensors.torch import save_file
    config, req = cache_assets(tmp_path)
    hashes = {'clipVision': hashlib.sha256(b'clip').hexdigest(), **{
        name: hashlib.sha256(name.encode()).hexdigest() for name in ('det_10g.onnx', 'w600k_r50.onnx')}}
    legacy_key = hashlib.sha256(json.dumps({'image': hashlib.sha256(b'image').hexdigest(),
        'face': 0, 'models': hashes, 'version': 2}, sort_keys=True).encode()).hexdigest()
    legacy = tmp_path/'cache/identity'/f'{legacy_key}.safetensors'
    legacy.parent.mkdir(parents=True)
    save_file(tensors(), str(legacy))
    before = legacy.read_bytes()
    _, info = reference_features(config, req, lambda *args: tensors())
    assert info['featureKey'] != legacy_key
    assert info['cacheHit'] is False
    assert info['featureVersion'] == 3
    assert legacy.read_bytes() == before
    _, warm = reference_features(config, req, lambda *a: pytest.fail('warm cache re-extracted'))
    assert warm['cacheHit'] is True


def test_visual_cache_contains_no_id_and_does_not_read_recognition_model(tmp_path):
    from identity_features import visual_reference_features
    config, req = cache_assets(tmp_path)
    (Path(config['insightfaceRoot'])/'models/buffalo_l/w600k_r50.onnx').unlink()
    features, info = visual_reference_features(config, req, lambda *a: tensors(True))
    assert set(features) == {'clip', 'negative_clip'}
    assert info['referenceKind'] == 'visual'
    assert 'w600k_r50.onnx' not in info['assetHashes']
    assert info['featureVersion'] == 1
    _, warm = visual_reference_features(config, req, lambda *a: pytest.fail('warm cache re-extracted'))
    assert warm['cacheHit'] is True


def test_visual_cache_rejects_accidental_biometric_tensor(tmp_path):
    from identity_features import visual_reference_features
    config, req = cache_assets(tmp_path)
    with pytest.raises(ValueError, match='特征'):
        visual_reference_features(config, req, lambda *a: tensors(False))


def test_visual_inspection_uses_detection_without_recognition(monkeypatch):
    import numpy as np
    from types import SimpleNamespace
    import identity_pipeline
    def detect(config, path, *, recognition=True):
        assert recognition is False, 'visual enrollment must not run biometric recognition'
        return np.zeros((80, 100, 3)), [SimpleNamespace(bbox=[10, 20, 50, 60])]
    monkeypatch.setattr(identity_pipeline, 'face_analysis', detect)
    result = identity_pipeline.inspect_reference({}, {'imagePath': 'reference', 'referenceKind': 'visual'})
    assert result['faces'] == [{'index': 0, 'box': [10., 20., 50., 60.]}]


@pytest.mark.parametrize('model', [VISUAL, 'illustrious-xl-v2.0-plus-face'])
def test_visual_session_uses_native_patch_projection_without_faceid_lora(tmp_path, monkeypatch, model):
    import torch
    import identity_features
    import identity_pipeline
    from types import SimpleNamespace
    import sys
    monkeypatch.setitem(sys.modules, 'diffusers', SimpleNamespace(
        EulerDiscreteScheduler=SimpleNamespace(from_config=lambda config, **kw: SimpleNamespace(config=config))))
    monkeypatch.setitem(sys.modules, 'diffusers.models.embeddings', SimpleNamespace(MultiIPAdapterImageProjection=None))
    config, req = cache_assets(tmp_path)
    adapter = tmp_path/'plus-face.safetensors'
    adapter.write_bytes(b'adapter')
    checkpoint = tmp_path/'checkpoint'
    checkpoint.write_bytes(b'checkpoint')
    config.update(adapter=str(adapter), checkpoint=str(checkpoint), architecture='SDXL', referenceKind='visual',
                  allowExperimentalVisualModels=True)
    req.update(request())
    req['modelId'] = model
    original_projection = object()
    class Pipe:
        scheduler = SimpleNamespace(config={})
        unet = SimpleNamespace(encoder_hid_proj=original_projection, peft_config={})
        vae = SimpleNamespace(enable_slicing=lambda: None, enable_tiling=lambda: None)
        def load_ip_adapter(self, path, **kw):
            assert path == str(tmp_path)
            assert kw['weight_name'] == 'plus-face.safetensors'
            assert kw['local_files_only'] is True
            assert kw['image_encoder_folder'] is None
        def set_ip_adapter_scale(self, value):
            self.scale = value
        def enable_sequential_cpu_offload(self):
            self.offloaded = True
    pipe = Pipe()
    monkeypatch.setattr(identity_pipeline, 'configure_cuda', lambda: None)
    monkeypatch.setattr(identity_pipeline, 'load_identity_pipe', lambda cfg: pipe)
    monkeypatch.setattr(identity_pipeline, 'extract_visual_features', lambda *a: tensors(True), raising=False)
    monkeypatch.setattr(identity_features, 'reference_features', lambda *a: pytest.fail('visual route called FaceID extractor'))
    session = identity_pipeline.IdentitySession(config, req, lambda event: None)
    assert pipe.unet.encoder_hid_proj is original_projection
    assert pipe.offloaded is True
    assert session.projected.shape == (2, 1, 257, 1280)
    assert set(session.hashes) == {'clipVision', 'det_10g.onnx', 'checkpoint', 'adapter'}
    assert session.feature_info['referenceKind'] == 'visual'


def test_old_hybrid_anime_features_refresh_clip_without_overwriting_archive(tmp_path, monkeypatch):
    import torch
    import identity_anime
    import identity_pipeline
    from PIL import Image
    from types import SimpleNamespace
    from safetensors.torch import save_file
    config, _ = cache_assets(tmp_path)
    name = 'anime-'+'a'*24
    folder = tmp_path/'data/identity/anime-profiles'
    folder.mkdir(parents=True)
    path = folder/(name+'.safetensors')
    old = tensors()
    save_file(old, str(path))
    before = path.read_bytes()
    source = folder/(name+'.png')
    Image.new('RGB', (100,100), 'blue').save(source)
    item = {'dreamRoot': str(tmp_path), 'animeFeaturesPath': str(path), 'animeImagePath': str(source),
            'animeProfile': {'id': name, 'featureKey': hashlib.sha256(before).hexdigest()}}
    monkeypatch.setattr(identity_anime, 'AnimeDetector', lambda _: SimpleNamespace(detect=lambda image: [[10,10,90,90]]))
    calls = []
    def corrected(*args):
        calls.append(1)
        return torch.full((1,257,1280), 2.), torch.zeros(1,257,1280)
    monkeypatch.setattr(identity_pipeline, 'extract_clip_features', corrected)
    updated = identity_anime.load_anime_features(item, config)
    assert torch.equal(updated['id'], old['id'])
    assert torch.all(updated['clip'] == 2)
    assert path.read_bytes() == before
    assert torch.equal(identity_anime.load_anime_features(item, config)['clip'], updated['clip'])
    assert len(calls) == 1


def test_visual_basic_trace_names_actual_sdxl_without_claiming_attention(render_case):
    _, session, item, _, trace = render_case
    item.update(modelId=VISUAL, structureStrength=0., faceLoraStrength=0.)
    result = session.render(item, 0, lambda event: None, None, 0)
    record = json.loads(trace.read_text(encoding='utf-8'))
    assert record['nodes'][0]['name'] == 'SDXL UNet（基础运行观察）'
    assert record['events'] == []
    assert result['metadata']['backend'] == 'diffusers-ipadapter-plus-face-sdxl'
    assert result['metadata']['research']['h7'] is False
