"""Task 4 contracts and CPU-only render/research regressions."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_identity_models import assets
from test_identity_pipeline_publication import render_case
from test_identity_visual_service import visual_service, reference
from test_identity_visual_polish import redraw_case
from test_identity_visual_polish_storage import redraw_service, completed


CYBER = 'cyberrealistic-xl-plus-face'
ILLUSTRIOUS = 'illustrious-xl-v2.0-plus-face'
FACEID = 'illustrious-xl-v2.0-faceid'
VISUALS = [CYBER, ILLUSTRIOUS]


def request(model=ILLUSTRIOUS, **changes):
    from identity_contract import IdentityGenerateRequest
    return IdentityGenerateRequest(**dict(referenceId='ref-'+'a'*24, faceIndex=0,
        prompt='clothed portrait', modelId=model, structureStrength=0., faceLoraStrength=0., **changes))


def bundles(tmp_path):
    config = assets(tmp_path)
    config['allowExperimentalVisualModels'] = True
    adapter = tmp_path/'plus-face.safetensors'
    adapter.write_bytes(b'visual adapter')
    config['models'][CYBER] = {'adapter': str(adapter)}
    return config


@pytest.fixture
def experimental_runtime(visual_service, tmp_path):
    from identity_service import atomic_json
    service, _ = visual_service
    service.config_path = tmp_path/'experimental-runtime.json'
    atomic_json(service.config_path, {'allowExperimentalVisualModels': True})


def test_illustrious_visual_composes_only_explicit_sdxl_assets(tmp_path):
    from identity_models import resolve_identity_model, identity_model_catalog
    config = bundles(tmp_path)
    before = copy.deepcopy(config)
    selected = resolve_identity_model(config, ILLUSTRIOUS)
    assert selected['checkpoint'] == config['models'][FACEID]['checkpoint']
    assert selected['pipelineConfig'] == config['models'][FACEID]['pipelineConfig']
    assert selected['adapter'] == config['models'][CYBER]['adapter']
    assert selected['architecture'] == 'SDXL' and selected['referenceKind'] == 'visual'
    assert selected['faceLora'] == '' and config == before
    rows = {row['id']: row for row in identity_model_catalog(config)}
    assert rows[ILLUSTRIOUS]['ready'] and rows[ILLUSTRIOUS]['referenceKind'] == 'visual'


@pytest.mark.parametrize('bundle,key', [(FACEID,'checkpoint'), (FACEID,'pipelineConfig'), (CYBER,'adapter')])
def test_missing_visual_component_never_inherits_sd15(tmp_path, bundle, key):
    from identity_models import resolve_identity_model
    config = bundles(tmp_path)
    del config['models'][bundle][key]
    with pytest.raises(ValueError, match=key+'|SDXL'):
        resolve_identity_model(config, ILLUSTRIOUS)


@pytest.mark.parametrize('model', VISUALS)
def test_visual_schedule_defaults_and_representative_research(model):
    params = request(model, traceLevel='h7', facePolish=True)
    assert (params.referenceStart, params.referenceEnd) == (0., 1.)
    assert request(model, referenceStart=.25, referenceEnd=.75).referenceEnd == .75
    with pytest.raises(ValueError, match='SDXL'):
        request(model, traceLevel='h7', researchCoverage='extended', width=512, height=512, steps=8)


@pytest.mark.parametrize('start,end', [(-.1,1.), (0.,1.1), (.5,.5), (.9,.1), (float('nan'),1.),
                                     (0.,float('inf')), ('0',1.), (True,1.)])
def test_visual_interval_rejects_invalid_or_coerced_values(start, end):
    # Ensure rejection is about the interval, not an unavailable model/field.
    assert request(CYBER, referenceStart=0., referenceEnd=1.).referenceEnd == 1.
    with pytest.raises(ValueError):
        request(CYBER, referenceStart=start, referenceEnd=end)


def test_faceid_only_accepts_legacy_full_interval():
    params = request(FACEID)
    assert params.referenceStart == 0. and params.referenceEnd == 1.
    assert request(FACEID, referenceStart=0., referenceEnd=1.) == params
    with pytest.raises(ValueError, match='视觉'):
        request(FACEID, referenceStart=.1)


def test_interval_mismatch_rejected_before_batch_model_loading(tmp_path, monkeypatch):
    import identity_pipeline
    from test_identity_batch_worker import make_item
    first = make_item(tmp_path, 0, **request(CYBER, seed=1).model_dump())
    second = make_item(tmp_path, 1, **request(CYBER, seed=2, referenceEnd=.5).model_dump())
    monkeypatch.setattr(identity_pipeline, 'IdentitySession', lambda *a: pytest.fail('loaded incompatible batch'))
    with pytest.raises(ValueError, match='同一'):
        identity_pipeline.generate_batch({}, {'items':[first, second]})


@pytest.mark.parametrize('model', VISUALS)
def test_visual_kind_reaches_service_and_persists_schedule(visual_service, experimental_runtime, model):
    service, boundary = visual_service
    ref = reference(service, 'visual')
    params = request(model, seed=9, referenceStart=.2, referenceEnd=.8)
    params = params.model_copy(update={'referenceId':ref['id']})
    job = service.submit(params)
    service._futures[job['id']].result(timeout=5)
    result = service.get(job['id'])
    assert result['state'] == 'complete', result['error']
    assert result['request']['referenceStart'] == .2
    payload = next(payload for op,payload in boundary.calls if op == 'generate')
    assert payload['modelId'] == model and payload['referenceEnd'] == .8


@pytest.mark.parametrize('model', VISUALS)
@pytest.mark.parametrize('fail', [False, True])
def test_render_applies_interval_and_restores_scale_on_success_or_error(render_case, model, fail):
    import torch
    _, session, item, _, _ = render_case
    item.update(request(model, seed=3, width=256, height=256, steps=4,
                        referenceStart=.25, referenceEnd=.75, identityStrength=.8).model_dump())
    session.architecture = 'SDXL'
    session.pipe.unet.adapter = torch.nn.Module()
    processor = SimpleNamespace(to_k_ip=object(), scale=[.37])
    session.pipe.unet.adapter.processor = processor
    original = processor.scale
    observed = []
    def observe(_module, _args):
        observed.append(processor.scale[0])
        if fail and len(observed) == 3:
            raise RuntimeError('sampling failed')
    handle = session.pipe.unet.register_forward_pre_hook(observe)
    try:
        if fail:
            with pytest.raises(RuntimeError, match='sampling failed'):
                session.render(item, 0, lambda e:None, None, 0)
        else:
            result = session.render(item, 0, lambda e:None, None, 0)
            assert result['metadata']['backend'] == 'diffusers-ipadapter-plus-face-sdxl'
            assert result['metadata']['identity']['referenceStart'] == .25
        assert observed == ([0.,.8,.8] if fail else [0.,.8,.8,0.])
        assert processor.scale is original and original == [.37]
    finally:
        handle.remove()


@pytest.mark.parametrize('model', VISUALS)
@pytest.mark.parametrize('fail', [False, True])
def test_visual_detail_schedule_restores_shared_scales(redraw_case, model, fail):
    import torch
    processor, item, image, calls, control, session, _ = redraw_case
    item.update(modelId=model, identityStrength=.8, referenceStart=.2, referenceEnd=.8)
    session.pipe.unet = torch.nn.Module()
    adapter = SimpleNamespace(to_k_ip=object(), scale=[.37])
    session.pipe.unet.processor = adapter
    original = adapter.scale
    observed = []
    def progress(stage):
        if ' / ' in stage:
            observed.append(adapter.scale[0])
            if fail and len(observed) == 4:
                raise RuntimeError('detail interrupted')
    if fail:
        with pytest.raises(RuntimeError, match='detail interrupted'):
            processor.apply(image, item, 1., progress)
    else:
        _, details = processor.apply(image, item, 1., progress)
        name = 'CyberRealistic XL' if model == CYBER else 'Illustrious XL v2.0'
        assert details['restoreModel'] == name + ' + Plus Face visual reference'
    assert observed == ([0.,0.,.8,.8] if fail else [0.,0.,.8,.8,.8,.8,.8,.8,0.,0.])
    assert adapter.scale is original and original == [.37]


@pytest.mark.parametrize('wrong_model', [False, True])
def test_illustrious_visual_polish_evidence_bound_to_actual_model(redraw_service, experimental_runtime, wrong_model):
    service, control = redraw_service
    ref = reference(service, 'visual')
    def receipt(metadata):
        metadata['model_id'] = ILLUSTRIOUS
        metadata['facePolish']['restoreModel'] = (
            'CyberRealistic XL' if wrong_model else 'Illustrious XL v2.0') + ' + Plus Face visual reference'
    control.damage = receipt
    params = request(seed=8, width=256, height=256, facePolish=True).model_copy(update={'referenceId':ref['id']})
    record = completed(service, params)
    assert record['state'] == ('failed' if wrong_model else 'complete'), record['error']


def observer_pipe():
    """Small real CPU projections and forwards; no synthetic attention maps."""
    import torch
    class Attention(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.to_q = torch.nn.Linear(4,4,bias=False)
            self.to_k = torch.nn.Linear(4,4,bias=False)
            self.to_v = torch.nn.Linear(4,4,bias=False)
            self.heads = 1
        def forward(self, x, context):
            return torch.nn.functional.scaled_dot_product_attention(self.to_q(x), self.to_k(context), self.to_v(context))
    class UNet(torch.nn.Module):
        def __init__(self):
            super().__init__()
            block = torch.nn.Module()
            block.attn1, block.attn2 = Attention(), Attention()
            block.attn2.processor = SimpleNamespace(to_k_ip=object(), scale=[.37])
            self.down_blocks = torch.nn.ModuleList([block])
            self.fail_ablation = False
        def forward(self, sample, timestep, encoder_hidden_states=None):
            block = self.down_blocks[0]
            scale = block.attn2.processor.scale[0]
            if self.fail_ablation and scale == 0.:
                raise RuntimeError('ablation failed')
            x = sample.flatten(2).transpose(1,2)
            x = block.attn1(x,x) + block.attn2(x,encoder_hidden_states)
            result = x.transpose(1,2).reshape_as(sample)
            result = result + torch.tensor([0., scale]).reshape(2,1,1,1)
            return (result,)
    return SimpleNamespace(unet=UNet().eval(), tokenizer=None)


@pytest.mark.parametrize('model', VISUALS)
@pytest.mark.parametrize('fail', [False, True])
def test_visual_observer_measures_same_forward_and_restores_nested_ablation(tmp_path, model, fail):
    import torch
    from identity_pipeline import visual_reference_schedule
    from identity_research import IdentityResearch
    from research_traces import ResearchTraceStore
    pipe = observer_pipe()
    adapter = pipe.unet.down_blocks[0].attn2.processor
    original = adapter.scale
    params = request(model, seed=4, steps=4, width=256, height=256, traceLevel='h7',
                     referenceStart=.25, referenceEnd=.75, identityStrength=.8)
    item = {'dreamRoot':str(tmp_path), 'jobId':'identity-'+'d'*24, 'outputPath':str(tmp_path/'out.png')}
    sample = torch.arange(32.).reshape(2,4,2,2)/32
    text = torch.arange(24.).reshape(2,3,4)/24
    collector = IdentityResearch(pipe, item, params)
    def run():
        with visual_reference_schedule(pipe, params.model_dump()) as advance, collector:
            collector.tokens = [{'slot':1,'tokenId':5,'text':'portrait','chunk':0,'weight':1.}]
            for i in range(4):
                if fail and i == 1:
                    pipe.unet.fail_ablation = True
                actual = pipe.unet(sample, i, encoder_hidden_states=text)[0]
                # Intervention must not replace the returned production sample.
                collector.suspended = True
                expected = pipe.unet(sample, i, encoder_hidden_states=text)[0]
                collector.suspended = False
                assert torch.equal(actual, expected)
                advance(i+1)
    if fail:
        with pytest.raises(RuntimeError, match='ablation failed'):
            run()
    else:
        run()
        result = collector.finish({'generation_time_ms':1, 'model_id':model, 'peakReservedMiB':0})
        assert result['h6'] is True and result['h7'] is True
        root = tmp_path/'traces'/item['jobId']
        influence = json.loads((root/'conditioning-influence.json').read_text(encoding='utf-8'))
        assert influence['method'] == 'visual-reference-ablation-guided'
        assert influence['provenance'] == {'modelId':model, 'referenceKind':'visual',
            'intervention':'ip-adapter-scale-zero', 'attentionSemantics':'conditional-text',
            'referenceImageTokenAttribution':False, 'referenceStart':.25, 'referenceEnd':.75}
        deltas = [s['chunks'][0]['deltaL2'] for s in influence['steps']]
        assert deltas[0] == deltas[3] == 0. and deltas[1] > 0. and deltas[2] > 0.
        cross = json.loads((root/'attention-index.json').read_text(encoding='utf-8'))
        assert cross['provenance'] == influence['provenance']
        store = ResearchTraceStore(tmp_path)
        public = store.influence(item['jobId'])
        assert public['available'] and public['method'] == influence['method']
        assert public['provenance'] == influence['provenance']
        index = store.self_attention_index(item['jobId'])
        assert index['available'] and index['provenance'] == influence['provenance']
        data = store.self_attention_map(item['jobId'], index['maps'][0]['id'])
        assert data['provenance'] == influence['provenance']
        assert sum(data['values']) == pytest.approx(1., abs=1e-6)
    assert adapter.scale is original and original == [.37]
    assert all(not m._forward_hooks and not m._forward_pre_hooks for m in pipe.unet.modules())


@pytest.mark.parametrize('target', ['conditioning-influence.json', 'latent-step-000-ch0.png'])
def test_sidecar_publication_failure_keeps_generated_image(render_case, monkeypatch, target):
    import identity_research
    _, session, item, _, _ = render_case
    session.pipe.unet.processor = SimpleNamespace(to_k_ip=object(), scale=[.82])
    item.update(modelId=CYBER, structureStrength=0., faceLoraStrength=0., traceLevel='h6')
    original = identity_research.write_artifact
    def fail(root, path, data):
        if Path(path).name == target:
            raise OSError('sidecar disk full')
        return original(root,path,data)
    monkeypatch.setattr(identity_research, 'write_artifact', fail)
    result = session.render(item, 0, lambda e:None, None, 0)
    assert Path(item['outputPath']).is_file() and Path(item['metadataPath']).is_file()
    assert result['metadata']['research']['status'] == 'failed'
    assert result['metadata']['research']['h6'] is False


def test_visual_ablation_requires_an_actual_adapter_before_claiming_observations(tmp_path):
    from identity_research import IdentityResearch
    pipe = observer_pipe()
    del pipe.unet.down_blocks[0].attn2.processor
    item = {'dreamRoot':str(tmp_path), 'jobId':'identity-'+'e'*24}
    with pytest.raises(ValueError, match='adapter'):
        with IdentityResearch(pipe, item, request(traceLevel='h6')):
            pytest.fail('visual ablation without an adapter was accepted')
    assert all(not m._forward_hooks and not m._forward_pre_hooks for m in pipe.unet.modules())


def test_artifact_budget_stops_before_crossing_512mib_and_reports_failure(tmp_path):
    from identity_research import IdentityResearch
    collector = IdentityResearch(observer_pipe(), {'dreamRoot':str(tmp_path), 'jobId':'identity-'+'e'*24},
                                 request(traceLevel='h6'))
    collector.directory.mkdir(parents=True)
    collector.bytes_written = 512 * 1024 * 1024 - 2
    collector._write_bytes('last.json', b'{}')
    assert (collector.directory/'last.json').read_bytes() == b'{}'
    collector._write_bytes('too-much.json', b'1')
    assert not (collector.directory/'too-much.json').exists()
    assert collector.bytes_written == 512 * 1024 * 1024
    with pytest.raises(RuntimeError, match='发布失败'):
        collector.finish({})


def test_visual_root_cannot_adopt_historic_faceid_sidecar(tmp_path):
    from research_traces import ResearchTraceStore
    from test_research_traces import INFLUENCE
    run = 'identity-'+'a'*24
    assets = tmp_path/'traces'/run
    assets.mkdir(parents=True)
    raw = copy.deepcopy(INFLUENCE)
    raw.update(source='diffusers-unet', method='identity-ablation-guided', totalChunks=1, capturedChunks=1)
    raw['steps'][0]['chunks'] = raw['steps'][0]['chunks'][:1]
    (assets/'conditioning-influence.json').write_text(json.dumps(raw))
    (assets.parent/(run+'.json')).write_text(json.dumps({'runId':run, 'nodes':[], 'totalTimeMs':1,
        'evidence':{'backend':'diffusers-unet', 'modelId':ILLUSTRIOUS, 'referenceKind':'visual'}}))
    assert ResearchTraceStore(tmp_path).influence(run)['available'] is False


@pytest.mark.parametrize('change', [{'referenceKind':'faceid'}, {'modelId':FACEID},
    {'referenceImageTokenAttribution':True}, {'attentionSemantics':'reference-image'},
    {'referenceStart':.8,'referenceEnd':.2}, {'intervention':'identity-replacement'}])
def test_visual_method_rejects_false_provenance(change):
    from research_traces import validate_influence, InvalidArtifact
    from test_research_traces import INFLUENCE
    raw = copy.deepcopy(INFLUENCE)
    raw.update(source='diffusers-unet', method='visual-reference-ablation-guided', totalChunks=1, capturedChunks=1,
        provenance={'modelId':ILLUSTRIOUS,'referenceKind':'visual','intervention':'ip-adapter-scale-zero',
                    'attentionSemantics':'conditional-text','referenceImageTokenAttribution':False,
                    'referenceStart':0.,'referenceEnd':1.})
    raw['steps'][0]['chunks'] = raw['steps'][0]['chunks'][:1]
    assert validate_influence(raw)['method'] == 'visual-reference-ablation-guided'
    raw['provenance'].update(change)
    with pytest.raises(InvalidArtifact):
        validate_influence(raw)
