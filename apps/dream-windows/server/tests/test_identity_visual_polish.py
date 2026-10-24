"""Optional visual redraw must retain its original, style and batch isolation."""
from types import SimpleNamespace
import sys

import numpy as np
from PIL import Image
import pytest

VISUAL = 'cyberrealistic-xl-plus-face'
REFERENCE = 'ref-' + 'a' * 24


def test_visual_session_routes_to_visual_redraw_never_real_face_swap(monkeypatch):
    import identity_face_polish
    from identity_pipeline import IdentitySession
    marker = object()
    monkeypatch.setitem(sys.modules, 'identity_visual_polish', SimpleNamespace(VisualReferencePolisher=lambda s: marker))
    monkeypatch.setattr(identity_face_polish, 'FacePolisher', lambda *a: pytest.fail('visual path loaded real face swap'))
    session = IdentitySession.__new__(IdentitySession)
    session.architecture, session.config = 'SDXL', {}
    assert session.face_polisher({'modelId': VISUAL}) is marker
    assert session.face_polisher({'modelId': VISUAL}) is marker


@pytest.fixture
def redraw_case(monkeypatch):
    import torch
    import identity_visual_polish as module
    class Vae:
        dtype = torch.float16
        def to(self, *, dtype): self.dtype = dtype
    vae = Vae()
    scheduler = SimpleNamespace(config={'name': 'base'}, step_index=30)
    pipe = SimpleNamespace(vae=vae, scheduler=scheduler, components={'vae': vae, 'scheduler': scheduler})
    embeds = torch.ones(2, 1, 257, 1280)
    session = SimpleNamespace(config={}, pipe=pipe, projected=embeds, visual_reference=(REFERENCE, 0),
                              feature_info={'featureKey': 'b'*64})
    observed = []
    control = {'fail': False, 'blank': False, 'boxes': [[35., 30., 85., 95.]]}
    def factory(**components):
        assert components['vae'] is vae
        assert components['scheduler'] is not scheduler
        def call(**kw):
            observed.append(kw)
            vae.dtype = torch.float32
            if control['fail']: raise RuntimeError('decode failure')
            callback = kw['callback_on_step_end']
            for step in range(int(kw['num_inference_steps'] * kw['strength'])):
                assert callback(None, step, None, {'latents': None}) == {'latents': None}
            patch = Image.new('RGB', kw['image'].size, 'black') if control['blank'] else Image.linear_gradient('L').resize(kw['image'].size).convert('RGB')
            return SimpleNamespace(images=[patch])
        return call
    monkeypatch.setitem(sys.modules, 'diffusers', SimpleNamespace(StableDiffusionXLImg2ImgPipeline=factory,
        StableDiffusionXLInpaintPipeline=factory,
        EulerDiscreteScheduler=SimpleNamespace(from_config=lambda c: object())))
    monkeypatch.setattr(module, 'AnimeDetector', lambda c: SimpleNamespace(detect=lambda i: control['boxes']))
    # Real offload recovery is separately covered with an Accelerate module test.
    recovered = []
    monkeypatch.setattr(module, 'restore_offload_state', lambda p: recovered.append(p))
    item = {'modelId':VISUAL, 'referenceId':REFERENCE, 'faceIndex':0, 'prompt':'anime portrait, adult woman',
            'negativePrompt':'photo', 'cfg':5., 'seed':42, 'animeDenoiseStrength':.35}
    image = Image.new('RGB', (120, 140), (30, 90, 160))
    return module.VisualReferencePolisher(session), item, image, observed, control, session, recovered


def test_redraw_uses_current_visual_embedding_and_changes_only_soft_mask(redraw_case):
    from identity_anime import face_mask
    processor, item, image, calls, _, session, _ = redraw_case
    stages = []
    output, details = processor.apply(image, item, 1., stages.append)
    assert calls[0]['ip_adapter_image_embeds'][0] is session.projected
    assert calls[0]['strength'] == .35 and calls[0]['num_inference_steps'] == 30
    assert calls[0]['guidance_scale'] == 5. and calls[0]['generator'].initial_seed() == 42
    assert output.size == image.size and output.mode == 'RGB'
    mask = np.asarray(face_mask(image.size, [35., 30., 85., 95.]))
    assert np.array_equal(np.asarray(output)[mask == 0], np.asarray(image)[mask == 0])
    assert not np.array_equal(np.asarray(output)[mask > 0], np.asarray(image)[mask > 0])
    assert details['method'] == 'visual-reference-local-redraw'
    assert details['referenceId'] == REFERENCE and details['faceIndex'] == 0
    assert details['featureKey'] == 'b'*64 and details['denoiseStrength'] == .35
    assert details['outsideMaskUnchanged'] is True
    assert 'swapModel' not in details and 'profileId' not in details
    assert any('10 / 10' in event for event in stages)


