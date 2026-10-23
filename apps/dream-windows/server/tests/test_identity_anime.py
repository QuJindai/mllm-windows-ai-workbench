from types import SimpleNamespace

import pytest
from PIL import Image


def test_anime_profile_requires_sdxl_and_bounded_denoising():
    from identity_contract import IdentityGenerateRequest
    request = dict(referenceId='ref-'+'a'*24, faceIndex=0, prompt='portrait', facePolish=True,
                   animeProfileId='anime-'+'b'*24, animeDenoiseStrength=.35)
    with pytest.raises(ValueError):
        IdentityGenerateRequest(**request)
    valid = IdentityGenerateRequest(**request, modelId='illustrious-xl-v2.0-faceid')
    assert valid.animeDenoiseStrength == .35
    with pytest.raises(ValueError):
        IdentityGenerateRequest(**{**request, 'animeDenoiseStrength': .9}, modelId='illustrious-xl-v2.0-faceid')


def test_detector_unletterboxes_and_suppresses_duplicate_faces():
    import numpy as np
    from identity_anime import detection_boxes
    # 200x100 source resized2x to400x200, centered vertically in400x400.
    predictions = np.array([[[200,202,20], [200,201,20], [100,100,10], [80,80,10], [.9,.8,.1]]], dtype=np.float32)
    boxes = detection_boxes(predictions, (200,100), (400,400), threshold=.3)
    assert len(boxes) == 1
    assert boxes[0] == pytest.approx([75,30,125,70])


def test_composite_changes_only_mask_and_preserves_image_dimensions():
    from identity_anime import blend_face, face_mask
    import numpy as np
    image = Image.new('RGB',(200,200),'blue')
    patch = Image.new('RGB',(100,100),'red')
    box = [60,50,140,140]
    crop = (40,30,160,170)
    result = blend_face(image,patch,box,crop)
    original = np.asarray(image)
    mask = np.asarray(face_mask(image.size,box))
    assert result.mode == 'RGB' and result.size == image.size
    assert np.array_equal(np.asarray(result)[mask==0], original[mask==0])
    assert result.getpixel((100,100))[0] > 240
    assert result.getpixel((5,5)) == (0,0,255)


def test_anime_refuses_multiple_faces_instead_of_selecting_largest():
    from identity_anime import one_face
    with pytest.raises(ValueError,match='多'):
        one_face([[0,0,50,50],[80,80,100,100]])
    with pytest.raises(ValueError,match='检测'):
        one_face([])


def test_anime_polish_disabled_never_calls_processor(tmp_path):
    from identity_face_polish import optional_face_polish
    image = Image.new('RGB',(64,64),'blue')
    def fail():
        raise AssertionError('disabled path loaded processor')
    result,info=optional_face_polish(image,SimpleNamespace(facePolish=False),{},fail,lambda s:None)
    assert result is image and info == {'enabled':False,'status':'disabled'}


def test_session_selects_anime_processor_without_real_face_loading(monkeypatch):
    import identity_anime
    import identity_face_polish
    from identity_pipeline import IdentitySession
    session = IdentitySession.__new__(IdentitySession)
    session.architecture = 'SDXL'
    marker = object()
    monkeypatch.setattr(identity_anime, 'AnimePolisher', lambda s: marker)
    monkeypatch.setattr(identity_face_polish, 'FacePolisher', lambda *a: pytest.fail('real-face processor loaded'))
    assert session.face_polisher({'animeProfileId':'anime-'+'a'*24}) is marker


def test_hybrid_features_keep_real_id_and_anime_clip(tmp_path, monkeypatch):
    import torch
    import identity_anime
    import identity_features
    import identity_pipeline
    from safetensors.torch import load_file
    real = {'id':torch.ones(1,512), 'clip':torch.zeros(1,257,1280), 'negative_clip':torch.zeros(1,257,1280)}
    monkeypatch.setattr(identity_features, 'reference_features', lambda *a:(real, {'featureKey':'parent'}))
    monkeypatch.setattr(identity_pipeline, 'extract_clip_features', lambda *a:(torch.ones(1,257,1280),torch.zeros(1,257,1280)))
    monkeypatch.setattr(identity_anime, 'AnimeDetector', lambda c:SimpleNamespace(detect=lambda i:[[10,10,90,90]]))
    source = tmp_path/'anime.png'
    Image.new('RGB',(100,100),'blue').save(source)
    target = tmp_path/'hybrid.safetensors'
    info = identity_anime.prepare_anime({}, {'animeImagePath':str(source),'animeFeaturesPath':str(target)})
    stored = load_file(str(target))
    assert torch.equal(stored['id'], real['id'])
    assert stored['clip'].sum() == 257*1280 and info['parentFeatureKey'] == 'parent'


