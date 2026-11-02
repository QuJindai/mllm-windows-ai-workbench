"""CPU tests of bounded, pixel-preserving DWPose border recovery."""
import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

from hq_tryon_conditioning import PipelineError, dwpose_white_context, estimate_dwpose_body


@pytest.fixture
def case(tmp_path):
    image = Image.new('RGB', (96, 128), 'white')
    ImageDraw.Draw(image).line([(48, 16), (30, 60), (62, 110)], fill='black', width=3)
    points = np.full((1, 133, 2), (48., 64.))
    points[0, 5:17] = np.column_stack([np.linspace(30, 66, 12), np.linspace(22, 105, 12)])
    scores = np.full((1, 133), .8)
    saved = []

    def save(name, value, transform):
        path = tmp_path / (name + '.png')
        with path.open('xb') as stream:
            value.save(stream, format='PNG')
        saved.append(path)
        return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'width': value.width, 'height': value.height, 'transform': transform}

    source = save('pose-input', image, 'native-test-image')
    run = SimpleNamespace(audit={'conditioning': {}, 'preprocessing': {'pose': source}},
                          check_cancel=lambda: None, save_image=save)
    return SimpleNamespace(image=image, points=points, scores=scores, run=run, saved=saved)


@pytest.mark.parametrize('size', [(96, 128), (400, 80), (80, 400)])
def test_white_context_preserves_all_pixels_bbox_and_affine_footprint(size):
    original = Image.new('RGB', size, 'white')
    original.putpixel((size[0] // 2, size[1] // 2), (0, 0, 0))
    padded, bbox, meta = dwpose_white_context(original)
    x, y = meta['offset']
    assert bbox == [x, y, x + size[0], y + size[1]]
    assert np.array_equal(np.asarray(padded)[y:y + size[1], x:x + size[0]], np.asarray(original))
    pixels = np.asarray(padded).copy()
    pixels[y:y + size[1], x:x + size[0]] = 255
    assert np.all(pixels == 255)
    sx, sy = max(size[0] * 1.25, size[1] * 1.25 * .75), max(size[1] * 1.25, size[0] * 1.25 / .75)
    center = np.array([x + size[0] / 2, y + size[1] / 2])
    assert np.all(center - np.array([sx, sy]) / 2 >= 0)
    assert np.all(center + np.array([sx, sy]) / 2 <= padded.size)


@pytest.mark.parametrize('background', ['black', 'gray', 'white'])
def test_empty_or_nonwhite_frames_have_no_border_retry(background):
    assert dwpose_white_context(Image.new('RGB', (96, 128), background)) is None


def test_native_success_does_not_retry_or_change_coordinates(case):
    calls = []
    def infer(pixels, bbox):
        calls.append(bbox)
        return case.points.copy(), case.scores.copy()
    body, points, scores = estimate_dwpose_body(case.image, infer, case.run)
    np.testing.assert_array_equal(points, case.points)
    np.testing.assert_array_equal(scores, case.scores)
    assert body.shape == (18, 3) and calls == [[]] and len(case.saved) == 1
    assert case.run.audit['conditioning']['pose']['selectedAttempt'] == 0


def retry_estimator(case, candidate_score=.6, displacement=0.):
    calls = []
    def infer(pixels, bbox):
        calls.append(bbox)
        points, scores = case.points.copy(), case.scores.copy()
        if not bbox:
            scores[0, 7] = .29
        else:
            left, top, right, bottom = bbox[0]
            np.testing.assert_array_equal(pixels[top:bottom, left:right], np.asarray(case.image))
            points += np.array([left, top])
            points[0, 8, 0] += displacement
            scores[0, 7] = candidate_score
        return points, scores
    return infer, calls


def test_retry_keeps_original_coordinates_and_records_both_real_responses(case):
    infer, calls = retry_estimator(case)
    _, points, scores = estimate_dwpose_body(case.image, infer, case.run)
    np.testing.assert_allclose(points, case.points, rtol=0, atol=1e-12)
    assert scores[0, 7] == .6 and len(calls) == 2
    record = case.run.audit['conditioning']['pose']
    assert record['estimationStatus'] == 'accepted' and record['selectedAttempt'] == 1
    assert record['attempts'][0]['accepted'] is False
    assert record['attempts'][0]['error']['details']['weakJoints'] == [{'joint': 'left-elbow', 'score': .29}]
    assert record['attempts'][1]['accepted'] is True
    assert record['requiredLimbScore'] == .3
    assert record['borderRetry']['agreement']['nativeAnchorCount'] == 11
    assert len(case.saved) == 2
    json.dumps(record, allow_nan=False)


def test_retry_does_not_lower_score_gate_or_invent_missing_joint(case):
    infer, calls = retry_estimator(case, candidate_score=.299)
    with pytest.raises(PipelineError) as failure:
        estimate_dwpose_body(case.image, infer, case.run)
    assert failure.value.code == 'POSE_LOW_CONFIDENCE'
    record = case.run.audit['conditioning']['pose']
    assert len(calls) == 2 and record['estimationStatus'] == 'rejected'
    assert 'selectedAttempt' not in record
    assert record['attempts'][1]['bodyScores'][7] == .299


def test_retry_cannot_move_reliable_joints_to_a_different_pose(case):
    infer, calls = retry_estimator(case, displacement=20.)
    with pytest.raises(PipelineError, match='disagrees'):
        estimate_dwpose_body(case.image, infer, case.run)
    record = case.run.audit['conditioning']['pose']
    assert len(calls) == 2 and record['estimationStatus'] == 'rejected'
    assert record['attempts'][-1]['accepted'] is False
    assert record['borderRetry']['agreement']['maximumDisplacementImageDiagonal'] > .05


def test_insufficient_native_anchors_cannot_be_rescued(case):
    calls = []
    def infer(pixels, bbox):
        calls.append(bbox)
        return case.points.copy(), np.full((1, 133), .1)
    with pytest.raises(PipelineError):
        estimate_dwpose_body(case.image, infer, case.run)
    assert calls == [[]] and len(case.saved) == 1
    assert case.run.audit['conditioning']['pose']['retrySkippedReason'] == 'fewer-than-six-native-limb-anchors'


def test_nonwhite_input_is_not_repainted_to_gain_confidence(case):
    image = case.image.copy()
    ImageDraw.Draw(image).rectangle((0, 0, 95, 2), fill='black')
    infer, calls = retry_estimator(case)
    with pytest.raises(PipelineError):
        estimate_dwpose_body(image, infer, case.run)
    assert calls == [[]] and len(case.saved) == 1


@pytest.mark.parametrize('bad', ['nan', 'shape'])
def test_invalid_model_response_is_not_retried_and_audit_remains_json_safe(case, bad):
    calls = []
    def infer(pixels, bbox):
        calls.append(bbox)
        points, scores = case.points.copy(), case.scores.copy()
        if bad == 'nan':
            scores[0, 7] = np.nan
        else:
            points = points[:, :132]
        return points, scores
    with pytest.raises(PipelineError):
        estimate_dwpose_body(case.image, infer, case.run)
    assert calls == [[]]
    json.dumps(case.run.audit, allow_nan=False)


def test_cancellation_before_retry_does_not_execute_another_estimator(case):
    infer, calls = retry_estimator(case)
    checks = []
    def cancel():
        checks.append(True)
        if len(checks) == 2:
            raise PipelineError('CANCELLED', 'cancelled before retry')
    case.run.check_cancel = cancel
    with pytest.raises(PipelineError) as failure:
        estimate_dwpose_body(case.image, infer, case.run)
    assert failure.value.code == 'CANCELLED' and calls == [[]] and len(case.saved) == 1
