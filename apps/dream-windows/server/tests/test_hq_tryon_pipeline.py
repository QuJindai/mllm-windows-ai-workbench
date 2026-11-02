"""CPU-only tests of HQ inside the mature IdentitySession and face-polish flow."""
import copy
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
from PIL import Image, PngImagePlugin

from hq_tryon_conditioning import (ConditioningObserver, IdentityHQConditioning, PipelineError,
                                   dwpose_body_keypoints, error_record, project_garment, tensor_record)
from hq_tryon_pipeline import BASE_BINDINGS, DIRECTORY_KEYS, FILE_KEYS, readiness, required_assets, validate_config
from identity_contract import IdentityGenerateRequest
from identity_pipeline import IdentitySession


@pytest.fixture
def case(tmp_path, monkeypatch):
    torch.set_num_threads(2)
    config = {'schemaVersion': 1, 'guidanceScale': 11., 'personScale': 1.2, 'personLoraScale': 1.4}
    for key in FILE_KEYS:
        config[key] = str(tmp_path / 'models' / (key + '.bin'))
    for key in DIRECTORY_KEYS:
        config[key] = str(tmp_path / 'models' / key)
    for path in required_assets(config).values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'CPU test asset; not model weights')
    config_path = tmp_path / 'hq.json'
    config_path.write_text(json.dumps(config), encoding='utf-8')
    identity = {target: config[source] for source, target in BASE_BINDINGS.items()}
    identity.update(architecture='SD1.5', lorasDir=str(tmp_path / 'loras'))
    original = Image.linear_gradient('L').resize((300, 400)).convert('RGB')
    person = tmp_path / 'person-original.png'
    info = PngImagePlugin.PngInfo(); info.add_text('original', 'different encoding same pixels')
    original.save(person, pnginfo=info)
    reference = tmp_path / 'reference.png'
    original.save(reference)
    inputs = {}
    for role, size, color in [('person', (300, 400), 'red'), ('garment', (150, 300), 'green'), ('pose', (900, 1200), 'blue')]:
        path = person if role == 'person' else tmp_path / (role + '.png')
        if role != 'person':
            Image.new('RGB', size, color).save(path)
        inputs[role] = {'path': str(path), 'id': role + '-source-id', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    params = IdentityGenerateRequest(referenceId='ref-' + 'b' * 24, faceIndex=0, prompt='portrait',
                                     seed=7, width=256, height=384, steps=2)
    first = {**params.model_dump(), 'jobId': 'identity-' + 'a' * 24, 'dreamRoot': str(tmp_path),
             'imagePath': str(reference), 'outputPath': str(tmp_path / 'output.png'), 'metadataPath': str(tmp_path / 'metadata.json'),
             'hqConditioning': {'configPath': str(config_path), 'inputs': inputs, 'auditPath': str(tmp_path / 'audit.json'),
                                'jobId': 'hq-parent', 'eventPath': str(tmp_path / 'events.jsonl')}}
    monkeypatch.setattr(torch.cuda, 'max_memory_allocated', lambda: 0)
    monkeypatch.setattr(torch.cuda, 'max_memory_reserved', lambda: 0)
    return SimpleNamespace(root=tmp_path, config=config, config_path=config_path, identity=identity,
                           first=first, params=params, inputs=inputs)


class CpuModel(torch.nn.Module):
    def forward(self, *args, **kwargs):
        return None


class CpuPipe:
    """Only the expensive model boundary is replaced, not IdentitySession.render."""
    def __init__(self):
        from diffusers import EulerDiscreteScheduler
        self.unet, self.controlnet = CpuModel(), CpuModel()
        self.scheduler = EulerDiscreteScheduler()
        self.tokenizer = None
        self.actions = []
        self.received = None
    def to(self, device):
        self.actions.append(('to', device)); return self
    def set_progress_bar_config(self, **kwargs):
        pass
    def enable_sequential_cpu_offload(self, **kwargs):
        self.actions.append(('offload', 'sequential'))
    def enable_model_cpu_offload(self, **kwargs):
        self.actions.append(('offload', 'model'))
    def remove_all_hooks(self):
        self.actions.append(('remove_hooks', None))
    def __call__(self, **kwargs):
        self.received = kwargs
        latents = torch.zeros(1, 4, 32, 48)
        for index in range(kwargs['num_inference_steps']):
            if 'image' in kwargs:
                self.controlnet(controlnet_cond=torch.cat([kwargs['image'], kwargs['image']]))
            self.unet(latents, index, added_cond_kwargs={'image_embeds': kwargs['ip_adapter_image_embeds']})
            kwargs['callback_on_step_end'](self, index, index, {'latents': latents})
        return SimpleNamespace(images=[Image.linear_gradient('L').resize((kwargs['width'], kwargs['height'])).convert('RGB')])


def cpu_session(case, *, hq=True):
    session = IdentitySession.__new__(IdentitySession)
    session.config, session.architecture = case.identity, 'SD1.5'
    session.pipe, session.projected = CpuPipe(), torch.randn(2, 1, 4, 768)
    session.initial_stages, session.hashes, session.started = [], {}, time.perf_counter()
    session.feature_info = {'cacheHit': True, 'featureKey': 'cpu-fixture-features'}
    session._hq_conditioning = None
    if hq:
        helper = IdentityHQConditioning(case.identity, case.first, case.params, lambda e: None)
        helper.garment = torch.randn(2, 1, 16, 768)
        helper.pose = torch.rand(1, 3, case.params.height, case.params.width)
        helper.run.audit['conditioning'] = {role: {'inputRole': role} for role in ('person', 'garment', 'pose')}
        session._hq_conditioning = helper
    return session


def test_readiness_stays_lightweight(case):
    assert readiness(case.config_path, case.identity)['ready']
    script = 'import sys,json;from hq_tryon_pipeline import readiness;print(readiness(sys.argv[1],json.loads(sys.argv[2]))["ready"],"torch" in sys.modules)'
    proc = subprocess.run([sys.executable, '-B', '-c', script, str(case.config_path), json.dumps(case.identity)],
                          cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == 'True False'


def test_hq_model_bundle_cannot_override_identity(case):
    alternate = {**case.config, 'checkpoint': str(case.root / 'other.safetensors')}
    with pytest.raises(PipelineError) as failure:
        validate_config(alternate, case.identity)
    assert failure.value.code == 'HQ_IDENTITY_CONFIG_MISMATCH'
    effective = validate_config(case.config, case.identity)
    assert not {'guidanceScale', 'personScale', 'personLoraScale'} & effective.keys()


def test_supplemental_only_config_and_disabled_legacy_cli(case):
    supplemental = {key: value for key, value in case.config.items() if key not in BASE_BINDINGS}
    case.config_path.write_text(json.dumps(supplemental), encoding='utf-8')
    assert readiness(case.config_path, case.identity)['ready']
    helper = IdentityHQConditioning(case.identity, case.first, case.params, lambda e: None)
    assert helper.config['checkpoint'] == str(Path(case.identity['checkpoint']).resolve())
    script = Path(__file__).resolve().parents[1] / 'hq_tryon_pipeline.py'
    result = subprocess.run([sys.executable, '-B', str(script)], capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 1
    assert json.loads(result.stdout)['code'] == 'HQ_IDENTITY_PIPELINE_REQUIRED'


@pytest.mark.parametrize('model', ['illustrious-xl-v2.0-faceid', 'cyberrealistic-xl-plus-face'])
def test_sdxl_rejected_before_any_cuda(case, model):
    settings = {**case.params.model_dump(), 'modelId': model}
    if 'plus-face' in model:
        settings.update(structureStrength=0., faceLoraStrength=0.)
    params = IdentityGenerateRequest(**settings)
    with pytest.raises(PipelineError) as failure:
        IdentityHQConditioning(case.identity, case.first, params, lambda e: None)
    assert failure.value.code == 'HQ_MODEL_UNSUPPORTED'
    assert not (case.root / 'audit.json').exists()


def test_original_encoding_can_differ_when_pixels_match(case):
    helper = IdentityHQConditioning(case.identity, case.first, case.params, lambda e: None)
    audit = helper.run.audit
    assert audit['inputs']['person']['sha256'] != audit['identityReference']['sha256']
    assert audit['identityReference']['pixelEqualityVerified'] is True
    assert audit['inputs']['person']['id'] == case.inputs['person']['id']
    assert helper.images['pose'].size == (900, 1200)
    assert helper.images['garment'].size == (224, 224)


def test_person_pixel_mismatch_rejected(case):
    Image.new('RGB', (300, 400), 'white').save(case.first['imagePath'])
    with pytest.raises(PipelineError) as failure:
        IdentityHQConditioning(case.identity, case.first, case.params, lambda e: None)
    assert failure.value.code == 'HQ_PERSON_BINDING_MISMATCH'
    assert json.loads((case.root / 'audit.json').read_text(encoding='utf-8'))['status'] == 'failed'


def test_input_hash_and_model_presence_fail_closed(case):
    case.inputs['garment']['sha256'] = '0' * 64
    with pytest.raises(PipelineError) as failure:
        IdentityHQConditioning(case.identity, case.first, case.params, lambda e: None)
    assert failure.value.code == 'INPUT_HASH_MISMATCH'
    Path(case.config['poseModel']).unlink()
    assert readiness(case.config_path, case.identity)['missing'][0]['key'] == 'poseModel'


def test_no_original_or_existing_audit_overwrite(case):
    spec = case.first['hqConditioning']
    spec['auditPath'] = case.inputs['person']['path']
    before = Path(spec['auditPath']).read_bytes()
    with pytest.raises(PipelineError) as failure:
        IdentityHQConditioning(case.identity, case.first, case.params, lambda e: None)
    assert failure.value.code == 'UNSAFE_DESTINATION'
    assert Path(spec['auditPath']).read_bytes() == before


@pytest.mark.parametrize('destination', ['outputPath', 'metadataPath'])
def test_identity_publication_cannot_overwrite_sources_or_prior_work(case, destination):
    original = Path(case.inputs['person']['path'])
    before = original.read_bytes()
    case.first[destination] = str(original)
    with pytest.raises(PipelineError) as failure:
        IdentityHQConditioning(case.identity, case.first, case.params, lambda e: None)
    assert failure.value.code == 'UNSAFE_DESTINATION'
    assert original.read_bytes() == before
    previous = case.root / 'prior-work.png'
    previous.write_bytes(b'preserve previous work')
    case.first[destination] = str(previous)
    with pytest.raises(PipelineError) as failure:
        IdentityHQConditioning(case.identity, case.first, case.params, lambda e: None)
    assert failure.value.code == 'OUTPUT_EXISTS'
    assert previous.read_bytes() == b'preserve previous work'


def test_hq_render_keeps_euler_identity_params_and_actual_bindings(case):
    session = cpu_session(case)
    scheduler = session.pipe.scheduler
    result = session.render(case.first, 0, lambda e: None, None, 0)
    metadata = result['metadata']; audit = metadata['hq']
    assert session.pipe.scheduler is scheduler
    assert metadata['sampler'] == 'Euler'
    assert metadata['cfg'] == 5.5
    assert metadata['identity']['identityStrength'] == .82
    assert metadata['identity']['structureStrength'] == .9
    assert metadata['identity']['faceLoraStrength'] == .55
    assert session.pipe.received['guidance_scale'] == 5.5
    assert ('to', 'cuda') not in session.pipe.actions
    assert len(session.pipe.received['ip_adapter_image_embeds']) == 2
    assert audit['jobId'] == case.first['jobId'] and audit['parentJobId'] == 'hq-parent'
    assert audit['status'] == 'completed' and audit['completedSteps'] == 2
    assert audit['facePolish'] == {'enabled': False, 'status': 'disabled'}
    for role in ('person', 'garment', 'pose'):
        observed = audit['conditioning'][role]['actualConditioning']
        assert observed['observed'] and observed['forwardCalls'] == 2
        assert len(observed['sha256']) == 64
    assert audit == json.loads((case.root / 'audit.json').read_text(encoding='utf-8'))
    assert json.loads(Path(case.first['metadataPath']).read_text(encoding='utf-8'))['hq'] == audit
    assert audit['output']['sha256'] == hashlib.sha256(Path(case.first['outputPath']).read_bytes()).hexdigest()
    assert result['imageUrl'] == f"/api/history/{case.first['jobId']}/image"
    assert not session.pipe.unet._forward_pre_hooks and not session.pipe.controlnet._forward_pre_hooks


def test_hq_uses_existing_face_polisher_and_original_storage(case, monkeypatch):
    import identity_face_polish
    case.first.update(facePolish=True, faceRestoreStrength=.35)
    case.params = IdentityGenerateRequest(**{k: v for k, v in case.first.items() if k in IdentityGenerateRequest.model_fields})
    called = []
    class ExistingPolisherBoundary:
        def __init__(self, config, item):
            assert config is case.identity
            called.append('existing-factory')
        def apply(self, image, item, strength, stage):
            assert strength == .35
            called.append('existing-apply')
            image.putpixel((10, 10), (255, 0, 0))
            return image, {'method': 'CPU-test-boundary'}
    monkeypatch.setattr(identity_face_polish, 'FacePolisher', ExistingPolisherBoundary)
    session = cpu_session(case)
    metadata = session.render(case.first, 0, lambda e: None, None, 0)['metadata']
    assert called == ['existing-factory', 'existing-apply']
    assert metadata['facePolish']['status'] == 'completed'
    original = case.root / 'data/identity/originals' / (case.first['jobId'] + '.png')
    assert original.is_file()
    assert metadata['hq']['baseBeforePolish']['path'] == str(original)
    assert metadata['hq']['baseBeforePolish']['sha256'] == hashlib.sha256(original.read_bytes()).hexdigest()
    assert metadata['hq']['output']['sha256'] != metadata['hq']['baseBeforePolish']['sha256']
    assert session.pipe.actions[-2:] == [('remove_hooks', None), ('to', 'cpu')]


def test_ordinary_identity_does_not_use_hq_or_controlnet(case):
    session = cpu_session(case, hq=False)
    item = {k: v for k, v in case.first.items() if k != 'hqConditioning'}
    result = session.render(item, 0, lambda e: None, None, 0)
    assert 'hq' not in result['metadata']
    assert 'image' not in session.pipe.received
    assert len(session.pipe.received['ip_adapter_image_embeds']) == 1
    assert session.pipe.actions == [('to', 'cuda')]
    assert not (case.root / 'audit.json').exists()


def test_cancel_at_real_forward_is_recorded_without_output(case):
    cancel = case.root / 'cancel.flag'
    case.first['hqConditioning']['cancelPath'] = str(cancel)
    session = cpu_session(case)
    original_step = session._hq_conditioning.on_step
    def cancel_next(index, timestep):
        original_step(index, timestep)
        cancel.touch()
    session._hq_conditioning.on_step = cancel_next
    with pytest.raises(PipelineError) as failure:
        session.render(case.first, 0, lambda e: None, None, 0)
    assert failure.value.code == 'CANCELLED'
    assert not Path(case.first['outputPath']).exists()
    audit = json.loads((case.root / 'audit.json').read_text(encoding='utf-8'))
    assert audit['status'] == 'cancelled' and audit['completedSteps'] == 1
    assert not session.pipe.unet._forward_pre_hooks


def test_misrouted_tensor_is_rejected(case):
    run = SimpleNamespace(audit={'conditioning': {r: {} for r in ('person', 'garment', 'pose')}}, check_cancel=lambda: None)
    person, garment = torch.zeros(2, 1, 4, 8), torch.ones(2, 1, 16, 8)
    observer = ConditioningObserver(run, [person, garment], torch.ones(2, 3, 8, 8))
    with pytest.raises(PipelineError, match='differs'):
        observer.record('person', garment, 'wrong-slot')
    with pytest.raises(PipelineError):
        observer.finish(2)
    assert not observer.records


def test_native_garment_projection_and_attention_are_independent():
    from diffusers.models.embeddings import IPAdapterPlusImageProjection, MultiIPAdapterImageProjection
    from diffusers.models.attention_processor import Attention, IPAdapterAttnProcessor2_0
    projection = IPAdapterPlusImageProjection(embed_dims=12, output_dims=8, hidden_dims=8, depth=1, dim_head=4, heads=2, num_queries=16)
    hidden = torch.randn(2, 17, 12)
    def project(clip):
        unet = SimpleNamespace(dtype=torch.float32, encoder_hid_proj=MultiIPAdapterImageProjection([torch.nn.Identity(), copy.deepcopy(projection)]))
        result = project_garment(SimpleNamespace(unet=unet), clip, device='cpu')
        assert isinstance(unet.encoder_hid_proj.image_projection_layers[0], torch.nn.Identity)
        return result
    first, changed = project(hidden), project(-hidden)
    assert first.shape == (2, 1, 16, 8) and not torch.equal(first, changed)
    proc = IPAdapterAttnProcessor2_0(hidden_size=8, cross_attention_dim=8, num_tokens=(4, 16), scale=[.82, .7])
    attn = Attention(query_dim=8, cross_attention_dim=8, heads=2, dim_head=4, processor=proc)
    query, text, person = torch.randn(2, 9, 8), torch.randn(2, 5, 8), torch.randn(2, 1, 4, 8)
    with torch.inference_mode():
        baseline = attn(query, encoder_hidden_states=(text, [person, first]))
        different_person = attn(query, encoder_hidden_states=(text, [-person, first]))
        different_garment = attn(query, encoder_hidden_states=(text, [person, changed]))
    assert not torch.allclose(baseline, different_person)
    assert not torch.allclose(baseline, different_garment)


@pytest.mark.parametrize('offload', [False, True])
def test_native_controlnet_wrapper_keeps_fp16_and_samples_both_adapters(monkeypatch, offload):
    from contextlib import nullcontext
    from diffusers import AutoencoderKL, ControlNetModel, EulerDiscreteScheduler, StableDiffusionPipeline, UNet2DConditionModel
    from diffusers.models.attention_processor import IPAdapterAttnProcessor2_0
    from diffusers.models.embeddings import MultiIPAdapterImageProjection
    from transformers import CLIPTextConfig, CLIPTextModel
    torch.set_num_threads(2)
    unet = UNet2DConditionModel(sample_size=8, in_channels=4, out_channels=4,
        down_block_types=('CrossAttnDownBlock2D', 'DownBlock2D'),
        up_block_types=('UpBlock2D', 'CrossAttnUpBlock2D'), block_out_channels=(8, 16),
        layers_per_block=1, norm_num_groups=4, cross_attention_dim=768, attention_head_dim=2).half()
    vae = AutoencoderKL(block_out_channels=(8, 8, 8, 8), norm_num_groups=4,
        down_block_types=('DownEncoderBlock2D',) * 4, up_block_types=('UpDecoderBlock2D',) * 4).half()
    text_encoder = CLIPTextModel(CLIPTextConfig(vocab_size=8, hidden_size=768,
        intermediate_size=16, num_hidden_layers=1, num_attention_heads=4)).half()
    base = StableDiffusionPipeline(vae, text_encoder, None, unet, EulerDiscreteScheduler(steps_offset=1),
                                  None, None, requires_safety_checker=False)
    controlnet = ControlNetModel.from_unet(unet, conditioning_embedding_out_channels=(4, 8, 8, 16)).half()
    monkeypatch.setattr(ControlNetModel, 'from_single_file', lambda *a, **k: controlnet)
    helper = IdentityHQConditioning.__new__(IdentityHQConditioning)
    helper.config = {'controlnet': 'CPU-fixture', 'controlnetConfig': 'CPU-fixture'}
    helper.run = SimpleNamespace(stage=lambda name: nullcontext(), audit={})
    pipe = helper.wrap_pipe(base)
    assert pipe.scheduler is base.scheduler
    assert all(getattr(pipe, name) is getattr(base, name) for name in ('unet', 'vae', 'text_encoder'))
    assert all(getattr(pipe, name).dtype == torch.float16 for name in ('unet', 'vae', 'text_encoder', 'controlnet'))
    processors = dict(pipe.unet.attn_processors)
    for name in processors:
        if name.endswith('attn2.processor'):
            attention = pipe.unet.get_submodule(name.removesuffix('.processor'))
            processors[name] = IPAdapterAttnProcessor2_0(hidden_size=attention.to_q.out_features,
                cross_attention_dim=768, num_tokens=(4, 16), scale=[.82, .7]).half()
    pipe.unet.set_attn_processor(processors)
    pipe.unet.encoder_hid_proj = MultiIPAdapterImageProjection([torch.nn.Identity(), torch.nn.Identity()])
    pipe.unet.register_to_config(encoder_hid_dim_type='ip_image_proj')
    person, garment = torch.randn(2, 1, 4, 768).half(), torch.randn(2, 1, 16, 768).half()
    pose = torch.rand(1, 3, 64, 64).half()
    run = SimpleNamespace(audit={'conditioning': {r: {} for r in ('person', 'garment', 'pose')}}, check_cancel=lambda: None)
    observer = ConditioningObserver(run, [person, garment], torch.cat([pose, pose]))
    if offload:
        # Exercise the real Accelerate meta/CPU hooks, with CPU as execution device.
        from accelerate import cpu_offload
        for module in pipe.components.values():
            if isinstance(module, torch.nn.Module):
                cpu_offload(module, execution_device=torch.device('cpu'))
        assert pipe.unet.conv_in.weight.device.type == 'meta'
    observer.attach(pipe)
    pipe.set_progress_bar_config(disable=True)
    try:
        with torch.inference_mode():
            result = pipe(prompt_embeds=torch.zeros(1, 5, 768).half(), negative_prompt_embeds=torch.zeros(1, 5, 768).half(),
                image=pose, ip_adapter_image_embeds=[person, garment], width=64, height=64,
                num_inference_steps=2, guidance_scale=5.5, output_type='latent',
                generator=torch.Generator(device='cpu').manual_seed(7)).images
        observer.finish(2)
        assert result.dtype == torch.float16 and torch.isfinite(result).all()
    finally:
        observer.close()
        pipe.remove_all_hooks()
    assert not torch.cuda.is_initialized()


def test_pose_mapping_and_low_confidence():
    import numpy as np
    points = np.full((1, 133, 2), 50.)
    points[0, 5], points[0, 6] = [20, 30], [40, 50]
    scores = np.full((1, 133), .8)
    body = dwpose_body_keypoints(points, scores, 100, 100)
    np.testing.assert_allclose(body[1], [.3, .4, .8])
    np.testing.assert_allclose(body[2], [.4, .5, .8])
    scores[0, 9] = .2
    with pytest.raises(PipelineError) as failure:
        dwpose_body_keypoints(points, scores, 100, 100)
    assert failure.value.code == 'POSE_LOW_CONFIDENCE'


def test_oom_error_code():
    assert error_record(RuntimeError('CUDA out of memory'))['code'] == 'VRAM_OOM'


def test_hq_cannot_share_a_batch_or_change_bound_parameters(case):
    from identity_pipeline import validate_batch_items
    with pytest.raises(ValueError, match='HQ'):
        validate_batch_items([case.first, case.first])
    session = cpu_session(case)
    changed = {**case.first, 'seed': case.params.seed + 1}
    with pytest.raises(PipelineError) as failure:
        session.render(changed, 0, lambda e: None, None, 0)
    assert failure.value.code == 'HQ_REUSE_FORBIDDEN'
    assert not Path(case.first['outputPath']).exists()


def test_worker_one_shot_ownership_barrier_and_structured_error(case):
    worker = Path(__file__).resolve().parents[1] / 'identity_worker.py'
    # Nonexistent runtime rejects before inference imports, after the real handshake.
    request = {**case.first, 'configPath': str(case.root / 'missing-runtime.json')}
    request_path, result_path = case.root / 'request.json', case.root / 'result.json'
    request_path.write_text(json.dumps(request), encoding='utf-8')
    process = subprocess.Popen([sys.executable, '-B', str(worker), '--operation', 'generate', '--ownership-handshake',
                                '--request', str(request_path), '--result', str(result_path)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
    try:
        ready = json.loads(process.stdout.readline())
        assert ready['workerReady'] is True and ready['pid'] > 0
        assert not result_path.exists()
        _, stderr = process.communicate('{"workerContinue":true}\n', timeout=30)
        assert process.returncode == 1, stderr
        assert 'Traceback (most recent call last):' in stderr and 'load_config' in stderr
        result = json.loads(result_path.read_text(encoding='utf-8'))
        assert not result['ok'] and isinstance(result['error'], dict)
    finally:
        if process.poll() is None:
            process.kill(); process.wait()


def test_cpu_tests_never_initialized_cuda():
    assert not torch.cuda.is_initialized()
