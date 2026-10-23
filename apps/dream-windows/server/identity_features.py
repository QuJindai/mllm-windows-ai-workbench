"""Versioned face features and a stat-validated local file fingerprint index."""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path

FEATURE_VERSION = 3  # ViT-H exact GELU; never reuse v2 quick_gelu features.
VISUAL_FEATURE_VERSION = 1
EXTRACTOR_KEYS = ('clipVision', 'det_10g.onnx', 'w600k_r50.onnx')


class FingerprintCache:
    def __init__(self, index: Path):
        self.index = Path(index)
        try:
            self.entries = json.loads(self.index.read_text(encoding='utf-8'))
            if not isinstance(self.entries, dict):
                self.entries = {}
        except (OSError, ValueError):
            self.entries = {}

    @staticmethod
    def _signature(path):
        stat = path.stat()
        return [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_dev, stat.st_ino]

    def digest(self, path, *, force=False):
        path = Path(path).resolve(strict=True)
        signature = self._signature(path)
        key = str(path)
        cached = self.entries.get(key, {})
        if not force and isinstance(cached, dict) and cached.get('stat') == signature and re.fullmatch(r'[0-9a-f]{64}', str(cached.get('sha256', ''))):
            return cached['sha256']
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(4 * 1024**2), b''):
                digest.update(block)
        if self._signature(path) != signature:
            raise ValueError('模型文件在校验期间发生变化，请重试')
        value = digest.hexdigest()
        self.entries[key] = {'stat': signature, 'sha256': value}
        self.index.parent.mkdir(parents=True, exist_ok=True)
        temp = self.index.with_name(self.index.name + f'.{os.getpid()}.tmp')
        temp.write_text(json.dumps(self.entries, ensure_ascii=False), encoding='utf-8')
        os.replace(temp, self.index)
        return value


def feature_key(image_digest, face_index, hashes):
    data = {'image': image_digest, 'face': face_index, 'models': {key: hashes[key] for key in EXTRACTOR_KEYS}, 'version': FEATURE_VERSION}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def validate_features(features, *, visual=False):
    import torch
    shapes = {'id': (1, 512), 'clip': (1, 257, 1280), 'negative_clip': (1, 257, 1280)}
    if visual:
        del shapes['id']
    if set(features) != set(shapes):
        raise ValueError('人物特征缓存字段无效，请重新建档')
    for key, shape in shapes.items():
        value = features[key]
        if tuple(value.shape) != shape or not torch.is_floating_point(value) or not torch.isfinite(value).all().item():
            raise ValueError('人物特征缓存无效，请重新建档')


def reference_features(config, request, extractor):
    from safetensors import SafetensorError
    from safetensors.torch import load_file, save_file
    root = Path(request['dreamRoot'])
    fingerprints = FingerprintCache(root / 'data' / 'identity' / 'fingerprints.json')
    force = bool(request.get('forceFingerprint', False))
    hashes = {'clipVision': fingerprints.digest(config['clipVision'], force=force)}
    for key in EXTRACTOR_KEYS[1:]:
        hashes[key] = fingerprints.digest(Path(config['insightfaceRoot']) / 'models' / 'buffalo_l' / key, force=force)
    key = feature_key(fingerprints.digest(request['imagePath'], force=force), request['faceIndex'], hashes)
    return _cached_features(root, key, hashes, lambda: extractor(config, request['imagePath'], request['faceIndex']),
                            version=FEATURE_VERSION)


def visual_reference_features(config, request, extractor):
    root = Path(request['dreamRoot'])
    fingerprints = FingerprintCache(root / 'data' / 'identity' / 'fingerprints.json')
    force = bool(request.get('forceFingerprint', False))
    hashes = {'clipVision': fingerprints.digest(config['clipVision'], force=force),
              'det_10g.onnx': fingerprints.digest(Path(config['insightfaceRoot']) / 'models/buffalo_l/det_10g.onnx', force=force)}
    detector = Path(config.get('animeFaceDetector', ''))
    if detector.is_file():
        hashes['animeFaceDetector'] = fingerprints.digest(detector, force=force)
    descriptor = {'kind': 'visual', 'version': VISUAL_FEATURE_VERSION, 'activation': 'gelu',
                  'crop': 'aligned224-detection-only-or-anime-box-margin30-v1', 'models': hashes,
                  'image': fingerprints.digest(request['imagePath'], force=force), 'face': request['faceIndex']}
    key = hashlib.sha256(json.dumps(descriptor, sort_keys=True).encode()).hexdigest()
    return _cached_features(root, key, hashes, lambda: extractor(config, request['imagePath'], request['faceIndex']),
                            visual=True, version=VISUAL_FEATURE_VERSION)


def _cached_features(root, key, hashes, extract, *, visual=False, version):
    from safetensors import SafetensorError
    from safetensors.torch import load_file, save_file
    cache = root / 'cache' / 'identity' / (key + '.safetensors')
    hit = cache.is_file()
    if hit:
        features = None
        try:
            if cache.stat().st_size > 8 * 1024**2:
                raise ValueError('人物特征缓存过大')
            features = load_file(str(cache), device='cpu')
            validate_features(features, visual=visual)
        except (SafetensorError, ValueError):
            # Preserve damaged data for inspection. Permission/IO failures are not corruption.
            features = None
            os.replace(cache, cache.with_name(cache.name + '.corrupt-' + uuid.uuid4().hex))
            hit = False
    if not hit:
        features = extract()
        validate_features(features, visual=visual)
        cache.parent.mkdir(parents=True, exist_ok=True)
        temp = cache.with_name(cache.name + f'.{os.getpid()}.tmp')
        save_file(features, str(temp), metadata={'featureVersion': str(version), 'referenceKind': 'visual' if visual else 'faceid', 'clipActivation': 'gelu'})
        os.replace(temp, cache)
    validate_features(features, visual=visual)
    return features, {'featureKey': key, 'cacheHit': hit, 'assetHashes': hashes, 'featureVersion': version,
                      'referenceKind': 'visual' if visual else 'faceid', 'clipActivation': 'gelu'}
