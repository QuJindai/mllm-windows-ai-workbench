from __future__ import annotations

import gc
import hashlib
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

MODEL_ID = 'realistic-vision-v5.1-faceid'


def select_face(faces, index):
    ordered = sorted(faces, key=lambda f: (float(f['bbox'][0]), float(f['bbox'][1])))
    if index < 0 or index >= len(ordered):
        raise ValueError('所选人脸不存在，请重新选择参考人脸')
    return ordered[index]


def require_cuda(available, free, total):
    if not available:
        raise RuntimeError('CUDA 不可用；人物生成不会静默退回 CPU')
    if free < 3 * 1024**3 or total < 4 * 1024**3:
        raise RuntimeError('可用显存不足，请关闭其他 GPU 任务后重试')


def asset_fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            digest.update(block)
    return digest.hexdigest()


def face_analysis(config, image_path, *, recognition=True):
    import cv2
    import onnxruntime as ort
    from insightface.app import FaceAnalysis
    root = Path(config['insightfaceRoot'])
    for filename in (('det_10g.onnx', 'w600k_r50.onnx') if recognition else ('det_10g.onnx',)):
        if not (root / 'models' / 'buffalo_l' / filename).is_file():
            raise ValueError('本地 InsightFace 模型不完整')
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    app = FaceAnalysis(name='buffalo_l', root=str(root), allowed_modules=['detection', 'recognition'] if recognition else ['detection'], providers=['CPUExecutionProvider'], sess_options=options)
    app.prepare(ctx_id=-1, det_size=(640, 640))
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError('无法读取参考图')
    faces = sorted(app.get(image), key=lambda face: (float(face.bbox[0]), float(face.bbox[1])))
    return image, faces


def reference_boxes(faces, width, height):
    result = []
    for index, face in enumerate(faces[:20]):
        box = [round(max(0, min(float(value), limit)), 2) for value, limit in zip(face.bbox, (width, height, width, height))]
        if box[2] > box[0] and box[3] > box[1]:
            result.append({'index': index, 'box': box})
    return result


def inspect_reference(config, request):
    if request.get('referenceKind') == 'visual':
        image, faces = visual_analysis(config, request['imagePath'])
        return {'faces': reference_boxes(faces, image.shape[1], image.shape[0])}
    image, faces = face_analysis(config, request['imagePath'])
    return {'faces': reference_boxes(faces, image.shape[1], image.shape[0])}


def visual_analysis(config, image_path):
    image, faces = face_analysis(config, image_path, recognition=False)
    if not faces:
        from PIL import Image
        from types import SimpleNamespace
        from identity_anime import AnimeDetector
        boxes = AnimeDetector(config).detect(Image.fromarray(image[:, :, ::-1]))
        faces = [SimpleNamespace(bbox=box, kps=None) for box in sorted(boxes, key=lambda b: (b[0], b[1]))]
    return image, faces


def registered_loras(config):
    directory = Path(config['lorasDir'])
    result = []
    if not directory.is_dir():
        return result
    for manifest in directory.glob('*.json'):
        try:
            item = json.loads(manifest.read_text(encoding='utf-8-sig'))
            path = (directory / item['file']).resolve()
            path.relative_to(directory.resolve())
            if item.get('architecture') != config.get('architecture', 'SD1.5') or not path.is_file() or path.suffix != '.safetensors':
                continue
            result.append({'id': manifest.stem, 'name': str(item.get('name') or manifest.stem), 'path': str(path)})
        except (ValueError, KeyError, OSError, TypeError):
            continue
    return result


def load_companion_lora(pipe, path):
    path = Path(path)
    return pipe.load_lora_weights(str(path.parent), weight_name=path.name, local_files_only=True, adapter_name='identity')


def load_identity_pipe(config):
    import torch
    from diffusers import StableDiffusionPipeline, StableDiffusionXLPipeline
    xl = config.get('architecture') == 'SDXL'
    factory = StableDiffusionXLPipeline if xl else StableDiffusionPipeline
    options = {'add_watermarker': False} if xl else {'safety_checker': None, 'requires_safety_checker': False}
    pipe = factory.from_single_file(config['checkpoint'], config=config['pipelineConfig'], local_files_only=True,
                                    torch_dtype=torch.float16, **options)
    if pipe.unet.config.cross_attention_dim != (2048 if xl else 768):
        raise ValueError('人物底模架构与身份配套配置不匹配')
    return pipe


