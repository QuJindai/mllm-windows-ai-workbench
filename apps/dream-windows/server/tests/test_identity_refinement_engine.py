"""CPU boundaries for independent edits: real pixels/files, mocked inference only."""
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

FACE = 'realistic-vision-v5.1-faceid'
ANIME = 'illustrious-xl-v2.0-faceid'
VISUAL = 'cyberrealistic-xl-plus-face'


def refine(config, item):
    from identity_refinement_engine import refine as operation
    return operation(config, item)


@pytest.fixture
def case(tmp_path, monkeypatch):
    import identity_pipeline
    import identity_face_polish
    import identity_anime
    import identity_visual_polish
    source = tmp_path / 'source.png'
    Image.new('RGB', (256, 272), (20, 60, 100)).save(source)
    reference = tmp_path / 'reference.png'
    Image.new('RGB', (256, 256), 'white').save(reference)
    item = dict(modelId=FACE, referenceId='ref-' + 'a' * 24, faceIndex=2,
                prompt='original scene', negativePrompt='original exclusions', seed=99,
                width=256, height=272, steps=28, cfg=5.5, identityStrength=.77,
                structureStrength=.9, faceLoraStrength=.55, facePolish=False,
                faceRestoreStrength=1., sourcePath=str(source), outputPath=str(tmp_path / 'edit.png'),
                imagePath=str(reference), dreamRoot=str(tmp_path), jobId='identity-' + 'b' * 24,
                editSettings=dict(mode='restore', strength=.3, prompt='edit face', negativePrompt='blur', seed=42))
    calls, control = [], {}
    def configure():
        calls.append(('cuda',))
        if control.get('cuda_error'):
            raise RuntimeError('CUDA admission failed')
    monkeypatch.setattr(identity_pipeline, 'configure_cuda', configure)
    monkeypatch.setattr(identity_pipeline, 'load_identity_pipe', lambda *a: pytest.fail('generation pipeline loaded'))
    route = identity_pipeline.IdentitySession.face_polisher

    class Session:
        def __init__(self, config, first, emit):
            calls.append(('session', copy.deepcopy(first)))
            assert first['modelId'] == VISUAL or first.get('animeProfileId'), 'plain restore loaded generation session'
            if control.get('load_error'):
                raise RuntimeError('pipeline load failed')
            self.config, self.architecture = config, 'SDXL'
            emit({'type': 'stage', 'stage': 'load fixture'})
            if control.get('anime_error'):
                self._anime_error = 'anime projection failed'
        face_polisher = route
    monkeypatch.setattr(identity_pipeline, 'IdentitySession', Session)

    class Processor:
        def __init__(self, kind, config=None, first=None):
            self.kind = kind
            calls.append(('processor', kind))
        def apply(self, image, selected, strength, stage):
            calls.append(('apply', self.kind, copy.deepcopy(selected), strength))
            stage('edit fixture')
            details = {'method': self.kind}
            if self.kind == 'visual' and selected['visualPolishMode'] == 'reference-anchor':
                from identity_stage_artifacts import save_visual_stage
                details['snapshots'] = [{'kind': kind, 'imageUrl': save_visual_stage(image, selected, kind)}
                                        for kind in ('anchor', 'harmonize')]
            if control.get('apply_error'):
                raise RuntimeError('inference failed')
            result = image.copy()
            if control.get('mutate_input'):
                result = image
            if not control.get('unchanged'):
                result.putpixel((10, 12), (200, 30, 50))
            if control.get('size_error'):
                result = result.resize((128, 128))
            if control.get('mode_error'):
                result = result.convert('L')
            if control.get('failed_details'):
                details['status'] = 'failed'
            return result, details
    monkeypatch.setattr(identity_face_polish, 'FacePolisher', lambda c, i: Processor('restore', c, i))
    monkeypatch.setattr(identity_anime, 'AnimePolisher', lambda s: Processor('anime'))
    monkeypatch.setattr(identity_visual_polish, 'VisualReferencePolisher', lambda s: Processor('visual'))
    return SimpleNamespace(item=item, config={'local': 'configuration'}, calls=calls, control=control,
                           source=source, output=Path(item['outputPath']))


