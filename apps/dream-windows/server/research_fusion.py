"""CPU replay of Android H6R4 paired-chunk epsilon fusion, not an image engine.

Inputs are imported raw predictions at ONE latent/timestep, before the scheduler.
Their declared device provenance is preserved, never attested by this replay.
Arithmetic follows patch_h2 / patch_h6_v7_fusion_core_v2 / patch_h6_v11_token_truth.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from datetime import datetime

MAX_ELEMENTS = 65_536
MAX_CHUNKS = 4
MAX_BODY_BYTES = 12 * 1024 * 1024
MODES = ('first_only', 'equal_mean', 'token_weighted', 'anchor_residual')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def finite(value, low, high):
    try:
        return type(value) in (float, int) and math.isfinite(value) and low <= value <= high
    except OverflowError:
        return False


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def fusion_capability():
    return {'available': True, 'contractVersion': 'mobile-chunk-fusion-replay-v1',
            'execution': 'cpu-import-replay', 'truth': 'derived', 'maxChunks': MAX_CHUNKS,
            'maxElements': MAX_ELEMENTS, 'maxBodyBytes': MAX_BODY_BYTES,
            'modes': list(MODES), 'nativeGenerationAvailable': False,
            'message': '仅支持导入成对原始预测的 CPU 数值重放；当前引擎未提供成对 chunk 导出或调度器回灌。'}


def replay_fusion(document):
    require(isinstance(document, dict), '预测文件必须是 JSON 对象')
    require(document.get('contractVersion') == 'mobile-chunk-predictions-v1', '预测文件版本不兼容')
    require(document.get('family') in ('sd15', 'sdxl') and document.get('predictionType') == 'epsilon',
            '仅支持 SD1.5/SDXL epsilon 预测；不支持 Anima 或 v_prediction')
    shape = document.get('shape')
    require(isinstance(shape, list) and 1 <= len(shape) <= 4
            and all(type(v) is int and 1 <= v <= 128 for v in shape), '预测 shape 无效')
    size = math.prod(shape)
    require(size <= MAX_ELEMENTS, '预测张量超过元素上限')
    cfg, alpha = document.get('cfg'), document.get('alpha')
    require(finite(cfg, 0, 30) and finite(alpha, 0, 1), 'cfg 或 alpha 无效')
    require(type(document.get('canSkipUncond')) is bool, '必须声明 canSkipUncond')
    skip = document['canSkipUncond'] and cfg == 1.
    provenance = document.get('provenance')
    require(isinstance(provenance, dict), '缺少 provenance 来源')
    for name in ('runId', 'modelId', 'engineRevision', 'engine'):
        require(isinstance(provenance.get(name), str) and 0 < len(provenance[name].strip()) <= 256,
                f'缺少来源 {name}')
    require(provenance['engine'] == 'android-qnn', '预测来源不兼容：需要 android-qnn 成对 chunk')
    for name in ('modelSha256', 'latentSha256', 'promptSha256', 'negativePromptSha256'):
        require(isinstance(provenance.get(name), str)
                and re.fullmatch('[0-9a-f]{64}', provenance[name]) is not None, f'缺少来源摘要 {name}')
    for name, maximum in (('step', 49), ('seed', 2**32 - 1)):
        require(type(provenance.get(name)) is int and 0 <= provenance[name] <= maximum, f'来源 {name} 无效')
    require(finite(provenance.get('timestep'), 0, 1e6), '来源 timestep 无效')
    try:
        captured = datetime.fromisoformat(provenance.get('capturedAt', '').replace('Z', '+00:00'))
        require(captured.tzinfo is not None, 'capturedAt 必须含时区')
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError('来源 capturedAt 无效') from exc

    chunks = document.get('chunks')
    require(isinstance(chunks, list) and 1 <= len(chunks) <= MAX_CHUNKS, 'chunk 数量超限或缺失')
    guided, counts = [], []
    for index, chunk in enumerate(chunks):
        require(isinstance(chunk, dict) and type(chunk.get('index')) is int and chunk['index'] == index,
                'chunk 顺序无效或重复')
        for name in ('positiveTokens', 'negativeTokens'):
            require(type(chunk.get(name)) is int and 0 <= chunk[name] <= 75, f'{name} 必须为实测内容 token 数')
        tensors = {}
        for name in ('positive', 'negative'):
            if name == 'negative' and skip and name not in chunk:
                continue
            values = chunk.get(name)
            require(isinstance(values, list) and len(values) == size
                    and all(finite(v, -1e6, 1e6) for v in values), f'{name} 原始预测缺失、形状不符或非有限值')
            tensors[name] = [f32(v) for v in values]
        guided.append(tensors['positive'] if skip else
                      [f32(u + f32(f32(cfg) * f32(p - u)))
                       for p, u in zip(tensors['positive'], tensors['negative'])])
        counts.append(max(1, chunk['positiveTokens'], 0 if skip else chunk['negativeTokens']))

    count = len(chunks)
    baseline = [f32(sum_values / count) for sum_values in _sum_predictions(guided, size)]
    baseline_norm = math.sqrt(math.fsum(v*v for v in baseline))
    variants = []
    for mode in MODES:
        if mode == 'first_only':
            weights, prediction = [1.] + [0.] * (count-1), guided[0][:]
        elif mode == 'equal_mean':
            weights, prediction = [f32(1/count)] * count, baseline
        elif mode == 'token_weighted':
            weights = [f32(v / sum(counts)) for v in counts]
            prediction = _sum_predictions([[f32(w*v) for v in values]
                                           for w, values in zip(weights, guided)], size)
        else:
            if count == 1:
                weights, prediction = [1.], guided[0][:]
            else:
                residual_weights = [f32(v / sum(counts[1:])) for v in counts[1:]]
                residual = _sum_predictions([[f32(w * f32(v-a)) for v, a in zip(values, guided[0])]
                                             for w, values in zip(residual_weights, guided[1:])], size)
                prediction = [f32(a + f32(f32(alpha)*r)) for a, r in zip(guided[0], residual)]
                weights = [f32(1-f32(alpha))] + [f32(f32(alpha)*w) for w in residual_weights]
        norm = math.sqrt(math.fsum(v*v for v in prediction))
        cosine = math.fsum(v*b for v, b in zip(prediction, baseline)) / (norm*baseline_norm) if norm and baseline_norm else None
        variants.append({'mode': mode, 'weights': weights, 'prediction': prediction,
                         'meanAbs': math.fsum(abs(v) for v in prediction)/size, 'l2': norm,
                         'deltaL2FromEqualMean': math.sqrt(math.fsum((v-b)**2 for v, b in zip(prediction, baseline))),
                         'cosineToEqualMean': max(-1., min(1., cosine)) if cosine is not None else None})
    return {'contractVersion': 'mobile-chunk-fusion-replay-v1', 'truth': 'derived',
            'execution': 'cpu-import-replay', 'shape': shape, 'cfg': cfg, 'alpha': alpha,
            'chunkCount': count, 'skippedUnconditional': skip,
            'provenance': {**provenance, 'inputSha256': digest(document), 'inputVerification': 'imported-unverified'},
            'variants': variants}


def _sum_predictions(predictions, size):
    result = [0.] * size
    for prediction in predictions:
        result = [f32(a+b) for a, b in zip(result, prediction)]
    return result