def place_identity_pipe(pipe, architecture):
    if architecture == 'SDXL':
        # Full SDXL UNet + IP-Adapter exceeds the safe budget on a 6GB GPU.
        # Retain CPU weights and move submodules for CUDA computation on demand.
        pipe.enable_sequential_cpu_offload()
    else:
        pipe.to('cuda')


def configure_cuda():
    import torch
    torch.set_num_threads(4)
    available = torch.cuda.is_available()
    free, total = torch.cuda.mem_get_info() if available else (0, 0)
    require_cuda(available, free, total)
    torch.cuda.set_per_process_memory_fraction(min(.80, (free - 1024**3) / total))
    torch.cuda.reset_peak_memory_stats()


def extract_reference_features(config, image_path, face_index):
    import numpy as np
    import torch
    from PIL import Image
    from insightface.utils import face_align
    configure_cuda()
    image, faces = face_analysis(config, image_path)
    face = select_face(faces, face_index)
    crop = Image.fromarray(face_align.norm_crop(image, landmark=face.kps, image_size=224)[:, :, ::-1])
    id_embeds = torch.from_numpy(np.array(face.normed_embedding, copy=True)).float().unsqueeze(0)
    clip, negative_clip = extract_clip_features(config, crop)
    return {'id': id_embeds, 'clip': clip, 'negative_clip': negative_clip}


def extract_visual_features(config, image_path, face_index):
    from PIL import Image
    from insightface.utils import face_align
    from identity_anime import crop_box
    image, faces = visual_analysis(config, image_path)
    if not 0 <= face_index < len(faces):
        raise ValueError('视觉参考中未检测到所选脸部，请使用清晰的单人近景图')
    face = faces[face_index]
    if face.kps is not None:
        crop = Image.fromarray(face_align.norm_crop(image, landmark=face.kps, image_size=224)[:, :, ::-1])
    else:
        source = Image.fromarray(image[:, :, ::-1])
        crop = source.crop(crop_box(source.size, face.bbox))
    clip, negative = extract_clip_features(config, crop)
    return {'clip': clip, 'negative_clip': negative}


def clip_vision_config():
    from transformers import CLIPVisionConfig
    # h94/IP-Adapter ViT-H uses exact GELU, not the Transformers quick_gelu default.
    return CLIPVisionConfig(hidden_act='gelu', hidden_size=1280, intermediate_size=5120,
                            num_hidden_layers=32, num_attention_heads=16, projection_dim=1024,
                            image_size=224, patch_size=14)


def extract_clip_features(config, crop):
    import torch
    from safetensors.torch import load_file
    from transformers import CLIPVisionConfig, CLIPVisionModelWithProjection, CLIPImageProcessor
    configure_cuda()
    vision_config = clip_vision_config()
    vision = CLIPVisionModelWithProjection(vision_config).to(dtype=torch.float16)
    weights = load_file(config['clipVision'])
    weights.pop('vision_model.embeddings.position_ids', None)
    vision.load_state_dict(weights, strict=True)
    del weights
    vision.to('cuda').eval()
    pixels = CLIPImageProcessor()(images=crop, return_tensors='pt').pixel_values.to('cuda', dtype=torch.float16)
    with torch.inference_mode():
        clip = vision(pixels, output_hidden_states=True).hidden_states[-2].cpu()
        negative_clip = vision(torch.zeros_like(pixels), output_hidden_states=True).hidden_states[-2].cpu()
    del vision, pixels
    gc.collect()
    torch.cuda.empty_cache()
    return clip, negative_clip


def prepare(config, request):
    from identity_features import reference_features, visual_reference_features
    if request.get('referenceKind') == 'visual':
        _, info = visual_reference_features(config, request, extract_visual_features)
    else:
        _, info = reference_features(config, request, extract_reference_features)
    return {'ok': True, **info}


def save_preview(pipe, latents, destination):
    import torch
    from PIL import Image
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with torch.inference_mode():
        decoded = pipe.vae.decode(latents[:1].detach().to(dtype=pipe.vae.dtype) / pipe.vae.config.scaling_factor, return_dict=False)[0]
        image = pipe.image_processor.postprocess(decoded, output_type='pil')[0]
    image.thumbnail((256, 256), Image.Resampling.LANCZOS)
    temp = destination.with_suffix('.tmp')
    image.save(temp, format='PNG')
    os.replace(temp, destination)