def visual(case, mode='reference-anchor'):
    case.item.update(modelId=VISUAL, structureStrength=0., faceLoraStrength=0.,
                     visualPolishMode='redraw', visualPolishPasses=2, visualAnchorStrength=.88,
                     referenceStart=.1, referenceEnd=.9)
    case.item['editSettings']['mode'] = mode


def test_plain_restore_skips_generation_and_preserves_source_reference_and_request(case):
    original = copy.deepcopy(case.item)
    source_bytes = case.source.read_bytes()
    reference_bytes = Path(case.item['imagePath']).read_bytes()
    result = refine(case.config, case.item)
    assert [entry[0] for entry in case.calls] == ['cuda', 'processor', 'apply']
    _, kind, applied, strength = case.calls[-1]
    assert kind == 'restore' and strength == .3
    assert (applied['referenceId'], applied['faceIndex'], applied['imagePath']) == (
        original['referenceId'], 2, original['imagePath'])
    assert case.item == original and case.source.read_bytes() == source_bytes
    assert Path(case.item['imagePath']).read_bytes() == reference_bytes
    with Image.open(case.output) as image:
        assert image.size == (256, 272) and image.mode == 'RGB' and image.format == 'PNG'
        assert image.getpixel((10, 12)) == (200, 30, 50)
    assert result['ok'] is True and result['durationMs'] >= 0
    assert result['sessionReused'] is False
    assert set(result['phasesMs']) == {'read', 'load', 'polish', 'diagnostics', 'save'}
    assert all(value >= 0 for value in result['phasesMs'].values())
    assert sum(result['phasesMs'].values()) <= result['durationMs'] + 1
    assert result['diagnostics']['retention']['whole']['changedPixels'] == 1
    assert 'not identity similarity' in result['diagnostics']['scope']
    assert result['diagnostics']['baselineLabel'] == 'selected-source'
    assert not list(case.output.parent.glob('*.tmp'))


@pytest.mark.parametrize('mode', ['redraw', 'reference-anchor'])
def test_visual_uses_one_pass_and_cleans_only_its_own_temporary_stages(case, mode):
    from identity_stage_artifacts import visual_stage_path
    visual(case, mode)
    old = {**case.item, 'jobId': 'identity-' + 'c' * 24}
    old_stage = visual_stage_path(old, 'anchor')
    old_stage.parent.mkdir(parents=True)
    old_stage.write_bytes(b'prior original stage')
    result = refine(case.config, case.item)
    assert [entry[0] for entry in case.calls] == ['session', 'processor', 'apply']
    first, applied = case.calls[0][1], case.calls[-1][2]
    assert first == applied
    assert applied['visualPolishMode'] == mode and applied['visualPolishPasses'] == 1
    assert applied['animeDenoiseStrength'] == .3 and case.calls[-1][3] == .3
    assert (applied['visualPolishPrompt'], applied['visualPolishNegativePrompt'], applied['seed']) == ('edit face', 'blur', 42)
    assert (applied['visualAnchorStrength'], applied['referenceStart'], applied['referenceEnd']) == (.88, .1, .9)
    assert old_stage.read_bytes() == b'prior original stage'
    assert not visual_stage_path(case.item, 'anchor').parent.exists()
    assert 'snapshots' not in result['polish']


def test_anime_profile_restore_initializes_existing_session_projection_and_direct_polisher(case):
    case.item.update(modelId=ANIME, animeProfileId='anime-' + 'd' * 24,
                     animeProfile={'id': 'anime-' + 'd' * 24}, animeFeaturesPath='local-features', animeImagePath='local-image')
    result = refine(case.config, case.item)
    first = case.calls[0][1]
    assert first['facePolish'] is True
    assert first['animeProfileId'] == case.item['animeProfileId'] and first['animeFeaturesPath'] == 'local-features'
    assert first['animeDenoiseStrength'] == .3
    assert (first['prompt'], first['negativePrompt'], first['seed']) == ('edit face', 'blur', 42)
    assert case.calls[-1][1] == 'anime' and result['polish']['method'] == 'anime'


@pytest.mark.parametrize('failure', ['cuda_error', 'apply_error', 'size_error', 'mode_error', 'failed_details', 'unchanged'])
def test_restore_errors_never_publish_unchanged_or_invalid_fallbacks(case, failure):
    before = case.source.read_bytes()
    case.control[failure] = True
    with pytest.raises((ValueError, RuntimeError)):
        refine(case.config, case.item)
    assert not case.output.exists() and case.source.read_bytes() == before
    assert not list(case.output.parent.glob('*.tmp'))


