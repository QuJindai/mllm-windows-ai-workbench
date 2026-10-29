"""Opt-in CPU face/neck edge-lighting candidate on the selected image.

Integration: improve_edge_lighting(config, item, image, strength, stage) returns
(RGB image, JSON-safe details). The parent owns version publication and selection.
No reference pixels, alignment, restorer, UNet, CUDA context or file writes are
used. Detection is SCRFD on CPU; parsing is the existing CPU FaceRegionParser.

Only face skin within the target-derived protected-v3 ring, near a directly
adjacent visible neck, may change. Neck pixels are never edits. The independent
immutable scene supplied by the parent is the lighting target. A smoothed local
scene-minus-selected luma residual supplies an additive offset, not blurred pixels.
Each quantized proposal must reduce that pixel's absolute scene-luma residual;
otherwise the selected pixel is retained. This is a local consistency guard,
not a perceptual quality test or a reason to alter the target-derived edit mask.
Strength .15..65 scales an 8-level ceiling; quantization can round a sub-level
bound up, but no channel can change by more than 8. Missing evidence raises;
an already balanced image returns status='unchanged' with honest diagnostics.
item['scenePath'] is required: original source-job PNG if available, otherwise
its generation result, resolved by the parent independently of selected sourcePath.
No fallback to the selected image or its neck is allowed. Equal source/scene
pixels have zero residual even if there is a natural face/neck lighting contrast.

ParseNet labels: https://github.com/xinntao/facexlib/blob/master/inference/inference_parsing_parsenet.py
1=skin, 16=necklace, 17=neck. Never borrow BiSeNet's different taxonomy.
This is a selectable appearance candidate, not an identity or quality guarantee.
"""
from __future__ import annotations

import hashlib
from io import BytesIO
import math
from pathlib import Path
from time import perf_counter

import numpy as np
from PIL import Image

from identity_quality import compare_images


def _strength(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not .15 <= value <= .65:
        raise ValueError('边缘光照强度必须为 0.15–0.65')
    return float(value)


def _pixels(image):
    if not isinstance(image, Image.Image) or image.mode != 'RGB' or min(image.size) < 16:
        raise ValueError('边缘光照需要原尺寸 RGB 图像')
    return np.asarray(image).astype(np.float64)


def target_geometry(config, image):
    """Run ReferenceAnchor's target-only detector without its reference constructor."""
    _pixels(image)
    root = config.get('insightfaceRoot')
    model = Path(root or '') / 'models/buffalo_l/det_10g.onnx'
    if not root or not model.is_file():
        raise ValueError('边缘光照检测模型未配置，请保留当前版本')
    import onnxruntime as ort
    from insightface.model_zoo.scrfd import SCRFD
    from identity_reference_anchor import ReferenceAnchor
    options = ort.SessionOptions()
    options.intra_op_num_threads, options.inter_op_num_threads = 2, 1
    session = ort.InferenceSession(str(model), sess_options=options, providers=['CPUExecutionProvider'])
    detector = SCRFD(str(model), session=session)
    detector.prepare(ctx_id=-1, input_size=(640, 640))
    # _target uses only .detector. Avoid __init__: it loads an unrelated reference
    # photo and detects its face, neither of which belongs to this selected edit.
    target = ReferenceAnchor.__new__(ReferenceAnchor)
    target.detector = detector
    return target._target(image)


def edge_lighting_masks(labels, points, box):
    """Return native masks derived from target labels/geometry, before pixel edits.

    The same target labels are passed twice to region_masks: no source reference
    or geometric warp participates. A visible skin-to-neck contact is required.
    """
    import cv2
    from identity_face_region import region_masks
    labels = np.asarray(labels)
    points, box = np.asarray(points, dtype=float), np.asarray(box, dtype=float)
    if (labels.ndim != 2 or min(labels.shape) < 16 or labels.dtype.kind not in 'ui'
            or labels.min() < 0 or labels.max() > 18):
        raise ValueError('目标 ParseNet 区域数据无效')
    height, width = labels.shape
    if (box.shape != (4,) or not np.isfinite(box).all()
            or not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height)
            or min(box[2:] - box[:2]) < 16):
        raise ValueError('目标脸区域无效')
    if (points.shape != (5, 2) or not np.isfinite(points).all()
            or np.any(points < box[:2]) or np.any(points >= box[2:])
            or np.linalg.norm(points[1] - points[0]) < 8
            or cv2.contourArea(cv2.convexHull(points.astype(np.float32))) < 64):
        raise ValueError('目标五点位置不可靠')
    alpha, ring, protected = region_masks(labels, labels, points, box.tolist())
    y, x = np.indices(labels.shape)
    face_size = float(min(box[2:] - box[:2]))
    feather = max(3., face_size * .08)
    mouth_y = float(points[3:, 1].mean())
    lower = y > mouth_y
    skin = (labels == 1) & (alpha > 0) & ~protected
    # Limit samples to the detected target, not another neck elsewhere on canvas.
    nearby = ((x >= box[0]) & (x < box[2]) & lower
              & (y < box[3] + .35 * face_size))
    neck = (labels == 17) & nearby
    cross = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    contact = neck & (cv2.dilate((skin & lower).astype(np.uint8), cross) > 0)
    if int(contact.sum()) < max(8, round(face_size * .08)):
        raise ValueError('缺少可靠的脸部与颈部接触边界，已保留当前版本')
    _, components = cv2.connectedComponents(neck.astype(np.uint8), connectivity=4)
    connected = np.unique(components[contact])
    neck &= np.isin(components, connected[connected != 0])
    distance = cv2.distanceTransform((~neck).astype(np.uint8), cv2.DIST_L2, 5)
    near_weight = np.clip((feather * 3 - distance) / feather, 0, 1)
    lower_weight = np.clip((y - mouth_y) / feather, 0, 1)
    edit = np.rint(np.asarray(ring).astype(float) * near_weight * lower_weight).astype(np.uint8)
    edit[~skin | protected] = 0
    if np.count_nonzero(edit) < 32:
        raise ValueError('缺少可用的下颌边缘区域，已保留当前版本')
    return {'edit': edit, 'protected': protected, 'neck': neck,
            'faceSamples': skin & lower & (distance < feather * 3),
            'faceContact': skin & lower,
            'sigma': max(3., face_size * .12)}


