"""Opt-in SD1.5/SDXL observers; never replace production sampling outputs.

Q/K are read from the actual projection outputs, including active LoRA weights.
Only conditional text attention is exported, averaged over heads. Self attention
uses nine spatial anchors. H6 disables IP-Adapter scale for a separate forward;
its result is never passed to the scheduler. No personal likeness tuning here.
"""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
import time
import io
import stat
import uuid


SOURCE = 'diffusers-unet'
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024


def estimated_capture_bytes(width, height, steps, token_count, extended):
    # SD1.5: two down + three up modules at each of the first three scales,
    # one mid module at 1/8. 26 bytes bounds serialized FP32 probabilities.
    grids = [math.ceil(width/8/2**i)*math.ceil(height/8/2**i) for i in range(4)]
    area = sum(5*value for value in grids[:3]) + grids[3] if extended else 2*grids[0]+grids[3]
    samples, layers = (steps, 16) if extended else (min(steps, 5), 3)
    maps = samples*layers*(token_count+9)
    return samples*area*(token_count+9)*26 + maps*1400 + steps*grids[0]*8 + 8*1024*1024


def write_artifact(root, path, data):
    """Exclusive random temporary file, checked existing Windows reparse paths.

    Protects against pre-existing redirects, not a hostile concurrent OS user.
    """
    root, path = Path(root).absolute(), Path(path).absolute()
    try:
        path.relative_to(root)
    except ValueError:
        raise ValueError('研究产物路径无效') from None
    for parent in (path, *path.parents):
        if parent.exists() or parent.is_symlink():
            info = parent.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('研究产物不允许重定向路径')
        if parent == root:
            break
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('研究产物路径无效')
    temporary = path.parent/f'.research-{uuid.uuid4().hex}.tmp'
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_BINARY', 0), 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        # Only our exclusively-created random file; never a user artifact.
        if temporary.exists():
            temporary.unlink()


def attention_probabilities(query, key, heads, query_indices=None):
    import torch
    q, k = query[-1].detach().float(), key[-1].detach().float()
    if q.shape[-1] % heads or k.shape[-1] != q.shape[-1]:
        raise ValueError('Attention dimensions do not match')
    dim = q.shape[-1] // heads
    q = q.reshape(-1, heads, dim).transpose(0, 1)
    k = k.reshape(-1, heads, dim).transpose(0, 1)
    if query_indices is not None:
        q = q[:, query_indices]
    # Bound transient logits, especially at 768 px. Never allocate full N×N.
    parts = []
    for start in range(0, q.shape[1], 128):
        scores = torch.matmul(q[:, start:start + 128], k.transpose(-1, -2)) / math.sqrt(dim)
        parts.append(scores.softmax(-1).mean(0).cpu())
    return torch.cat(parts, dim=0)


def influence_sample(actual, ablated, cfg, step):
    import torch
    a, b = actual.detach().float(), ablated.detach().float()
    if a.shape != b.shape or a.ndim != 4 or a.shape[0] != 2:
        raise ValueError('H6 requires one conditional/unconditional image pair')
    full = a[0] + cfg * (a[1] - a[0])
    without = b[0] + cfg * (b[1] - b[0])
    cosine = lambda x, y: float(torch.nn.functional.cosine_similarity(x.flatten(), y.flatten(), dim=0).clamp(-1, 1).cpu())
    return {'step': step, 'width': a.shape[-1], 'height': a.shape[-2],
            'cfgDeltaL2': float((full-a[1]).norm().cpu()), 'cfgCosine': cosine(full, a[1]),
            'chunks': [{'chunk': 0, 'tokenStart': 0, 'tokenEnd': 77,
                        'meanAbs': float(without.abs().mean().cpu()), 'l2': float(without.norm().cpu()),
                        'cosineFull': cosine(without, full), 'deltaL2': float((without-full).norm().cpu()),
                        'spatialDelta': (without-full).abs().mean(0).flatten().cpu().tolist()}]}