@pytest.mark.parametrize('failure', ['load_error', 'apply_error'])
def test_visual_failure_propagates_and_cleans_owned_stage_files(case, failure):
    from identity_stage_artifacts import visual_stage_path
    visual(case)
    case.control[failure] = True
    with pytest.raises(RuntimeError, match='failed'):
        refine(case.config, case.item)
    assert not case.output.exists() and not visual_stage_path(case.item, 'anchor').parent.exists()


def test_existing_stage_job_is_never_reused_or_cleaned(case):
    from identity_stage_artifacts import visual_stage_path
    visual(case)
    path = visual_stage_path(case.item, 'anchor')
    path.parent.mkdir(parents=True)
    path.write_bytes(b'pre-existing stage')
    with pytest.raises(FileExistsError):
        refine(case.config, case.item)
    assert path.read_bytes() == b'pre-existing stage' and not case.output.exists()
    assert not case.calls


@pytest.mark.parametrize('inference_failed', [False, True])
def test_stage_cleanup_failure_blocks_publication_without_masking_inference_error(case, monkeypatch, inference_failed):
    import identity_stage_artifacts
    visual(case)
    case.control['apply_error'] = inference_failed
    cleanup = identity_stage_artifacts.cleanup_visual_stages
    def fail_cleanup(item):
        cleanup(item)
        raise OSError('cleanup failed')
    monkeypatch.setattr(identity_stage_artifacts, 'cleanup_visual_stages', fail_cleanup)
    error_type, message = (RuntimeError, 'inference failed') if inference_failed else (OSError, 'cleanup failed')
    with pytest.raises(error_type, match=message):
        refine(case.config, case.item)
    assert not case.output.exists()


def test_existing_output_is_never_overwritten(case):
    case.output.write_bytes(b'previous edit')
    with pytest.raises(FileExistsError):
        refine(case.config, case.item)
    assert case.output.read_bytes() == b'previous edit' and not case.calls


def test_source_dimensions_are_checked_before_loading_any_model(case):
    case.item['height'] = 256
    with pytest.raises(ValueError, match='尺寸'):
        refine(case.config, case.item)
    assert not case.calls and not case.output.exists()


def test_diagnostics_use_an_immutable_baseline_even_if_polisher_mutates_its_input(case):
    case.control['mutate_input'] = True
    result = refine(case.config, case.item)
    assert result['diagnostics']['retention']['whole']['changedPixels'] == 1


@pytest.mark.parametrize('edit', [{'mode': 'redraw'}, {'mode': 'reference-anchor'}, {'strength': .1},
                                  {'strength': float('nan')}, {'seed': -1}, {'seed': True}])
def test_invalid_or_incompatible_edit_fails_before_model_loading(case, edit):
    case.item['editSettings'].update(edit)
    with pytest.raises(ValueError):
        refine(case.config, case.item)
    assert not case.calls and not case.output.exists()


def test_anime_projection_failure_is_not_hidden_by_optional_restore_fallback(case):
    case.item.update(modelId=ANIME, animeProfileId='anime-' + 'd' * 24)
    case.control['anime_error'] = True
    with pytest.raises(ValueError, match='anime projection failed'):
        refine(case.config, case.item)
    assert not case.output.exists()


def test_atomic_publish_uses_unique_complete_temp_and_cleans_up_on_failure(case, monkeypatch):
    import identity_refinement_engine as engine
    occupied = case.output.with_suffix('.tmp')
    occupied.write_bytes(b'unrelated temp')
    def fail_publish(source, destination):
        assert Path(source) != occupied and Path(source).parent == case.output.parent
        assert Path(destination) == case.output
        with Image.open(source) as image:
            assert image.size == (256, 272) and image.getpixel((10, 12)) == (200, 30, 50)
        raise OSError('publication failed')
    monkeypatch.setattr(engine.os, 'link', fail_publish)
    with pytest.raises(OSError, match='publication failed'):
        refine(case.config, case.item)
    assert not case.output.exists()
    assert list(case.output.parent.glob('*.tmp')) == [occupied]
    assert occupied.read_bytes() == b'unrelated temp'


