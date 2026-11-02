"""Immutable, R2-sourced pairs used by the approved HQ depth preset."""
import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from hq_tryon_conditioning import PipelineError

ESTIMATOR = 'paired-depth-r2-v1'
PIPELINE = 'identity-session-hq-paired-depth-v1'
LEGACY_PIPELINE = 'identity-session-hq-sd15-v1'
ASSETS = Path(__file__).resolve().parents[3] / 'config' / 'dream' / 'hq-paired-depth-v1'
CONTROLNET_SHA256 = '761077ffe369fe8cf16ae353f8226bd4ca29805b161052f82c0170c7b50f1d99'
CONTROLNET_CONFIG_SHA256 = 'ee789f6b46cd8c443c80ffb81e5c05e14b8b3cbec9e861829bfa3d2a6d3ee16f'
OPENPOSE_SHA256 = 'db97becd92cd19aff71352a60e93c2508decba3dee64f01f686727b9b406a9dd'
OPENPOSE_CONFIG_SHA256 = 'aa6fecc8745c0d0b26f0d2ca0f686600c8b33177c667d44eb41a51e56e44a697'


def pipeline_id(config, pose_id=None):
    if config.get('poseEstimator') != ESTIMATOR:
        return LEGACY_PIPELINE
    if pose_id is None or pose_id in _index(config)[1]:
        return PIPELINE
    return LEGACY_PIPELINE


def model_config(config, pipeline):
    """Select only the weights belonging to this job from the trusted server config."""
    if pipeline == LEGACY_PIPELINE and config.get('poseEstimator') == ESTIMATOR:
        skeleton = config.get('openpose')
        if not isinstance(skeleton, dict) or not all(skeleton.get(key) for key in ('controlnet', 'controlnetConfig')):
            raise PipelineError('MODEL_NOT_READY', '本机尚未配置姿势骨架模型')
        return {**config, 'poseEstimator': 'dwpose-full-image', 'controlnet': skeleton['controlnet'],
                'controlnetConfig': skeleton['controlnetConfig']}
    return config


def manifest_path(config=None):
    if config and config.get('pairedDepthLibrary'):
        return Path(config['pairedDepthLibrary']) / 'manifest.json'
    return ASSETS / 'manifest.json'


@lru_cache(maxsize=1)
def full_release():
    return json.loads((ASSETS / 'full-release.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=8)
def _read_index(path, full, stat_key):
    # Cache only contents that passed the release pin. Replacements invalidate
    # the entry via the resolved path and filesystem timestamps.
    if stat_key[0] > 2 * 1024 * 1024:
        raise ValueError('Oversized pose index')
    raw = path.read_bytes()
    data = json.loads(raw.decode('utf-8-sig'))
    items = data['items']
    if full:
        lock = full_release()
        if (hashlib.sha256(raw).hexdigest() != lock['manifestSHA256'] or len(items) != lock['count']
                or data['depthRelease'] != lock['depthRelease'] or data['release'] != lock['whiteRelease']):
            raise ValueError('Depth release checksum or version mismatch')
    by_id = {row['id']: row for row in items}
    if data['poseEstimator'] != ESTIMATOR or not items or len(by_id) != len(items):
        raise ValueError('Invalid pair inventory')
    for row in items:
        if (not re.fullmatch(r'[A-Za-z0-9_-]{2,64}', row['id'])
                or any(not re.fullmatch(r'[0-9a-f]{64}', row[key]) for key in ('depthSha256', 'fullSha256'))):
            raise ValueError('Invalid pose/checksum in pair inventory')
        if full and row['r2Object'] != f"hq-tryon-assets/dream-depth/v1/objects/{row['depthSha256']}.webp":
            raise ValueError('Unexpected R2 depth object')
    return data, by_id


def _index(config=None):
    path = manifest_path(config)
    try:
        stat = path.stat()
        return _read_index(path, bool(config and config.get('pairedDepthLibrary')),
                           (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise PipelineError('MODEL_NOT_READY', '本机配对深度素材清单无法读取') from exc


def catalog(config=None):
    return _index(config)[0]


def lookup(pose_id, config=None):
    row = _index(config)[1].get(pose_id)
    if row is None:
        raise PipelineError('HQ_DEPTH_UNAVAILABLE', '这个姿势没有已核验的配对深度图，请在姿势页重新选择')
    return row


def object_path(pair, config=None):
    root = Path(config['pairedDepthLibrary']) / 'objects' if config and config.get('pairedDepthLibrary') else ASSETS
    return root / (pair['depthSha256'] + '.webp')


def verified_pair(run, config):
    pose = run.inputs['pose']
    pair = lookup(pose['id'], config)
    if pair['fullSha256'] != pose['sha256']:
        raise PipelineError('HQ_DEPTH_PAIR_MISMATCH', '姿势原图与配对深度图的版本不一致')
    return pair


def ensure_depth(run, config):
    """Only Dream's local worker may fill this content-addressed cache from R2."""
    pair = verified_pair(run, config)
    if not config.get('pairedDepthLibrary'):
        return 'bundled-r2-copy'
    target = object_path(pair, config)
    if target.is_file() and target.stat().st_size == pair['bytes'] and hashlib.sha256(target.read_bytes()).hexdigest() == pair['depthSha256']:
        return 'verified-r2-cache'
    if not config.get('depthReaderNode') or not config.get('depthReaderCli'):
        raise PipelineError('HQ_DEPTH_CACHE_MISS', '深度图需要重新同步，请恢复已校验的 R2 素材包')
    run.check_cancel()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.depth-', dir=target.parent) as tmp:
            local = Path(tmp) / 'object.webp'
            command = [config['depthReaderNode'], config['depthReaderCli'], 'r2', 'object', 'get', pair['r2Object'],
                       '--remote', '--file', str(local), '--config', str(ASSETS / 'reader.jsonc')]
            subprocess.run(command, cwd=tmp, check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=75, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                           env={**os.environ, 'CI': '1', 'WRANGLER_SEND_METRICS': 'false', 'WRANGLER_LOG': 'error'})
            run.check_cancel()
            if local.stat().st_size != pair['bytes'] or hashlib.sha256(local.read_bytes()).hexdigest() != pair['depthSha256']:
                raise PipelineError('HQ_DEPTH_HASH_MISMATCH', 'R2 返回的深度图校验失败')
            os.replace(local, target)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PipelineError('HQ_DEPTH_FETCH_FAILED', '读取 R2 深度图失败，请检查本机授权或恢复深度素材包') from exc
    return 'r2-download'


def control_image(run, native, config=None, source='bundled-r2-copy'):
    from PIL import Image, ImageOps
    pose = run.inputs['pose']
    pair = verified_pair(run, config)
    path = object_path(pair, config)
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
        'receipt': {'poseId': pose['id'], 'poseSha256': pose['sha256'], 'sha256': pair['depthSha256'], 'source': source,
                    'r2Object': pair['r2Object'], 'bytes': len(raw)},
        'guidanceStart': 0.0, 'guidanceEnd': 1.0,
    }
    return control