def latent_sample(latents, previous, step, directory, writer=None):
    import numpy as np
    from PIL import Image
    z = latents.detach().float().cpu().numpy().astype(np.float64)
    if z.ndim != 4 or z.shape[1] != 4 or not np.isfinite(z).all():
        raise ValueError('Invalid SD1.5 latent')
    batch, channels, height, width = z.shape
    matrix = z.transpose(1, 0, 2, 3).reshape(channels, -1)
    centered = matrix - matrix.mean(1, keepdims=True)
    norms = np.linalg.norm(centered, axis=1)
    correlation = [[None if norms[i] == 0 or norms[j] == 0 else float(np.clip(np.dot(centered[i], centered[j]) / (norms[i]*norms[j]), -1, 1)) for j in range(channels)] for i in range(channels)]
    result = {'step': step, 'shape': [width, height, channels, batch], 'mean': float(z.mean()),
              'std': float(z.std()), 'l2': float(np.linalg.norm(z)), 'truth': 'observed',
              'kind': 'latent-state', 'channels': [], 'channel_correlation': correlation,
              'correlation_method': 'pearson'}
    if previous is not None:
        old = previous.detach().float().cpu().numpy().astype(np.float64)
        denominator = np.linalg.norm(z)*np.linalg.norm(old)
        result.update(delta_l2=float(np.linalg.norm(z-old)), delta_mean_abs=float(np.abs(z-old).mean()),
                      cosine=float(np.clip(np.sum(z*old)/denominator, -1, 1)) if denominator else 0.)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if previous is not None:
        if old.shape != z.shape or not np.isfinite(old).all():
            raise ValueError('Invalid previous latent')
        spatial = np.abs(z-old).mean(axis=(0,1))
        maximum = float(spatial.max())
        pixels = spatial/maximum if maximum else np.zeros_like(spatial)
        filename = f'latent-step-{step:03d}-delta.png'
        encoded = io.BytesIO()
        Image.fromarray(np.clip(pixels*255, 0, 255).astype(np.uint8)).save(encoded, format='PNG')
        if writer:
            writer(filename, encoded.getvalue())
        else:
            write_artifact(directory, directory/filename, encoded.getvalue())
        result['delta_file_name'] = filename
    for channel in range(channels):
        values = matrix[channel]
        low, high = float(values.min()), float(values.max())
        pixels = (z[0, channel]-low)/(high-low) if high > low else np.full((height, width), .5)
        filename = f'latent-step-{step:03d}-ch{channel}.png'
        encoded = io.BytesIO()
        Image.fromarray(np.clip(pixels*255, 0, 255).astype(np.uint8)).save(encoded, format='PNG')
        if writer:
            writer(filename, encoded.getvalue())
        else:
            write_artifact(directory, directory/filename, encoded.getvalue())
        counts = np.histogram(values, bins=32, range=(low, high) if high > low else (low-1, high+1))[0].tolist()
        result['channels'].append({'channel': channel, 'file_name': filename, 'min': low, 'max': high,
                                   'mean': float(values.mean()), 'std': float(values.std()), 'l2': float(np.linalg.norm(values)),
                                   'histogram': counts, 'truth': 'observed', 'kind': 'latent-channel'})
    return result


@contextmanager
def without_identity(unet):
    processors = [(module.processor, module.processor.scale) for module in unet.modules()
                  if hasattr(module, 'processor') and hasattr(module.processor, 'to_k_ip')]
    try:
        for processor, scale in processors:
            processor.scale = [0. for _ in scale]
        yield
    finally:
        for processor, scale in processors:
            processor.scale = scale