@pytest.mark.parametrize('changes', [{'referenceId':'ref-'+'c'*24}, {'faceIndex':1}, {'modelId':'realistic-vision-v5.1-faceid'}, {'animeProfileId':'anime-'+'d'*24}])
def test_redraw_rejects_cross_reference_or_real_model(redraw_case, changes):
    processor, item, image, calls, _, _, _ = redraw_case
    with pytest.raises(ValueError): processor.apply(image, {**item, **changes}, 1., lambda s:None)
    assert calls == []


@pytest.mark.parametrize('boxes', [[], [[10,10,30,30], [40,40,80,80]]])
def test_ambiguous_face_retains_original_without_running_redraw(redraw_case, tmp_path, boxes):
    from identity_face_polish import optional_face_polish
    processor, item, image, calls, control, _, _ = redraw_case
    control['boxes'] = boxes
    item.update(dreamRoot=str(tmp_path), jobId='identity-'+'e'*24)
    output, info = optional_face_polish(image, SimpleNamespace(facePolish=True,faceRestoreStrength=1.),
                                      item, lambda:processor, lambda s:None)
    assert output is image and info['status'] == 'failed' and info['originalImageUrl']
    assert calls == []
    assert Image.open(tmp_path/'data/identity/originals'/(item['jobId']+'.png')).tobytes() == image.tobytes()


def test_redraw_failure_restores_shared_vae_and_next_item_is_usable(redraw_case):
    import torch
    processor, item, image, _, control, session, recovered = redraw_case
    control['fail'] = True
    with pytest.raises(RuntimeError): processor.apply(image, item, 1., lambda s:None)
    assert session.pipe.vae.dtype == torch.float16 and recovered == [session.pipe]
    control['fail'] = False
    output, info = processor.apply(image, item, 1., lambda s:None)
    assert output.size == image.size and info['outsideMaskUnchanged']
    assert session.pipe.vae.dtype == torch.float16 and session.pipe.scheduler.step_index == 30


def test_blank_redraw_is_not_published_as_a_success(redraw_case):
    processor, item, image, _, control, _, _ = redraw_case
    control['blank'] = True
    with pytest.raises(ValueError, match='原图'): processor.apply(image, item, 1., lambda s:None)


def test_visual_polish_status_needs_only_local_detector(tmp_path):
    from identity_visual_polish import visual_polish_status
    assert not visual_polish_status({})['ready']
    detector = tmp_path/'detector.onnx'
    detector.write_bytes(b'local test weight')
    assert visual_polish_status({'animeFaceDetector':str(detector)})['ready']


def test_detailer_does_not_shrink_a_large_face_to_512_crop(redraw_case):
    processor, item, _, calls, control, _, _ = redraw_case
    control['boxes'] = [[170., 130., 602., 598.]]
    image = Image.new('RGB', (768, 768), (30, 90, 160))
    _, details = processor.apply(image, item, 1., lambda s: None)
    width, height = calls[0]['image'].size
    assert 720 <= width <= 768 and 720 <= height <= 768
    assert width % 8 == height % 8 == 0
    assert details['processingSize'] == [width, height]


def test_detailer_passes_a_spatial_mask_into_sampling(redraw_case):
    processor, item, image, calls, _, _, _ = redraw_case
    processor.apply(image, item, 1., lambda s: None)
    mask = calls[0].get('mask_image')
    assert isinstance(mask, Image.Image), 'a paste-back mask is not a sampling mask'
    assert mask.size == calls[0]['image'].size and mask.mode == 'L'
    pixels = np.asarray(mask)
    assert pixels[0, 0] == 0 and pixels.max() == 255 and np.any(pixels == 0)
    assert calls[0]['width'] == mask.width and calls[0]['height'] == mask.height


def test_detail_prompt_does_not_inherit_scene_framing(redraw_case):
    processor, item, image, calls, _, _, _ = redraw_case
    item['prompt'] = 'waist-up, park, sweater'
    _, details = processor.apply(image, item, 1., lambda s: None)
    assert calls[0]['prompt'] != item['prompt']
    assert 'park' not in calls[0]['prompt'] and 'sweater' not in calls[0]['prompt']
    assert details['detailPrompt'] == calls[0]['prompt']
    assert details['detailerVersion'] == 'masked-face-v1'


def test_detail_prompt_override_is_independent_and_recorded(redraw_case):
    processor, item, image, calls, _, _, _ = redraw_case
    item.update(visualPolishPrompt='clean anime linework, gentle smile', visualPolishNegativePrompt='blurry eyes')
    _, details = processor.apply(image, item, 1., lambda s: None)
    assert calls[0]['prompt'] == 'clean anime linework, gentle smile'
    assert calls[0]['negative_prompt'] == 'blurry eyes'
    assert details['detailNegativePrompt'] == 'blurry eyes'