def test_partial_png_encoding_is_cleaned_without_publishing(case, monkeypatch):
    before = case.source.read_bytes()
    def fail_save(image, stream, **kwargs):
        stream.write(b'partial PNG')
        raise OSError('encoding failed')
    monkeypatch.setattr(Image.Image, 'save', fail_save)
    with pytest.raises(OSError, match='encoding failed'):
        refine(case.config, case.item)
    assert not case.output.exists() and not list(case.output.parent.glob('*.tmp'))
    assert case.source.read_bytes() == before


@pytest.mark.parametrize('model,anime', [(FACE, False), (ANIME, False), (ANIME, True),
                                       (VISUAL, False), ('illustrious-xl-v2.0-plus-face', False)])
def test_edge_lighting_calls_only_helper_and_keeps_its_actual_mask_diagnostics(case, monkeypatch, model, anime):
    import numpy as np
    from identity_quality import compare_images
    case.item['modelId'] = model
    case.item['editSettings'].update(mode='edge-lighting', strength=.65)
    scene = case.source.parent / 'immutable-scene.png'
    Image.new('RGB', (256, 272), (80, 90, 100)).save(scene)
    scene_bytes = scene.read_bytes()
    case.item['scenePath'] = str(scene)
    if anime:
        case.item['animeProfileId'] = 'anime-' + 'd'*24
    original = copy.deepcopy(case.item)
    observed = []
    def helper(config, item, image, strength, stage):
        observed.append((config, copy.deepcopy(item), strength))
        assert Path(item['scenePath']).read_bytes() == scene_bytes
        assert image.getpixel((0, 0)) == (20, 60, 100)  # selected source, not immutable scene
        stage('edge fixture')
        result = image.copy()
        result.putpixel((10, 12), (200, 30, 50))
        edit_mask = np.zeros((image.height, image.width), dtype=bool)
        edit_mask[12, 10] = True
        protected_mask = np.zeros_like(edit_mask)
        protected_mask[11, 11] = True
        diagnostics = compare_images(image, result, edit_mask=edit_mask, protected_mask=protected_mask,
                                     baseline_label='selected-source', candidate_label='refinement')
        return result, {'method': 'edge-lighting', 'maskSource': 'actual-helper-mask', 'diagnostics': diagnostics}
    monkeypatch.setitem(sys.modules, 'identity_edge_lighting', SimpleNamespace(improve_edge_lighting=helper))
    result = refine(case.config, case.item)
    assert case.calls == []  # no CUDA admission, generation session or FacePolisher
    assert len(observed) == 1 and observed[0][0] == case.config and observed[0][2] == .65
    assert observed[0][1] == {**original, 'seed': 42}
    assert case.item == original
    assert result['mode'] == 'edge-lighting' and result['polish']['maskSource'] == 'actual-helper-mask'
    assert result['sessionReused'] is False and scene.read_bytes() == scene_bytes
    assert result['diagnostics']['retention']['editSupport']['pixelCount'] == 1
    assert result['diagnostics']['retention']['protected']['exactRetentionFraction'] == 1
    assert result['diagnostics']['retention']['outsideEdit']['changedPixels'] == 0
    assert result['diagnostics']['seam']['edgeCount'] == 4
    assert 'diagnostics' not in result['polish']
    assert not (case.source.parent / 'data/identity/stages').exists()


@pytest.mark.parametrize('strength', [.15, .65])
def test_edge_lighting_forwards_strength_endpoints_without_loading_models(case, monkeypatch, strength):
    case.item['editSettings'].update(mode='edge-lighting', strength=strength)
    def helper(config, item, image, actual_strength, stage):
        assert actual_strength == strength
        raise RuntimeError('helper failure')
    monkeypatch.setitem(sys.modules, 'identity_edge_lighting', SimpleNamespace(improve_edge_lighting=helper))
    with pytest.raises(RuntimeError, match='helper failure'):
        refine(case.config, case.item)
    assert case.calls == [] and not case.output.exists()