@contextmanager
def capture_denoised_preview(scheduler, enabled):
    """Observe Euler's existing x0 estimate without extra UNet calls or changing sampling."""
    state = {}
    if not enabled:
        yield state
        return
    original = scheduler.step
    @wraps(original)
    def observed_step(*args, **kwargs):
        result = original(*args, **kwargs)
        state['latents'] = result[1] if isinstance(result, tuple) else result.pred_original_sample
        return result
    scheduler.step = observed_step
    try:
        yield state
    finally:
        scheduler.step = original
        state.clear()


def sampling_callback(job_id, item_index, total_steps, emit, preview_dir, preview_every, started, denoised=None, research=None):
    def callback(pipe, index, timestep, values):
        step = index + 1
        if research is not None:
            research.on_step(values['latents'], index)
        event = {'type': 'step', 'itemIndex': item_index, 'step': step,
                 'totalSteps': total_steps, 'elapsedMs': round((time.perf_counter() - started) * 1000)}
        if preview_every and (step % preview_every == 0 or step == total_steps):
            filename = f'{job_id}-step-{step:03d}.png'
            try:
                # x0 is the scheduler's measured denoised estimate, not a separate generated image.
                preview_latents = denoised['latents'] if denoised is not None else values['latents']
                save_preview(pipe, preview_latents, Path(preview_dir) / filename)
                event['previewFile'] = filename
                event['previewSource'] = 'predicted_original_sample' if denoised is not None else 'latents'
            except Exception:
                # Preview is optional: don't substitute a fake image or fail final generation.
                emit({'type': 'preview_error', 'itemIndex': item_index, 'message': '中间预览解码失败，继续生成'})
        emit(event)
        if step == total_steps:
            emit({'type': 'stage', 'stage': 'VAE 解码', 'itemIndex': item_index})
        return values
    return callback


@contextmanager
def visual_reference_schedule(pipe, item, steps=None):
    """Gate Plus Face on i/N in [start,end); restore exact prior processor scales."""
    from identity_models import is_visual_model_id
    unet = getattr(pipe, 'unet', None)
    processors = [(module.processor, module.processor.scale) for module in unet.modules()
                  if hasattr(module, 'processor') and hasattr(module.processor, 'to_k_ip')] if unet is not None else []
    visual = is_visual_model_id(item.get('modelId'))
    total = max(1, steps if steps is not None else item['steps'])
    def shaped(scale, value):
        return [shaped(part, value) for part in scale] if isinstance(scale, list) else value
    def advance(index):
        if visual:
            active = item.get('referenceStart', 0.) <= index / total < item.get('referenceEnd', 1.)
            for processor, original in processors:
                processor.scale = shaped(original, item.get('identityStrength', .82) if active else 0.)
    try:
        advance(0)
        yield advance
    finally:
        if visual:
            for processor, original in processors:
                processor.scale = original


