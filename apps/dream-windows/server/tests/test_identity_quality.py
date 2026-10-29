"""Synthetic counterexamples: retention, illumination steps and lost texture."""
import json

import numpy as np
from PIL import Image, ImageFilter
import pytest


def test_retention_counts_changed_pixels_not_channels_and_respects_soft_mask_support():
    from identity_quality import compare_images
    before = np.full((8, 8, 3), 50, dtype=np.uint8)
    after = before.copy()
    edit = np.zeros((8, 8), dtype=np.uint8)
    edit[2:6, 2:6] = 1  # Nonzero feather pixels belong to the edit support.
    protected = np.zeros((8, 8), dtype=bool)
    protected[3:5, 3:5] = True
    after[3, 3] += 30
    after[0, 0, 0] += 24
    report = compare_images(before, after, edit_mask=edit, protected_mask=protected,
                            baseline_label='anchor', candidate_label='pass-1')
    assert report['baselineLabel'] == 'anchor'
    assert report['candidateLabel'] == 'pass-1'
    keep = report['retention']['protected']
    assert keep['pixelCount'] == 4
    assert keep['changedPixels'] == 1
    assert keep['exactRetentionFraction'] == .75
    assert keep['meanAbsoluteRgbDelta'] == 7.5
    assert report['retention']['outsideEdit']['pixelCount'] == 48
    assert report['retention']['outsideEdit']['changedPixels'] == 1
    assert report['retention']['outsideEdit']['meanAbsoluteRgbDelta'] == pytest.approx(1 / 6)
    assert before[3, 3].tolist() == [50, 50, 50]
    assert 'identityScore' not in report and 'score' not in report
    json.dumps(report, allow_nan=False)


def test_added_seam_is_distinguished_from_an_existing_scene_edge():
    from identity_quality import compare_images
    before = np.full((10, 10, 3), 40, dtype=np.uint8)
    mask = np.zeros((10, 10), dtype=np.uint8)
    mask[:, 5:] = 255
    after = before.copy()
    after[:, 5:] = 100
    seam = compare_images(before, after, edit_mask=mask)['seam']
    assert seam['edgeCount'] == 10  # Do not count the canvas border.
    assert seam['baselineMeanAbsRgbJump'] == 0
    assert seam['candidateMeanAbsRgbJump'] == 60
    assert seam['meanAbsRgbJumpChange'] == 60
    assert seam['meanAbsResidualRgbJump'] == 60
    unchanged = compare_images(after, after, edit_mask=mask)['seam']
    assert unchanged['candidateMeanAbsRgbJump'] == 60
    assert unchanged['meanAbsResidualRgbJump'] == 0


def test_uniform_exposure_change_is_not_called_an_added_seam():
    from identity_quality import compare_images
    mask = np.zeros((8, 8), dtype=np.uint8)
    mask[:, 4:] = 255
    report = compare_images(Image.new('RGB', (8, 8), (40, 40, 40)),
                            Image.new('RGB', (8, 8), (60, 60, 60)), edit_mask=mask)
    assert report['seam']['meanAbsResidualRgbJump'] == 0
    assert report['lighting']['meanLumaDelta'] == pytest.approx(20)


def test_texture_describes_blur_without_promising_identity_or_quality():
    from identity_quality import image_diagnostics
    pixels = np.zeros((64, 64, 3), dtype=np.uint8)
    pixels[::2, ::2] = 220
    pixels[1::2, 1::2] = 220
    original = Image.fromarray(pixels)
    blurred = original.filter(ImageFilter.GaussianBlur(2))
    sharp = image_diagnostics(original)['regions']['whole']
    soft = image_diagnostics(blurred)['regions']['whole']
    assert sharp['laplacianVariance'] > soft['laplacianVariance'] * 100
    assert sharp['meanAbsLumaNeighborDifference'] > soft['meanAbsLumaNeighborDifference'] * 20


def test_region_texture_does_not_count_mask_boundary_as_skin_detail():
    from identity_quality import image_diagnostics
    pixels = np.zeros((10, 10, 3), dtype=np.uint8)
    pixels[2:8, 2:8] = 200
    mask = np.zeros((10, 10), dtype=bool)
    mask[2:8, 2:8] = True
    region = image_diagnostics(pixels, protected_mask=mask)['regions']['protected']
    assert region['meanAbsLumaNeighborDifference'] == 0
    assert region['laplacianVariance'] == 0
    assert region['laplacianPixelCount'] == 16


def test_missing_empty_and_full_masks_are_not_false_perfect_retention():
    from identity_quality import compare_images
    image = Image.new('RGB', (8, 8), 'gray')
    missing = compare_images(image, image)
    assert missing['retention']['protected'] is None
    assert missing['retention']['outsideEdit'] is None
    assert missing['seam'] is None
    empty = compare_images(image, image, edit_mask=np.ones((8, 8), dtype=bool),
                           protected_mask=np.zeros((8, 8), dtype=bool))
    assert empty['retention']['protected']['pixelCount'] == 0
    assert empty['retention']['protected']['exactRetentionFraction'] is None
    assert empty['retention']['outsideEdit']['exactRetentionFraction'] is None
    assert empty['seam']['edgeCount'] == 0
    assert empty['seam']['candidateMeanAbsRgbJump'] is None
    json.dumps(empty, allow_nan=False)


@pytest.mark.parametrize('bad', [np.zeros((4, 4), dtype=np.uint8),
                                    np.ones((8, 8), dtype=float),
                                    np.zeros((8, 8, 3), dtype=np.uint8)])
def test_invalid_masks_are_rejected_without_resizing_or_threshold_guessing(bad):
    from identity_quality import compare_images
    with pytest.raises(ValueError, match='mask'):
        compare_images(Image.new('RGB', (8, 8)), Image.new('RGB', (8, 8)), edit_mask=bad)


def test_different_size_and_transparent_inputs_require_explicit_preprocessing():
    from identity_quality import compare_images
    with pytest.raises(ValueError, match='dimensions'):
        compare_images(Image.new('RGB', (8, 8)), Image.new('RGB', (9, 8)))
    with pytest.raises(ValueError, match='RGB'):
        compare_images(Image.new('RGBA', (8, 8)), Image.new('RGB', (8, 8)))


@pytest.mark.parametrize('size', [(1, 1), (1, 4), (4, 1), (2, 2)])
def test_tiny_images_have_no_invented_texture_neighborhoods(size):
    from identity_quality import image_diagnostics
    result = image_diagnostics(Image.new('RGB', size, 'white'))
    assert result['regions']['whole']['laplacianPixelCount'] == 0
    assert result['regions']['whole']['laplacianVariance'] is None
    json.dumps(result, allow_nan=False)
