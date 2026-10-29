"""CPU pixel proofs, with detector/parser inference replaced only at its boundary."""
import json
import builtins
import hashlib
import sys
from types import ModuleType, SimpleNamespace

import numpy as np
from PIL import Image
import pytest


POINTS = np.array([[55., 63.], [105., 63.], [80., 83.], [65., 108.], [95., 108.]])
BOX = [20., 10., 140., 150.]


def fixture_pixels(face=150, neck=100):
    labels = np.zeros((180, 160), dtype=np.uint8)
    labels[20:140, 25:135] = 1
    labels[45:50, 45:63] = 6
    labels[45:50, 97:115] = 7
    labels[140:175, 45:115] = 17
    labels[150:175, 10:35] = 18
    pixels = np.full((180, 160, 3), 30, dtype=np.uint8)
    pixels[20:140, 25:135] = face
    pixels[140:175, 45:115] = neck
    pixels[150:175, 10:35] = 250
    return Image.fromarray(pixels), labels


def scene_fixture(face=100, neck=100):
    return fixture_pixels(face=face, neck=neck)[0]


def scene_item(tmp_path, scene=None):
    path = tmp_path / 'immutable-scene.png'
    (scene or scene_fixture()).save(path)
    return {'scenePath': str(path)}


def test_dark_neck_correction_is_local_and_bounded_with_measured_protection():
    from identity_edge_lighting import edge_lighting_candidate
    image, labels = fixture_pixels()
    before = np.asarray(image).copy()
    result, info = edge_lighting_candidate(image, labels, POINTS, BOX, .65, scene=scene_fixture())
    after = np.asarray(result)
    delta = after.astype(int) - before.astype(int)
    assert (delta < 0).any()
    assert delta.min() >= -8 and delta.max() == 0
    assert np.array_equal(before[labels != 1], after[labels != 1])
    assert np.array_equal(before[50:115, 52:108], after[50:115, 52:108])
    assert np.array_equal(before[:100], after[:100])
    assert np.array_equal(before, np.asarray(image))
    report = info['diagnostics']
    assert report['retention']['protected']['changedPixels'] == 0
    assert report['retention']['outsideEdit']['changedPixels'] == 0
    assert report['retention']['whole']['changedPixels'] > 0
    assert info['boundary']['candidateMeanAbsLumaJump'] < info['boundary']['baselineMeanAbsLumaJump']
    assert info['boundary']['edgeCount'] == 70
    assert info['maskProvenance']['source'] == 'selected-image-target-parsing-and-five-landmarks'
    assert len(info['masks']['edit']['sha256']) == 64
    json.dumps(info, allow_nan=False)


def test_brighter_neck_is_supported_and_strength_scales_the_bound():
    from identity_edge_lighting import edge_lighting_candidate
    image, labels = fixture_pixels(face=90, neck=180)
    low, low_info = edge_lighting_candidate(image, labels, POINTS, BOX, .15, scene=scene_fixture(face=180, neck=180))
    high, _ = edge_lighting_candidate(image, labels, POINTS, BOX, .65, scene=scene_fixture(face=180, neck=180))
    dlow = np.asarray(low).astype(int) - np.asarray(image).astype(int)
    dhigh = np.asarray(high).astype(int) - np.asarray(image).astype(int)
    assert dlow.min() == 0 and 0 < dlow.max() <= 2
    assert dhigh.max() > dlow.max() and dhigh.max() <= 8
    assert low_info['maxChannelDelta'] == dlow.max()


def test_uniform_skin_is_an_honest_unchanged_candidate():
    from identity_edge_lighting import edge_lighting_candidate
    image, labels = fixture_pixels(face=120, neck=120)
    result, info = edge_lighting_candidate(image, labels, POINTS, BOX, .65, scene=image.copy())
    assert np.array_equal(np.asarray(result), np.asarray(image))
    assert info['changedPixels'] == 0
    assert info['status'] == 'unchanged'
    assert info['masks']['edit']['pixelCount'] > 0  # Mask predates pixel changes.


