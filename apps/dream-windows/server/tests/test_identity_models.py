import copy
import json
from pathlib import Path

import pytest
from test_identity_api import harness, upload, submit, finished
from test_identity_pipeline_publication import render_case

RV = 'realistic-vision-v5.1-faceid'
XL = 'illustrious-xl-v2.0-faceid'


def request(**changes):
    return dict(referenceId='ref-' + 'a' * 24, faceIndex=0, prompt='portrait', seed=42, **changes)


def assets(tmp_path):
    cfg = {'lorasDir': str(tmp_path / 'loras'), 'insightfaceRoot': str(tmp_path)}
    for key in ('checkpoint', 'adapter', 'faceLora', 'clipVision'):
        path = tmp_path / key
        path.write_bytes(b'weight')
        cfg[key] = str(path)
    cfg['pipelineConfig'] = str(tmp_path / 'sd15')
    Path(cfg['pipelineConfig']).mkdir()
    face = tmp_path / 'models' / 'buffalo_l'
    face.mkdir(parents=True)
    for name in ('det_10g.onnx', 'w600k_r50.onnx'):
        (face / name).write_bytes(b'face')
    xl = {}
    for key in ('checkpoint', 'adapter', 'faceLora'):
        path = tmp_path / ('xl-' + key)
        path.write_bytes(b'xl-weight')
        xl[key] = str(path)
    xl['pipelineConfig'] = str(tmp_path / 'sdxl')
    Path(xl['pipelineConfig']).mkdir()
    cfg['models'] = {XL: xl}
    return cfg


def test_legacy_request_defaults_to_rv_and_xl_is_explicit():
    from identity_contract import IdentityGenerateRequest
    assert IdentityGenerateRequest(**request()).modelId == RV
    assert IdentityGenerateRequest(**request(modelId=XL)).modelId == XL
    with pytest.raises(ValueError):
        IdentityGenerateRequest(**request(modelId='../other'))


def test_model_resolver_uses_whole_sdxl_bundle_without_mutating_legacy(tmp_path):
    from identity_models import resolve_identity_model
    config = assets(tmp_path)
    before = copy.deepcopy(config)
    selected = resolve_identity_model(config, XL)
    assert selected['architecture'] == 'SDXL'
    assert selected['checkpoint'] == str(tmp_path / 'xl-checkpoint')
    assert selected['adapter'] == str(tmp_path / 'xl-adapter')
    assert selected['faceLora'] == str(tmp_path / 'xl-faceLora')
    assert selected['clipVision'] == config['clipVision']
    assert resolve_identity_model(config)['checkpoint'] == config['checkpoint']
    assert config == before


def test_missing_sdxl_asset_never_falls_back_and_default_stays_ready(tmp_path):
    from identity_models import resolve_identity_model, identity_model_catalog
    config = assets(tmp_path)
    del config['models'][XL]['adapter']
    with pytest.raises(ValueError, match='adapter'):
        resolve_identity_model(config, XL)
    rows = {row['id']: row for row in identity_model_catalog(config)}
    assert rows[RV]['ready'] is True
    assert rows[XL]['ready'] is False
    assert str(tmp_path) not in json.dumps(rows)


def test_loras_are_filtered_to_selected_architecture(tmp_path):
    from identity_pipeline import registered_loras
    (tmp_path / 'style.safetensors').write_bytes(b'weight')
    for identifier, architecture in [('photo', 'SD1.5'), ('illustration', 'SDXL')]:
        (tmp_path / (identifier + '.json')).write_text(json.dumps({'architecture': architecture, 'file': 'style.safetensors'}))
    assert [row['id'] for row in registered_loras({'lorasDir': str(tmp_path), 'architecture': 'SDXL'})] == ['illustration']


def test_mixed_model_batch_is_rejected_before_loading(tmp_path, monkeypatch):
    import identity_pipeline
    from test_identity_batch_worker import make_item
    monkeypatch.setattr(identity_pipeline, 'IdentitySession', lambda *args: pytest.fail('must not load mixed models'))
    with pytest.raises(ValueError, match='同一'):
        identity_pipeline.generate_batch({}, {'items': [make_item(tmp_path, 0), make_item(tmp_path, 1, modelId=XL)]})


