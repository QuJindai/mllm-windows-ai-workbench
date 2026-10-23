"""Anime-reference local redraw. Never treats an anime face as biometric enrollment."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path


def anime_status(config):
    ready = Path(config.get('animeFaceDetector', '')).is_file()
    return {'ready': ready, 'message': '动漫脸检测与 Illustrious 局部重绘；不使用真人换脸/GFPGAN' if ready else '动漫脸检测模型未配置'}


def detection_boxes(output, original_size, input_size, threshold=.278):
    import numpy as np
    rows = np.asarray(output, dtype=np.float32)
    if rows.ndim != 3 or rows.shape[0] != 1:
        raise ValueError('动漫检测输出形状无效')
    rows = rows[0]
    if rows.shape[0] == 5:
        rows = rows.T
    if rows.shape[1] != 5 or not np.isfinite(rows).all():
        raise ValueError('动漫检测输出无效')
    width, height = original_size
    iw, ih = input_size
    scale = min(iw / width, ih / height)
    ox, oy = (iw-round(width*scale))//2, (ih-round(height*scale))//2
    candidates = []
    for cx, cy, bw, bh, confidence in rows:
        if confidence < threshold or bw <= 0 or bh <= 0:
            continue
        x1, y1 = max(0., (cx-bw/2-ox)/scale), max(0., (cy-bh/2-oy)/scale)
        x2, y2 = min(float(width), (cx+bw/2-ox)/scale), min(float(height), (cy+bh/2-oy)/scale)
        if x2-x1 >= 16 and y2-y1 >= 16:
            candidates.append((float(confidence), [float(x1),float(y1),float(x2),float(y2)]))
    selected = []
    for _, box in sorted(candidates, key=lambda x:x[0], reverse=True):
        def overlap(other):
            intersection = max(0,min(box[2],other[2])-max(box[0],other[0]))*max(0,min(box[3],other[3])-max(box[1],other[1]))
            area = (box[2]-box[0])*(box[3]-box[1])+(other[2]-other[0])*(other[3]-other[1])-intersection
            return intersection/max(area,1)
        if not any(overlap(old) > .5 for old in selected):
            selected.append(box)
    return sorted(selected, key=lambda b:(b[0],b[1]))


class AnimeDetector:
    def __init__(self, config):
        import onnxruntime as ort
        if not anime_status(config)['ready']:
            raise ValueError('动漫脸检测模型配置不完整')
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(config['animeFaceDetector'], sess_options=options, providers=['CPUExecutionProvider'])

    def detect(self, image):
        import numpy as np
        from PIL import Image
        image = image.convert('RGB')
        width,height = image.size
        scale = min(640/width,640/height)
        resized = image.resize((round(width*scale),round(height*scale)),Image.Resampling.BILINEAR)
        canvas = Image.new('RGB',(640,640),(114,114,114))
        canvas.paste(resized,((640-resized.width)//2,(640-resized.height)//2))
        tensor = np.asarray(canvas,dtype=np.float32).transpose(2,0,1)[None]/255.
        output = self.session.run(None,{self.session.get_inputs()[0].name:tensor})[0]
        return detection_boxes(output,image.size,canvas.size)


def one_face(boxes):
    if not boxes:
        raise ValueError('未检测到清晰动漫脸，请使用单人近景构图')
    if len(boxes) != 1:
        raise ValueError('检测到多个动漫脸，未自动选择替换对象')
    return boxes[0]


def crop_box(size, box):
    width,height = size
    x1,y1,x2,y2 = box
    margin = .30*max(x2-x1,y2-y1)
    return (max(0,math.floor(x1-margin)), max(0,math.floor(y1-margin)),
            min(width,math.ceil(x2+margin)), min(height,math.ceil(y2+margin)))


def face_mask(size, box):
    from PIL import Image, ImageDraw, ImageFilter
    mask = Image.new('L',size,0)
    ImageDraw.Draw(mask).ellipse(tuple(box), fill=255)
    return mask.filter(ImageFilter.GaussianBlur(max(1,min(box[2]-box[0],box[3]-box[1])*.035)))


def blend_face(image, patch, box, crop):
    from PIL import Image
    canvas = image.copy().convert('RGB')
    canvas.paste(patch.resize((crop[2]-crop[0],crop[3]-crop[1]),Image.Resampling.LANCZOS),crop[:2])
    return Image.composite(canvas,image.convert('RGB'),face_mask(image.size,box))


def prepare_anime(config, request):
    from PIL import Image
    from safetensors.torch import save_file
    from identity_features import reference_features, validate_features, FEATURE_VERSION
    from identity_pipeline import extract_reference_features, extract_clip_features
    # The ID vector is from the real profile, never extracted from the cartoon.
    features, info = reference_features(config,request,extract_reference_features)
    with Image.open(request['animeImagePath']) as source:
        image = source.convert('RGB')
    box = one_face(AnimeDetector(config).detect(image))
    clip, negative = extract_clip_features(config,image.crop(crop_box(image.size,box)))
    hybrid = {'id':features['id'],'clip':clip,'negative_clip':negative}
    validate_features(hybrid)
    path = Path(request['animeFeaturesPath'])
    path.parent.mkdir(parents=True,exist_ok=True)
    temp = path.with_suffix('.tmp')
    save_file(hybrid,str(temp), metadata={'featureVersion':str(FEATURE_VERSION), 'clipActivation':'gelu'})
    os.replace(temp,path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'ok':True,'featureKey':digest,'faceBox':box,'parentFeatureKey':info['featureKey']}


def load_anime_features(item, config=None):
    from safetensors import safe_open
    from safetensors.torch import load_file
    from identity_features import validate_features
    profile = item['animeProfile']
    if not re.fullmatch(r'anime-[a-f0-9]{24}', profile['id']):
        raise ValueError('动漫档案编号无效')
    root = Path(item['dreamRoot']).resolve()/ 'data'/'identity'/'anime-profiles'
    path = root/(profile['id']+'.safetensors')
    if path.resolve() != path or str(path.resolve()) != str(Path(item['animeFeaturesPath']).resolve()):
        raise ValueError('动漫特征路径无效')
    if path.stat().st_size > 8*1024**2 or hashlib.sha256(path.read_bytes()).hexdigest() != profile['featureKey']:
        raise ValueError('动漫档案特征校验失败，请重新建档')
    features = load_file(str(path),device='cpu')
    validate_features(features)
    if config is not None:
        from identity_features import FEATURE_VERSION, FingerprintCache, _cached_features
        with safe_open(str(path), framework='pt', device='cpu') as stored:
            version = (stored.metadata() or {}).get('featureVersion')
        if version != str(FEATURE_VERSION):
            # Immutable archive remains the binding; corrected derived features
            # live in the versioned cache, never overwriting the enrolled data.
            from PIL import Image
            from identity_pipeline import extract_clip_features
            fingerprints = FingerprintCache(Path(item['dreamRoot'])/'data/identity/fingerprints.json')
            hashes = {'clipVision':fingerprints.digest(config['clipVision'])}
            descriptor = {'kind':'hybrid-anime-gelu', 'version':FEATURE_VERSION,
                          'source':profile['featureKey'], 'encoder':hashes['clipVision'],
                          'image':fingerprints.digest(item['animeImagePath'])}
            detector = Path(config.get('animeFaceDetector', ''))
            if detector.is_file():
                descriptor['detector'] = fingerprints.digest(detector)
            key = hashlib.sha256(json.dumps(descriptor,sort_keys=True).encode()).hexdigest()
            original_id = features['id']
            def refresh():
                with Image.open(item['animeImagePath']) as source:
                    image = source.convert('RGB')
                box = one_face(AnimeDetector(config).detect(image))
                clip, negative = extract_clip_features(config,image.crop(crop_box(image.size,box)))
                return {'id':original_id,'clip':clip,'negative_clip':negative}
            features, _ = _cached_features(Path(item['dreamRoot']),key,hashes,refresh,version=FEATURE_VERSION)
    return features


class AnimePolisher:
    def __init__(self, session):
        self.session = session
        self.detector = AnimeDetector(session.config)

    def apply(self, image, item, strength, stage):
        import torch
        from diffusers import StableDiffusionXLImg2ImgPipeline, EulerDiscreteScheduler
        from PIL import Image
        profile = item['animeProfile']
        if profile['id'] != item.get('animeProfileId'):
            raise ValueError('动漫修脸档案与任务不一致')
        stage('定位动漫脸')
        box = one_face(self.detector.detect(image))
        crop = crop_box(image.size,box)
        source = image.crop(crop)
        width = max(256,min(512,round(source.width/source.height*512/8)*8))
        height = max(256,min(512,round(source.height/source.width*512/8)*8))
        source = source.resize((width,height),Image.Resampling.LANCZOS)
        stage('按动漫档案局部重绘')
        pipe = self.session.pipe
        # Same offloaded modules, a separate scheduler; no second SDXL model in VRAM.
        redraw = StableDiffusionXLImg2ImgPipeline(**{**pipe.components,
            'scheduler':EulerDiscreteScheduler.from_config(pipe.scheduler.config)}, add_watermarker=False)
        vae_dtype = pipe.vae.dtype
        try:
            with torch.inference_mode():
                patch = redraw(prompt=item['prompt'],negative_prompt=item.get('negativePrompt',''),
                    image=source,strength=item.get('animeDenoiseStrength',.35),num_inference_steps=30,
                    guidance_scale=item['cfg'],generator=torch.Generator(device='cpu').manual_seed(item['seed']),
                    ip_adapter_image_embeds=[self.session.anime_projected]).images[0]
        except Exception:
            restore_offload_state(pipe)
            raise
        finally:
            # Diffusers normally restores its temporary FP32 VAE conversion only
            # on success. A failed optional pass must not poison the next item.
            if pipe.vae.dtype != vae_dtype:
                pipe.vae.to(dtype=vae_dtype)
        from PIL import ImageStat
        if max(ImageStat.Stat(patch.convert('RGB')).stddev) < 2:
            raise ValueError('动漫局部重绘结果异常，保留原图')
        result = blend_face(image,patch,box,crop)
        return result, {'method':'anime-reference-local-redraw','profileId':profile['id'],'profileName':profile['name'],
            'restoreModel':'Illustrious XL + FaceID/CLIP anime reference','restoreDevice':'CUDA sequential offload',
            'faceBox':box,'cropBox':list(crop),'denoiseStrength':item.get('animeDenoiseStrength',.35),
            'outsideMaskUnchanged':True,'featureKey':profile['featureKey']}


def restore_offload_state(pipe):
    """Finish only Accelerate offload hooks whose pre-forward actually ran.

    Accelerate doesn't call post_forward on exceptions. CPU weights_map remains
    authoritative; evict the resident copies without removing/rebuilding hooks.
    """
    import torch
    from accelerate.hooks import AlignDevicesHook, SequentialHook
    def finish(module, hook):
        if isinstance(hook, SequentialHook):
            for child in hook.hooks: finish(module, child)
        elif isinstance(hook, AlignDevicesHook) and hook.offload and hasattr(hook,'tied_pointers_to_remove'):
            hook.post_forward(module,None)
    seen=set()
    for component in pipe.components.values():
        if not isinstance(component,torch.nn.Module): continue
        for module in component.modules():
            if id(module) in seen: continue
            seen.add(id(module))
            finish(module,getattr(module,'_hf_hook',None))
