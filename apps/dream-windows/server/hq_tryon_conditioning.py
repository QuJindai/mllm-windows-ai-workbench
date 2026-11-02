"""Optional garment/pose conditioning for the existing SD1.5 IdentitySession."""
from __future__ import annotations

import gc
import hashlib
import io
import json
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class PipelineError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code = code
        self.details = details


def error_record(exc):
    if isinstance(exc, PipelineError):
        return {'code': exc.code, 'message': str(exc), 'details': exc.details}
    if type(exc).__name__ == 'OutOfMemoryError' or 'cuda out of memory' in str(exc).lower():
        return {'code': 'VRAM_OOM', 'message': str(exc), 'details': {}}
    code = 'MODEL_NOT_READY' if isinstance(exc, (ImportError, FileNotFoundError)) else 'HQ_CONDITIONING_FAILED'
    return {'code': code, 'message': str(exc), 'details': {'exception': type(exc).__name__}}


def image_digest(image):
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def project_garment(pipe, clip, device='cuda'):
    import torch
    from diffusers.models.embeddings import IPAdapterPlusImageProjection, MultiIPAdapterImageProjection
    layers = pipe.unet.encoder_hid_proj.image_projection_layers
    if len(layers) != 2 or not isinstance(layers[1], IPAdapterPlusImageProjection):
        raise PipelineError('MODEL_NOT_READY', 'HQ requires a separate IP-Adapter Plus garment projection')
    layer = layers[1].to(device=device, dtype=pipe.unet.dtype)
    with torch.inference_mode():
        garment = layer(clip.to(device=device, dtype=pipe.unet.dtype)).unsqueeze(1).cpu()
    layer.to('cpu')
    # IdentitySession has already executed its unchanged FaceID projection.
    pipe.unet.encoder_hid_proj = MultiIPAdapterImageProjection([torch.nn.Identity(), torch.nn.Identity()])
    return garment


def tensor_record(tensor):
    """Hash dtype, shape and contiguous CPU bytes, not a label or source image."""
    value = tensor.detach().cpu().contiguous()
    header = {'shape': list(value.shape), 'dtype': str(value.dtype)}
    digest = hashlib.sha256(json.dumps(header, sort_keys=True).encode() + b'\0')
    digest.update(value.numpy().tobytes())
    return {**header, 'sha256': digest.hexdigest(), 'hashFormat': 'dtype-shape-json-nul-raw-v1'}


def save_tensor(run, name, tensor):
    from safetensors.torch import save_file
    path = run.artifact_dir / (name + '.safetensors')
    value = tensor.detach().cpu().contiguous()
    save_file({'conditioning': value}, str(path))
    return {**tensor_record(value), 'path': str(path), 'fileSha256': run.digest(path)}


def load_adapter(path):
    """Normalize both official formats without unsafe pickle deserialization."""
    import torch
    from safetensors.torch import load_file
    if Path(path).suffix == '.safetensors':
        flat = load_file(str(path), device='cpu')
        state = {prefix: {key[len(prefix) + 1:]: value for key, value in flat.items()
                          if key.startswith(prefix + '.')}
                 for prefix in ('image_proj', 'ip_adapter')}
    else:
        state = torch.load(str(path), map_location='cpu', weights_only=True)
    if not all(state.get(key) for key in ('image_proj', 'ip_adapter')):
        raise PipelineError('MODEL_NOT_READY', 'IP-Adapter weights are incomplete', path=str(path))
    return state




def adapter_layout(pipe):
    branches = []
    for name, proc in pipe.unet.attn_processors.items():
        if hasattr(proc, 'to_k_ip'):
            if len(proc.to_k_ip) != 2 or len(proc.to_v_ip) != 2 or list(proc.num_tokens) != [4, 16]:
                raise PipelineError('MODEL_NOT_READY', 'Adapter attention slots do not match [person, garment]', layer=name)
            branches.append({'layer': name, 'tokens': list(proc.num_tokens), 'scales': list(proc.scale),
                             'processor': type(proc).__name__})
    if not branches:
        raise PipelineError('MODEL_NOT_READY', 'No image attention branches were loaded')
    return branches


