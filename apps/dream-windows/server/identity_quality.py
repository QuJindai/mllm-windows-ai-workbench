"""CPU-only pixel diagnostics; no face recognition, perceptual score or ranking.

Inputs must already be registered, same-size, 8-bit RGB. Masks are bool/uint8
at native resolution. Every nonzero mask pixel is support (including feathers).
No resize, alignment, colour-management or alpha compositing is performed here.
"""
from __future__ import annotations

import numpy as np


SCOPE = (
    'Registered RGB pixel diagnostics only; not identity similarity or a quality ranking. '
    'Texture and seam values depend on resolution, content and masks. '
    'Luma is encoded RGB weighted by Rec.709 coefficients, not physical luminance.'
)


def _rgb(image):
    if hasattr(image, 'mode') and image.mode != 'RGB':
        raise ValueError('image must be RGB; preprocess colour/alpha explicitly')
    pixels = np.asarray(image)
    if (pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 3
            or min(pixels.shape[:2]) < 1):
        raise ValueError('image must be nonempty uint8 RGB')
    return pixels.astype(np.float64)


def _mask(mask, shape):
    if mask is None:
        return None
    values = np.asarray(mask)
    if values.shape != shape or values.dtype not in (np.dtype('bool'), np.dtype('uint8')):
        raise ValueError('mask must be native-size 2D bool or uint8')
    return values > 0


def _luma(rgb):
    return rgb @ np.array([.2126, .7152, .0722])


def _mean(values):
    return float(np.mean(values)) if values.size else None


def _regions(shape, edit, protected):
    return {'whole': np.ones(shape, dtype=bool), 'protected': protected,
            'editSupport': edit, 'outsideEdit': None if edit is None else ~edit}


def _texture(rgb, selected):
    if selected is None:
        return None
    luma = _luma(rgb)
    horizontal = selected[:, 1:] & selected[:, :-1]
    vertical = selected[1:, :] & selected[:-1, :]
    neighbors = np.concatenate((np.abs(np.diff(luma, axis=1))[horizontal],
                                np.abs(np.diff(luma, axis=0))[vertical]))
    # A complete 3x3 neighborhood must belong to this region; neither the canvas
    # boundary nor a mask edge should masquerade as intrinsic texture.
    core = selected[1:-1, 1:-1].copy()
    height, width = core.shape
    for dy in range(3):
        for dx in range(3):
            core &= selected[dy:dy + height, dx:dx + width]
    laplacian = (luma[:-2, 1:-1] + luma[2:, 1:-1] + luma[1:-1, :-2]
                 + luma[1:-1, 2:] - 4 * luma[1:-1, 1:-1])[core]
    pixels = rgb[selected]
    return {'pixelCount': int(selected.sum()), 'meanLuma': _mean(luma[selected]),
            'lumaStdDev': float(luma[selected].std()) if pixels.size else None,
            'channelEndpointFraction': _mean((pixels == 0) | (pixels == 255)),
            'neighborPairCount': int(neighbors.size),
            'meanAbsLumaNeighborDifference': _mean(neighbors),
            'laplacianPixelCount': int(laplacian.size),
            'laplacianVariance': float(laplacian.var()) if laplacian.size else None}


def image_diagnostics(image, *, edit_mask=None, protected_mask=None):
    """Describe whole/selected-region texture and encoded brightness, no score."""
    rgb = _rgb(image)
    shape = rgb.shape[:2]
    edit, protected = _mask(edit_mask, shape), _mask(protected_mask, shape)
    return {'schemaVersion': 1, 'scope': SCOPE, 'width': shape[1], 'height': shape[0],
            'maskRule': 'nonzero-support',
            'regions': {name: _texture(rgb, selected) for name, selected
                        in _regions(shape, edit, protected).items()}}


def _retention(delta, selected):
    if selected is None:
        return None
    values = np.abs(delta[selected])
    count = int(selected.sum())
    changed = int(np.any(values != 0, axis=1).sum())
    return {'pixelCount': count, 'changedPixels': changed,
            'exactRetentionFraction': (count - changed) / count if count else None,
            'meanAbsoluteRgbDelta': _mean(values),
            'maxAbsoluteRgbDelta': float(values.max()) if count else None}


def _seam(before, after, support):
    if support is None:
        return None
    before_edges, after_edges = [], []
    # Every 4-connected edge crossing support is counted once, on either side
    # of a ring. Image borders and diagonal contacts are not seam observations.
    for axis in (0, 1):
        crossing = np.diff(support.astype(np.int8), axis=axis) != 0
        before_edges.append(np.diff(before, axis=axis)[crossing])
        after_edges.append(np.diff(after, axis=axis)[crossing])
    old, new = np.concatenate(before_edges), np.concatenate(after_edges)
    old_mean, new_mean = _mean(np.abs(old)), _mean(np.abs(new))
    return {'edgeCount': len(old), 'baselineMeanAbsRgbJump': old_mean,
            'candidateMeanAbsRgbJump': new_mean,
            'meanAbsRgbJumpChange': None if old_mean is None else new_mean - old_mean,
            'meanAbsResidualRgbJump': _mean(np.abs(new - old))}


def compare_images(baseline, candidate, *, edit_mask=None, protected_mask=None,
                   baseline_label='baseline', candidate_label='candidate'):
    """Compare registered images against the explicitly named pixel baseline.

    Pass an anchored stage as baseline to audit protected-face-v3 polishing.
    Comparing original scene to final instead describes the entire replacement.
    Missing regions are None; empty-region fractions/means are None, never 1/0.
    """
    before, after = _rgb(baseline), _rgb(candidate)
    if before.shape != after.shape:
        raise ValueError('paired image dimensions must match; no automatic alignment')
    shape = before.shape[:2]
    edit, protected = _mask(edit_mask, shape), _mask(protected_mask, shape)
    delta = after - before
    return {'schemaVersion': 1, 'scope': SCOPE,
            'baselineLabel': str(baseline_label), 'candidateLabel': str(candidate_label),
            'baseline': image_diagnostics(baseline, edit_mask=edit, protected_mask=protected),
            'candidate': image_diagnostics(candidate, edit_mask=edit, protected_mask=protected),
            'retention': {name: _retention(delta, selected) for name, selected
                          in _regions(shape, edit, protected).items()},
            'lighting': {'meanLumaDelta': float(_luma(delta).mean()),
                         'meanAbsoluteLumaDelta': float(np.abs(_luma(delta)).mean()),
                         'meanRgbDelta': delta.mean(axis=(0, 1)).tolist()},
            'seam': _seam(before, after, edit)}
