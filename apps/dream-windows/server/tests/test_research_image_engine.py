import importlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch


def engine():
    assert importlib.util.find_spec('research_image_engine'), 'Image fusion engine missing'
    return importlib.import_module('research_image_engine')


class Tokenizer:
    bos_token_id, eos_token_id, pad_token_id, model_max_length = 1000, 1001, 1001, 77

    def __call__(self, text, **kwargs):
        assert kwargs == {'add_special_tokens': False, 'truncation': False}
        return {'input_ids': [int(x) for x in text.split()]}


class Scheduler:
    init_noise_sigma = 1.
    config = {'prediction_type': 'epsilon'}

    def __init__(self):
        self.inputs, self.outputs = [], []

    def set_timesteps(self, steps, device=None):
        self.timesteps = list(range(steps, 0, -1))

    def scale_model_input(self, latent, timestep):
        return latent

    def step(self, prediction, timestep, latent):
        self.inputs.append((latent.clone(), prediction.clone(), timestep))
        output = latent - prediction
        self.outputs.append(output.clone())
        return SimpleNamespace(prev_sample=output)


def test_token_pairing_preserves_all_negative_chunks_and_encoded_content_counts():
    pairs = engine().pair_tokens(Tokenizer(), ' '.join(['2'] * 76), ' '.join(['3'] * 150))
    assert [(p['positiveTokens'], p['negativeTokens']) for p in pairs] == [(75, 75), (1, 75)]
    assert pairs[1]['positiveIds'] == [1000, 2, 1001] + [1001]*74
    assert pairs[1]['negativeIds'] == [1000] + [3]*75 + [1001]
    empty = engine().pair_tokens(Tokenizer(), '2', ' '.join(['3'] * 151))
    assert empty[2]['positiveTokens'] == 0 and empty[2]['negativeTokens'] == 1
    with pytest.raises(ValueError, match='300'):
        engine().pair_tokens(Tokenizer(), ' '.join(['2'] * 301), '')


@pytest.mark.parametrize('mode,expected', [('first_only', 3.), ('equal_mean', 6.5),
                                        ('token_weighted', 4.75), ('anchor_residual', 4.75)])
def test_fused_cfg_enters_scheduler_once_per_step_with_exact_paired_negative(mode, expected):
    calls = []
    def predict(latent, timestep, embedding):
        calls.append((latent.clone(), timestep, embedding.item()))
        return torch.full_like(latent, embedding.item())
    scheduler = Scheduler()
    chunks = [{'positive': torch.tensor(2.), 'negative': torch.tensor(1.), 'positiveTokens': 3, 'negativeTokens': 1},
              {'positive': torch.tensor(6.), 'negative': torch.tensor(2.), 'positiveTokens': 1, 'negativeTokens': 1}]
    initial = torch.tensor([100.])
    result, weights = engine().sample_fused(predict, scheduler, chunks, initial, mode, steps=2, cfg=2., alpha=.25)
    assert len(scheduler.inputs) == 2
    assert result.item() == pytest.approx(100 - 2*expected)
    assert initial.item() == 100
    expected_branches = [2., 1.] if mode == 'first_only' else [2., 1., 6., 2.]
    assert [c[2] for c in calls] == expected_branches*2
    assert all(c[0].item() == 100 for c in calls[:len(expected_branches)])
    assert all(c[0].item() == 100-expected for c in calls[len(expected_branches):])


def test_cfg_one_uses_positive_counts_and_residual_uses_only_tail_denominator():
    chunks = [{'positive': torch.tensor(v), 'negative': torch.tensor(-99.),
               'positiveTokens': n, 'negativeTokens': 75} for v,n in [(2.,3),(6.,1),(10.,3)]]
    calls=[]
    def predict(x,t,e):
        calls.append(e.item()); return torch.full_like(x, e.item())
    output, weights = engine().sample_fused(predict, Scheduler(), chunks, torch.tensor([100.]),
        'anchor_residual', steps=1, cfg=1., alpha=.5)
    assert calls == [2.,6.,10.]
    assert weights == pytest.approx([.5,.125,.375])
    assert output.item() == pytest.approx(94.5)


@pytest.mark.parametrize('mode',['first_only','equal_mean','token_weighted','anchor_residual'])
def test_cfg_one_negative_length_cannot_add_active_positive_chunks(mode):
    outputs=[]
    for negative_length in (1,76,151,300):
        pairs=engine().pair_tokens(Tokenizer(),'2',' '.join(['3']*negative_length))
        chunks=[{**p,'positive':torch.tensor(2. if p['positiveTokens'] else 0.),
                 'negative':torch.tensor(-99.)} for p in pairs]
        calls=[]
        def predict(x,t,e):
            calls.append(e.item()); return torch.full_like(x,e.item())
        result,weights=engine().sample_fused(predict,Scheduler(),chunks,torch.tensor([100.]),mode,
            steps=1,cfg=1.,alpha=.5)
        outputs.append(result.item())
        assert calls==[2.] and weights==[1.]
    assert outputs==[98.]*4