class ConditioningObserver:
    """Observe actual model forward arguments, and refuse unobserved success."""
    def __init__(self, run, expected_adapters, expected_pose):
        self.run = run
        self.expected = {role: tensor_record(value) for role, value in zip(('person', 'garment'), expected_adapters)}
        self.expected['pose'] = tensor_record(expected_pose)
        self.records = {}
        self.handles = []

    def record(self, role, value, target):
        self.run.check_cancel()
        if role not in self.records:
            actual = tensor_record(value)
            if actual != self.expected[role]:
                raise PipelineError('CONDITIONING_MISMATCH', 'Forward conditioning differs from prepared tensor', role=role)
            self.records[role] = {**actual, 'target': target, 'forwardCalls': 0, 'observed': True}
            self.run.audit['conditioning'][role]['actualConditioning'] = self.records[role]
        self.records[role]['forwardCalls'] += 1

    def attach(self, pipe):
        def unet_hook(module, args, kwargs):
            embeds = kwargs.get('added_cond_kwargs', {}).get('image_embeds')
            if not isinstance(embeds, list) or len(embeds) != 2:
                raise PipelineError('CONDITIONING_MISMATCH', 'UNet did not receive two image adapter inputs')
            self.record('person', embeds[0], 'unet.added_cond_kwargs.image_embeds[0]')
            self.record('garment', embeds[1], 'unet.added_cond_kwargs.image_embeds[1]')

        def controlnet_hook(module, args, kwargs):
            self.record('pose', kwargs['controlnet_cond'], 'controlnet.controlnet_cond')

        self.handles = [pipe.unet.register_forward_pre_hook(unet_hook, with_kwargs=True),
                        pipe.controlnet.register_forward_pre_hook(controlnet_hook, with_kwargs=True)]

    def finish(self, steps):
        if set(self.records) != {'person', 'garment', 'pose'} or any(
            row['forwardCalls'] != steps for row in self.records.values()
        ):
            raise PipelineError('CONDITIONING_MISMATCH', 'Not all conditioning branches executed every denoising step',
                                observed=self.records, expectedSteps=steps)

    def close(self):
        for handle in self.handles:
            handle.remove()




_DWPOSE_LIMB_NAMES = ('left-shoulder', 'right-shoulder', 'left-elbow', 'right-elbow',
                      'left-wrist', 'right-wrist', 'left-hip', 'right-hip',
                      'left-knee', 'right-knee', 'left-ankle', 'right-ankle')


def dwpose_body_keypoints(points, scores, width, height):
    """COCO -> OpenPose order, using the same neck construction as DWPose."""
    import numpy as np
    if points.shape != (1, 133, 2) or scores.shape != (1, 133):
        raise PipelineError('MODEL_NOT_READY', 'Expected DWPose 133-keypoint whole-body output')
    # Require both shoulder/elbow/wrist/hip/knee/ankle chains. Do not publish a
    # plausible-looking partial skeleton after a low-confidence model response.
    if not np.isfinite(points).all() or not np.isfinite(scores).all():
        raise PipelineError('POSE_LOW_CONFIDENCE', 'DWPose returned non-finite keypoints or scores')
    if np.any(scores[0, 5:17] < .3):
        raise PipelineError('POSE_LOW_CONFIDENCE', 'DWPose could not resolve all major limb joints',
                            limbScores=scores[0, 5:17].tolist(), requiredScore=.3,
                            weakJoints=[{'joint': name, 'score': float(score)}
                                        for name, score in zip(_DWPOSE_LIMB_NAMES, scores[0, 5:17]) if score < .3])
    coco = np.concatenate([points[0, :17], scores[0, :17, None]], axis=-1)
    neck = np.array([*coco[[5, 6], :2].mean(axis=0), min(coco[5, 2], coco[6, 2])])
    all_points = np.vstack([coco, neck])
    # nose, neck, right arm, left arm, right leg, left leg, eyes, ears.
    order = [0, 17, 6, 8, 10, 5, 7, 9, 12, 14, 16, 11, 13, 15, 2, 1, 4, 3]
    body = all_points[order].copy()
    body[:, 0] /= width
    body[:, 1] /= height
    if np.any(body[1:14, :2] < 0) or np.any(body[1:14, :2] > 1):
        raise PipelineError('POSE_LOW_CONFIDENCE', 'Predicted body joints extend outside the reference image')
    return body


