import hashlib
import json
import time
from pathlib import Path

import pytest

from test_identity_profiles import profile_harness, create_profile, wait_profile
from test_identity_api import harness, upload, submit, finished


@pytest.fixture
def anime_harness(profile_harness, monkeypatch):
    import identity_service
    original = identity_service.IdentityService._worker
    def worker(self, operation, payload, cancelled=None):
        if operation=='batch' and payload['items'][0].get('animeProfileId'):
            for item in payload['items']: worker(self,'generate',item,cancelled)
            return {'ok':True,'items':[{'jobId':item['jobId']} for item in payload['items']]}
        if operation == 'generate' and payload.get('animeProfileId'):
            from PIL import Image
            from identity_face_polish import save_original
            image=Image.linear_gradient('L').resize((payload['width'],payload['height'])).convert('RGB')
            save_original(image,payload)
            image.save(payload['outputPath'])
            Path(payload['metadataPath']).write_text(json.dumps({'facePolish':{'enabled':True,'status':'completed',
                'originalImageUrl':f"/api/identity/jobs/{payload['jobId']}/original",'method':'anime-reference-local-redraw',
                'profileId':payload['animeProfileId'],'profileName':payload['animeProfile']['name'],
                'featureKey':payload['animeProfile']['featureKey'],'faceBox':[10.,10.,100.,100.],
                'cropBox':[0,0,120,120],'denoiseStrength':payload['animeDenoiseStrength'],'outsideMaskUnchanged':True}}))
            return {'ok':True}
        if operation != 'anime_prepare':
            return original(self, operation, payload, cancelled)
        # Only the inference boundary is replaced. Routes, queue and storage are real.
        path = Path(payload['animeFeaturesPath'])
        path.write_bytes(b'test-feature-boundary')
        return {'ok':True, 'featureKey':hashlib.sha256(path.read_bytes()).hexdigest(),
                'faceBox':[10.,10.,100.,100.], 'parentFeatureKey':'a'*64}
    monkeypatch.setattr(identity_service.IdentityService, '_worker', worker)
    yield profile_harness


def source_pair(client, **values):
    ref = upload(client)
    parent = wait_profile(client, create_profile(client, ref)['id'])
    job = finished(client, submit(client, ref, modelId='illustrious-xl-v2.0-faceid', **values)['id'])
    return parent, job


def create_anime(client, parent, job):
    return client.post('/api/identity/anime-profiles', json={'name':'Example-动漫','profileId':parent['id'],'jobId':job['id']})


def wait_anime(client, anime_id):
    for _ in range(300):
        records = client.get('/api/identity/anime-profiles').json()
        row = next(p for p in records if p['id']==anime_id)
        if row['state'] != 'preparing': return row
        time.sleep(.01)
    pytest.fail('anime preparation timed out')


def test_anime_archive_is_separate_and_survives_source_deletion(anime_harness):
    client,config,_,_=anime_harness
    parent,job=source_pair(client)
    before=(config.dream_root/'data/identity/profiles'/f"{parent['id']}.json").read_bytes()
    response=create_anime(client,parent,job)
    assert response.status_code==200,response.text
    anime=wait_anime(client,response.json()['id'])
    assert anime['state']=='ready' and anime['name']=='Example-动漫'
    assert not any('Path' in key for key in anime)
    assert client.get(anime['imageUrl']).status_code==200
    # Simulate the source being removed later: profile owns its copy.
    Path(job['result']['metadata']['output']).unlink()
    assert client.get(anime['imageUrl']).status_code==200
    assert before==(config.dream_root/'data/identity/profiles'/f"{parent['id']}.json").read_bytes()
    assert create_anime(client,parent,job).status_code==409


def test_anime_rejects_other_person_deleted_source_and_unready_profile(anime_harness):
    client,_,_,_=anime_harness
    parent,job=source_pair(client)
    other=wait_profile(client,create_profile(client)['id'])
    assert create_anime(client,other,job).status_code==409
    Path(job['result']['metadata']['output']).unlink()
    assert create_anime(client,parent,job).status_code==409


