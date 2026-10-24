"""Optional Plus Face local redraw, using the selected visual reference only."""
from pathlib import Path
import time

from identity_anime import AnimeDetector, one_face, crop_box, face_mask, blend_face, restore_offload_state
from identity_models import is_visual_model_id, visual_restore_model


def detail_prompts(item):
    # A cropped face is not a second scene composition. Empty overrides select
    # local-detail defaults rather than inheriting clothing/framing instructions.
    return (
        item.get('visualPolishPrompt', '').strip() or
        'anime face, clean lineart, detailed eyes, natural facial proportions, coherent shading',
        item.get('visualPolishNegativePrompt', '').strip() or
        'photograph, photorealistic, blurry, deformed eyes, distorted face, extra eyes, text, watermark',
    )


def detail_size(crop, box):
    width, height = crop[2]-crop[0], crop[3]-crop[1]
    face_side = min(box[2]-box[0], box[3]-box[1])
    if min(width, height, face_side) <= 0:
        raise ValueError('无效修脸区域')
    # Aim for a 512px face, not a 512px padded crop. Keep native pixels when
    # already large; the 768 crop ceiling protects this machine's 6GiB GPU.
    scale = min(max(1., 512 / face_side), 768 / max(width, height))
    size = (int(width*scale)//8*8, int(height*scale)//8*8)
    if min(size) < 128:
        raise ValueError('修脸区域过窄，保留原图')
    return size


def visual_polish_status(config, find_spec=None):
    # Inspect package availability in the worker interpreter without importing
    # model libraries, loading weights, or initializing a GPU context.
    if find_spec is None:
        from importlib.util import find_spec
    ready = Path(config.get('animeFaceDetector', '')).is_file()
    missing = []
    if not ready:
        missing.append('animeFaceDetector')
    if not Path(config.get('faceParsingModel') or '').is_file():
        missing.append('faceParsingModel')
    alignment_root = config.get('insightfaceRoot')
    if not alignment_root or not (Path(alignment_root) / 'models/buffalo_l/det_10g.onnx').is_file():
        missing.append('insightfaceRoot/models/buffalo_l/det_10g.onnx')
    for name in ('facexlib', 'cv2', 'insightface', 'onnxruntime', 'torch'):
        try:
            available = find_spec(name) is not None
        except (ImportError, ValueError):
            available = False
        if not available:
            missing.append(name)
    return {'ready': ready, 'message': (
        '支持局部重绘与分阶段细化；复用当前视觉参考底模，保留原图与阶段结果'
        if ready else '动漫脸检测模型未配置，关闭修脸仍可生成'),
        'referenceAnchorReady': not missing,
        'referenceAnchorMessage': ('参考脸对齐与中心五官保护组件就绪；实际效果需生成验证'
                                   if not missing else '参考脸对齐未就绪，缺少：' + ', '.join(missing))}


class VisualReferencePolisher:
    def __init__(self, session):
        self.session = session
        self.detector = AnimeDetector(session.config)

    def apply(self, image, item, strength, stage):
        # `strength` belongs to legacy GFPGAN. This path deliberately uses the
        # explicit bounded denoise control instead, never a biometric restorer.
        if (not is_visual_model_id(item.get('modelId'))
                or item.get('animeProfileId')
                or (item.get('referenceId'), item.get('faceIndex')) != self.session.visual_reference):
            raise ValueError('动漫视觉修脸参考与当前任务不一致')
        import torch
        from diffusers import StableDiffusionXLInpaintPipeline, EulerDiscreteScheduler
        from PIL import Image, ImageStat

        pipe = self.session.pipe
        vae_dtype = pipe.vae.dtype
        mode = item.get('visualPolishMode', 'redraw')
        pass_count = item.get('visualPolishPasses', 1)
        staged = mode == 'reference-anchor' or pass_count > 1
        snapshots, passes, anchor_info = [], [], {}
        if staged:
            from identity_stage_artifacts import save_visual_stage, cleanup_visual_stages
        prompt, negative = detail_prompts(item)
        denoise = item.get('animeDenoiseStrength', .35)
        try:
            stage('定位动漫脸')
            current = image
            if mode == 'reference-anchor':
                from identity_reference_anchor import ReferenceAnchor
                stage('参考脸对齐初始化')
                binding = (item['imagePath'], item['faceIndex'])
                if getattr(self, '_anchor_binding', None) != binding:
                    self._anchor = ReferenceAnchor(self.session.config, *binding)
                    self._anchor_binding = binding
                current, box, anchor_info, blend_mask = self._anchor.apply_protected(
                    image, item.get('visualAnchorStrength', .95), self.session.config)
                snapshots.append({'kind': 'anchor', 'imageUrl': save_visual_stage(current, item, 'anchor')})
            else:
                box = one_face(self.detector.detect(image))
            crop = crop_box(image.size, box)
            width, height = detail_size(crop, box)
            if mode != 'reference-anchor':
                blend_mask = face_mask(image.size, box)
            # Sample the entire nonzero seam, including its feathered outer edge.
            # Native-resolution compositing separately enforces protected pixels.
            cutoff = 0 if mode == 'reference-anchor' else 127
            mask = blend_mask.point(lambda value: 255 if value > cutoff else 0)
            mask = mask.crop(crop).resize((width, height), Image.Resampling.NEAREST)
            from identity_pipeline import visual_reference_schedule
            for index in range(pass_count):
                kind = 'harmonize' if index == 0 else 'detail'
                label = '第一轮融合' if index == 0 else '第二轮细化'
                strength_now = denoise if index == 0 else .15
                total = max(1, int(30 * strength_now))
                started = time.perf_counter()
                region = '保留五官，仅融合边缘' if mode == 'reference-anchor' else '脸部蒙版细化'
                stage(f'{label} · {region} {width}×{height}')
                source = current.crop(crop).resize((width, height), Image.Resampling.LANCZOS)
                # Share offloaded modules. Each pass starts a fresh scheduler,
                # and refines the preceding image rather than rerunning the scene.
                redraw = StableDiffusionXLInpaintPipeline(**{**pipe.components,
                    'scheduler': EulerDiscreteScheduler.from_config(pipe.scheduler.config)}, add_watermarker=False)
                def progress(_pipe, step, _timestep, values):
                    stage(f'{label} · 动漫修脸重绘 {step + 1} / {total} 步')
                    advance(step + 1)
                    return values
                with visual_reference_schedule(pipe, item, total) as advance, torch.inference_mode():
                    patch = redraw(prompt=prompt, negative_prompt=negative,
                        image=source, mask_image=mask, width=width, height=height,
                        strength=strength_now, num_inference_steps=30, guidance_scale=item['cfg'],
                        generator=torch.Generator(device='cpu').manual_seed(item['seed']),
                        ip_adapter_image_embeds=[self.session.projected], callback_on_step_end=progress,
                        callback_on_step_end_tensor_inputs=['latents']).images[0]
                if max(ImageStat.Stat(patch.convert('RGB')).stddev) < 2:
                    raise ValueError('动漫局部重绘结果异常，保留原图')
                # Refine the preceding stage. Blending every pass against the
                # original resurrects its face at feathered boundaries even
                # when the model returns an unchanged patch.
                if mode == 'reference-anchor':
                    from identity_face_region import composite_region
                    current = composite_region(current, patch, crop, blend_mask)
                else:
                    current = blend_face(current, patch, box, crop)
                if staged:
                    snapshots.append({'kind': kind, 'imageUrl': save_visual_stage(current, item, kind)})
                    passes.append({'kind': kind, 'denoiseStrength': strength_now, 'steps': total,
                                   'durationMs': round((time.perf_counter()-started)*1000)})
        except Exception:
            restore_offload_state(pipe)
            if staged:
                cleanup_visual_stages(item)
            raise
        finally:
            if pipe.vae.dtype != vae_dtype:
                pipe.vae.to(dtype=vae_dtype)
        details = {'method': 'visual-reference-local-redraw',
            'referenceId': item['referenceId'], 'faceIndex': item['faceIndex'],
            'featureKey': self.session.feature_info['featureKey'],
            'restoreModel': visual_restore_model(item['modelId']),
            'restoreDevice': 'CUDA sequential offload', 'faceBox': box, 'cropBox': list(crop),
            'denoiseStrength': denoise, 'outsideMaskUnchanged': True,
            'detailerVersion': 'masked-face-v1', 'processingSize': [width, height],
            'detailPrompt': prompt, 'detailNegativePrompt': negative}
        if staged:
            details.update(detailerVersion='staged-face-v2', polishMode=mode,
                           passes=passes, snapshots=snapshots, **anchor_info)
            if mode == 'reference-anchor':
                details.update(detailerVersion='protected-face-v3', featureProtection='central-features-v1')
        return current, details