def dwpose_white_context(image):
    """Extend a near-white image boundary; retain every original pixel and bbox."""
    import math
    import numpy as np
    from PIL import ImageOps
    rgb = image.convert('RGB')
    pixels = np.asarray(rgb)
    edge = max(1, min(16, min(rgb.size) // 100))
    border = np.concatenate([pixels[:edge].reshape(-1, 3), pixels[-edge:].reshape(-1, 3),
                             pixels[:, :edge].reshape(-1, 3), pixels[:, -edge:].reshape(-1, 3)])
    fraction = float(np.mean(np.min(border, axis=1) >= 250))
    if fraction < .995 or not np.any(pixels.min(axis=2) < 230):
        return None
    # DWPose expands its bbox by 1.25, then fits the 288:384 model aspect.
    # Supply enough white context for that entire affine footprint, rather than
    # allowing cv2.warpAffine's default black border to surround a white drawing.
    width, height = rgb.size
    scale_width = max(width * 1.25, height * 1.25 * .75)
    scale_height = max(height * 1.25, width * 1.25 / .75)
    left = max(math.ceil(width / 4), math.ceil((scale_width - width) / 2) + 2)
    top = max(math.ceil(height / 4), math.ceil((scale_height - height) / 2) + 2)
    padded = ImageOps.expand(rgb, border=(left, top, left, top), fill='white')
    return padded, [left, top, left + width, top + height], {
        'offset': [left, top], 'borderWhiteFraction': fraction, 'edgeWidth': edge,
        'transform': 'white-context-outside-original-frame-no-crop',
    }


def estimate_dwpose_body(image, infer, run):
    """One unchanged native attempt, then at most one justified border retry."""
    import numpy as np
    record = {'inputRole': 'pose', 'estimationStatus': 'estimating', 'attempts': [],
              'requiredLimbScore': .3, 'scoresAreCalibratedProbabilities': False}
    run.audit['conditioning']['pose'] = record

    def attempt(source, bbox, offset, method, image_info):
        run.check_cancel()
        points, scores = infer(np.asarray(source), bbox)
        points = points - np.asarray(offset)
        row = {'method': method, 'image': image_info, 'bbox': bbox, 'coordinateOffset': list(offset),
               'pointsShape': list(points.shape), 'scoresShape': list(scores.shape)}
        record['attempts'].append(row)
        if points.shape == (1, 133, 2) and scores.shape == (1, 133) and np.isfinite(points).all() and np.isfinite(scores).all():
            row.update(bodyPoints=points[0, :17].tolist(), bodyScores=scores[0, :17].tolist(),
                       limbScores=scores[0, 5:17].tolist(), minimumLimbScore=float(scores[0, 5:17].min()),
                       coordinates='original-preprocessed-image-pixels')
        try:
            body = dwpose_body_keypoints(points, scores, image.width, image.height)
        except PipelineError as exc:
            row.update(accepted=False, error=error_record(exc))
            return points, scores, None, exc
        row['accepted'] = True
        return points, scores, body, None

    original_info = run.audit.get('preprocessing', {}).get('pose')
    points, scores, body, failure = attempt(image, [], (0, 0), 'full-image-default-border', original_info)
    if failure is None:
        record.update(estimationStatus='accepted', selectedAttempt=0)
        return body, points, scores
    record['estimationStatus'] = 'rejected'
    if failure.code != 'POSE_LOW_CONFIDENCE' or not np.isfinite(points).all() or not np.isfinite(scores).all():
        raise failure
    trusted = scores[0, 5:17] >= .3
    if trusted.sum() < 6:
        record['retrySkippedReason'] = 'fewer-than-six-native-limb-anchors'
        raise failure
    context = dwpose_white_context(image)
    if context is None:
        record['retrySkippedReason'] = 'boundary-not-uniform-white-or-empty-image'
        raise failure
    padded, bbox, transform = context
    run.check_cancel()
    info = run.save_image('pose-white-context', padded, transform['transform'])
    record['borderRetry'] = {**transform, 'image': info, 'reason': 'native-low-confidence'}
    new_points, new_scores, body, retry_failure = attempt(padded, [bbox], transform['offset'],
                                                        'full-image-white-context', info)
    if retry_failure is not None:
        raise retry_failure
    # A border change must not select a different pose. Compare only native
    # joints which already cleared the unchanged score gate; never interpolate
    # missing joints or mix coordinates from the two model executions.
    distances = np.linalg.norm(new_points[0, 5:17][trusted] - points[0, 5:17][trusted], axis=1)
    displacement = float(distances.max() / np.hypot(image.width, image.height))
    record['borderRetry']['agreement'] = {'nativeAnchorCount': int(trusted.sum()),
        'maximumDisplacementImageDiagonal': displacement, 'allowedDisplacementImageDiagonal': .05}
    if displacement > .05:
        record['attempts'][-1]['accepted'] = False
        raise PipelineError('POSE_LOW_CONFIDENCE', 'White-context pose disagrees with reliable native joints',
                            maximumDisplacementImageDiagonal=displacement, allowedDisplacementImageDiagonal=.05)
    record.update(estimationStatus='accepted', selectedAttempt=1)
    return body, new_points, new_scores


def extract_pose(config, image, run):
    import numpy as np
    import onnxruntime as ort
    from PIL import Image, ImageOps
    source = str(Path(config['poseAuxSource']).resolve())
    previous_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.path.insert(0, source)
    try:
        from custom_controlnet_aux import dwpose
        from custom_controlnet_aux.dwpose.dw_onnx.cv_ox_pose import inference_pose
        from custom_controlnet_aux.dwpose.types import BodyResult, Keypoint, PoseResult
    finally:
        sys.path.remove(source)
        sys.dont_write_bytecode = previous_bytecode
    if not Path(dwpose.__file__).resolve().is_relative_to(Path(source)):
        raise PipelineError('MODEL_NOT_READY', 'Unexpected DWPose module source', path=dwpose.__file__)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    options.inter_op_num_threads = 1
    detector = ort.InferenceSession(config['poseModel'], sess_options=options, providers=['CPUExecutionProvider'])
    if detector.get_inputs()[0].shape[1:] != [3, 384, 288]:
        raise PipelineError('MODEL_NOT_READY', 'Expected dw-ll_ucoco_384.onnx input shape')
    # Official estimator supports an empty bbox list as explicit full-image
    # top-down inference. It is appropriate for these single-person references;
    # no failed object detector is silently replaced with invented coordinates.
    body, points, scores = estimate_dwpose_body(image,
        lambda pixels, bbox: inference_pose(detector, bbox, pixels, (288, 384)), run)
    keypoints = [Keypoint(float(x), float(y), float(score), i) if score >= .3 else None
                 for i, (x, y, score) in enumerate(body)]
    poses = [PoseResult(BodyResult(keypoints, float(body[:, 2].sum()), sum(p is not None for p in keypoints)), None, None, None)]
    canvas = dwpose.draw_poses(poses, image.height, image.width, draw_body=True, draw_hand=False, draw_face=False)
    if not np.any(canvas):
        raise PipelineError('POSE_NOT_DETECTED', 'DWPose returned an empty skeleton')
    native = Image.fromarray(canvas)
    native_info = run.save_image('pose-native-skeleton', native, 'dwpose-full-image-body-only-on-black')
    params = run.audit['parameters']
    skeleton = ImageOps.pad(native, (params['width'], params['height']), method=Image.Resampling.BILINEAR, color='black')
    pose_info = run.save_image('pose-openpose', skeleton, 'skeleton-contain-letterbox-to-output-size')
    keypoints = [[p.x, p.y, p.score] if p is not None else None for p in poses[0].body.keypoints]
    run.audit['conditioning']['pose'].update({
        'inputRole': 'pose', 'method': 'DWPose-body-to-OpenPose-ControlNet', 'skeleton': pose_info,
        'nativeSkeleton': native_info, 'keypoints': keypoints, 'keypointCoordinates': 'normalized-to-native-skeleton',
        'detectorDevice': 'cpu', 'providers': detector.get_providers(), 'singleSubjectAssumption': True,
        'estimatorInputSize': [288, 384], 'limbScores': scores[0, 5:17].tolist(),
        'minimumLimbScore': float(scores[0, 5:17].min()), 'requiredLimbScore': .3,
        'includesFace': False, 'includesHands': False, 'scoresAreCalibratedProbabilities': False,
    })
    return skeleton


class IdentityHQConditioning:
    """Add two conditions to an IdentitySession; never own sampling or publication."""
    def __init__(self, identity_config, first, params, emit):
        from hq_tryon_pipeline import ConditioningAudit, read_json, validate_config
        import hq_paired_depth as paired_depth
        if params.modelId != 'realistic-vision-v5.1-faceid' or identity_config.get('architecture', 'SD1.5') != 'SD1.5':
            raise PipelineError('HQ_MODEL_UNSUPPORTED', 'HQ conditioning currently supports only existing RV SD1.5 FaceID')
        if params.animeProfileId or params.identityStrength <= 0:
            raise PipelineError('HQ_MODEL_UNSUPPORTED', 'HQ requires active FaceID identity conditioning without an anime profile')
        self.identity_config = identity_config
        self.first = first
        self.params = params
        self.run = ConditioningAudit(first, params.model_dump(), emit)
        self.offloaded = False
        self.render_started = False
        self.observer = None
        try:
            with self.run.stage('HQ 校验原始素材与模型绑定'):
                configured = read_json(self.run.config_path)
                expected = paired_depth.pipeline_id(configured, self.run.inputs['pose']['id'])
                if expected != self.run.audit['pipeline']:
                    raise PipelineError('HQ_PIPELINE_CHANGED', '任务提交后所选姿势的管线发生变化，请重新提交')
                self.config = validate_config(paired_depth.model_config(configured, expected), identity_config)
                self.images = self.run.prepare_images()
                if expected == paired_depth.PIPELINE:
                    self.depth_source = paired_depth.ensure_depth(self.run, self.config)
                self.run.audit['identityReference'].update(referenceId=params.referenceId, faceIndex=params.faceIndex)
                self.run.fingerprint_models(self.config, identity_config)
                if configured.get('poseEstimator') == paired_depth.ESTIMATOR and expected == paired_depth.LEGACY_PIPELINE:
                    models = self.run.audit['models']
                    if (models['controlnet']['sha256'] != paired_depth.OPENPOSE_SHA256 or
                            models['controlnetConfig/config.json']['sha256'] != paired_depth.OPENPOSE_CONFIG_SHA256):
                        raise PipelineError('MODEL_NOT_READY', '骨架 ControlNet 与已验证的版本不一致')
                self.run.audit['configuration'] = {'path': str(self.run.config_path),
                    'sha256': self.run.audit['models']['hqConfig']['sha256'], 'effective': self.config,
                    'parameterAuthority': 'IdentityGenerateRequest', 'modelAuthority': 'resolved-identity-runtime'}
                import importlib.metadata
                self.run.audit['runtime'] = {'python': sys.version, 'executable': sys.executable, 'packages': {}}
                for name in ('torch', 'diffusers', 'transformers', 'accelerate', 'peft', 'insightface', 'onnxruntime', 'safetensors'):
                    try:
                        self.run.audit['runtime']['packages'][name] = importlib.metadata.version(name)
                    except importlib.metadata.PackageNotFoundError:
                        self.run.audit['runtime']['packages'][name] = None
        except Exception as exc:
            self.fail(exc)
            raise

    def fail(self, exc):
        error = error_record(exc)
        self.run.audit.update(status='cancelled' if error['code'] == 'CANCELLED' else 'failed', error=error,
                              finishedAt=datetime.now(timezone.utc).isoformat())
        try:
            self.run.flush()
            self.run.emit('error', error=error)
        except Exception as publication_error:
            exc.add_note('HQ failure audit could not be updated: ' + str(publication_error))

    def prepare(self, features, feature_info):
        import torch
        from PIL import Image
        from insightface.utils import face_align
        from identity_pipeline import extract_clip_features, face_analysis, select_face
        with self.run.stage('HQ 记录成熟人物条件与服装图像特征'):
            image, faces = face_analysis(self.identity_config, self.first['imagePath'])
            face = select_face(faces, self.params.faceIndex)
            crop = Image.fromarray(face_align.norm_crop(image, landmark=face.kps, image_size=224)[:, :, ::-1])
            self.run.audit['preprocessing']['person'] = self.run.save_image('person-aligned-face', crop, 'existing-identity-5-landmark-224')
            self.run.audit['conditioning']['person'] = {
                'inputRole': 'person', 'adapterIndex': 0, 'method': 'existing-IdentitySession-FaceID-PlusV2',
                'featureKey': feature_info['featureKey'], 'cacheHit': feature_info['cacheHit'],
                'featureVersion': feature_info.get('featureVersion'), 'faceBox': face.bbox.tolist(),
                'landmarks': face.kps.tolist(), 'scale': self.params.identityStrength,
                'structureScale': self.params.structureStrength, 'loraScale': self.params.faceLoraStrength,
                'features': {name: save_tensor(self.run, 'person-' + name, tensor) for name, tensor in features.items()},
                'featureSource': 'existing-identity-reference_features',
            }
            positive, negative = extract_clip_features(self.identity_config, self.images['garment'])
            self.garment_clip = torch.cat([negative, positive])
            self.run.audit['conditioning']['garment'] = {
                'inputRole': 'garment', 'adapterIndex': 1, 'method': 'IP-Adapter-Plus',
                'scale': self.config['garmentScale'], 'clipHiddenLayer': -2, 'cfgOrder': ['negative', 'positive'],
                'clipHiddenStates': save_tensor(self.run, 'garment-clip-hidden', self.garment_clip),
                'featureSource': 'existing-identity-extract_clip_features',
            }
        import hq_paired_depth as paired_depth
        depth_mode = self.config['poseEstimator'] == paired_depth.ESTIMATOR
        with self.run.stage('HQ 读取已配对的原始深度图' if depth_mode else 'HQ CPU 姿态提取'):
            if depth_mode:
                self.pose_image = paired_depth.control_image(self.run, self.images['pose'], self.config, self.depth_source)
            else:
                self.pose_image = extract_pose(self.config, self.images['pose'], self.run)
            self.run.audit['conditioning']['pose']['scale'] = self.config['poseScale']
        del self.images

    def wrap_pipe(self, pipe):
        import torch
        from diffusers import ControlNetModel, StableDiffusionControlNetPipeline
        with self.run.stage('HQ 为现有底模装配 ControlNet'):
            controlnet = ControlNetModel.from_single_file(self.config['controlnet'], config=self.config['controlnetConfig'],
                                                         torch_dtype=torch.float16, local_files_only=True)
            if controlnet.config.cross_attention_dim != 768 or pipe.unet.config.cross_attention_dim != 768:
                raise PipelineError('MODEL_NOT_READY', 'HQ ControlNet must match the existing SD1.5 UNet')
            # diffusers 0.36 defaults from_pipe to float32 and casts the shared
            # modules in place. Preserve IdentitySession's fp16 weights/tokens.
            wrapped = StableDiffusionControlNetPipeline.from_pipe(pipe, controlnet=controlnet, torch_dtype=None)
            for name in ('unet', 'vae', 'text_encoder', 'tokenizer', 'scheduler'):
                if getattr(wrapped, name) is not getattr(pipe, name):
                    raise PipelineError('HQ_REUSE_FAILED', 'ControlNet wrapper must share identity components', component=name)
            self.run.audit['sharedIdentityComponents'] = ['unet', 'vae', 'text_encoder', 'tokenizer', 'scheduler']
            self.run.audit['componentDtypes'] = {name: str(getattr(wrapped, name).dtype)
                                                for name in ('unet', 'vae', 'text_encoder', 'controlnet')}
            return wrapped

    def load_adapters(self, pipe):
        from diffusers.models.embeddings import IPAdapterFaceIDPlusImageProjection
        states = [load_adapter(self.identity_config['adapter']), load_adapter(self.config['garmentAdapter'])]
        pipe.load_ip_adapter(states, subfolder=['', ''], weight_name=['person.bin', 'garment.bin'],
                             image_encoder_folder=None, local_files_only=True)
        if not isinstance(pipe.unet.encoder_hid_proj.image_projection_layers[0], IPAdapterFaceIDPlusImageProjection):
            raise PipelineError('MODEL_NOT_READY', 'Expected the existing FaceID Plus V2 projection in slot 0')

    def finish_projection(self, pipe, person):
        import torch
        with self.run.stage('HQ 投影服装条件并绑定独立槽'):
            self.garment = project_garment(pipe, self.garment_clip)
            del self.garment_clip
            self.run.audit['adapterAttention'] = adapter_layout(pipe)
            for role, tensor in (('person', person), ('garment', self.garment)):
                self.run.audit['conditioning'][role]['preparedConditioning'] = save_tensor(self.run, role + '-tokens', tensor)
            self.pose = pipe.control_image_processor.preprocess(self.pose_image, width=self.params.width, height=self.params.height)
            self.pose = self.pose.to(dtype=pipe.controlnet.dtype)
            self.run.audit['conditioning']['pose']['preparedConditioning'] = save_tensor(self.run, 'pose-controlnet', self.pose)
            del self.pose_image
            self.run.audit['device'] = {'name': torch.cuda.get_device_name(), 'offload': self.config['offload'], 'dtype': str(pipe.unet.dtype)}

    def place(self, pipe):
        self.run.check_cancel()
        if not self.offloaded:
            pipe.set_progress_bar_config(disable=True)
            if self.config['offload'] == 'sequential':
                pipe.enable_sequential_cpu_offload(device='cuda')
            else:
                pipe.enable_model_cpu_offload(device='cuda')
            self.offloaded = True

    def release_for_polish(self, pipe):
        # Restore Accelerate's meta tensors from CPU maps before the mature
        # FacePolisher performs its existing pipe.to('cpu') / GFPGAN sequence.
        pipe.remove_all_hooks()
        pipe.to('cpu')
        self.offloaded = False

    def image_embeds(self, person):
        return [person, self.garment]

    @contextmanager
    def sampling(self, pipe, person, item):
        import torch
        from identity_contract import IdentityGenerateRequest
        if self.render_started or item.get('jobId') != self.first['jobId'] or item.get('hqConditioning') != self.first['hqConditioning']:
            raise PipelineError('HQ_REUSE_FORBIDDEN', 'HQ conditions belong to one identity child job; start a fresh worker')
        current = IdentityGenerateRequest.model_validate({k: v for k, v in item.items() if k in IdentityGenerateRequest.model_fields})
        if current != self.params:
            raise PipelineError('HQ_REUSE_FORBIDDEN', 'Identity parameters changed after HQ conditioning was bound')
        self.render_started = True
        self.run.check_cancel()
        self.run.audit['status'] = 'sampling'
        self.run.audit['scheduler'] = {'class': type(pipe.scheduler).__name__, 'config': dict(pipe.scheduler.config)}
        observer = ConditioningObserver(self.run, [person, self.garment], torch.cat([self.pose, self.pose]))
        self.observer = observer
        observer.attach(pipe)
        try:
            with self.run.stage('HQ 通过 IdentitySession 采样'):
                yield {'image': self.pose, 'controlnet_conditioning_scale': self.config['poseScale'],
                       'control_guidance_start': 0., 'control_guidance_end': 1., 'guess_mode': False}
                observer.finish(self.params.steps)
        finally:
            observer.close()

    def on_step(self, index, timestep):
        self.run.check_cancel()
        self.run.audit['completedSteps'] = index + 1
        # Main identity progress already comes from sampling_callback; the optional
        # HQ event sidecar also carries that exact step for local consumers.
        if self.run.event_path:
            event = {'type': 'step', 'jobId': self.first['jobId'], 'step': index + 1,
                     'totalSteps': self.params.steps, 'timestep': float(timestep)}
            with self.run.event_path.open('a', encoding='utf-8', newline='\n') as stream:
                stream.write(json.dumps(event) + '\n')
                stream.flush()

    def base_image(self, image):
        self.run.check_cancel()
        self.run.audit['baseBeforePolish'] = {'sha256': image_digest(image), 'width': image.width, 'height': image.height}

    def complete(self, metadata):
        import copy
        self.run.verify_unchanged()
        self.run.check_cancel()
        output = Path(metadata['output'])
        self.run.audit.update(status='completed', finishedAt=datetime.now(timezone.utc).isoformat(),
            output={'path': str(output), 'sha256': self.run.digest(output), 'width': metadata['width'], 'height': metadata['height'],
                    'bytes': output.stat().st_size}, facePolish=metadata['facePolish'],
            peakAllocatedMiB=metadata['peakAllocatedMiB'], peakReservedMiB=metadata['peakReservedMiB'])
        if metadata['facePolish'].get('originalImageUrl'):
            original = Path(self.first['dreamRoot']) / 'data/identity/originals' / (self.first['jobId'] + '.png')
            digest = self.run.digest(original)
            if digest != self.run.audit['baseBeforePolish']['sha256']:
                raise PipelineError('HQ_ORIGINAL_MISMATCH', 'Identity original differs from the observed base image')
            self.run.audit['baseBeforePolish'].update(path=str(original), originalImageUrl=metadata['facePolish']['originalImageUrl'])
        self.run.flush()
        return copy.deepcopy(self.run.audit)
