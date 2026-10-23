"""Cross-attention provenance at the real HTTP/file boundary; no model loads."""
import copy
import json

import pytest
from fastapi.testclient import TestClient

from app import create_app
from runtime import DreamRuntime
from test_generation_jobs import make_config


RUN = 'identity-'+'a'*24
CYBER = 'cyberrealistic-xl-plus-face'
ILLUSTRIOUS = 'illustrious-xl-v2.0-plus-face'
FACEID = 'illustrious-xl-v2.0-faceid'
PROVENANCE = {'modelId': ILLUSTRIOUS, 'referenceKind': 'visual',
    'intervention': 'ip-adapter-scale-zero', 'attentionSemantics': 'conditional-text',
    'referenceImageTokenAttribution': False, 'referenceStart': .2, 'referenceEnd': .8}


@pytest.fixture
def capture(tmp_path):
    config = make_config(tmp_path)
    folder = config.dream_root/'traces'/RUN
    folder.mkdir(parents=True)
    marker = {'contractVersion': 'h7-attention-v1', 'kind': 'cross-attention',
              'truth': 'observed', 'source': 'diffusers-unet', 'provenance': copy.deepcopy(PROVENANCE)}
    descriptor = {'id':'cross-0', 'step':0, 'layerId':'down-1', 'tokenSlot':1,
                  'width':2, 'height':2, 'entropy':1., 'peak':.25, 'coverage':1.}
    documents = {
        'root': {'runId':RUN, 'totalTimeMs':1, 'nodes':[], 'provenance':copy.deepcopy(PROVENANCE),
                 'evidence':{'backend':'diffusers-unet', 'modelId':ILLUSTRIOUS, 'referenceKind':'visual'}},
        'index': {**copy.deepcopy(marker), 'tokens':[{'slot':1,'tokenId':100,'text':'portrait','chunk':0,'weight':1.}],
                  'layers':[{'id':'down-1','stage':'down','label':'Down 1'}],
                  'maps':[{**descriptor, 'fileName':'attention-cross-0.json'}]},
        'map': {**copy.deepcopy(marker), **descriptor, 'values':[.25]*4},
    }
    def save():
        for key, path in [('root',folder.parent/(RUN+'.json')), ('index',folder/'attention-index.json'),
                          ('map',folder/'attention-cross-0.json')]:
            path.write_text(json.dumps(documents[key]), encoding='utf-8')
    save()
    with TestClient(create_app(config, DreamRuntime(config))) as client:
        yield client, documents, save


@pytest.mark.parametrize('model', [CYBER, ILLUSTRIOUS, FACEID])
@pytest.mark.parametrize('selected', [RUN, 'latest'])
def test_cross_attention_preserves_validated_provenance_and_strips_private_fields(capture, model, selected):
    client, documents, save = capture
    expected = {**PROVENANCE, 'modelId':model}
    if model == FACEID:
        expected.update(referenceKind='faceid', referenceStart=0., referenceEnd=1.)
    for value in documents.values():
        value['provenance'] = copy.deepcopy(expected)
    documents['root']['evidence'].update(modelId=model, referenceKind=expected['referenceKind'])
    for key in ('index','map'):
        documents[key]['provenance']['privatePath'] = 'private-asset-path'
    save()
    response = client.get(f'/api/traces/{selected}/attention')
    assert response.status_code == 200
    result = response.json()
    assert result['available'] and result['provenance'] == expected
    assert result['runId'] == RUN and 'private-asset-path' not in response.text
    mapped = client.get(result['maps'][0]['mapUrl'])
    assert mapped.status_code == 200 and mapped.json()['values'] == [.25]*4
    assert mapped.json()['provenance'] == expected and 'private-asset-path' not in mapped.text


@pytest.mark.parametrize('selected', [RUN, 'latest'])
@pytest.mark.parametrize('damage', ['missing-index', 'null-index', 'invalid-index', 'false-image-attribution',
    'wrong-attention-semantics', 'wrong-model-kind', 'wrong-root-model', 'wrong-root-kind', 'wrong-root-interval',
    'missing-root', 'numeric-root-attribution', 'missing-backend', 'native-index', 'invalid-source', 'wrong-run'])