def test_cfg_one_pairing_does_not_encode_negative_only_chunks():
    pairs=engine().pair_tokens(Tokenizer(),'2',' '.join(['3']*76),skip_negative=True)
    assert len(pairs)==1 and pairs[0]['positiveTokens']==1
    pairs=engine().pair_tokens(Tokenizer(),' '.join(['2']*76),' '.join(['3']*300),skip_negative=True)
    assert [p['positiveTokens'] for p in pairs]==[75,1]


def test_cancellation_stops_before_scheduler_and_no_later_chunk_is_predicted():
    stopped=False
    def predict(x,t,e):
        nonlocal stopped
        stopped=True
        return x
    def check():
        if stopped: raise RuntimeError('cancelled')
    scheduler=Scheduler()
    with pytest.raises(RuntimeError, match='cancelled'):
        engine().sample_fused(predict,scheduler,[{'positive':torch.tensor(1.),'negative':torch.tensor(0.),
            'positiveTokens':1,'negativeTokens':1}],torch.tensor([1.]),'equal_mean',steps=2,cfg=2.,alpha=.5,check_cancelled=check)
    assert scheduler.inputs == []


@pytest.mark.parametrize('cfg',[2.,1.])
def test_four_real_png_outputs_share_initial_noise_and_reset_scheduler_without_overwrite(tmp_path,monkeypatch,cfg):
    from PIL import Image
    from test_research_image_service import assets
    from research_fusion import MODES
    module=engine()
    assert hasattr(module,'generate_fusion_images'), 'Worker image entrypoint missing'
    config=assets(tmp_path)
    instances=[]; encoded=[]
    class ResetScheduler(Scheduler):
        @classmethod
        def from_config(cls,config,**kwargs):
            item=cls(); instances.append(item); return item
    class Encoder:
        config=SimpleNamespace(use_attention_mask=False)
        def __call__(self,ids,**kwargs):
            encoded.append(ids.clone())
            return (ids[:,1:2].float(),)
    class UNet:
        dtype=torch.float32
        config=SimpleNamespace(in_channels=4,cross_attention_dim=768)
        def __call__(self,x,t,encoder_hidden_states):
            return SimpleNamespace(sample=torch.full_like(x,float(encoder_hidden_states[0,0])))
    pipe=SimpleNamespace(tokenizer=Tokenizer(),text_encoder=Encoder(),unet=UNet(),scheduler=ResetScheduler(),
        _execution_device=torch.device('cpu'),vae_scale_factor=8,
        vae=SimpleNamespace(config=SimpleNamespace(scaling_factor=.18215),decode=lambda x,return_dict: (x,)),
        image_processor=SimpleNamespace(postprocess=lambda x,output_type: [Image.new('RGB',(256,256),int(abs(x.mean().item()))%255)]),
        maybe_free_model_hooks=lambda:None)
    monkeypatch.setattr(module,'_load_pipeline',lambda config:pipe,raising=False)
    # Only dependencies/model load are replaced: actual token pairing, denoising,
    # scheduler control, hashing and PNG publication execute on CPU.
    monkeypatch.setattr(module,'_versions',lambda:{'torchVersion':torch.__version__,'diffusersVersion':'test-boundary'},raising=False)
    settings={'modelId':'realistic-vision-v5.1-fusion','prompt':' '.join(['2']*76),'negativePrompt':'1',
              'seed':42,'steps':2,'cfg':2.,'alpha':.25,'width':256,'height':256,'requestId':'test-request-id-0001'}
    if cfg==1: settings.update(prompt='2',negativePrompt=' '.join(['1']*76),cfg=1.)
    job='fusion-'+'a'*24
    directory=tmp_path/'data/identity/fusion-images'/job
    payload={'jobId':job,'dreamRoot':str(tmp_path),'settings':settings,'assetBinding':module.resolve_assets(config),
             'outputPaths':{mode:str(directory/(mode+'.pending.png')) for mode in MODES},'eventPath':str(directory/'events.jsonl')}
    result=module.generate_fusion_images(config,payload)
    assert len(instances)==4 and all(len(s.inputs)==2 for s in instances)
    assert all(torch.equal(s.inputs[0][0],instances[0].inputs[0][0]) for s in instances)
    if cfg==1:
        assert result['provenance']['chunkCounts']==[{'positive':1,'negative':75}]
        assert result['provenance']['negativeEncodingPerformed'] is False
        assert len(encoded)==1
        assert all(v['effectiveWeights']==[1.] for v in result['variants'])
        assert len({v['imageSha256'] for v in result['variants']})==1
    else:
        assert result['provenance']['chunkCounts']==[{'positive':75,'negative':1},{'positive':1,'negative':0}]
    assert result['provenance']['scheduler']=='EulerDiscreteScheduler'
    for variant in result['variants']:
        path=Path(payload['outputPaths'][variant['mode']])
        assert Image.open(path).size==(256,256)
        assert variant['imageSha256']==module.file_sha256(path)
    before={mode:Path(path).read_bytes() for mode,path in payload['outputPaths'].items()}
    with pytest.raises((FileExistsError,ValueError)):
        module.generate_fusion_images(config,payload)
    assert before=={mode:Path(path).read_bytes() for mode,path in payload['outputPaths'].items()}