def test_necklace_and_clothing_do_not_supply_the_lighting_target():
    from identity_edge_lighting import edge_lighting_candidate
    image, labels = fixture_pixels()
    pixels = np.asarray(image).copy()
    labels[145:155, 55:105] = 16
    pixels[labels == 16] = 255
    result, info = edge_lighting_candidate(Image.fromarray(pixels), labels, POINTS, BOX, .65, scene=scene_fixture())
    delta = np.asarray(result).astype(int) - pixels.astype(int)
    assert delta.max() == 0 and delta.min() < 0
    assert np.array_equal(np.asarray(result)[labels == 16], pixels[labels == 16])
    assert info['maskProvenance']['lightingTarget'] == 'immutable-scene'


def test_high_frequency_skin_texture_is_not_blurred_away():
    from identity_edge_lighting import edge_lighting_candidate
    image, labels = fixture_pixels()
    pixels = np.asarray(image).copy()
    y, x = np.indices(labels.shape)
    pixels[labels == 1] += (((x + y) % 2)[labels == 1] * 4).astype(np.uint8)[:, None]
    result, info = edge_lighting_candidate(Image.fromarray(pixels), labels, POINTS, BOX, .65, scene=scene_fixture())
    before = info['diagnostics']['baseline']['regions']['editSupport']['meanAbsLumaNeighborDifference']
    after = info['diagnostics']['candidate']['regions']['editSupport']['meanAbsLumaNeighborDifference']
    assert before > 3.5 and after > 3.5
    assert abs(after - before) < .3


@pytest.mark.parametrize('case', ['empty', 'no-neck', 'tiny-neck', 'occluded-mouth', 'disconnected-neck', 'wrong-shape'])
def test_unreliable_or_occluded_regions_fail_instead_of_guessing(case):
    from identity_edge_lighting import edge_lighting_candidate
    image, labels = fixture_pixels()
    original = image.tobytes()
    if case == 'empty': labels[:] = 0
    if case == 'no-neck': labels[labels == 17] = 18
    if case == 'tiny-neck':
        labels[labels == 17] = 0
        labels[140:142, 79:81] = 17
    if case == 'occluded-mouth': labels[102:116, 60:101] = 13
    if case == 'disconnected-neck': labels[140:155] = 0
    if case == 'wrong-shape': labels = labels[:-1]
    with pytest.raises(ValueError):
        edge_lighting_candidate(image, labels, POINTS, BOX, .65, scene=scene_fixture())
    assert image.tobytes() == original


@pytest.mark.parametrize('points', [np.zeros((5, 2)), POINTS + [300, 0],
                                    np.full((5, 2), np.nan), POINTS[:4]])
def test_degenerate_landmarks_fail(points):
    from identity_edge_lighting import edge_lighting_candidate
    image, labels = fixture_pixels()
    with pytest.raises(ValueError):
        edge_lighting_candidate(image, labels, points, BOX, .3, scene=scene_fixture())


@pytest.mark.parametrize('strength', [0, .14, .66, True, float('nan')])
def test_invalid_strength_fails_before_inference(strength, monkeypatch):
    import identity_edge_lighting as edge
    def forbidden(*args):
        pytest.fail('invalid request must not initialize models')
    monkeypatch.setattr(edge, 'target_geometry', forbidden)
    with pytest.raises(ValueError):
        edge.improve_edge_lighting({}, {}, Image.new('RGB', (160, 180)), strength, lambda _: None)


def test_adapter_uses_selected_pixels_and_target_only_inference(monkeypatch, tmp_path):
    import identity_edge_lighting as edge
    import identity_face_region
    image, labels = fixture_pixels()
    original = image.tobytes()
    seen = []
    def geometry(config, selected):
        assert selected.tobytes() == original
        return BOX, POINTS
    class Parser:
        def __init__(self, config): pass
        def labels(self, selected, box):
            assert selected.tobytes() == original
            return labels
    monkeypatch.setattr(edge, 'target_geometry', geometry)
    monkeypatch.setattr(identity_face_region, 'FaceRegionParser', Parser)
    # Neither this unrelated reference nor a generation session is needed.
    item = {**scene_item(tmp_path), 'imagePath': 'X:/does-not-exist/reference.png', 'seed': 123}
    result, info = edge.improve_edge_lighting({}, item, image, .65, seen.append)
    assert result.tobytes() != original
    assert info['mode'] == 'edge-lighting' and info['device'] == 'CPU'
    assert info['diagnostics']['baselineLabel'] == 'selected-source'
    assert info['diagnostics']['retention']['protected']['exactRetentionFraction'] == 1
    assert info['scene']['path'] == item['scenePath']
    assert info['scene']['fileSha256'] == hashlib.sha256((tmp_path / 'immutable-scene.png').read_bytes()).hexdigest()
    assert seen