def test_anime_request_rejects_missing_or_wrong_reference_before_queue(anime_harness):
    client,_,_,_=anime_harness
    parent,job=source_pair(client)
    request={**job['request'],'facePolish':True,'animeProfileId':'anime-'+'f'*24}
    assert client.post('/api/identity/generate',json=request).status_code==404
    response=create_anime(client,parent,job)
    anime=wait_anime(client,response.json()['id'])
    request.update(animeProfileId=anime['id'],faceIndex=0)
    assert client.post('/api/identity/generate',json=request).status_code==409
    assert client.post('/api/identity/batches',json={'request':request,'count':1,'previewEvery':0}).status_code==409


def test_anime_private_worker_binding_and_metadata_roundtrip(anime_harness):
    client,config,_,_=anime_harness
    parent,job=source_pair(client)
    anime=wait_anime(client,create_anime(client,parent,job).json()['id'])
    response=client.post('/api/identity/generate',json={**job['request'],'facePolish':True,'animeProfileId':anime['id'],'animeDenoiseStrength':.4})
    assert response.status_code==200,response.text
    final=finished(client,response.json()['id'])
    assert final['state']=='complete', final['error']
    assert 'animeProfile' not in final['request'] and 'animeFeaturesPath' not in final['request']
    info=final['result']['metadata']['facePolish']
    assert info['profileName']=='Example-动漫' and info['denoiseStrength']==.4 and info['outsideMaskUnchanged']
    assert client.get(info['originalImageUrl']).status_code==200
    assert client.get(final['result']['imageUrl']).status_code==200
    path=config.dream_root/'data/identity/anime-profiles'/f"{anime['id']}.safetensors"
    path.write_bytes(b'corrupted')
    assert client.post('/api/identity/generate',json=final['request']).status_code==409


@pytest.mark.parametrize('field,value',[('featureKey','f'*64),('profileName','Wrong person')])
@pytest.mark.parametrize('operation',['generate','batch'])
def test_anime_completion_rejects_wrong_dispatched_provenance(anime_harness,monkeypatch,field,value,operation):
    import identity_service
    client,_,_,_=anime_harness
    parent,job=source_pair(client)
    anime=wait_anime(client,create_anime(client,parent,job).json()['id'])
    original=identity_service.IdentityService._worker
    def corrupt(self,op,payload,cancelled=None):
        result=original(self,op,payload,cancelled)
        if op==operation:
            for item in payload.get('items',[payload]):
                path=Path(item['metadataPath']);info=json.loads(path.read_text())
                info['facePolish'][field]=value
                path.write_text(json.dumps(info))
        return result
    monkeypatch.setattr(identity_service.IdentityService,'_worker',corrupt)
    request={**job['request'],'facePolish':True,'animeProfileId':anime['id']}
    if operation=='generate':
        response=client.post('/api/identity/generate',json=request)
        final=finished(client,response.json()['id'])
    else:
        response=client.post('/api/identity/batches',json={'request':request,'count':1,'previewEvery':0})
        for _ in range(300):
            final=client.get('/api/identity/batches/'+response.json()['id']).json()
            if final['state'] in ('failed','complete','cancelled'):break
            time.sleep(.01)
    assert final['state']=='failed'


@pytest.mark.parametrize('invalid',[{'faceBox':[0.,0.,float('nan'),50.]},{'featureKey':None},{'faceBox':None},{'faceBox':[100.,0.,50.,50.]}])
def test_corrupt_anime_record_is_isolated_on_recovery(anime_harness,invalid):
    from identity_anime_profiles import AnimeProfiles
    from identity_service import IdentityService
    client,config,runner,_=anime_harness
    parent,job=source_pair(client)
    anime=wait_anime(client,create_anime(client,parent,job).json()['id'])
    path=config.dream_root/'data/identity/anime-profiles'/f"{anime['id']}.json"
    record=json.loads(path.read_text());record.update(id='anime-'+'e'*24,**invalid)
    corrupt=path.with_name(record['id']+'.json');corrupt.write_text(json.dumps(record))
    library=AnimeProfiles(IdentityService(config,runner))
    library.recover()
    assert [p['id'] for p in library.list()]==[anime['id']]
    assert corrupt.exists()