@pytest.mark.parametrize('strength', [.14, .66])
def test_edge_lighting_rejects_out_of_range_strength_before_helper(case, monkeypatch, strength):
    case.item['editSettings'].update(mode='edge-lighting', strength=strength)
    def forbidden(*args):
        pytest.fail('invalid strength reached helper')
    monkeypatch.setitem(sys.modules, 'identity_edge_lighting', SimpleNamespace(improve_edge_lighting=forbidden))
    with pytest.raises(ValueError):
        refine(case.config, case.item)
    assert case.calls == [] and not case.output.exists()


def test_edge_lighting_requires_helper_diagnostics_instead_of_inventing_masks(case, monkeypatch):
    case.item['editSettings']['mode'] = 'edge-lighting'
    def helper(config, item, image, strength, stage):
        image.putpixel((10, 12), (200, 30, 50))
        return image, {'method': 'edge-lighting'}
    monkeypatch.setitem(sys.modules, 'identity_edge_lighting', SimpleNamespace(improve_edge_lighting=helper))
    with pytest.raises(ValueError, match='diagnostics'):
        refine(case.config, case.item)
    assert case.calls == [] and not case.output.exists()


def test_edge_lighting_unchanged_candidate_is_a_meaningful_error_without_a_version(case, monkeypatch):
    from identity_quality import compare_images
    case.item['editSettings']['mode'] = 'edge-lighting'
    def helper(config, item, image, strength, stage):
        return image, {'status': 'unchanged', 'diagnostics': compare_images(image, image)}
    monkeypatch.setitem(sys.modules, 'identity_edge_lighting', SimpleNamespace(improve_edge_lighting=helper))
    with pytest.raises(ValueError, match='未产生像素变化'):
        refine(case.config, case.item)
    assert not case.output.exists() and not case.calls


def test_plain_restore_config_does_not_require_unused_generation_assets(case, monkeypatch):
    import identity_models
    from identity_worker import load_config
    path = case.source.parent / 'runtime.json'
    path.write_text(json.dumps(case.config))
    monkeypatch.setattr(identity_models, 'resolve_identity_model', lambda *a: pytest.fail('unused checkpoint validation'))
    assert load_config({**case.item, 'configPath': str(path)}, operation='refine') == case.config


@pytest.mark.parametrize('model,profile', [(VISUAL, None), (ANIME, 'anime-' + 'd' * 24)])
def test_session_routes_still_resolve_the_requested_model(case, monkeypatch, model, profile):
    import identity_models
    from identity_worker import load_config
    path = case.source.parent / 'runtime.json'
    path.write_text(json.dumps(case.config))
    def resolve(config, model_id):
        assert model_id == model
        return {**config, 'resolved': model_id}
    monkeypatch.setattr(identity_models, 'resolve_identity_model', resolve)
    result = load_config({**case.item, 'configPath': str(path), 'modelId': model, 'animeProfileId': profile}, operation='refine')
    assert result['resolved'] == model


@pytest.mark.parametrize('fail', [False, True])
def test_worker_dispatches_refine_and_propagates_failures_without_generation_imports(case, monkeypatch, fail):
    import identity_worker
    request_file, result_file = case.source.parent / 'request.json', case.source.parent / 'result.json'
    request_file.write_text(json.dumps(case.item))
    monkeypatch.setattr(identity_worker, 'load_config', lambda request, operation: case.config if operation == 'refine' else pytest.fail('wrong operation'))
    monkeypatch.setitem(sys.modules, 'identity_pipeline', SimpleNamespace())
    def operation(config, request):
        assert config == case.config and request == case.item
        if fail:
            raise RuntimeError('pipeline failure')
        return {'ok': True, 'durationMs': 17}
    monkeypatch.setitem(sys.modules, 'identity_refinement_engine', SimpleNamespace(refine=operation))
    monkeypatch.setattr(sys.stdout, 'reconfigure', lambda **kw: None, raising=False)
    monkeypatch.setattr(sys.stderr, 'reconfigure', lambda **kw: None, raising=False)
    monkeypatch.setattr(sys, 'argv', ['worker', '--operation', 'refine', '--request', str(request_file), '--result', str(result_file)])
    assert identity_worker.main() == (1 if fail else 0)
    result = json.loads(result_file.read_text(encoding='utf-8'))
    assert result['ok'] is not fail
    if fail:
        assert result['code'] == 'IDENTITY_WORKER_FAILED'
    else:
        assert result['durationMs'] == 17