def test_worker_rejects_output_path_outside_its_job_before_loading_models(tmp_path,monkeypatch):
    from test_research_image_service import assets
    from research_fusion import MODES
    module=engine()
    assert hasattr(module,'generate_fusion_images'), 'Worker image entrypoint missing'
    config=assets(tmp_path)
    monkeypatch.setattr(module,'_load_pipeline',lambda config:pytest.fail('loaded model for invalid path'),raising=False)
    payload={'jobId':'fusion-'+'a'*24,'dreamRoot':str(tmp_path),'settings':{'prompt':'2','requestId':'test-request-id-0001'},
             'assetBinding':module.resolve_assets(config),'outputPaths':{mode:str(tmp_path/(mode+'.png')) for mode in MODES}}
    with pytest.raises(ValueError): module.generate_fusion_images(config,payload)


def test_loader_uses_only_local_config_and_checks_cuda_before_allocating(monkeypatch):
    import sys
    import identity_pipeline
    order=[]; captured={}
    monkeypatch.setattr(identity_pipeline,'configure_cuda',lambda:order.append('cuda-guard'))
    pipe=SimpleNamespace(unet=SimpleNamespace(config=SimpleNamespace(in_channels=4,cross_attention_dim=768)),
        scheduler=SimpleNamespace(config={'prediction_type':'epsilon'}),
        enable_attention_slicing=lambda:order.append('attention-slicing'),
        enable_vae_slicing=lambda:order.append('vae-slicing'),to=lambda device:order.append(device))
    def load(path,**kwargs):
        order.append('load');captured.update(path=path,**kwargs);return pipe
    monkeypatch.setitem(sys.modules,'diffusers',SimpleNamespace(
        StableDiffusionPipeline=SimpleNamespace(from_single_file=load),
        EulerDiscreteScheduler=SimpleNamespace(from_config=lambda config,**kwargs:SimpleNamespace(config=kwargs))))
    assert engine()._load_pipeline({'checkpoint':'existing.safetensors','pipelineConfig':'local-config'}) is pipe
    assert order==['cuda-guard','load','attention-slicing','vae-slicing','cuda']
    assert captured['local_files_only'] is True and captured['config']=='local-config'
    assert captured['torch_dtype']==torch.float16
    assert pipe.scheduler.config['prediction_type']=='epsilon' and pipe.scheduler.config['use_karras_sigmas'] is False


def test_parent_worker_cli_dispatches_fusion_with_raw_local_config(tmp_path,monkeypatch):
    import sys
    import identity_worker
    import identity_pipeline
    from test_research_image_service import assets
    config=assets(tmp_path)
    config_path=tmp_path/'runtime.json'; config_path.write_text(json.dumps(config))
    payload={'jobId':'fusion-'+'a'*24,'configPath':str(config_path)}
    request=tmp_path/'request.json'; request.write_text(json.dumps(payload))
    result=tmp_path/'result.json'; calls=[]
    def boundary(runtime,data):
        calls.append((runtime,data)); return {'jobId':data['jobId'],'boundaryTest':True}
    monkeypatch.setattr(engine(),'generate_fusion_images',boundary)
    monkeypatch.setattr(identity_pipeline,'generate',lambda *args:pytest.fail('fusion dispatched ordinary identity generation'))
    monkeypatch.setattr(identity_pipeline,'configure_cuda',lambda:pytest.fail('GPU boundary reached in a dispatch-only test'))
    monkeypatch.setattr(identity_worker,'sys',SimpleNamespace(
        stdout=SimpleNamespace(reconfigure=lambda **kwargs:None),
        stderr=SimpleNamespace(reconfigure=lambda **kwargs:None,write=lambda text:None,flush=lambda:None)))
    monkeypatch.setattr(sys,'argv',['identity_worker.py','--operation','fusion','--request',str(request),'--result',str(result)])
    assert identity_worker.main()==0
    assert calls==[(config,payload)]
    assert json.loads(result.read_text())=={'jobId':payload['jobId'],'boundaryTest':True}