def test_redraw_error_restores_shared_vae_dtype_and_next_item_works(monkeypatch):
    import sys
    import torch
    import identity_anime
    class Vae:
        dtype = torch.float16
        def to(self, *, dtype): self.dtype=dtype
    vae=Vae()
    scheduler=SimpleNamespace(config={'name':'base'},step_index=30)
    base=SimpleNamespace(vae=vae,scheduler=scheduler,components={'vae':vae,'scheduler':scheduler})
    attempts=[]
    def factory(**components):
        assert components['scheduler'] is not scheduler
        def call(**kw):
            attempts.append(1)
            vae.dtype=torch.float32
            if len(attempts)==1: raise RuntimeError('decode failed')
            return SimpleNamespace(images=[kw['image']])
        return call
    monkeypatch.setitem(sys.modules,'diffusers',SimpleNamespace(StableDiffusionXLImg2ImgPipeline=factory,
        EulerDiscreteScheduler=SimpleNamespace(from_config=lambda c:object())))
    monkeypatch.setattr(identity_anime,'AnimeDetector',lambda c:SimpleNamespace(detect=lambda i:[[20,20,80,80]]))
    processor=identity_anime.AnimePolisher(SimpleNamespace(config={},pipe=base,anime_projected=object()))
    item={'animeProfile':{'id':'anime-'+'a'*24,'name':'Example-动漫','featureKey':'b'*64},'animeProfileId':'anime-'+'a'*24,
          'prompt':'portrait','cfg':5.,'seed':42}
    image=Image.linear_gradient('L').resize((100,100)).convert('RGB')
    with pytest.raises(RuntimeError): processor.apply(image,item,1,lambda s:None)
    assert vae.dtype==torch.float16
    output,info=processor.apply(image,item,1,lambda s:None)
    assert output.size==image.size and info['outsideMaskUnchanged']
    assert vae.dtype==torch.float16 and base.scheduler is scheduler and scheduler.step_index==30


def test_accelerate_failure_cleanup_offloads_real_parameters(monkeypatch):
    import torch
    from accelerate.hooks import AlignDevicesHook, add_hook_to_module
    from identity_anime import restore_offload_state
    class Broken(torch.nn.Linear):
        fail=True
        def forward(self,x):
            if self.fail: raise RuntimeError('injected')
            return super().forward(x)
    layer=Broken(2,2)
    add_hook_to_module(layer,AlignDevicesHook(execution_device='cpu',offload=True))
    with pytest.raises(RuntimeError): layer(torch.zeros(1,2))
    assert layer.weight.device.type=='cpu'
    restore_offload_state(SimpleNamespace(components={'unet':layer}))
    assert layer.weight.device.type=='meta'
    layer.fail=False
    assert layer(torch.zeros(1,2)).shape==(1,2)
    assert layer.weight.device.type=='meta'


def test_optional_feature_failure_does_not_abort_base_generation(tmp_path,monkeypatch):
    import identity_anime
    from identity_pipeline import IdentitySession
    from identity_face_polish import optional_face_polish
    def missing(item): raise FileNotFoundError('features disappeared after submission')
    monkeypatch.setattr(identity_anime,'load_anime_features',missing)
    session=IdentitySession.__new__(IdentitySession)
    session.project_anime(None,{})
    image=Image.new('RGB',(64,64),'blue')
    item={'dreamRoot':str(tmp_path),'jobId':'identity-'+'c'*24,'animeProfileId':'anime-'+'a'*24}
    final,info=optional_face_polish(image,SimpleNamespace(facePolish=True,faceRestoreStrength=1.),item,
                                  lambda:session.face_polisher(item),lambda s:None)
    assert final is image and info['status']=='failed' and info['originalImageUrl']