def test_cross_attention_rejects_unbound_or_false_visual_provenance(capture, selected, damage):
    client, documents, save = capture
    root, index = documents['root'], documents['index']
    if damage == 'missing-index': index.pop('provenance')
    elif damage == 'null-index': index['provenance'] = None
    elif damage == 'invalid-index': index['provenance'] = []
    elif damage == 'false-image-attribution': index['provenance']['referenceImageTokenAttribution'] = True
    elif damage == 'wrong-attention-semantics': index['provenance']['attentionSemantics'] = 'reference-image'
    elif damage == 'wrong-model-kind': index['provenance']['modelId'] = FACEID
    elif damage == 'wrong-root-model': root['evidence']['modelId'] = CYBER
    elif damage == 'wrong-root-kind': root['evidence']['referenceKind'] = 'faceid'
    elif damage == 'wrong-root-interval': root['provenance']['referenceStart'] = .1
    elif damage == 'missing-root': root.pop('provenance')
    elif damage == 'numeric-root-attribution': root['provenance']['referenceImageTokenAttribution'] = 0
    elif damage == 'missing-backend': root['evidence'].pop('backend')
    elif damage == 'native-index':
        index['source'] = 'debug-unet'
        index.pop('provenance')
    elif damage == 'invalid-source': index['source'] = []
    elif damage == 'wrong-run': root['runId'] = 'another-run'
    save()
    response = client.get(f'/api/traces/{selected}/attention')
    assert response.status_code == 200 and response.json()['available'] is False
    assert response.json()['truth'] == 'unavailable'
    assert client.get(f'/api/traces/{selected}/attention/maps/cross-0').status_code == 404
    listing = client.get('/api/traces')
    assert listing.status_code == 200 and listing.json()[0]['hasAttention'] is False


@pytest.mark.parametrize('damage', ['missing', 'null', 'different-model', 'different-interval',
    'false-image-attribution', 'invalid-source'])
def test_cross_attention_map_must_match_index_provenance(capture, damage):
    client, documents, save = capture
    sample = documents['map']
    if damage == 'missing': sample.pop('provenance')
    elif damage == 'null': sample['provenance'] = None
    elif damage == 'different-model': sample['provenance']['modelId'] = CYBER
    elif damage == 'different-interval': sample['provenance']['referenceStart'] = .1
    elif damage == 'false-image-attribution': sample['provenance']['referenceImageTokenAttribution'] = True
    elif damage == 'invalid-source': sample['source'] = []
    save()
    index = client.get(f'/api/traces/{RUN}/attention').json()
    assert index['available'] is True
    result = client.get(index['maps'][0]['mapUrl'])
    assert result.status_code == 422 and result.json()['code'] == 'ATTENTION_MAP_INVALID'


@pytest.mark.parametrize('source', ['debug-unet', 'diffusers-unet'])
def test_historic_native_and_faceid_cross_attention_remain_readable(capture, source):
    client, documents, save = capture
    for value in documents.values():
        value.pop('provenance')
    documents['root']['evidence'] = {'backend':source}
    documents['index']['source'] = documents['map']['source'] = source
    save()
    result = client.get(f'/api/traces/{RUN}/attention').json()
    assert result['available'] and result['source'] == source and 'provenance' not in result
    sample = client.get(result['maps'][0]['mapUrl']).json()
    assert sample['values'] == [.25]*4 and 'provenance' not in sample


def test_modern_faceid_root_cannot_silently_drop_provenance(capture):
    client, documents, save = capture
    for value in documents.values():
        value['provenance'].update(modelId=FACEID, referenceKind='faceid', referenceStart=0., referenceEnd=1.)
    documents['root']['evidence'].update(modelId=FACEID, referenceKind='faceid')
    documents['index'].pop('provenance')
    save()
    assert client.get(f'/api/traces/{RUN}/attention').json()['available'] is False


@pytest.mark.parametrize('model', [CYBER, ILLUSTRIOUS])
def test_actual_cpu_observer_cross_attention_roundtrips_through_runtime(tmp_path, model):
    import torch
    from identity_research import IdentityResearch
    from test_identity_visual_upgrade import observer_pipe, request
    config = make_config(tmp_path)
    pipe = observer_pipe()
    params = request(model, traceLevel='h7', width=256, height=256, steps=1)
    item = {'dreamRoot':str(config.dream_root), 'jobId':RUN, 'outputPath':str(config.dream_root/'out.png')}
    with IdentityResearch(pipe, item, params) as collector:
        collector.tokens = [{'slot':1,'tokenId':100,'text':'portrait','chunk':0,'weight':1.}]
        pipe.unet(torch.arange(32.).reshape(2,4,2,2)/32, 0,
                  encoder_hidden_states=torch.arange(24.).reshape(2,3,4)/24)
    evidence = collector.finish({'generation_time_ms':1,'model_id':model,'peakReservedMiB':0})
    with TestClient(create_app(config, DreamRuntime(config))) as client:
        index = client.get(f'/api/traces/{RUN}/attention').json()
        assert index['available'] and index['provenance'] == evidence['provenance']
        sample = client.get(index['maps'][0]['mapUrl']).json()
        assert sample['provenance'] == evidence['provenance']
        saved = json.loads((config.dream_root/'traces'/RUN/collector.cross_maps[0]['fileName']).read_text())
        assert sample['values'] == saved['values']
