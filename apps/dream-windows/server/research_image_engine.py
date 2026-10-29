"""Controlled Diffusers SD1.5 generation with paired-chunk CFG at every step.

This is a dedicated text-to-image experiment, not FaceID or native/device parity.
The parent worker owns CUDA lifetime and cancellation; no process/pool is created.
"""
from __future__ import annotations

from research_fusion import MODES

ASSET_FILES = ('model_index.json', 'scheduler/scheduler_config.json', 'text_encoder/config.json',
               'unet/config.json', 'vae/config.json', 'tokenizer/tokenizer_config.json',
               'tokenizer/special_tokens_map.json', 'tokenizer/vocab.json', 'tokenizer/merges.txt')


def file_sha256(path):
    import hashlib
    value = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(4*1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def resolve_assets(config):
    """Freeze existing configured assets without hashing a multi-GB model on HTTP."""
    import json
    from pathlib import Path
    binding = {}
    for key in ('checkpoint', 'pipelineConfig'):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError('本地RV实验配置缺失：'+key)
    checkpoint = Path(config['checkpoint']).resolve(strict=True)
    if not checkpoint.is_file() or checkpoint.suffix != '.safetensors':
        raise ValueError('RV实验需要已配置的safetensors模型文件')
    info = checkpoint.stat()
    binding['checkpoint'] = {'path': str(checkpoint), 'size': info.st_size, 'mtimeNs': info.st_mtime_ns}
    pipeline = Path(config['pipelineConfig']).resolve(strict=True)
    binding['pipelineConfig'] = str(pipeline)
    binding['files'] = {}
    for name in ASSET_FILES:
        path = pipeline/name
        if not path.is_file() or path.stat().st_size > 4*1024*1024:
            raise ValueError('本地SD1.5配置缺失或超限：'+name)
        binding['files'][name] = file_sha256(path)
    unet = json.loads((pipeline/'unet/config.json').read_text(encoding='utf-8-sig'))
    if unet.get('cross_attention_dim') != 768 or unet.get('in_channels') != 4:
        raise ValueError('受控实验需要SD1.5四通道UNet配置')
    return binding


def pair_tokens(tokenizer, prompt, negative_prompt, *, skip_negative=False):
    if tokenizer.model_max_length != 77:
        raise ValueError('实验仅支持固定77位置的CLIP配置')
    positive = tokenizer(prompt, add_special_tokens=False, truncation=False)['input_ids']
    negative = tokenizer(negative_prompt, add_special_tokens=False, truncation=False)['input_ids']
    if max(len(positive), len(negative)) > 300:
        raise ValueError('提示词超过300个内容token（最多4块），不会截断')
    active_length = len(positive) if skip_negative else max(len(positive), len(negative))
    count = max(1, (active_length+74)//75)
    def pack(ids):
        return [tokenizer.bos_token_id, *ids, tokenizer.eos_token_id] + [tokenizer.pad_token_id]*(75-len(ids))
    return [{'positiveIds': pack(positive[i*75:(i+1)*75]),
             'negativeIds': pack(negative[i*75:(i+1)*75]),
             'positiveTokens': len(positive[i*75:(i+1)*75]),
             'negativeTokens': len(negative[i*75:(i+1)*75])} for i in range(count)]


def sample_fused(predict, scheduler, chunks, initial_latent, mode, *, steps, cfg, alpha,
                 check_cancelled=lambda: None, progress=lambda step: None):
    import torch
    if mode not in MODES or not 1 <= len(chunks) <= 4 or not 1 <= steps <= 30 or not 1 <= cfg <= 15 or not 0 <= alpha <= 1:
        raise ValueError('受控融合参数无效')
    skip_negative = cfg == 1.
    if skip_negative:
        # A longer, unused negative prompt must not create empty positive passes.
        end = len(chunks)
        while end > 1 and chunks[end-1]['positiveTokens'] == 0:
            end -= 1
        chunks = chunks[:end]
    counts = [max(1, c['positiveTokens'], 0 if skip_negative else c['negativeTokens']) for c in chunks]
    n = len(chunks)
    if mode == 'first_only': weights = [1.] + [0.]*(n-1)
    elif mode == 'equal_mean': weights = [1/n]*n
    elif mode == 'token_weighted': weights = [v/sum(counts) for v in counts]
    else: weights = [1.] if n == 1 else [1-alpha] + [alpha*v/sum(counts[1:]) for v in counts[1:]]
    scheduler.set_timesteps(steps, device=initial_latent.device)
    latent = initial_latent.clone() * scheduler.init_noise_sigma
    for index, timestep in enumerate(scheduler.timesteps):
        check_cancelled()
        model_input = scheduler.scale_model_input(latent, timestep)
        predictions = []
        for chunk in chunks[:1] if mode == 'first_only' else chunks:
            check_cancelled()
            positive = predict(model_input, timestep, chunk['positive']).float()
            check_cancelled()
            if skip_negative:
                guided = positive
            else:
                negative = predict(model_input, timestep, chunk['negative']).float()
                guided = negative + cfg*(positive-negative)
            if guided.shape != latent.shape or not torch.isfinite(guided).all():
                raise ValueError('UNet预测形状不符或非有限值')
            predictions.append(guided)
        check_cancelled()
        if mode == 'first_only' or n == 1:
            fused = predictions[0]
        elif mode == 'equal_mean':
            fused = sum(predictions)/n
        elif mode == 'token_weighted':
            fused = sum(w*p for w,p in zip(weights, predictions))
        else:
            anchor = predictions[0]
            residual = sum((counts[j]/sum(counts[1:]))*(predictions[j]-anchor) for j in range(1,n))
            fused = anchor + alpha*residual
        # Exactly one update per timestep, after every paired guided prediction.
        latent = scheduler.step(fused.to(latent.dtype), timestep, latent).prev_sample
        if not torch.isfinite(latent).all():
            raise ValueError('调度器返回非有限latent')
        progress(index+1)
    return latent, weights


def _load_pipeline(config):
    import os
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    import torch
    from diffusers import StableDiffusionPipeline, EulerDiscreteScheduler
    from identity_pipeline import configure_cuda
    configure_cuda()
    pipe = StableDiffusionPipeline.from_single_file(
        config['checkpoint'], config=config['pipelineConfig'], local_files_only=True,
        torch_dtype=torch.float16, safety_checker=None, requires_safety_checker=False)
    if pipe.unet.config.in_channels != 4 or pipe.unet.config.cross_attention_dim != 768:
        raise ValueError('受控融合模型架构不是SD1.5')
    pipe.scheduler = EulerDiscreteScheduler.from_config(pipe.scheduler.config,
        prediction_type='epsilon', timestep_spacing='linspace', use_karras_sigmas=False,
        use_exponential_sigmas=False, use_beta_sigmas=False)
    pipe.enable_attention_slicing()
    pipe.enable_vae_slicing()
    pipe.to('cuda')
    return pipe


def _versions():
    import torch
    import diffusers
    return {'torchVersion':str(torch.__version__), 'diffusersVersion':str(diffusers.__version__)}


def _publish_png(image, path):
    import os
    from pathlib import Path
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile('w+b',prefix='.fusion-',suffix='.tmp',dir=path.parent,delete=False) as stream:
            temporary=Path(stream.name)
            image.save(stream, format='PNG'); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary,path)  # fail if another result already owns this path
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def generate_fusion_images(config, payload):
    """File-worker entrypoint. Parent supplies all output paths; no client paths."""
    import hashlib
    from pathlib import Path
    import re
    from time import perf_counter
    import torch
    from history_transactions import validate_history_path
    from identity_events import emit_event
    from research_fusion import digest
    from research_image_service import FusionImageRequest

    job=payload.get('jobId','')
    if not isinstance(job,str) or re.fullmatch(r'fusion-[a-f0-9]{24}',job) is None:
        raise ValueError('图像实验jobId无效')
    root=Path(payload['dreamRoot']).absolute()
    folder=root/'data/identity/fusion-images'/job
    paths=payload.get('outputPaths')
    if not isinstance(paths,dict) or set(paths)!=set(MODES): raise ValueError('实验输出路径集无效')
    for mode in MODES:
        expected=validate_history_path(root,folder/(mode+'.pending.png'))
        if Path(paths[mode])!=expected: raise ValueError('实验输出必须属于当前job目录')
        if expected.exists(): raise FileExistsError('实验输出已存在，未覆盖')
    event_path=validate_history_path(root,folder/'events.jsonl')
    if payload.get('eventPath')!=str(event_path): raise ValueError('实验事件路径无效')
    settings=FusionImageRequest.model_validate(payload['settings']).model_dump()
    binding=resolve_assets(config)
    if binding!=payload.get('assetBinding'): raise ValueError('实验资产已改变')
    model_hash=file_sha256(binding['checkpoint']['path'])
    if resolve_assets(config)!=binding: raise ValueError('计算摘要时模型资产发生变化')
    pipe=None
    variants=[]
    try:
        pipe=_load_pipeline({'checkpoint':binding['checkpoint']['path'],'pipelineConfig':binding['pipelineConfig']})
        pairs=pair_tokens(pipe.tokenizer,settings['prompt'],settings['negativePrompt'],skip_negative=settings['cfg']==1)
        device=pipe._execution_device
        dtype=pipe.unet.dtype
        chunks=[]
        def encode(ids, count):
            tokens=torch.tensor([ids],device=device,dtype=torch.long)
            extra={}
            if getattr(pipe.text_encoder.config,'use_attention_mask',False):
                extra['attention_mask']=torch.tensor([[1]*(count+2)+[0]*(75-count)],device=device)
            return pipe.text_encoder(tokens,**extra)[0].to(device=device,dtype=dtype)
        with torch.inference_mode():
            for pair in pairs:
                chunks.append({'positive':encode(pair['positiveIds'],pair['positiveTokens']),
                               'negative':encode(pair['negativeIds'],pair['negativeTokens']) if settings['cfg']!=1 else None,
                               'positiveTokens':pair['positiveTokens'],'negativeTokens':pair['negativeTokens']})
            noise=torch.randn((1,4,settings['height']//pipe.vae_scale_factor,settings['width']//pipe.vae_scale_factor),
                              generator=torch.Generator(device='cpu').manual_seed(settings['seed']),device='cpu',dtype=torch.float32)
            initial_hash=hashlib.sha256(noise.contiguous().numpy().tobytes()).hexdigest()
            initial=noise.to(device=device,dtype=dtype)
            def predict(latent,timestep,embedding):
                return pipe.unet(latent,timestep,encoder_hidden_states=embedding).sample
            for mode in MODES:
                started=perf_counter()
                scheduler=type(pipe.scheduler).from_config(pipe.scheduler.config)
                def progress(step):
                    emit_event(str(event_path),{'type':'fusion-progress','jobId':job,'mode':mode,
                                               'step':step,'totalSteps':settings['steps']})
                progress(0)
                latent,weights=sample_fused(predict,scheduler,chunks,initial,mode,steps=settings['steps'],
                                           cfg=settings['cfg'],alpha=settings['alpha'],progress=progress)
                decoded=pipe.vae.decode(latent/pipe.vae.config.scaling_factor,return_dict=False)[0]
                image=pipe.image_processor.postprocess(decoded,output_type='pil')[0]
                if image.size!=(settings['width'],settings['height']): raise ValueError('解码图片尺寸无效')
                output=Path(paths[mode])
                _publish_png(image,output)
                variants.append({'mode':mode,'effectiveWeights':weights,'imageSha256':file_sha256(output),
                                 'durationMs':round((perf_counter()-started)*1000)})
                del latent,decoded,image
        if resolve_assets(config)!=binding: raise ValueError('推理期间模型资产发生变化')
        return {'contractVersion':'diffusers-chunk-fusion-images-v1','jobId':job,'settingsSha256':digest(settings),
                'variants':variants,'provenance':{'engine':'diffusers-sd15-paired-chunk-cfg',
                    'scheduler':'EulerDiscreteScheduler','predictionType':'epsilon',
                    'modelSha256':model_hash,'pipelineConfigSha256':digest(binding['files']),
                    'assetBinding':binding,'initialLatentSha256':initial_hash,'settings':settings,
                    'engineRevision':file_sha256(__file__),**_versions(),
                    'chunkCounts':[{'positive':p['positiveTokens'],'negative':p['negativeTokens']} for p in pairs],
                    'encodedTokenIds':[{'positive':p['positiveIds'],'negative':p['negativeIds']} for p in pairs],
                    'negativeEncodingPerformed':settings['cfg']!=1,'nativeDeviceParity':False}}
    finally:
        if pipe is not None:
            cuda=str(pipe._execution_device).startswith('cuda')
            try:
                pipe.maybe_free_model_hooks()
                if hasattr(pipe,'to'): pipe.to('cpu')
            finally:
                del pipe
                if cuda: torch.cuda.empty_cache()
