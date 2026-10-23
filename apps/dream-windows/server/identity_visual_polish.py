"""Optional Plus Face local redraw, using the selected visual reference only."""
from pathlib import Path

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


def visual_polish_status(config):
    ready = Path(config.get('animeFaceDetector', '')).is_file()
    return {'ready': ready, 'message': (
        '脸部目标尺寸细化 + 采样蒙版 + 独立提示词；复用当前视觉参考，不使用真人换脸或 GFPGAN'
        if ready else '动漫脸检测模型未配置，关闭修脸仍可生成')}


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

        stage('定位动漫脸')
        box = one_face(self.detector.detect(image))
        crop = crop_box(image.size, box)
        source = image.crop(crop)
        width, height = detail_size(crop, box)
        source = source.resize((width, height), Image.Resampling.LANCZOS)
        # A binary mask constrains denoising, while the existing soft mask is
        # retained separately for pixel-exact preservation outside the blend.
        mask = face_mask(image.size, box).point(lambda value: 255 if value >= 128 else 0)
        mask = mask.crop(crop).resize((width, height), Image.Resampling.NEAREST)
        prompt, negative = detail_prompts(item)
        denoise = item.get('animeDenoiseStrength', .35)
        steps = 30
        total = max(1, int(steps * denoise))
        stage(f'脸部蒙版细化 {width}×{height}')
        def progress(_pipe, index, _timestep, values):
            stage(f'动漫修脸重绘 {index + 1} / {total} 步')
            advance(index + 1)
            return values

        pipe = self.session.pipe
        # Share the already offloaded modules and native Plus projection; only
        # the scheduler is independent. No second checkpoint lives in VRAM.
        vae_dtype = pipe.vae.dtype
        try:
            redraw = StableDiffusionXLInpaintPipeline(**{**pipe.components,
                'scheduler': EulerDiscreteScheduler.from_config(pipe.scheduler.config)}, add_watermarker=False)
            from identity_pipeline import visual_reference_schedule
            with visual_reference_schedule(pipe, item, total) as advance, torch.inference_mode():
                patch = redraw(prompt=prompt, negative_prompt=negative,
                    image=source, mask_image=mask, width=width, height=height,
                    strength=denoise, num_inference_steps=steps, guidance_scale=item['cfg'],
                    generator=torch.Generator(device='cpu').manual_seed(item['seed']),
                    ip_adapter_image_embeds=[self.session.projected], callback_on_step_end=progress,
                    callback_on_step_end_tensor_inputs=['latents']).images[0]
        except Exception:
            restore_offload_state(pipe)
            raise
        finally:
            if pipe.vae.dtype != vae_dtype:
                pipe.vae.to(dtype=vae_dtype)
        if max(ImageStat.Stat(patch.convert('RGB')).stddev) < 2:
            raise ValueError('动漫局部重绘结果异常，保留原图')
        result = blend_face(image, patch, box, crop)
        return result, {'method': 'visual-reference-local-redraw',
            'referenceId': item['referenceId'], 'faceIndex': item['faceIndex'],
            'featureKey': self.session.feature_info['featureKey'],
            'restoreModel': visual_restore_model(item['modelId']),
            'restoreDevice': 'CUDA sequential offload', 'faceBox': box, 'cropBox': list(crop),
            'denoiseStrength': denoise, 'outsideMaskUnchanged': True,
            'detailerVersion': 'masked-face-v1', 'processingSize': [width, height],
            'detailPrompt': prompt, 'detailNegativePrompt': negative}
