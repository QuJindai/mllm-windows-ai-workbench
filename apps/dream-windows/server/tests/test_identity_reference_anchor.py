"""Reference alignment must preserve pose, boundaries and non-face pixels."""
import numpy as np
from PIL import Image
import pytest


POINTS = np.array([[45., 55.], [95., 55.], [70., 80.], [52., 105.], [88., 105.]])


def test_similarity_alignment_reconstructs_rotation_without_mirroring():
    from identity_reference_anchor import similarity_alignment
    angle = .22
    linear = 1.3 * np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    target = POINTS @ linear.T + [35, 9]
    matrix, error = similarity_alignment(POINTS, target)
    np.testing.assert_allclose(np.column_stack([POINTS, np.ones(5)]) @ matrix[:2].T, target, atol=1e-6)
    assert np.linalg.det(matrix[:2,:2]) > 0 and error < 1e-8


@pytest.mark.parametrize('invalid', [np.zeros((5,2)), [[1,2]], np.full((5,2), float('nan'))])
def test_invalid_landmarks_are_rejected(invalid):
    from identity_reference_anchor import similarity_alignment
    with pytest.raises(ValueError): similarity_alignment(invalid, POINTS)


def test_pose_mismatch_is_not_forced_into_a_face():
    from identity_reference_anchor import similarity_alignment
    target = POINTS.copy()
    target[2] += [40, 15]
    with pytest.raises(ValueError, match='姿态'): similarity_alignment(POINTS, target)


def test_reference_initialization_changes_face_but_preserves_outside_exactly():
    from identity_reference_anchor import align_reference_face
    from identity_anime import face_mask
    source = Image.new('RGB', (160,160), (200,90,70))
    target = Image.new('RGB', (200,200), (20,50,90))
    box = [30., 20., 140., 150.]
    result, info = align_reference_face(source,target,POINTS,POINTS,box,.95)
    mask = np.asarray(face_mask(target.size,box))
    assert np.array_equal(np.asarray(result)[mask==0],np.asarray(target)[mask==0])
    assert np.asarray(result)[80,70,0] > 170
    assert result.size == target.size and info['anchorStrength'] == .95
    assert info['alignmentError'] < 1e-8
    assert 'similarity' not in info


@pytest.mark.parametrize('strength', [-1., .1, 1.1, float('nan'), True])
def test_anchor_strength_is_finite_bounded_and_not_boolean(strength):
    from identity_reference_anchor import align_reference_face
    image=Image.new('RGB',(160,160))
    with pytest.raises(ValueError): align_reference_face(image,image,POINTS,POINTS,[20,20,140,150],strength)


def test_transformed_reference_never_adds_black_outside_its_canvas():
    from identity_reference_anchor import align_reference_face
    source=Image.new('RGB',(160,160),(210,110,80))
    target=Image.new('RGB',(250,220),(30,60,90))
    result,_=align_reference_face(source,target,POINTS,POINTS+[100,0],[100,20,249,160],1.)
    assert np.min(np.asarray(result)) >= 30


def test_anchor_can_only_select_one_target_face(monkeypatch):
    from identity_reference_anchor import ReferenceAnchor
    anchor=ReferenceAnchor.__new__(ReferenceAnchor)
    anchor.detector=type('Detector',(),{'detect':lambda self, image, **kw:(np.array([[1,1,50,70,.99],[80,1,120,70,.99]]),np.array([POINTS,POINTS]))})()
    with pytest.raises(ValueError,match='多个'): anchor.apply(Image.new('RGB',(200,200)),.95)


def test_missing_reference_pixels_cannot_be_reported_as_alignment_success():
    from identity_reference_anchor import align_reference_face
    image=Image.new('RGB',(160,160))
    with pytest.raises(ValueError,match='覆盖'):
        align_reference_face(image,image,POINTS+1000,POINTS,[20,20,140,150],.95)