def _local_mean(luma, mask, sigma):
    import cv2
    weight = cv2.GaussianBlur(mask.astype(float), (0, 0), sigma)
    total = cv2.GaussianBlur(luma * mask, (0, 0), sigma)
    return np.divide(total, weight, out=np.zeros_like(total), where=weight > .01), weight


def _samples(luma, mask):
    import cv2
    # Erode semantic edges before testing contrast so clothing, hair or necklace
    # pixels cannot enter either local mean. Keep low-amplitude skin texture.
    interior = cv2.erode(mask.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    maximum = cv2.dilate(luma, np.ones((3, 3), np.uint8))
    minimum = cv2.erode(luma, np.ones((3, 3), np.uint8))
    return interior & ((maximum - minimum) <= 16)


def _mask_info(mask):
    values = np.ascontiguousarray(mask, dtype=np.uint8)
    return {'pixelCount': int(np.count_nonzero(values)), 'sha256': hashlib.sha256(values.tobytes()).hexdigest(),
            'width': values.shape[1], 'height': values.shape[0], 'encoding': 'uint8-row-major'}


def _boundary(before, after, skin, neck):
    old, new = [], []
    for axis in (0, 1):
        a, b = (slice(None, -1), slice(1, None))
        if axis == 0:
            crossing = (skin[a, :] & neck[b, :]) | (neck[a, :] & skin[b, :])
        else:
            crossing = (skin[:, a] & neck[:, b]) | (neck[:, a] & skin[:, b])
        old.extend(np.abs(np.diff(before, axis=axis))[crossing].tolist())
        new.extend(np.abs(np.diff(after, axis=axis))[crossing].tolist())
    return {'edgeCount': len(old), 'baselineMeanAbsLumaJump': float(np.mean(old)) if old else None,
            'candidateMeanAbsLumaJump': float(np.mean(new)) if new else None,
            'scope': 'Observed target skin/neck contacts; lower is not a universal quality ranking'}


def edge_lighting_candidate(image, labels, points, box, strength=.3, *, scene):
    """Pure CPU candidate; scene must be the independent, registered source scene.

    Dimensions/encoding must match. Neither inputs nor masks are aligned/resized.
    Geometry and masks come from selected image parsing, never from changed pixels.
    """
    strength = _strength(strength)
    rgb = _pixels(image)
    try:
        scene_rgb = _pixels(scene)
    except ValueError as exc:
        raise ValueError('不可用的原始场景 RGB 图像') from exc
    if scene_rgb.shape != rgb.shape:
        raise ValueError('原始场景与选中图像尺寸不一致，未自动缩放')
    if np.asarray(labels).shape != rgb.shape[:2]:
        raise ValueError('目标区域与图像尺寸不一致')
    masks = edge_lighting_masks(labels, points, box)
    luma = rgb @ np.array([.2126, .7152, .0722])
    scene_luma = scene_rgb @ np.array([.2126, .7152, .0722])
    residual = scene_luma - luma
    # Both images must be locally smooth at a current-image skin sample. This
    # excludes shape/texture edges from fitting without treating colour averages
    # as identity validation or inferring a new mask from changed pixels.
    face_samples = (_samples(luma, masks['faceSamples'])
                    & _samples(scene_luma, masks['faceSamples']))
    if int(face_samples.sum()) < 32:
        raise ValueError('平稳皮肤采样不足，已保留当前版本')
    smoothed_residual, sample_weight = _local_mean(residual, face_samples, masks['sigma'])
    supported = sample_weight > .01
    edit = masks['edit'].copy()
    edit[~supported] = 0
    if np.count_nonzero(edit) < 32:
        raise ValueError('局部场景光照证据不足，已保留当前版本')
    bound = 8 * strength / .65
    correction = np.clip(smoothed_residual, -bound, bound) * (edit.astype(float) / 255)
    result_pixels = np.clip(np.rint(rgb + correction[..., None]), 0, 255).astype(np.uint8)
    frozen = (edit == 0) | masks['protected']
    result_pixels[frozen] = np.asarray(image)[frozen]
    # Nearby residuals can have the opposite sign, or overwhelm an already
    # matching pixel. Check the actual quantized/clipped proposal, not only its
    # floating offset or a regional mean. Keep masks independent of acceptance.
    proposed = np.any(result_pixels != rgb, axis=2)
    proposed_luma = result_pixels @ np.array([.2126, .7152, .0722])
    rejected = proposed & (np.abs(scene_luma - proposed_luma) >= np.abs(residual) - 1e-10)
    result_pixels[rejected] = np.asarray(image)[rejected]
    result = Image.fromarray(result_pixels)
    diagnostics = compare_images(image, result, edit_mask=edit, protected_mask=masks['protected'],
                                 baseline_label='selected-source', candidate_label='edge-lighting')
    changed = diagnostics['retention']['whole']['changedPixels']
    edited_support = edit > 0
    result_luma = result_pixels @ np.array([.2126, .7152, .0722])
    return result, {'mode': 'edge-lighting', 'method': 'immutable-scene-luma-ring-v3', 'device': 'CPU',
        'status': 'complete' if changed else 'unchanged', 'strength': strength,
        'reasonCode': None if changed else ('NO_LIGHTING_RESIDUAL' if not np.any(residual[edited_support])
                                            else 'NO_PIXEL_CHANGE_WITHIN_BOUND'),
        'maxAllowedChannelDelta': 8, 'scaledFloatBound': bound,
        'maxChannelDelta': diagnostics['retention']['whole']['maxAbsoluteRgbDelta'],
        'changedPixels': changed, 'sigmaPixels': masks['sigma'],
        'settings': {'strength': strength, 'maxChannelDelta': 8, 'scaledFloatBound': bound,
                     'sigmaPixels': masks['sigma'], 'sampleContrastLimit': 16,
                     'sampleRule': 'current-and-scene-low-gradient-current-skin',
                     'acceptanceRule': 'quantized-pixel-absolute-scene-luma-residual-must-decrease',
                     'minimumSamples': 32, 'minimumSmoothedSupport': .01},
        'localGuard': {'proposedChangedPixels': int(proposed.sum()),
                       'rejectedNonImprovingPixels': int(rejected.sum())},
        'scene': {'pixelSha256': hashlib.sha256(scene.tobytes()).hexdigest(),
                  'width': scene.width, 'height': scene.height, 'encoding': 'RGB-uint8-row-major',
                  'binding': 'parent-resolved-immutable-source-job-scene'},
        'selectedPixelSha256': hashlib.sha256(image.tobytes()).hexdigest(),
        'sceneResidual': {'samplePixelCount': int(face_samples.sum()),
                          'baselineMeanAbsoluteLuma': float(np.abs(residual[edited_support]).mean()),
                          'candidateMeanAbsoluteLuma': float(np.abs((scene_luma - result_luma)[edited_support]).mean()),
                          'scope': 'Current edit support versus supplied scene; not identity similarity'},
        'faceBox': [float(v) for v in box], 'targetLandmarks': np.asarray(points).tolist(),
        'maskProvenance': {'source': 'selected-image-target-parsing-and-five-landmarks',
                           'lightingTarget': 'immutable-scene',
                           'parser': 'ParseNet', 'skinLabel': 1, 'neckLabel': 17,
                           'protection': 'central-features-v1', 'editSupportRule': 'nonzero-native-mask'},
        'masks': {'edit': _mask_info(edit), 'protected': _mask_info(masks['protected']),
                  'faceSamples': _mask_info(face_samples), 'neckRegion': _mask_info(masks['neck'])},
        'boundary': _boundary(luma, result_luma,
                              masks['faceContact'], masks['neck']),
        'diagnostics': diagnostics,
        'scope': 'Bounded face-side lighting candidate using the immutable source-job scene; '
                 'neck and protected/outside pixels are unchanged. Not an identity score or automatic quality decision.'}


def improve_edge_lighting(config, item, image, strength, stage):
    """Worker adapter; requires parent-resolved item.scenePath, never imagePath.

    Return this result as a separate version. Propagate errors; do not convert an
    unavailable face/neck observation into fallback success. Parent may decline
    publishing status='unchanged'. All timings below are observed CPU wall time.
    """
    _strength(strength)
    _pixels(image)
    from identity_face_region import FaceRegionParser
    started = perf_counter()
    scene_path = item.get('scenePath')
    if not isinstance(scene_path, (str, Path)) or not str(scene_path).strip() or not Path(scene_path).is_absolute():
        raise ValueError('边缘光照需要服务提供的原始场景 scenePath')
    try:
        # Hash and decode the same immutable snapshot; no second open / TOCTOU.
        scene_bytes = Path(scene_path).read_bytes()
        with Image.open(BytesIO(scene_bytes)) as opened:
            if opened.format != 'PNG' or opened.mode != 'RGB' or opened.size != image.size:
                raise ValueError('原始场景必须为与选中图像同尺寸的 RGB PNG')
            scene = opened.copy()
    except (OSError, ValueError) as exc:
        raise ValueError(f'原始场景不可用，已保留当前版本：{exc}') from exc
    scene_read = perf_counter()
    stage('检测选中图像的人脸与五点位置（CPU）')
    box, points = target_geometry(config, image)
    detected = perf_counter()
    stage('解析选中图像的皮肤、颈部与五官保护区（CPU）')
    labels = FaceRegionParser(config).labels(image, box)
    parsed = perf_counter()
    stage('仅调整下颌边缘光照，保留五官与颈部像素')
    result, details = edge_lighting_candidate(image, labels, points, box, strength, scene=scene)
    finished = perf_counter()
    details['scene'].update(path=str(scene_path), fileSha256=hashlib.sha256(scene_bytes).hexdigest())
    details['phasesMs'] = {'sceneRead': (scene_read - started) * 1000,
                          'targetDetection': (detected - scene_read) * 1000,
                          'targetParsing': (parsed - detected) * 1000,
                          'correctionAndDiagnostics': (finished - parsed) * 1000}
    details['durationMs'] = (finished - started) * 1000
    return result, details