def test_inference_errors_propagate_without_fallback_success(monkeypatch, tmp_path):
    import identity_edge_lighting as edge
    image, _ = fixture_pixels()
    def failed(*args): raise ValueError('no reliable target face')
    monkeypatch.setattr(edge, 'target_geometry', failed)
    with pytest.raises(ValueError, match='no reliable target face'):
        edge.improve_edge_lighting({}, scene_item(tmp_path), image, .3, lambda _: None)


def test_missing_detector_is_an_error_without_loading_model_packages(tmp_path):
    from identity_edge_lighting import target_geometry
    with pytest.raises(ValueError, match='检测模型'):
        target_geometry({'insightfaceRoot': str(tmp_path)}, Image.new('RGB', (160, 180)))


@pytest.mark.parametrize('faces', [0, 1, 2])
def test_target_detection_is_cpu_only_and_does_not_initialize_reference(tmp_path, monkeypatch, faces):
    from identity_edge_lighting import target_geometry
    from identity_reference_anchor import ReferenceAnchor
    model = tmp_path / 'models/buffalo_l/det_10g.onnx'
    model.parent.mkdir(parents=True)
    model.write_bytes(b'synthetic-detector-placeholder')
    observed = {}
    ort = ModuleType('onnxruntime')
    ort.SessionOptions = SimpleNamespace
    def session(path, *, sess_options, providers):
        observed['providers'] = providers
        return object()
    ort.InferenceSession = session
    scrfd = ModuleType('insightface.model_zoo.scrfd')
    class Detector:
        def __init__(self, path, session): pass
        def prepare(self, *, ctx_id, input_size):
            observed['ctx_id'] = ctx_id
        def detect(self, pixels, max_num):
            observed['firstBgr'] = pixels[0, 0].tolist()
            return np.array([BOX + [.99]] * faces), np.array([POINTS] * faces)
    scrfd.SCRFD = Detector
    monkeypatch.setitem(sys.modules, 'onnxruntime', ort)
    monkeypatch.setitem(sys.modules, 'insightface.model_zoo.scrfd', scrfd)
    def no_reference(*args, **kwargs):
        pytest.fail('target-only edit must not initialize a reference anchor')
    monkeypatch.setattr(ReferenceAnchor, '__init__', no_reference)
    image = Image.new('RGB', (160, 180), (11, 22, 33))
    if faces == 1:
        box, points = target_geometry({'insightfaceRoot': str(tmp_path)}, image)
        assert box == BOX
        assert points.tolist() == POINTS.tolist()
    else:
        with pytest.raises(ValueError):
            target_geometry({'insightfaceRoot': str(tmp_path)}, image)
    assert observed == {'providers': ['CPUExecutionProvider'], 'ctx_id': -1, 'firstBgr': [33, 22, 11]}


def test_selected_adapter_never_imports_generation_pipeline(monkeypatch, tmp_path):
    import identity_edge_lighting as edge
    import identity_face_region
    image, labels = fixture_pixels()
    monkeypatch.setattr(edge, 'target_geometry', lambda *_: (BOX, POINTS))
    class Parser:
        def __init__(self, config): pass
        def labels(self, selected, box): return labels
    monkeypatch.setattr(identity_face_region, 'FaceRegionParser', Parser)
    real_import = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.split('.')[0] in {'diffusers', 'identity_pipeline', 'identity_face_polish'}:
            pytest.fail('edge-lighting must not load a generation or restoration model')
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded)
    output, info = edge.improve_edge_lighting({}, scene_item(tmp_path), image, .65, lambda _: None)
    assert output.tobytes() != image.tobytes()
    assert info['durationMs'] >= 0