class IdentityResearch:
    def __init__(self, pipe, item, params):
        from identity_models import is_visual_model_id
        self.pipe, self.item, self.params = pipe, item, params
        self.visual = is_visual_model_id(params.modelId)
        self.method = 'visual-reference-ablation-guided' if self.visual else 'identity-ablation-guided'
        self.provenance = {'modelId': params.modelId, 'referenceKind': 'visual' if self.visual else 'faceid',
                           'intervention': 'ip-adapter-scale-zero', 'attentionSemantics': 'conditional-text',
                           'referenceImageTokenAttribution': False,
                           'referenceStart': params.referenceStart, 'referenceEnd': params.referenceEnd}
        self.publication_error = None
        self.enabled = params.traceLevel != 'off'
        self.capture_influence = params.traceLevel in ('h6', 'h7')
        self.extended = params.researchCoverage == 'extended'
        self.step = 0
        self.suspended = False
        self.handles, self.cross_maps, self.self_maps, self.influence, self.latents = [], [], [], [], []
        self.layers, self.tokens, self.pending_q = [], [], {}
        self.previous = None
        self.bytes_written = 0
        self.unet_ms, self.unet_calls, self.intervention_ms = 0., 0, 0.
        self.directory = Path(item['dreamRoot'])/'traces'/item['jobId']
        self.selected_steps = set(range(params.steps)) if self.extended else {round(i*(params.steps-1)/max(1,min(5,params.steps)-1)) for i in range(min(5,params.steps))}

    def _write(self, filename, value):
        data = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        self._write_bytes(filename, data)

    def _write_bytes(self, filename, data, root_trace=False):
        if self.publication_error is not None:
            return
        parent = self.directory.parent if root_trace else self.directory
        path = parent/filename
        if path.parent != parent or Path(filename).name != filename:
            raise ValueError('研究产物路径无效')
        try:
            if self.bytes_written + len(data) > MAX_ARTIFACT_BYTES:
                raise ValueError('研究产物超过512MiB上限，请减少采样步数或采集范围')
            write_artifact(Path(self.item['dreamRoot']), path, data)
        except (OSError, ValueError) as exc:
            # Optional sidecars must not discard an otherwise generated image.
            # Stop collecting/publishing; finish reports failure after PNG save.
            self.publication_error = exc
            return
        self.bytes_written += len(data)

    def __enter__(self):
        if not self.enabled:
            return self
        root = Path(self.item['dreamRoot']).resolve()
        if not re.fullmatch(r'identity-[a-f0-9]{24}', self.item['jobId']) or self.directory.resolve() != root/'traces'/self.item['jobId']:
            raise ValueError('研究目录无效')
        if self.visual and self.capture_influence and not any(
                hasattr(module, 'processor') and hasattr(module.processor, 'to_k_ip')
                for module in self.pipe.unet.modules()):
            raise ValueError('视觉研究需要实际加载的 IP adapter')
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.pipe.tokenizer is not None:
            ids = self.pipe.tokenizer(self.params.prompt, padding='max_length', max_length=77, truncation=True).input_ids
            end = ids.index(self.pipe.tokenizer.eos_token_id) if self.pipe.tokenizer.eos_token_id in ids else len(ids)
            positions = list(range(1, max(2, end)))[:77 if self.extended else 32]
            self.tokens = [{'slot': pos, 'tokenId': ids[pos], 'text': self.pipe.tokenizer.decode([ids[pos]]).strip() or str(ids[pos]), 'chunk': 0, 'weight': 1.} for pos in positions]
        try:
            self.handles.append(self.pipe.unet.register_forward_pre_hook(self._before, with_kwargs=True))
            self.handles.append(self.pipe.unet.register_forward_hook(self._after, with_kwargs=True))
            if self.params.traceLevel == 'h7':
                modules = [(name, module) for name, module in self.pipe.unet.named_modules()
                           if name.startswith(('down_blocks.', 'mid_block.', 'up_blocks.'))
                           and name.endswith(('.attn1', '.attn2')) and hasattr(module, 'to_q') and hasattr(module, 'to_k')]
                for kind in ('attn1', 'attn2'):
                    candidates = [(name, module) for name, module in modules if name.endswith(kind)]
                    if not self.extended:
                        selected = []
                        for stage in ('down_blocks.', 'mid_block.', 'up_blocks.'):
                            rows = [row for row in candidates if row[0].startswith(stage)]
                            if rows:
                                selected.append(rows[0] if stage != 'up_blocks.' else rows[-1])
                        candidates = selected
                    for name, module in candidates:
                        layer_id = name.rsplit('.', 1)[0]
                        stage = 'down' if name.startswith('down') else 'up' if name.startswith('up') else 'mid'
                        layer = {'id': layer_id, 'stage': stage, 'label': layer_id}
                        if layer not in self.layers:
                            self.layers.append(layer)
                        if getattr(module, 'norm_q', None) is not None or getattr(module, 'norm_k', None) is not None:
                            raise ValueError('研究观察器尚不支持 Q/K 归一化的非SD1.5模型')
                        self.handles.append(module.to_q.register_forward_hook(lambda _m, _args, output, key=name: self._query(key, output)))
                        self.handles.append(module.to_k.register_forward_hook(lambda _m, _args, output, key=name, heads=module.heads: self._key(key, output, heads)))
            return self
        except BaseException:
            self._remove_hooks()
            raise

    def _before(self, _module, _args, _kwargs):
        if not self.suspended:
            self.forward_started = time.perf_counter()

    def _after(self, module, args, kwargs, output):
        if self.suspended:
            return
        self.unet_ms += (time.perf_counter()-self.forward_started)*1000
        self.unet_calls += 1
        if self.capture_influence and self.publication_error is None and self.step in self.selected_steps:
            point = time.perf_counter()
            self.suspended = True
            try:
                with without_identity(module):
                    alternative = module(*args, **kwargs)
                actual = output[0] if isinstance(output, tuple) else output.sample
                ablated = alternative[0] if isinstance(alternative, tuple) else alternative.sample
                self.influence.append(influence_sample(actual, ablated, self.params.cfg, self.step))
            finally:
                self.suspended = False
                self.intervention_ms += (time.perf_counter()-point)*1000
        self.step += 1

    def _query(self, name, output):
        if not self.suspended and self.publication_error is None and self.step in self.selected_steps:
            self.pending_q[name] = output.detach()

    def _key(self, name, output, heads):
        if self.suspended or self.publication_error is not None or self.step not in self.selected_steps or name not in self.pending_q:
            return
        query = self.pending_q.pop(name)
        count = query.shape[1]
        ratio = self.params.width/self.params.height
        height = max(1, round(math.sqrt(count/ratio)))
        while height > 1 and count % height:
            height -= 1
        width = count//height
        layer = name.rsplit('.', 1)[0]
        if name.endswith('attn2'):
            probabilities = attention_probabilities(query, output, heads)
            for token in self.tokens:
                if token['slot'] < probabilities.shape[1]:
                    self._map('cross', layer, width, height, probabilities[:, token['slot']], tokenSlot=token['slot'])
        else:
            anchors = sorted({y*width+x for y in (0,(height-1)//2,height-1) for x in (0,(width-1)//2,width-1)})
            probabilities = attention_probabilities(query, output, heads, anchors)
            for index, anchor in enumerate(anchors):
                self._map('self', layer, width, height, probabilities[index], queryIndex=anchor, queryX=anchor%width, queryY=anchor//width)

    def _map(self, kind, layer, width, height, tensor, **selection):
        import torch
        values = tensor.flatten().float()
        if not torch.isfinite(values).all():
            raise ValueError('Attention observation contains nonfinite values')
        normalized = values / values.sum().clamp_min(1e-20)
        entropy = float(-(normalized*normalized.clamp_min(1e-20).log()).sum()/math.log(max(2, values.numel())))
        selector = selection.get('tokenSlot', selection.get('queryIndex'))
        identifier = f'{self.step}-{layer}-{selector}'
        prefix = 'attention' if kind == 'cross' else 'self-attention'
        descriptor = {'id': identifier, 'step': self.step, 'layerId': layer, 'width': width, 'height': height,
                      **selection, 'entropy': min(1., max(0., entropy)), 'peak': float(values.max()),
                      'coverage': float((values > values.mean()).float().mean()), 'fileName': f'{prefix}-{identifier}.json'}
        marker = {'contractVersion': 'h7-attention-v1' if kind == 'cross' else 'h7-self-attention-v1',
                  'kind': 'cross-attention' if kind == 'cross' else 'self-attention', 'truth': 'observed', 'source': SOURCE,
                  'provenance': self.provenance}
        self._write(descriptor['fileName'], {**marker, **{k:v for k,v in descriptor.items() if k != 'fileName'}, 'values': values.tolist()})
        (self.cross_maps if kind == 'cross' else self.self_maps).append(descriptor)

    def on_step(self, latents, step):
        if self.enabled and self.publication_error is None:
            self.latents.append(latent_sample(latents, self.previous, step, self.directory, self._write_bytes))
            self.previous = latents.detach().clone()

    def _remove_hooks(self):
        for handle in self.handles:
            handle.remove()
        self.handles.clear()
        self.pending_q.clear()
        self.previous = None

    def __exit__(self, exc_type, _exc, _tb):
        self._remove_hooks()
        if not self.enabled or exc_type is not None or self.publication_error is not None:
            return
        coverage = {'mode': self.params.researchCoverage, 'headAggregation': 'mean', 'conditionalBranch': True,
                    'probabilityComputation': 'fp32-softmax-from-observed-qk',
                    'steps': sorted(self.selected_steps), 'selfAnchorsPerLayer': 9, 'textTokenLimit': 77 if self.extended else 32}
        for kind, maps in (('cross', self.cross_maps), ('self', self.self_maps)):
            if not maps:
                continue
            self._write('attention-index.json' if kind == 'cross' else 'self-attention-index.json',
                        {'contractVersion': 'h7-attention-v1' if kind == 'cross' else 'h7-self-attention-v1',
                         'kind': 'cross-attention' if kind == 'cross' else 'self-attention', 'truth': 'observed', 'source': SOURCE,
                         'provenance': self.provenance,
                         'layers': [layer for layer in self.layers if any(item['layerId'] == layer['id'] for item in maps)],
                         **({'tokens': self.tokens} if kind == 'cross' else {}), 'maps': maps, 'coverage': coverage})
        if self.influence:
            self._write('conditioning-influence.json', {'contractVersion': 'h6-conditioning-v1', 'kind': 'conditioning-influence',
                        'truth': 'observed', 'source': SOURCE, 'method': self.method, 'provenance': self.provenance, 'chunkSize': 77,
                        'totalChunks': 1, 'capturedChunks': 1, 'steps': self.influence, 'coverage': coverage})

    def finish(self, metadata):
        if not self.enabled:
            return {'h6': False, 'h7': False, 'message': '未开启研究采集'}
        if self.publication_error is not None:
            raise RuntimeError('研究产物发布失败') from self.publication_error
        from identity_models import MODEL_SPECS
        architecture = MODEL_SPECS[self.params.modelId][1]
        observer = '含注意力观察' if self.params.traceLevel == 'h7' else '基础运行观察'
        trace = {'runId': self.item['jobId'], 'totalTimeMs': metadata['generation_time_ms'], 'truth': 'observed',
                 'provenance': self.provenance,
                 'nodes': [{'id': 'unet', 'name': f'{architecture} UNet（{observer}）', 'backend': SOURCE,
                            'observedCalls': self.unet_calls, 'observedCallsTruth': 'observed', 'durationMs': self.unet_ms,
                            'status': 'executed', 'truth': 'observed'}],
                 'events': [{'phase': 'research', 'label': '视觉参考消融前向' if self.visual else '身份条件干预前向', 'durationMs': self.intervention_ms, 'truth': 'observed'}] if self.influence else [],
                 'latentTelemetry': self.latents,
                 'evidence': {'truth': 'observed', 'modelId': metadata['model_id'], 'referenceKind': self.provenance['referenceKind'], 'backend': SOURCE, 'backendTruth': 'observed',
                              'steps': self.params.steps, 'cfg': self.params.cfg, 'outputPath': self.item['outputPath'],
                              'samplingMethod': 'Euler', 'scheduler': 'Discrete', 'peakVramMiB': metadata['peakReservedMiB']}}
        # Publish root after sidecars are flushed; readers require this file.
        self._write_bytes(f"{self.item['jobId']}.json", json.dumps(trace, ensure_ascii=False, allow_nan=False).encode('utf-8'), root_trace=True)
        if self.publication_error is not None:
            raise RuntimeError('研究产物发布失败') from self.publication_error
        return {'h6': bool(self.influence), 'h7': bool(self.cross_maps and self.self_maps), 'traceLevel': self.params.traceLevel,
                'coverage': self.params.researchCoverage, 'source': SOURCE, 'runId': self.item['jobId'],
                'method': self.method, 'provenance': self.provenance,
                'crossMaps': len(self.cross_maps), 'selfMaps': len(self.self_maps), 'latentSteps': len(self.latents),
                'message': '原始潜变量与基础运行记录；未采集条件干预或注意力' if self.params.traceLevel == 'basic' else (
                    '视觉参考消融、自注意力与条件文本交叉注意力；多头均值、固定空间锚点，不是参考图 token 归因'
                    if self.visual else '原始潜变量、身份条件干预与所选范围注意力；多头均值、固定空间锚点')}
