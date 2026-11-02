"""Lightweight HQ asset checks and audit storage. Inference belongs to IdentitySession."""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from hq_tryon_conditioning import PipelineError
from identity_contract import HQ_PROFILE_PNG_MAX_BYTES
import hq_paired_depth as paired_depth

ROLES = ('person', 'garment', 'pose')
FILE_KEYS = ('checkpoint', 'personAdapter', 'personLora', 'garmentAdapter', 'clipVision', 'controlnet', 'poseModel')
DIRECTORY_KEYS = ('pipelineConfig', 'insightfaceRoot', 'controlnetConfig', 'poseAuxSource')
BASE_BINDINGS = {'checkpoint': 'checkpoint', 'personAdapter': 'adapter', 'personLora': 'faceLora',
                 'clipVision': 'clipVision', 'pipelineConfig': 'pipelineConfig', 'insightfaceRoot': 'insightfaceRoot'}
DEFAULTS = {'offload': 'sequential', 'garmentScale': .7, 'poseScale': .9, 'poseEstimator': 'dwpose-full-image'}


def read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if not isinstance(value, dict):
            raise ValueError('Expected an object')
        return value
    except (OSError, UnicodeError, ValueError) as exc:
        raise PipelineError('MODEL_NOT_READY', 'Cannot read local HQ configuration', path=str(path), reason=str(exc)) from exc


def absolute_path(value, field):
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise PipelineError('INVALID_HQ_CONDITIONING', 'An absolute local path is required', field=field)
    return Path(value).resolve()