def test_parser_failure_and_cancellation_callback_abort_without_changing_input(monkeypatch, tmp_path):
    import identity_edge_lighting as edge
    import identity_face_region
    image, _ = fixture_pixels()
    before = image.tobytes()
    monkeypatch.setattr(edge, 'target_geometry', lambda *_: (BOX, POINTS))
    class Parser:
        def __init__(self, config): raise RuntimeError('parser weights unreadable')
    monkeypatch.setattr(identity_face_region, 'FaceRegionParser', Parser)
    with pytest.raises(RuntimeError, match='parser weights unreadable'):
        edge.improve_edge_lighting({}, scene_item(tmp_path), image, .3, lambda _: None)
    def cancelled(_): raise InterruptedError('cancelled by owner')
    with pytest.raises(InterruptedError, match='cancelled by owner'):
        edge.improve_edge_lighting({}, scene_item(tmp_path), image, .3, cancelled)
    assert image.tobytes() == before


@pytest.mark.parametrize('bad_box', [[-1, 10, 140, 150], [20, 10, 200, 150],
                                     [20, 10, 20, 150], [20, 10, float('nan'), 150]])
def test_invalid_boxes_do_not_create_masks(bad_box):
    from identity_edge_lighting import edge_lighting_candidate
    image, labels = fixture_pixels()
    with pytest.raises(ValueError):
        edge_lighting_candidate(image, labels, POINTS, bad_box, .3, scene=scene_fixture())


def test_skin_outside_the_target_face_cannot_establish_a_neck_contact():
    from identity_edge_lighting import edge_lighting_candidate
    image, labels = fixture_pixels()
    labels[labels == 17] = 0
    # A false neck touches unrelated skin outside the permitted face ellipse;
    # there is a one-pixel background gap to the actual face at x=25.
    labels[120:170, 20:24] = 17
    labels[120:170, 19] = 1
    with pytest.raises(ValueError):
        edge_lighting_candidate(image, labels, POINTS, BOX, .65, scene=scene_fixture())


def test_scene_not_selected_neck_drives_correction_direction():
    from identity_edge_lighting import edge_lighting_candidate
    # The selected neck is darker, but the trustworthy scene is brighter.
    # Reusing selected-image neck means would incorrectly darken this face.
    image, labels = fixture_pixels(face=150, neck=100)
    result, info = edge_lighting_candidate(image, labels, POINTS, BOX, .65,
                                          scene=scene_fixture(face=180, neck=100))
    delta = np.asarray(result).astype(int) - np.asarray(image).astype(int)
    assert delta.min() == 0 and 0 < delta.max() <= 8
    assert info['sceneResidual']['candidateMeanAbsoluteLuma'] < info['sceneResidual']['baselineMeanAbsoluteLuma']
    assert info['settings']['maxChannelDelta'] == 8


def test_identical_scene_with_real_face_neck_contrast_is_unchanged():
    from identity_edge_lighting import edge_lighting_candidate
    image, labels = fixture_pixels(face=150, neck=100)
    result, info = edge_lighting_candidate(image, labels, POINTS, BOX, .65, scene=image.copy())
    assert result.tobytes() == image.tobytes()
    assert info['status'] == 'unchanged'
    assert info['reasonCode'] == 'NO_LIGHTING_RESIDUAL'
    assert info['sceneResidual']['baselineMeanAbsoluteLuma'] == 0


@pytest.mark.parametrize('patch_rgb', [(150, 150, 150), (149, 149, 149), (151, 150, 150)])
def test_nearby_lighting_residual_cannot_worsen_a_local_scene_match(patch_rgb):
    from identity_edge_lighting import edge_lighting_candidate
    image, labels = fixture_pixels(face=150)
    scene_pixels = np.asarray(scene_fixture(face=180)).copy()
    # A small jaw patch already matches the scene, needs the opposite sign, or
    # needs less than one RGB level. Nearby skin still needs brightening. This
    # reproduces local regressions hidden by an improving regional mean.
    scene_pixels[126:133, 70:90] = patch_rgb
    scene = Image.fromarray(scene_pixels)
    selected_bytes, scene_bytes = image.tobytes(), scene.tobytes()
    result, info = edge_lighting_candidate(image, labels, POINTS, BOX, .65, scene=scene)
    before, after = np.asarray(image).astype(float), np.asarray(result).astype(float)
    luma = lambda pixels: (.2126 * pixels[..., 0] + .7152 * pixels[..., 1]
                           + .0722 * pixels[..., 2])
    old_error = np.abs(luma(scene_pixels) - luma(before))
    new_error = np.abs(luma(scene_pixels) - luma(after))
    assert np.all(new_error <= old_error + 1e-10)
    assert np.array_equal(after[126:133, 70:90], before[126:133, 70:90])
    assert (after > before).any()  # A valid surrounding correction is retained.
    assert info['diagnostics']['retention']['protected']['changedPixels'] == 0
    assert info['diagnostics']['retention']['outsideEdit']['changedPixels'] == 0
    assert image.tobytes() == selected_bytes and scene.tobytes() == scene_bytes