class IdentitySession:
    """One pipeline per batch. CUDA lifetime remains bounded by the worker process."""
    def __init__(self, config, first, emit):
        import torch
        from safetensors.torch import load_file
        from diffusers import EulerDiscreteScheduler
        from diffusers.models.embeddings import MultiIPAdapterImageProjection
        from identity_contract import IdentityGenerateRequest
        from identity_features import FingerprintCache, reference_features, visual_reference_features
        from identity_models import is_visual_model_id
        params = IdentityGenerateRequest.model_validate({k: v for k, v in first.items() if k in IdentityGenerateRequest.model_fields})
        self.architecture = config.get('architecture', 'SD1.5')
        visual = is_visual_model_id(params.modelId)
        if visual:
            self.visual_reference = (params.referenceId, params.faceIndex)
        configure_cuda()
        self.started = time.perf_counter()
        self.initial_stages = []
        point = time.perf_counter()
        emit({'type': 'stage', 'stage': '读取档案身份特征'})
        if visual:
            features, self.feature_info = visual_reference_features(config, first, extract_visual_features)
        else:
            features, self.feature_info = reference_features(config, first, extract_reference_features)
        fingerprints = FingerprintCache(Path(first['dreamRoot']) / 'data' / 'identity' / 'fingerprints.json')
        self.hashes = dict(self.feature_info['assetHashes'])
        for key in (('checkpoint', 'adapter') if visual else ('checkpoint', 'adapter', 'faceLora')):
            self.hashes[key] = fingerprints.digest(config[key], force=bool(first.get('forceFingerprint', False)))
        self.initial_stages.append({'name': '参考人脸与特征缓存', 'durationMs': round((time.perf_counter() - point) * 1000), 'truth': 'observed'})
        point = time.perf_counter()
        emit({'type': 'stage', 'stage': f'加载 {self.architecture} 与身份条件'})
        pipe = load_identity_pipe(config)
        pipe.scheduler = EulerDiscreteScheduler.from_config(pipe.scheduler.config, use_karras_sigmas=False)
        if visual:
            adapter_path = Path(config['adapter'])
            pipe.load_ip_adapter(str(adapter_path.parent), subfolder='', weight_name=adapter_path.name,
                                 image_encoder_folder=None, local_files_only=True)
        else:
            adapter = torch.load(config['adapter'], map_location='cpu', weights_only=True)
            pipe.load_ip_adapter(adapter, subfolder='', weight_name='faceid.bin', image_encoder_folder=None)
            del adapter
        if getattr(pipe.unet, 'peft_config', {}):
            pipe.unload_lora_weights()
        names, scales = [], []
        if not visual:
            load_companion_lora(pipe, config['faceLora'])
            names, scales = ['identity'], [params.faceLoraStrength]
        if params.loraId:
            candidate = next((row for row in registered_loras(config) if row['id'] == params.loraId), None)
            if candidate is None:
                raise ValueError('所选 LoRA 与底模架构不匹配或不可用')
            style = load_file(candidate['path'])
            if self.architecture == 'SD1.5' and any('text_encoder_2' in key or 'lora_te2' in key for key in style):
                raise ValueError('不能将 SDXL LoRA 用于 SD1.5')
            pipe.load_lora_weights(style, adapter_name='style')
            names.append('style')
            scales.append(params.loraStrength)
            self.hashes['styleLora'] = fingerprints.digest(candidate['path'])
            del style
        if names:
            pipe.set_adapters(names, adapter_weights=scales)
        pipe.set_ip_adapter_scale(params.identityStrength)
        if visual:
            # Retain the native Plus Face patch projection used by the accepted A/B route.
            self.projected = torch.cat([features['negative_clip'], features['clip']]).unsqueeze(1).to(dtype=torch.float16)
        else:
            projection = pipe.unet.encoder_hid_proj.image_projection_layers[0].to('cuda', dtype=torch.float16)
            projection.shortcut = True
            projection.shortcut_scale = params.structureStrength
            projection.clip_embeds = torch.cat([features['negative_clip'], features['clip']]).unsqueeze(1).to('cuda', dtype=torch.float16)
            face_embeddings = torch.cat([torch.zeros_like(features['id']), features['id']]).to('cuda', dtype=torch.float16)
            with torch.inference_mode():
                self.projected = projection(face_embeddings).unsqueeze(1)
                if params.facePolish and params.animeProfileId:
                    self.project_anime(projection, first, config)
            pipe.unet.encoder_hid_proj = MultiIPAdapterImageProjection([torch.nn.Identity()])
            del projection, face_embeddings
        del features
        gc.collect()
        torch.cuda.empty_cache()
        pipe.vae.enable_slicing()
        pipe.vae.enable_tiling()
        place_identity_pipe(pipe, self.architecture)
        self.pipe = pipe
        self.config = config
        self.initial_stages.append({'name': f'{self.architecture} 与身份条件加载', 'durationMs': round((time.perf_counter() - point) * 1000), 'truth': 'observed'})

    def render(self, item, item_index, emit, preview_dir, preview_every):
        import torch
        from PIL import ImageStat
        from identity_contract import IdentityGenerateRequest
        from identity_research import IdentityResearch
        params = IdentityGenerateRequest.model_validate({k: v for k, v in item.items() if k in IdentityGenerateRequest.model_fields})
        point = time.perf_counter()
        if getattr(self, 'architecture', 'SD1.5') != 'SDXL':
            self.pipe.to('cuda')
        emit({'type': 'stage', 'stage': '采样', 'itemIndex': item_index})
        with visual_reference_schedule(self.pipe, params.model_dump()) as advance, torch.inference_mode(), capture_denoised_preview(self.pipe.scheduler, bool(preview_every)) as denoised, IdentityResearch(self.pipe, item, params) as research:
            progress = sampling_callback(item['jobId'], item_index, params.steps, emit, preview_dir, preview_every, point, denoised, research)
            def callback(pipe, index, timestep, values):
                values = progress(pipe, index, timestep, values)
                advance(index + 1)
                return values
            result = self.pipe(prompt=params.prompt, negative_prompt=params.negativePrompt, width=params.width, height=params.height,
                               num_inference_steps=params.steps, guidance_scale=params.cfg,
                               generator=torch.Generator(device='cpu').manual_seed(params.seed), ip_adapter_image_embeds=[self.projected],
                               callback_on_step_end=callback, callback_on_step_end_tensor_inputs=['latents']).images[0]
        stages = list(self.initial_stages if item_index == 0 else [])
        stages.append({'name': '采样与 VAE 解码', 'durationMs': round((time.perf_counter() - point) * 1000), 'truth': 'observed'})
        if max(ImageStat.Stat(result.convert('RGB')).stddev) < 2:
            raise RuntimeError('生成结果近乎纯色，未通过图像检查')
        from identity_face_polish import optional_face_polish
        result, polish = optional_face_polish(result, params, item, lambda: self.face_polisher(item),
                                              lambda stage: emit({'type': 'stage', 'stage': stage, 'itemIndex': item_index}))
        if polish['enabled']:
            stages.append({'name': '可选修脸', 'durationMs': polish['durationMs'], 'truth': 'observed', 'status': polish['status']})
        emit({'type': 'stage', 'stage': '保存结果', 'itemIndex': item_index})
        output = Path(item['outputPath'])
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = output.with_suffix('.tmp')
        result.save(temp, format='PNG')
        os.replace(temp, output)
        elapsed = round((time.perf_counter() - (self.started if item_index == 0 else point)) * 1000)
        from identity_models import MODEL_SPECS, is_visual_model_id
        metadata = {'id': item['jobId'], 'model_id': params.modelId, 'model_name': MODEL_SPECS[params.modelId][0],
                    'prompt': params.prompt, 'negative_prompt': params.negativePrompt, 'width': params.width, 'height': params.height,
                    'steps': params.steps, 'cfg': params.cfg, 'seed': params.seed, 'sampler': 'Euler', 'output': str(output),
                    'generation_time_ms': elapsed, 'generated_at': datetime.now(timezone.utc).isoformat(), 'identity': params.model_dump(),
                    'backend': ('diffusers-ipadapter-plus-face-sdxl' if is_visual_model_id(params.modelId) else 'diffusers-faceid-sdxl' if params.modelId == 'illustrious-xl-v2.0-faceid' else 'diffusers-faceid-sd15'), 'stages': stages, 'facePolish': polish, 'cacheHit': self.feature_info['cacheHit'],
                    'featureKey': self.feature_info['featureKey'], 'modelReused': item_index > 0, 'batchItemIndex': item_index,
                    'previewEvery': preview_every, 'previewSource': 'predicted_original_sample' if preview_every else None,
                    'assetHashes': self.hashes, 'peakAllocatedMiB': round(torch.cuda.max_memory_allocated() / 1024**2),
                    'peakReservedMiB': round(torch.cuda.max_memory_reserved() / 1024**2),
                    'referenceKind': self.feature_info.get('referenceKind', 'faceid'),
                    'featureVersion': self.feature_info.get('featureVersion'), 'clipActivation': self.feature_info.get('clipActivation'),
                    'tags': ['人物创作', '动漫视觉参考' if is_visual_model_id(params.modelId) else 'FaceID']}
        try:
            metadata['research'] = research.finish(metadata)
        except Exception as exc:
            # The image is already generated and published. A trace-publication
            # failure must not prevent its history record from being saved.
            print(f'Research publication failed: {type(exc).__name__}: {exc}', file=sys.stderr)
            metadata['research'] = {
                'h6': False, 'h7': False, 'status': 'failed',
                'traceLevel': params.traceLevel, 'coverage': params.researchCoverage,
                'error': {'code': 'IDENTITY_RESEARCH_PUBLICATION_FAILED'},
                'message': '研究产物发布失败，已保留生成图片和历史记录；本次研究结果不可用',
            }
        metadata_path = Path(item['metadataPath'])
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        temp = metadata_path.with_suffix('.tmp')
        temp.write_text(json.dumps(metadata, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
        os.replace(temp, metadata_path)
        return {'jobId': item['jobId'], 'imageUrl': f"/api/history/{item['jobId']}/image", 'metadata': metadata}

    def project_anime(self, projection, item, config=None):
        import torch
        from identity_anime import load_anime_features
        try:
            anime = load_anime_features(item, config) if config is not None else load_anime_features(item)
            projection.clip_embeds = torch.cat([anime['negative_clip'], anime['clip']]).unsqueeze(1).to('cuda', dtype=torch.float16)
            anime_id = torch.cat([torch.zeros_like(anime['id']), anime['id']]).to('cuda', dtype=torch.float16)
            with torch.inference_mode():
                self.anime_projected = projection(anime_id).unsqueeze(1)
        except Exception as exc:
            print(f'Optional anime projection failed: {type(exc).__name__}: {exc}', file=sys.stderr)
            self._anime_error = '动漫参考特征加载失败，已保留正常生图；请检查档案后重试'

    def face_polisher(self, item):
        from identity_models import is_visual_model_id
        if is_visual_model_id(item.get('modelId')):
            from identity_visual_polish import VisualReferencePolisher
            if not hasattr(self, '_visual_polisher'):
                self._visual_polisher = VisualReferencePolisher(self)
            return self._visual_polisher
        if item.get('animeProfileId'):
            if getattr(self, '_anime_error', None):
                raise ValueError(self._anime_error)
            from identity_anime import AnimePolisher
            if not hasattr(self, '_anime_polisher'):
                self._anime_polisher = AnimePolisher(self)
            return self._anime_polisher
        import torch
        from identity_face_polish import FacePolisher
        # Retain warm CPU models between batch items; never overlap generation and
        # FP32 face restoration on a 6 GB device.
        if getattr(self, 'architecture', 'SD1.5') != 'SDXL':
            self.pipe.to('cpu')
        torch.cuda.empty_cache()
        if not hasattr(self, '_face_polisher'):
            self._face_polisher = FacePolisher(self.config, item)
        return self._face_polisher


def validate_batch_items(items):
    from identity_contract import IdentityGenerateRequest
    if not isinstance(items, list) or not 1 <= len(items) <= 16:
        raise ValueError('人物批次数量必须在 1 到 16 之间')
    fixed = ('modelId', 'referenceId', 'faceIndex', 'width', 'height', 'cfg', 'identityStrength', 'referenceStart', 'referenceEnd', 'structureStrength', 'faceLoraStrength', 'loraId', 'loraStrength', 'facePolish', 'animeProfileId')
    signatures, paths = [], set()
    for item in items:
        params = IdentityGenerateRequest.model_validate({k: v for k, v in item.items() if k in IdentityGenerateRequest.model_fields})
        if not isinstance(params.seed, int):
            raise ValueError('任务种子尚未固化')
        signatures.append(tuple(getattr(params, key) for key in fixed) + (str(Path(item['imagePath']).resolve()), str(Path(item['dreamRoot']).resolve())))
        for key in ('outputPath', 'metadataPath'):
            path = str(Path(item[key]).resolve())
            if path in paths:
                raise ValueError('批次输出路径重复')
            paths.add(path)
    if any(value != signatures[0] for value in signatures[1:]):
        raise ValueError('同一批次只能复用同一人物、尺寸和身份条件')


def generate_batch(config, request):
    from identity_events import emit_event
    items = request.get('items')
    validate_batch_items(items)
    interval = request.get('previewEvery', 0)
    if isinstance(interval, bool) or interval not in (0, 5, 10):
        raise ValueError('预览间隔必须为 0、5 或 10')
    started = time.perf_counter()
    def emit(event):
        emit_event(request.get('eventPath'), {**event, 'elapsedMs': round((time.perf_counter() - started) * 1000)})
    session = IdentitySession(config, items[0], emit)
    results = []
    for index, item in enumerate(items):
        result = session.render(item, index, emit, request.get('previewDir'), interval)
        if not Path(item['outputPath']).is_file() or not Path(item['metadataPath']).is_file():
            raise RuntimeError('人物结果文件未完整写入')
        results.append(result)
        emit({'type': 'item_complete', 'itemIndex': index, 'jobId': item['jobId']})
    return {'ok': True, 'items': results}


def generate(config, request):
    result = generate_batch(config, {'items': [request], 'previewEvery': 0})['items'][0]
    return {'ok': True, **result}