def test_detail_parameters_are_validated_and_survive_request_roundtrip():
    from identity_contract import IdentityGenerateRequest
    values = dict(modelId=VISUAL, referenceId=REFERENCE, faceIndex=0, prompt='park',
                  structureStrength=0., faceLoraStrength=0., visualPolishPrompt='  clean eyes  ',
                  visualPolishNegativePrompt=' blurry ')
    parsed = IdentityGenerateRequest.model_validate(values)
    assert parsed.model_dump()['visualPolishPrompt'] == 'clean eyes'
    assert parsed.model_dump()['visualPolishNegativePrompt'] == 'blurry'
    for invalid in ('x'*2001, 123, None):
        with pytest.raises(ValueError):
            IdentityGenerateRequest.model_validate({**values, 'visualPolishPrompt': invalid})


@pytest.fixture
def staged_artifacts(monkeypatch):
    saved, cleaned = [], []
    def save(image, item, kind):
        saved.append((kind,image.copy()))
        return f"/api/identity/jobs/{item['jobId']}/stages/{kind}"
    monkeypatch.setitem(sys.modules,'identity_stage_artifacts',SimpleNamespace(
        save_visual_stage=save,cleanup_visual_stages=lambda item:cleaned.append(item['jobId'])))
    return saved,cleaned


def test_anchor_initializes_before_redraw_and_records_each_stage(redraw_case,staged_artifacts,monkeypatch):
    import identity_reference_anchor
    processor,item,image,calls,_,_,_=redraw_case
    item.update(visualPolishMode='reference-anchor',visualAnchorStrength=.95,visualPolishPasses=1,
                jobId='identity-'+'e'*24,imagePath='local-reference.png')
    anchor=Image.linear_gradient('L').resize(image.size).convert('RGB')
    monkeypatch.setattr(identity_reference_anchor,'ReferenceAnchor',lambda *a:SimpleNamespace(
        apply=lambda image,strength:(anchor,[35.,30.,85.,95.],{'anchorStrength':strength,'alignmentError':.05})))
    output,info=processor.apply(image,item,1.,lambda s:None)
    assert calls[0]['image'].getextrema() != image.getextrema()
    assert [kind for kind,_ in staged_artifacts[0]] == ['anchor','harmonize']
    assert info['detailerVersion']=='staged-face-v2' and info['polishMode']=='reference-anchor'
    assert info['alignmentError']==.05 and info['anchorStrength']==.95
    assert len(info['passes'])==1 and info['passes'][0]['steps']==10
    assert info['passes'][0]['durationMs']>=0
    assert [s['kind'] for s in info['snapshots']]==['anchor','harmonize']


def test_two_pass_redraw_reuses_first_result_instead_of_regenerating_scene(redraw_case,staged_artifacts):
    processor,item,image,calls,_,_,_=redraw_case
    item.update(visualPolishPasses=2,jobId='identity-'+'e'*24)
    stages=[]
    output,info=processor.apply(image,item,1.,stages.append)
    assert len(calls)==2 and calls[1]['strength']==.15
    assert calls[1]['image'].tobytes()!=calls[0]['image'].tobytes()
    assert [r['kind'] for r in info['passes']]==['harmonize','detail']
    assert [r['steps'] for r in info['passes']]==[10,4]
    assert [kind for kind,_ in staged_artifacts[0]]==['harmonize','detail']
    assert info['polishMode']=='redraw'
    from identity_anime import face_mask
    mask=np.asarray(face_mask(image.size,[35.,30.,85.,95.]))
    assert np.array_equal(np.asarray(output)[mask==0],np.asarray(image)[mask==0])


def test_second_pass_failure_retains_original_and_removes_partial_snapshots(redraw_case,staged_artifacts,tmp_path):
    from identity_face_polish import optional_face_polish
    processor,item,image,calls,control,_,_=redraw_case
    item.update(visualPolishPasses=2,jobId='identity-'+'e'*24,dreamRoot=str(tmp_path))
    def stage(message):
        if '第二轮' in message: control['fail']=True
    output,info=optional_face_polish(image,SimpleNamespace(facePolish=True,faceRestoreStrength=1.),
                                    item,lambda:processor,stage)
    assert len(calls)==2 and info['status']=='failed'
    assert output is image and staged_artifacts[1]==[item['jobId']]
    assert 'snapshots' not in info


@pytest.mark.parametrize('change',[{'visualPolishMode':'reference-anchor'},{'visualAnchorStrength':.7},{'visualPolishPasses':2}])
def test_batch_cannot_mix_staged_polish_controls(tmp_path,change):
    from identity_contract import IdentityGenerateRequest
    from identity_pipeline import validate_batch_items
    request=IdentityGenerateRequest(modelId=VISUAL,referenceId=REFERENCE,faceIndex=0,prompt='portrait',seed=42,
                                    structureStrength=0.,faceLoraStrength=0.).model_dump()
    base={**request,'imagePath':str(tmp_path/'reference.png'),'dreamRoot':str(tmp_path),
          'outputPath':str(tmp_path/'one.png'),'metadataPath':str(tmp_path/'one.json')}
    second={**base,**change,'outputPath':str(tmp_path/'two.png'),'metadataPath':str(tmp_path/'two.json')}
    with pytest.raises(ValueError,match='同一批次'): validate_batch_items([base,second])