def test_sdxl_extended_research_is_rejected_but_representative_allowed():
    from identity_contract import IdentityGenerateRequest
    assert IdentityGenerateRequest(**request(modelId=XL, traceLevel='h7')).traceLevel == 'h7'
    with pytest.raises(ValueError, match='SDXL'):
        IdentityGenerateRequest(**request(modelId=XL, width=512, height=512, steps=8, traceLevel='h7', researchCoverage='extended'))


def test_worker_selects_model_inside_batch_request(tmp_path):
    from identity_worker import load_config
    config = assets(tmp_path)
    path = tmp_path / 'runtime.json'
    path.write_text(json.dumps(config))
    assert load_config({'configPath': str(path), 'items': [request(modelId=XL)]})['architecture'] == 'SDXL'


def test_sdxl_pipe_is_loaded_offline_and_never_wholly_moved_to_cuda(monkeypatch):
    from identity_pipeline import load_identity_pipe, place_identity_pipe
    from types import SimpleNamespace
    import sys
    class Pipe:
        unet = SimpleNamespace(config=SimpleNamespace(cross_attention_dim=2048))
        def enable_sequential_cpu_offload(self):
            self.offloaded = True
        def to(self, device):
            pytest.fail('SDXL must not move entire model to GPU')
    class XLLoader:
        @staticmethod
        def from_single_file(path, **options):
            assert path == 'xl.safetensors'
            assert options['config'] == 'local-sdxl'
            assert options['local_files_only'] is True
            return Pipe()
    monkeypatch.setitem(sys.modules, 'diffusers', SimpleNamespace(StableDiffusionXLPipeline=XLLoader, StableDiffusionPipeline=None))
    pipe = load_identity_pipe({'architecture': 'SDXL', 'checkpoint': 'xl.safetensors', 'pipelineConfig': 'local-sdxl'})
    place_identity_pipe(pipe, 'SDXL')
    assert pipe.offloaded is True


def test_sdxl_request_keeps_selected_model_in_published_history(harness):
    client, _, _, _ = harness
    reference = upload(client)
    job = finished(client, submit(client, reference, modelId=XL)['id'])
    assert job['result']['metadata']['model_id'] == XL
    assert job['request']['modelId'] == XL


def test_sdxl_render_research_identifies_actual_architecture(render_case):
    _, session, item, _, trace = render_case
    item['modelId'] = XL
    result = session.render(item, 0, [].append, None, 0)
    assert result['metadata']['backend'] == 'diffusers-faceid-sdxl'
    assert result['metadata']['model_id'] == XL
    data = json.loads(trace.read_text(encoding='utf-8'))
    assert data['nodes'][0]['name'].startswith('SDXL')


def test_public_status_preserves_model_readiness_without_local_paths(harness, monkeypatch):
    from identity_service import IdentityService
    client, _, _, _ = harness
    monkeypatch.setattr(IdentityService, '_worker', lambda *args: {'ready': True, 'loras': [], 'models': [
        {'id': XL, 'name': 'Illustrious XL', 'architecture': 'SDXL', 'ready': False,
         'message': 'missing assets', 'loras': [], 'checkpoint': 'private/path'}]})
    result = client.get('/api/identity/status').json()
    assert result['models'][0]['ready'] is False
    assert result['models'][0]['id'] == XL
    assert 'private/path' not in json.dumps(result)


@pytest.mark.parametrize('operation', ['inspect', 'prepare'])
def test_xl_only_install_can_inspect_and_prepare_without_rv_assets(tmp_path, operation):
    from identity_worker import load_config
    from identity_models import identity_model_catalog
    config = assets(tmp_path)
    Path(config['checkpoint']).unlink()
    path = tmp_path / 'runtime.json'
    path.write_text(json.dumps(config))
    rows = {row['id']: row for row in identity_model_catalog(config)}
    assert rows[XL]['ready'] is True and rows[RV]['ready'] is False
    resolved = load_config({'configPath': str(path)}, operation=operation)
    assert resolved['clipVision'] == config['clipVision']


def test_inspection_needs_face_detector_but_not_clip_or_base(tmp_path):
    from identity_worker import load_config
    config = assets(tmp_path)
    Path(config['clipVision']).unlink()
    path = tmp_path / 'runtime.json'
    path.write_text(json.dumps(config))
    load_config({'configPath': str(path)}, operation='inspect')
    with pytest.raises(ValueError, match='clipVision'):
        load_config({'configPath': str(path)}, operation='prepare')
