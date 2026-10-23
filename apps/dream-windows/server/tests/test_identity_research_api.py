import copy
import json

from fastapi.testclient import TestClient
from app import create_app
from runtime import DreamRuntime
from test_generation_jobs import make_config
from test_research_traces import INFLUENCE, SELF_INDEX, SELF_MAP


def test_identity_observations_retain_provenance_and_nonzero_ablation(tmp_path):
    config = make_config(tmp_path)
    root = config.dream_root/'traces'
    run = 'identity-'+'a'*24
    assets = root/run
    assets.mkdir(parents=True)
    (root/f'{run}.json').write_text(json.dumps({'runId': run, 'totalTimeMs': 10, 'nodes': [], 'evidence': {'backend': 'diffusers-unet'}}))
    influence = copy.deepcopy(INFLUENCE)
    influence.update(source='diffusers-unet', method='identity-ablation-guided', totalChunks=1, capturedChunks=1)
    influence['steps'][0]['chunks'] = influence['steps'][0]['chunks'][:1]
    (assets/'conditioning-influence.json').write_text(json.dumps(influence))
    index, sample = copy.deepcopy(SELF_INDEX), copy.deepcopy(SELF_MAP)
    index['source'] = sample['source'] = 'diffusers-unet'
    (assets/'self-attention-index.json').write_text(json.dumps(index))
    (assets/index['maps'][0]['fileName']).write_text(json.dumps(sample))
    cross = {**index, 'contractVersion':'h7-attention-v1','kind':'cross-attention',
             'tokens':[{'slot':1,'tokenId':123,'text':'portrait','chunk':0,'weight':1}],
             'maps':[{k:v for k,v in index['maps'][0].items() if k not in ('queryIndex','queryX','queryY')}]}
    cross['maps'][0].update(tokenSlot=1, fileName='attention-one.json')
    (assets/'attention-index.json').write_text(json.dumps(cross))
    (assets/'attention-one.json').write_text(json.dumps({k:v for k,v in {**cross, **cross['maps'][0], 'values':[.25]*4}.items() if k not in ('tokens','maps','layers','fileName')}))
    runtime = DreamRuntime(config)
    with TestClient(create_app(config=config, runtime=runtime)) as client:
        response = client.get(f'/api/traces/{run}/influence').json()
        assert response['available'] is True
        assert response['source'] == 'diffusers-unet'
        assert response['method'] == 'identity-ablation-guided'
        assert response['steps'][0]['chunks'][0]['deltaL2'] == .2
        for route in ('self-attention','attention'):
            observed = client.get(f'/api/traces/{run}/{route}').json()
            assert observed['available'] is True
            assert observed['source'] == 'diffusers-unet'
            result = client.get(observed['maps'][0]['mapUrl'])
            assert result.status_code == 200
            assert result.json()['source'] == 'diffusers-unet'
            assert result.json()['values'] == [.25]*4
        # A valid document padded beyond the index allocation limit must fail
        # closed before parsing, even though all descriptor counts are valid.
        (assets/'attention-index.json').write_text(json.dumps(cross) + ' '*(8*1024*1024))
        assert client.get(f'/api/traces/{run}/attention').json()['available'] is False


def test_identity_extended_self_index_accepts_multiple_layers_in_one_stage():
    from research_traces import validate_self_index
    raw = copy.deepcopy(SELF_INDEX)
    raw['source'] = 'diffusers-unet'
    raw['layers'].append({'id':'down-2','stage':'down','label':'Down2'})
    raw['maps'].append({**raw['maps'][0], 'id':'second', 'layerId':'down-2','fileName':'self-attention-second.json'})
    assert len(validate_self_index(raw)['layers']) == 2
