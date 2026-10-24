import numpy as np
from PIL import Image
import pytest


def test_parsenet_skin_excludes_hair_ears_neck_and_keeps_both_brows():
    from identity_face_region import skin_labels
    selected = skin_labels(np.arange(19).reshape(1, 19))
    assert selected[0, 6] and selected[0, 7]
    assert not selected[0, 13]  # ParseNet hair, NOT BiSeNet lower lip.
    assert not selected[0, [0, 8, 9, 14, 15, 16, 17, 18]].any()


def test_destructive_patch_cannot_change_features_or_hair_even_after_two_passes():
    from identity_face_region import region_masks, composite_region
    labels = np.zeros((160, 160), dtype=np.uint8)
    labels[20:140, 25:135] = 1
    labels[45:50, 45:63] = 6
    labels[45:50, 97:115] = 7
    points = np.array([[55., 63.], [105., 63.], [80., 83.], [65., 108.], [95., 108.]])
    alpha, ring, protected = region_masks(labels, labels, points, [20, 10, 140, 150])
    pixels = np.asarray(ring)
    assert pixels.max() > 0 and not pixels[protected].any()
    assert np.all(protected[45:50, 45:63]) and np.all(protected[45:50, 97:115])
    original = Image.new('RGB', (160, 160), (30, 80, 150))
    current = original
    for _ in range(2):
        current = composite_region(current, Image.new('RGB', (160, 160), 'red'), (0, 0, 160, 160), ring)
    assert np.array_equal(np.asarray(current)[protected], np.asarray(original)[protected])
    assert np.array_equal(np.asarray(current)[labels == 0], np.asarray(original)[labels == 0])
    assert not np.array_equal(np.asarray(current)[pixels > 0], np.asarray(original)[pixels > 0])


def test_empty_or_feature_occluded_segmentation_cannot_be_called_protected():
    from identity_face_region import region_masks
    points = np.array([[55., 63.], [105., 63.], [80., 83.], [65., 108.], [95., 108.]])
    with pytest.raises(ValueError):
        region_masks(np.zeros((160,160), dtype=np.uint8), np.ones((160,160), dtype=np.uint8), points, [20,10,140,150])


def test_five_valid_points_do_not_hide_a_clipped_eyebrow():
    from identity_face_region import region_masks
    source = np.zeros((160,160), dtype=np.uint8)
    source[20:140,25:135] = 1
    source[40:46,45:65] = 6
    target = source.copy()
    target[40:46,45:56] = 13  # Occlusion misses the detector's five points.
    points = np.array([[55.,63.],[105.,63.],[80.,83.],[65.,108.],[95.,108.]])
    with pytest.raises(ValueError, match='五官'):
        region_masks(source,target,points,[20,10,140,150])


def test_edit_mask_fades_toward_protected_boundary_instead_of_hard_cut():
    import cv2
    from identity_face_region import region_masks
    labels = np.zeros((160,160), dtype=np.uint8)
    labels[20:140,25:135] = 1
    labels[40:46,45:65] = 6
    points = np.array([[55.,63.],[105.,63.],[80.,83.],[65.,108.],[95.,108.]])
    _, ring, protected = region_masks(labels,labels,points,[20,10,140,150])
    adjacent = (cv2.dilate(protected.astype('uint8'), np.ones((3,3),np.uint8))>0)&~protected
    assert np.asarray(ring)[adjacent].max() < 100


def test_normal_hairline_feathering_does_not_count_as_semantic_occlusion():
    from identity_face_region import region_masks
    labels = np.zeros((160,160), dtype=np.uint8)
    labels[20:140,25:135] = 1
    labels[21:24,65:95] = 6
    points = np.array([[55.,63.],[105.,63.],[80.,83.],[65.,108.],[95.,108.]])
    alpha, _, _ = region_masks(labels,labels,points,[20,10,140,150])
    assert (alpha[labels==6]<.8).all()