def validate_config(config, identity_config=None):
    if config.get('schemaVersion') != 1:
        raise PipelineError('MODEL_NOT_READY', 'HQ config schemaVersion must be 1')
    result = {**DEFAULTS, **config}
    depth_mode = result['poseEstimator'] == paired_depth.ESTIMATOR
    path_keys = tuple(key for key in FILE_KEYS + DIRECTORY_KEYS
                      if not depth_mode or key not in ('poseModel', 'poseAuxSource'))
    for key in path_keys:
        if identity_config is not None and key in BASE_BINDINGS:
            authoritative = absolute_path(identity_config.get(BASE_BINDINGS[key]), 'identity.' + BASE_BINDINGS[key])
            if key in config and absolute_path(config[key], key) != authoritative:
                raise PipelineError('HQ_IDENTITY_CONFIG_MISMATCH', 'HQ must reuse the resolved identity model bundle', field=key)
            result[key] = str(authoritative)
        else:
            result[key] = str(absolute_path(result.get(key), key))
    if result['offload'] not in ('sequential', 'model'):
        raise PipelineError('MODEL_NOT_READY', 'offload must be sequential or model')
    if not depth_mode and result['poseEstimator'] != 'dwpose-full-image':
        raise PipelineError('MODEL_NOT_READY', 'Unknown HQ pose estimator')
    if depth_mode and (result['garmentScale'], result['poseScale']) != (.7, .9):
        raise PipelineError('MODEL_NOT_READY', '配对深度预设要求服装权重 0.7、姿势权重 0.9')
    for key in ('garmentScale', 'poseScale'):
        value = result[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 2:
            raise PipelineError('MODEL_NOT_READY', 'Conditioning scale must be positive and at most 2', field=key)
        result[key] = float(value)
    if depth_mode and result.get('pairedDepthLibrary'):
        if bool(result.get('depthReaderNode')) != bool(result.get('depthReaderCli')):
            raise PipelineError('MODEL_NOT_READY', 'R2 深度读取工具配置不完整')
        for key in ('pairedDepthLibrary', 'depthReaderNode', 'depthReaderCli'):
            if result.get(key):
                result[key] = str(absolute_path(result[key], key))
                path_keys += (key,)
    # Sampling, FaceID and restoration parameters belong to IdentityGenerateRequest.
    # Legacy duplicated HQ settings are not allowed to override that request.
    return {'schemaVersion': 1, **{key: result[key] for key in path_keys + tuple(DEFAULTS)}}


def required_assets(config, pose_id=None):
    cfg = validate_config(config)
    rows = {key: Path(cfg[key]) for key in FILE_KEYS if key in cfg}
    rows['controlnetConfig/config.json'] = Path(cfg['controlnetConfig']) / 'config.json'
    for name in ('det_10g.onnx', 'w600k_r50.onnx'):
        rows['insightface/' + name] = Path(cfg['insightfaceRoot']) / 'models' / 'buffalo_l' / name
    root = Path(cfg['pipelineConfig'])
    for name in ('model_index.json', 'unet/config.json', 'vae/config.json', 'text_encoder/config.json',
                 'scheduler/scheduler_config.json', 'tokenizer/tokenizer_config.json', 'tokenizer/vocab.json', 'tokenizer/merges.txt'):
        rows['pipelineConfig/' + name] = root / name
    if root.is_dir():
        for path in root.rglob('*'):
            if path.is_file() and '.cache' not in path.parts:
                rows['pipelineConfig/' + path.relative_to(root).as_posix()] = path
    if cfg['poseEstimator'] == paired_depth.ESTIMATOR:
        rows['posePairs/manifest'] = paired_depth.manifest_path(cfg)
        library = paired_depth.catalog(cfg)
        # A full library can be cached lazily. Fingerprint the depth map used
        # by this job after it has been fetched and verified.
        items = [paired_depth.lookup(pose_id, cfg)] if pose_id else ([] if cfg.get('pairedDepthLibrary') else library['items'])
        for item in items:
            rows['posePairs/' + item['id']] = paired_depth.object_path(item, cfg)
        return rows
    aux = Path(cfg['poseAuxSource']) / 'custom_controlnet_aux'
    for name in ('__init__.py', 'util.py', 'dwpose/__init__.py', 'dwpose/wholebody.py', 'dwpose/util.py',
                 'dwpose/types.py', 'dwpose/dw_onnx/cv_ox_pose.py'):
        rows['poseSource/' + name] = aux / name
    if (aux / 'dwpose').is_dir():
        for path in (aux / 'dwpose').rglob('*.py'):
            rows['poseSource/' + path.relative_to(aux).as_posix()] = path
    return rows


def readiness(config_path, identity_config=None, *, pipeline=None):
    """Presence-only service inventory. No inference imports, GPU or downloads."""
    try:
        if identity_config is None:
            from identity_worker import load_config
            identity_config = load_config({'modelId': 'realistic-vision-v5.1-faceid'})
        config = read_json(config_path)
        effective = validate_config(paired_depth.model_config(config, pipeline), identity_config)
        missing = [{'key': key, 'path': str(path)} for key, path in required_assets(effective).items()
                   if not path.is_file()]
        return {'ready': not missing, 'code': 'MODEL_NOT_READY' if missing else None, 'missing': missing}
    except PipelineError as exc:
        return {'ready': False, 'code': exc.code, 'message': str(exc), **exc.details}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {'ready': False, 'code': 'MODEL_NOT_READY', 'message': str(exc)}


class ConditioningAudit:
    def __init__(self, first, parameters, emit):
        spec = first['hqConditioning']
        if not isinstance(spec, dict):
            raise PipelineError('INVALID_HQ_CONDITIONING', 'hqConditioning must be a trusted internal object')
        inputs = spec.get('inputs')
        if not isinstance(inputs, dict) or set(inputs) != set(ROLES):
            raise PipelineError('INVALID_HQ_CONDITIONING', 'Exactly person, garment and pose are required')
        self.inputs = inputs
        for role, item in inputs.items():
            if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id']:
                raise PipelineError('INVALID_HQ_CONDITIONING', 'Each input requires an id', role=role)
            absolute_path(item.get('path'), role)
            value = item.get('sha256')
            if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdefABCDEF' for c in value):
                raise PipelineError('INVALID_HQ_CONDITIONING', 'Each input requires SHA256', role=role)
        self.identity_image = absolute_path(first.get('imagePath'), 'imagePath')
        self.config_path = absolute_path(spec.get('configPath'), 'configPath')
        self.audit_path = absolute_path(spec.get('auditPath'), 'auditPath')
        self.event_path = absolute_path(spec['eventPath'], 'eventPath') if spec.get('eventPath') else None
        self.cancel_path = absolute_path(spec['cancelPath'], 'cancelPath') if spec.get('cancelPath') else None
        self.artifact_dir = self.audit_path.with_name(self.audit_path.stem + '.conditioning')
        sources = {self.config_path, self.identity_image, *(absolute_path(inputs[role]['path'], role) for role in ROLES)}
        publications = [absolute_path(first[key], key) for key in ('outputPath', 'metadataPath')]
        if len(set(publications)) != 2 or any(path in sources for path in publications):
            raise PipelineError('UNSAFE_DESTINATION', 'Identity output destinations cannot overwrite HQ originals or configuration')
        if any(path.exists() for path in publications):
            raise PipelineError('OUTPUT_EXISTS', 'Use fresh identity output and metadata paths for HQ')
        protected = sources | set(publications)
        destinations = [p for p in (self.audit_path, self.artifact_dir, self.event_path, self.cancel_path) if p is not None]
        if len(set(destinations)) != len(destinations) or any(p in protected for p in destinations):
            raise PipelineError('UNSAFE_DESTINATION', 'HQ audit destinations collide with original or identity files')
        if any(self.artifact_dir in p.parents for p in protected):
            raise PipelineError('UNSAFE_DESTINATION', 'HQ artifacts cannot contain source files')
        if self.audit_path.exists() or self.artifact_dir.exists() or (self.event_path and self.event_path.exists()):
            raise PipelineError('OUTPUT_EXISTS', 'Use fresh HQ audit and artifact paths')
        self.started = time.perf_counter()
        self.parent_emit = emit
        self.audit = {'schemaVersion': 2, 'pipeline': spec.get('pipeline', paired_depth.LEGACY_PIPELINE), 'jobId': first['jobId'],
                      'parentJobId': spec.get('jobId'),
                      'status': 'preparing', 'startedAt': datetime.now(timezone.utc).isoformat(),
                      'parameters': parameters, 'inputs': {}, 'preprocessing': {}, 'conditioning': {},
                      'models': {}, 'timings': [], 'completedSteps': 0}
        self.model_stats = {}
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_dir.mkdir(exist_ok=False)
        with self.audit_path.open('x', encoding='utf-8') as stream:
            json.dump(self.audit, stream)
        if self.event_path:
            self.event_path.parent.mkdir(parents=True, exist_ok=True)
            self.event_path.touch(exist_ok=False)

    def check_cancel(self):
        if self.cancel_path and self.cancel_path.exists():
            raise PipelineError('CANCELLED', 'Local identity HQ job was cancelled')

    def digest(self, path):
        digest = hashlib.sha256()
        with Path(path).open('rb') as stream:
            for chunk in iter(lambda: stream.read(4 * 1024**2), b''):
                self.check_cancel()
                digest.update(chunk)
        return digest.hexdigest()

    def emit(self, kind, **fields):
        event = {'type': kind, 'jobId': self.audit['jobId'],
                 'elapsedMs': round((time.perf_counter() - self.started) * 1000), **fields}
        self.parent_emit(event)
        if self.event_path:
            with self.event_path.open('a', encoding='utf-8', newline='\n') as stream:
                stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n')
                stream.flush()

    def flush(self):
        self.audit['durationMs'] = round((time.perf_counter() - self.started) * 1000)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.audit_path.parent,
                                             prefix='.hq-audit-', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(self.audit, stream, ensure_ascii=False, allow_nan=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.audit_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @contextmanager
    def stage(self, name):
        self.check_cancel()
        started = time.perf_counter()
        self.emit('stage', stage=name)
        ok = False
        try:
            yield
            self.check_cancel()
            ok = True
        finally:
            self.audit['timings'].append({'stage': name, 'durationMs': round((time.perf_counter() - started) * 1000), 'completed': ok})
            self.flush()

    def save_image(self, name, image, transform):
        path = self.artifact_dir / (name + '.png')
        with path.open('xb') as stream:
            image.save(stream, format='PNG')
        return {'path': str(path), 'sha256': self.digest(path), 'width': image.width, 'height': image.height,
                'mode': image.mode, 'transform': transform}

    def prepare_images(self):
        from PIL import Image, ImageOps
        images = {}
        for role, item in self.inputs.items():
            self.check_cancel()
            path = absolute_path(item['path'], role)
            size_limit = HQ_PROFILE_PNG_MAX_BYTES if role == 'person' and item.get('source') == 'profile' else 30 * 1024**2
            if not path.is_file() or path.stat().st_size > size_limit:
                raise PipelineError('INVALID_INPUT', 'Local input image missing or exceeds its size limit', role=role)
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if digest != item['sha256'].lower():
                raise PipelineError('INPUT_HASH_MISMATCH', 'Input bytes differ from the trusted request', role=role)
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > 40_000_000 or getattr(image, 'n_frames', 1) != 1:
                    raise PipelineError('INVALID_INPUT', 'Expected one image of at most 40 megapixels', role=role)
                self.audit['inputs'][role] = {'id': item['id'], 'path': str(path), 'sha256': digest,
                                              'width': image.width, 'height': image.height, 'mode': image.mode,
                                              'exifOrientation': image.getexif().get(274), 'bytes': len(data)}
                if role == 'person':
                    if item.get('source'):
                        self.audit['inputs'][role]['source'] = item['source']
                    # Identity upload stores normalized PNG; original R2 bytes
                    # may differ. Require exact oriented RGB pixels, not filenames.
                    original_rgb = ImageOps.exif_transpose(image).convert('RGB')
                    with Image.open(self.identity_image) as reference:
                        reference_rgb = ImageOps.exif_transpose(reference).convert('RGB')
                    if original_rgb.size != reference_rgb.size or original_rgb.tobytes() != reference_rgb.tobytes():
                        raise PipelineError('HQ_PERSON_BINDING_MISMATCH', 'HQ person pixels differ from the existing identity reference')
                    self.audit['identityReference'] = {
                        'path': str(self.identity_image), 'sha256': self.digest(self.identity_image),
                        'normalizedRgbSha256': hashlib.sha256(reference_rgb.tobytes()).hexdigest(),
                        'width': reference_rgb.width, 'height': reference_rgb.height,
                        'pixelEqualityVerified': True, 'normalization': 'PIL-exif-transpose-convert-RGB-v1',
                    }
                    continue
                rgba = ImageOps.exif_transpose(image).convert('RGBA')
                rgb = Image.new('RGBA', rgba.size, 'white')
                rgb.alpha_composite(rgba)
                rgb = rgb.convert('RGB')
            if role == 'garment':
                rgb = ImageOps.pad(rgb, (224, 224), method=Image.Resampling.LANCZOS, color='white')
                transform = 'exif-alpha-white-contain-letterbox-224'
            else:
                rgb.thumbnail((1536, 1536), Image.Resampling.LANCZOS)
                transform = 'exif-alpha-white-contain-max1536-before-estimation'
            self.audit['preprocessing'][role] = self.save_image(role + '-input', rgb, transform)
            images[role] = rgb
        return images

    def fingerprint_models(self, config, identity_config):
        rows = required_assets(config, self.inputs['pose']['id'])
        for key in ('faceSwapModel', 'faceRestoreModel', 'faceParsingModel'):
            if identity_config.get(key) and Path(identity_config[key]).is_file():
                rows['identity/' + key] = Path(identity_config[key])
        rows['hqConfig'] = self.config_path
        rows['identity/referenceImage'] = self.identity_image
        missing = [{'key': key, 'path': str(path)} for key, path in rows.items() if not path.is_file()]
        if missing:
            raise PipelineError('MODEL_NOT_READY', 'Required local conditioning assets are missing', missing=missing)
        for key, path in rows.items():
            stat = path.stat()
            digest = self.digest(path)
            after = path.stat()
            signature = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            if signature != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise PipelineError('MODEL_NOT_READY', 'Model changed while hashing', path=str(path))
            self.model_stats[str(path)] = signature
            self.audit['models'][key] = {'path': str(path), 'sha256': digest, 'bytes': stat.st_size}
        if config['poseEstimator'] == paired_depth.ESTIMATOR:
            for key, expected in [('controlnet', paired_depth.CONTROLNET_SHA256),
                                  ('controlnetConfig/config.json', paired_depth.CONTROLNET_CONFIG_SHA256)]:
                if self.audit['models'][key]['sha256'] != expected:
                    raise PipelineError('MODEL_NOT_READY', '深度 ControlNet 与已验证的版本不一致', model=key)

    def verify_unchanged(self):
        for filename, expected in self.model_stats.items():
            self.check_cancel()
            stat = Path(filename).stat()
            if (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns) != expected:
                raise PipelineError('MODEL_NOT_READY', 'Model asset changed during inference', path=filename)
        for role, item in self.inputs.items():
            if self.digest(item['path']) != item['sha256'].lower():
                raise PipelineError('INPUT_HASH_MISMATCH', 'Input changed during inference', role=role)


if __name__ == '__main__':
    print(json.dumps({'ok': False, 'code': 'HQ_IDENTITY_PIPELINE_REQUIRED',
                      'message': 'Use trusted hqConditioning through the existing identity worker; standalone HQ generation was removed.'}))
    raise SystemExit(1)
