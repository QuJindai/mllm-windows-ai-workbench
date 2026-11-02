"""Immutable, R2-sourced pairs used by the approved HQ depth preset."""
import hashlib
import io
import json
import re
from pathlib import Path

from hq_tryon_conditioning import PipelineError

ESTIMATOR = 'paired-depth-r2-v1'
PIPELINE = 'identity-session-hq-paired-depth-v1'
LEGACY_PIPELINE = 'identity-session-hq-sd15-v1'
ASSETS = Path(__file__).resolve().parents[3] / 'config' / 'dream' / 'hq-paired-depth-v1'
CONTROLNET_SHA256 = '761077ffe369fe8cf16ae353f8226bd4ca29805b161052f82c0170c7b50f1d99'
CONTROLNET_CONFIG_SHA256 = 'ee789f6b46cd8c443c80ffb81e5c05e14b8b3cbec9e861829bfa3d2a6d3ee16f'


def pipeline_id(config):
    return PIPELINE if config.get('poseEstimator') == ESTIMATOR else LEGACY_PIPELINE


def catalog():
    try:
        data = json.loads((ASSETS / 'manifest.json').read_text(encoding='utf-8-sig'))
        items = data['items']
        if (data['poseEstimator'] != ESTIMATOR or not items
                or len({row['id'] for row in items}) != len(items)):
            raise ValueError('Invalid pair inventory')
        for row in items:
            if (not re.fullmatch(r'[A-Za-z0-9_-]{2,64}', row['id'])
                    or any(not re.fullmatch(r'[0-9a-f]{64}', row[key]) for key in ('depthSha256', 'fullSha256'))):
                raise ValueError('Invalid pose/checksum in pair inventory')
        return data
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise PipelineError('MODEL_NOT_READY', '本机配对深度素材清单无法读取') from exc


def lookup(pose_id):
    row = next((item for item in catalog()['items'] if item['id'] == pose_id), None)
    if row is None:
        raise PipelineError('HQ_DEPTH_UNAVAILABLE', '这个姿势没有已核验的配对深度图，请在姿势页重新选择')
    return row


def control_image(run, native):
    from PIL import Image, ImageOps
    pose = run.inputs['pose']
    pair = lookup(pose['id'])
    if pair['fullSha256'] != pose['sha256']:
        raise PipelineError('HQ_DEPTH_PAIR_MISMATCH', '姿势原图与配对深度图的版本不一致')
    path = ASSETS / (pair['depthSha256'] + '.webp')
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != pair['depthSha256']:
            raise PipelineError('HQ_DEPTH_HASH_MISMATCH', '配对深度图校验失败')
        with Image.open(io.BytesIO(raw)) as depth:
            if depth.format != 'WEBP' or depth.n_frames != 1 or depth.size != native.size:
                raise PipelineError('HQ_DEPTH_PAIR_MISMATCH', '配对深度图与姿势原图尺寸不一致')
            params = run.audit['parameters']
            control = ImageOps.pad(depth.convert('RGB'), (params['width'], params['height']),
                                   method=Image.Resampling.BILINEAR, color='black')
    except OSError as exc:
        raise PipelineError('MODEL_NOT_READY', '本机配对深度原图缺失或不可读') from exc
    saved = run.save_image('paired-depth-control', control, 'original R2 depth; aspect-preserving black letterbox')
    run.audit['conditioning']['pose'] = {
        'inputRole': 'pose', 'method': ESTIMATOR, 'detectorUsed': False, 'controlImage': saved,
        'receipt': {'poseId': pose['id'], 'poseSha256': pose['sha256'], 'sha256': pair['depthSha256'],
                    'r2Object': pair['r2Object'], 'bytes': len(raw)},
        'guidanceStart': 0.0, 'guidanceEnd': 1.0,
    }
    return control
