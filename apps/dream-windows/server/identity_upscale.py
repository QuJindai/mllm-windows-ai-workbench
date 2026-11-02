"""Bounded optional SR in the existing refinement worker, using local weights.

No generator, face swap, network download or source-file writes. Tile halos
follow the context-crop approach of Real-ESRGAN's public inference utility:
https://github.com/xinntao/Real-ESRGAN/blob/master/realesrgan/utils.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path
from time import perf_counter

MAX_INPUT_PIXELS = 768 * 1152
MAX_MODEL_BYTES = 256 * 1024**2


def upscale_status(config):
    value = config.get('upscaleModel')
    try:
        path = Path(value) if isinstance(value, str) and value else None
        valid = path is not None and path.is_file() and 0 < path.stat().st_size <= MAX_MODEL_BYTES
    except OSError:
        valid = False
    if not valid:
        return {'ready': False, 'message': '未配置本机清晰增强模型；生成结果仍可使用'}
    if any(importlib.util.find_spec(name) is None for name in ('torch', 'spandrel', 'PIL')):
        return {'ready': False, 'message': '本机清晰增强组件不完整'}
    return {'ready': True, 'message': '本机增强模型文件已配置；生成后可选2倍清晰增强'}


def tiled_forward(model, source, *, scale=4, tile=128, padding=32, device='cuda', progress=None):
    """Keep complete input/output in CPU RAM; move one context tile to GPU."""
    import torch
    if (source.ndim != 4 or source.shape[0:2] != (1, 3) or scale != 4
            or tile < 16 or tile > 128 or padding < 1 or padding > 32):
        raise ValueError('清晰增强分块参数无效')
    height, width = source.shape[-2:]
    if min(height, width) < 1 or max(height, width) > 1152 or height*width > MAX_INPUT_PIXELS:
        raise ValueError('清晰增强源图尺寸超过限制')
    if not torch.isfinite(source).all():
        raise ValueError('清晰增强输入数值无效')
    output = torch.empty(1, 3, height*scale, width*scale, dtype=torch.float32, device='cpu')
    total = ((height+tile-1)//tile) * ((width+tile-1)//tile)
    calls = 0
    with torch.inference_mode():
        for top in range(0, height, tile):
            for left in range(0, width, tile):
                if progress:
                    progress(calls+1, total)
                bottom, right = min(top+tile, height), min(left+tile, width)
                y0, x0 = max(0, top-padding), max(0, left-padding)
                y1, x1 = min(height, bottom+padding), min(width, right+padding)
                part = source[:, :, y0:y1, x0:x1].to(device=device, dtype=torch.float32)
                candidate = model(part)
                expected = (1, 3, (y1-y0)*scale, (x1-x0)*scale)
                if tuple(candidate.shape) != expected or not torch.isfinite(candidate).all():
                    raise ValueError('清晰增强模型输出尺寸或数值无效')
                crop = candidate[:, :, (top-y0)*scale:(bottom-y0)*scale,
                                 (left-x0)*scale:(right-x0)*scale]
                output[:, :, top*scale:bottom*scale, left*scale:right*scale] = crop.float().cpu()
                calls += 1
                del candidate, crop, part
    return output, calls


def enhance(config, image, stage):
    width, height = image.size
    if min(width, height) < 1 or max(width, height) > 1152 or width*height > MAX_INPUT_PIXELS:
        raise ValueError('清晰增强源图尺寸超过 768×1152 像素预算')
    status = upscale_status(config)
    if not status['ready']:
        raise ValueError(status['message'])
    import numpy as np
    import torch
    from PIL import Image
    from spandrel import ImageModelDescriptor, ModelLoader
    from identity_pipeline import configure_cuda

    started = perf_counter()
    stage('读取本机清晰增强模型')
    path = Path(config['upscaleModel'])
    with path.open('rb') as stream:
        raw = stream.read(MAX_MODEL_BYTES+1)
    if len(raw) > MAX_MODEL_BYTES:
        raise ValueError('清晰增强模型文件超过限制')
    digest = hashlib.sha256(raw).hexdigest()
    state = torch.load(io.BytesIO(raw), map_location='cpu', weights_only=True)
    descriptor = ModelLoader(device='cpu').load_from_state_dict(state.get('params_ema', state.get('params', state)))
    if (not isinstance(descriptor, ImageModelDescriptor) or str(descriptor.architecture.id) != 'ESRGAN'
            or descriptor.scale != 4 or descriptor.input_channels != 3 or descriptor.output_channels != 3):
        raise ValueError('清晰增强需要本机已适配的4倍 ESRGAN RGB 模型')
    del raw, state
    configure_cuda()  # Reuse Dream's available-memory guard and process budget.
    descriptor.eval().to(device='cuda', dtype=torch.float32)
    source = torch.from_numpy(np.asarray(image.convert('RGB'), dtype=np.float32).copy() / 255).permute(2,0,1).unsqueeze(0)
    try:
        pixels, calls = tiled_forward(descriptor, source, progress=lambda i,n:stage(f'2倍清晰增强：分块 {i}/{n}'))
        native = Image.fromarray((pixels.squeeze(0).permute(1,2,0).clamp(0,1).numpy()*255).round().astype(np.uint8))
        result = native.resize((width*2, height*2), Image.Resampling.LANCZOS)
        torch.cuda.synchronize()
        peak = round(torch.cuda.max_memory_allocated()/1024**2, 2)
    finally:
        descriptor.to('cpu')
        torch.cuda.empty_cache()
    return result, {
        'status':'completed', 'method':'esrgan-local-tiled-v1', 'modelName':path.name,
        'modelSha256':digest, 'architecture':'ESRGAN', 'nativeModelScale':4, 'outputScale':2,
        'inputWidth':width, 'inputHeight':height, 'outputWidth':width*2, 'outputHeight':height*2,
        'device':'CUDA FP32', 'tileSize':128, 'tilePadding':32, 'tileCalls':calls,
        'peakAllocatedMiB':peak, 'durationMs':round((perf_counter()-started)*1000),
        'resampleAfterModel':'Lanczos 4x to 2x', 'usesDiffusion':False, 'usesFaceSwap':False,
        'qualityClaim':'Learned detail enhancement; missing real details and identity fidelity are not verified',
    }