@pytest.mark.parametrize('mode', ['missing', 'not-found', 'different-size', 'rgba'])
def test_scene_is_required_and_checked_before_model_loading(mode, monkeypatch, tmp_path):
    import identity_edge_lighting as edge
    image, _ = fixture_pixels()
    def forbidden(*args): pytest.fail('invalid scene must not initialize inference')
    monkeypatch.setattr(edge, 'target_geometry', forbidden)
    if mode == 'missing': item = {}
    elif mode == 'not-found': item = {'scenePath': str(tmp_path / 'absent.png')}
    elif mode == 'different-size': item = scene_item(tmp_path, Image.new('RGB', (40, 40)))
    else: item = scene_item(tmp_path, Image.new('RGBA', image.size))
    with pytest.raises(ValueError, match='场景'):
        edge.improve_edge_lighting({}, item, image, .3, lambda _: None)


def test_changed_scene_does_not_change_the_protected_or_outside_pixels():
    from identity_edge_lighting import edge_lighting_candidate
    image, labels = fixture_pixels()
    scene = scene_fixture(face=20, neck=250)
    before_scene = scene.tobytes()
    result, info = edge_lighting_candidate(image, labels, POINTS, BOX, .65, scene=scene)
    assert result.tobytes() != image.tobytes()
    assert info['diagnostics']['retention']['protected']['exactRetentionFraction'] == 1
    assert info['diagnostics']['retention']['outsideEdit']['exactRetentionFraction'] == 1
    assert scene.tobytes() == before_scene
    assert info['scene']['pixelSha256'] == hashlib.sha256(scene.tobytes()).hexdigest()


def test_low_level_candidate_rejects_scene_dimension_mismatch():
    from identity_edge_lighting import edge_lighting_candidate
    image, labels = fixture_pixels()
    with pytest.raises(ValueError, match='场景'):
        edge_lighting_candidate(image, labels, POINTS, BOX, .3, scene=Image.new('RGB', (30, 30)))


def test_adapter_scene_is_independent_of_selected_source_path(monkeypatch, tmp_path):
    import identity_edge_lighting as edge
    import identity_face_region
    image, labels = fixture_pixels(face=150, neck=100)
    selected_path = tmp_path / 'selected-refinement.png'
    image.save(selected_path)
    monkeypatch.setattr(edge, 'target_geometry', lambda *_: (BOX, POINTS))
    class Parser:
        def __init__(self, config): pass
        def labels(self, selected, box): return labels
    monkeypatch.setattr(identity_face_region, 'FaceRegionParser', Parser)
    item = {**scene_item(tmp_path, scene_fixture(face=180, neck=100)),
            'sourcePath': str(selected_path)}
    result, info = edge.improve_edge_lighting({}, item, image, .65, lambda _: None)
    delta = np.asarray(result).astype(int) - np.asarray(image).astype(int)
    assert delta.min() == 0 and delta.max() > 0
    assert info['scene']['fileSha256'] != hashlib.sha256(selected_path.read_bytes()).hexdigest()
    item['scenePath'] = str(selected_path)
    unchanged, details = edge.improve_edge_lighting({}, item, image, .65, lambda _: None)
    assert unchanged.tobytes() == image.tobytes()
    assert details['reasonCode'] == 'NO_LIGHTING_RESIDUAL'
    assert details['diagnostics']['retention']['protected']['exactRetentionFraction'] == 1
