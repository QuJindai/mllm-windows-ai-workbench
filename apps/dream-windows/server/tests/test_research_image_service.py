import hashlib
import importlib
import importlib.util
import json
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from identity_service import IdentityService
from job_runner import JobRunner
from research_fusion import digest, MODES
from config import DreamServerConfig


def module():
    assert importlib.util.find_spec('research_image_service'), 'Shared-queue fusion image service missing'
    return importlib.import_module('research_image_service')


def assets(root):
    checkpoint = root/'rv.safetensors'; checkpoint.write_bytes(b'fixture checkpoint')
    pipeline = root/'sd15'
    for name in ('model_index.json','scheduler/scheduler_config.json','text_encoder/config.json','unet/config.json',
                 'vae/config.json','tokenizer/tokenizer_config.json','tokenizer/special_tokens_map.json','tokenizer/vocab.json','tokenizer/merges.txt'):
        path=pipeline/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text('{}')
    (pipeline/'unet/config.json').write_text(json.dumps({'cross_attention_dim':768,'in_channels':4}))
    return {'checkpoint': str(checkpoint), 'pipelineConfig': str(pipeline)}


def worker_result(payload):
    variants=[]
    for mode,path in payload['outputPaths'].items():
        path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
        Image.new('RGB',(payload['settings']['width'],payload['settings']['height']),'navy').save(path)
        variants.append({'mode':mode,'imageSha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                         'effectiveWeights':[1.], 'durationMs':1})
    return {'contractVersion':'diffusers-chunk-fusion-images-v1','jobId':payload['jobId'],
            'settingsSha256':digest(payload['settings']), 'variants':variants,
            'provenance':{'engine':'diffusers-sd15-paired-chunk-cfg','modelSha256':'a'*64,
                          'pipelineConfigSha256':digest(payload['assetBinding']['files']),'initialLatentSha256':'c'*64,
                          'assetBinding':payload['assetBinding'],'scheduler':'EulerDiscreteScheduler',
                          'predictionType':'epsilon','chunkCounts':[{'positive':1,'negative':0}],
                          'settings':payload['settings'],'engineRevision':'d'*64,
                          'torchVersion':'test-cpu','diffusersVersion':'boundary-fixture',
                          'nativeDeviceParity':False,'negativeEncodingPerformed':payload['settings']['cfg']!=1,
                          'encodedTokenIds':[{'positive':[1]*77,'negative':[2]*77}]}}


@pytest.fixture
def harness(tmp_path, monkeypatch):
    dream_root=tmp_path/'Dream'; dream_root.mkdir()
    config=DreamServerConfig(repo_root=tmp_path,dream_root=dream_root,core_exe=tmp_path/'unused-core',
        engine_exe=tmp_path/'unused-engine',wrapper=tmp_path/'unused-wrapper',
        registry_path=tmp_path/'unused-registry',frontend_dist=tmp_path/'unused-dist')
    runtime_path=tmp_path/'identity-runtime.json'
    runtime_path.write_text(json.dumps(assets(tmp_path)))
    monkeypatch.setenv('DREAM_IDENTITY_CONFIG',str(runtime_path))
    runner=JobRunner(config)
    order=[]
    runner.release_native_for_identity=lambda: order.append('release-native')
    service=IdentityService(config,runner)
    release,started=threading.Event(),threading.Event()
    release.set()
    def worker(operation,payload,event):
        order.append(operation); started.set()
        while not release.wait(.01):
            if event.is_set(): raise RuntimeError('cancelled')
        if event.is_set(): raise RuntimeError('cancelled')
        return worker_result(payload)
    monkeypatch.setattr(service,'_run_worker',worker)
    research=module().ResearchImageService(service)
    yield research,service,runner,order,release,started
    release.set(); service.close(); runner._executor.shutdown(wait=True,cancel_futures=True)


def settings(**changes):
    return module().FusionImageRequest(prompt='long prompt', seed=42, steps=2, width=256,height=256,
                                       requestId='test-request-id-0001',**changes)


def terminal(research,job):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        row=research.operation('get',job)
        if row['state'] in ('complete','failed','cancelled'): return row
        time.sleep(.01)
    pytest.fail('research job did not settle')


def test_submission_is_nonblocking_uses_existing_serial_queue_and_releases_native(harness):
    research,service,runner,order,release,started=harness
    release.clear()
    row=research.operation('submit',settings())
    assert row['state']=='queued' and row['id'] in service._background
    assert started.wait(2)
    assert order == ['release-native','fusion']
    assert research.operation('get',row['id'])['state']=='running'
    # The same executor cannot run another native/identity operation concurrently.
    later=runner.submit_serial(lambda: order.append('later-native'))
    assert not later.done()
    release.set()
    done=terminal(research,row['id']); later.result(2)
    assert done['state']=='complete',done
    assert len(done['result']['variants'])==4
    assert order[-1]=='later-native'
    assert done['result']['provenance']['engine']=='diffusers-sd15-paired-chunk-cfg'
    for variant in done['result']['variants']:
        assert research.operation('image',row['id'],variant['mode']).is_file()


def test_duplicate_request_returns_same_record_and_changed_request_conflicts(harness):
    research,*_=harness
    a=research.operation('submit',settings())
    b=research.operation('submit',settings())
    assert a['id']==b['id']
    from errors import DreamApiError
    with pytest.raises(DreamApiError) as error:
        research.operation('submit',settings(cfg=7.))
    assert error.value.status_code==409
    assert terminal(research,a['id'])['state']=='complete'


def test_cancel_running_uses_shared_event_and_never_publishes_an_image(harness):
    research,service,_,_,release,started=harness
    release.clear()
    row=research.operation('submit',settings())
    assert started.wait(2)
    cancelled=research.operation('cancel',row['id'])
    assert cancelled['state'] in ('cancelling','cancelled')
    assert service._background[row['id']][1].is_set()
    done=terminal(research,row['id'])
    assert done['state']=='cancelled' and done['result'] is None
    from errors import DreamApiError
    with pytest.raises(DreamApiError): research.operation('image',row['id'],'equal_mean')


def test_queued_cancel_does_not_start_worker(harness):
    research,service,runner,order,release,_=harness
    blocker=threading.Event()
    running=runner.submit_serial(lambda: blocker.wait(3))
    row=research.operation('submit',settings())
    assert research.operation('cancel',row['id'])['state']=='cancelled'
    blocker.set(); running.result(2)
    assert order==[]


def test_config_changed_after_acceptance_fails_before_native_release(harness):
    research,service,runner,order,_,_=harness
    blocker=threading.Event(); running=runner.submit_serial(lambda:blocker.wait(3))
    row=research.operation('submit',settings())
    config=json.loads(service.config_path.read_text()); Path(config['checkpoint']).write_bytes(b'changed')
    blocker.set();running.result(2)
    assert terminal(research,row['id'])['state']=='failed'
    assert order==[]


def test_bad_worker_provenance_and_tampered_result_are_rejected(harness,monkeypatch):
    research,service,_,_,_,_=harness
    def bad(operation,payload,event):
        result=worker_result(payload); result['jobId']='different'; return result
    monkeypatch.setattr(service,'_run_worker',bad)
    row=research.operation('submit',settings())
    assert terminal(research,row['id'])['state']=='failed'
    monkeypatch.setattr(service,'_run_worker',lambda op,p,e:worker_result(p))
    good=research.operation('submit',module().FusionImageRequest(prompt='x',seed=1,steps=1,width=256,height=256,requestId='another-request-0001'))
    assert terminal(research,good['id'])['state']=='complete'
    path=research.operation('image',good['id'],'first_only'); path.write_bytes(b'tampered')
    from errors import DreamApiError
    with pytest.raises(DreamApiError): research.operation('image',good['id'],'first_only')


@pytest.mark.parametrize('changes',[{'steps':31},{'width':1024},{'width':300},{'cfg':float('nan')},
                                   {'modelId':'unknown'},{'outputPath':'E:/other.png'}])
def test_request_refuses_unbounded_compute_and_caller_paths(changes):
    with pytest.raises(ValueError): module().FusionImageRequest(prompt='x',requestId='valid-request-0001',**changes)


@pytest.mark.parametrize('corruption',['weights','native-parity','encoded-ids','negative-skipped'])
def test_incompatible_fusion_provenance_is_not_published(harness,monkeypatch,corruption):
    research,service,*_=harness
    def bad(op,payload,event):
        result=worker_result(payload); provenance=result['provenance']
        if corruption=='weights':
            provenance['chunkCounts']*=2; provenance['encodedTokenIds']*=2
            for variant in result['variants']: variant['effectiveWeights']=[.5,.5]
        elif corruption=='native-parity': provenance['nativeDeviceParity']=True
        elif corruption=='encoded-ids': provenance.pop('encodedTokenIds')
        else: provenance['negativeEncodingPerformed']=False
        return result
    monkeypatch.setattr(service,'_run_worker',bad)
    row=research.operation('submit',settings())
    done=terminal(research,row['id'])
    assert done['state']=='failed' and done['result'] is None
    assert not list(research.path(row['id']).parent.glob('*.png'))


def test_saved_result_with_missing_provenance_is_rejected_on_read(harness):
    research,*_=harness
    row=research.operation('submit',settings())
    assert terminal(research,row['id'])['state']=='complete'
    path=research.path(row['id']); value=json.loads(path.read_text(encoding='utf-8'))
    value['result']['provenance'].pop('modelSha256')
    path.write_text(json.dumps(value),encoding='utf-8')
    from errors import DreamApiError
    with pytest.raises(DreamApiError): research.operation('get',row['id'])


def test_cancellation_after_worker_output_prevents_publication(harness,monkeypatch):
    research,service,*_=harness
    def worker(op,payload,event):
        result=worker_result(payload); event.set(); return result
    monkeypatch.setattr(service,'_run_worker',worker)
    row=research.operation('submit',settings())
    assert terminal(research,row['id'])['state']=='cancelled'
    assert not list(research.path(row['id']).parent.glob('*.png'))


def test_existing_service_close_cancels_fusion_before_releasing_storage(harness):
    research,service,_,_,release,started=harness
    release.clear()
    row=research.operation('submit',settings())
    assert started.wait(2)
    service.close()
    assert service._closed and service._background[row['id']][0].done()
    saved=json.loads(research.path(row['id']).read_text(encoding='utf-8'))
    assert saved['state']=='cancelled' and saved['result'] is None


def test_record_capacity_rejects_new_work_but_allows_idempotent_readback(harness,monkeypatch):
    research,*_=harness
    monkeypatch.setattr(module(),'MAX_RECORDS',1)
    row=research.operation('submit',settings())
    assert terminal(research,row['id'])['state']=='complete'
    assert research.operation('submit',settings())['id']==row['id']
    from errors import DreamApiError
    with pytest.raises(DreamApiError):
        research.operation('submit',module().FusionImageRequest(prompt='x',requestId='different-request-0001'))


@pytest.mark.parametrize('damage',['json','provenance','state'])
def test_corrupt_old_record_does_not_block_healthy_retry_or_new_job(harness,damage):
    research,*_=harness
    bad=research.operation('submit',settings())
    assert terminal(research,bad['id'])['state']=='complete'
    healthy_settings=module().FusionImageRequest(prompt='healthy',requestId='healthy-request-0001')
    healthy=research.operation('submit',healthy_settings)
    assert terminal(research,healthy['id'])['state']=='complete'
    path=research.path(bad['id'])
    if damage=='json': path.write_text('{',encoding='utf-8')
    else:
        raw=json.loads(path.read_text(encoding='utf-8'))
        if damage=='state': raw['state']=[]
        else: raw['result']['provenance'].pop('modelSha256')
        path.write_text(json.dumps(raw),encoding='utf-8')
    unchanged=path.read_bytes()
    assert research.operation('submit',healthy_settings)['id']==healthy['id']
    new=research.operation('submit',module().FusionImageRequest(prompt='new',requestId='brand-new-request-0001'))
    assert terminal(research,new['id'])['state']=='complete'
    assert path.read_bytes()==unchanged
    from errors import DreamApiError
    with pytest.raises(DreamApiError): research.operation('get',bad['id'])
    if damage!='json':
        with pytest.raises(DreamApiError): research.operation('submit',settings())


@pytest.mark.parametrize('damage',['json','missing'])
def test_corrupt_and_missing_records_still_count_toward_capacity(harness,monkeypatch,damage):
    research,*_=harness
    bad=research.operation('submit',settings())
    assert terminal(research,bad['id'])['state']=='complete'
    healthy_settings=module().FusionImageRequest(prompt='healthy',requestId='healthy-request-0001')
    healthy=research.operation('submit',healthy_settings)
    assert terminal(research,healthy['id'])['state']=='complete'
    path=research.path(bad['id'])
    if damage=='missing': path.unlink()
    else: path.write_text('{',encoding='utf-8')
    monkeypatch.setattr(module(),'MAX_RECORDS',2)
    assert research.operation('submit',healthy_settings)['id']==healthy['id']
    from errors import DreamApiError
    with pytest.raises(DreamApiError) as error:
        research.operation('submit',module().FusionImageRequest(prompt='new',requestId='brand-new-request-0001'))
    assert error.value.status_code==409


@pytest.mark.parametrize('damage',['json','missing','forged-terminal'])
def test_active_registry_blocks_new_work_even_when_its_record_is_unusable(harness,damage):
    research,service,_,order,release,started=harness
    release.clear()
    active=research.operation('submit',settings())
    assert started.wait(2)
    path=research.path(active['id']); original=path.read_bytes()
    if damage=='missing': path.unlink()
    elif damage=='json': path.write_text('{',encoding='utf-8')
    else:
        row=json.loads(original); row.update(state='failed',result=None)
        path.write_text(json.dumps(row),encoding='utf-8')
    from errors import DreamApiError
    try:
        with pytest.raises(DreamApiError) as error:
            research.operation('submit',module().FusionImageRequest(prompt='new',requestId='brand-new-request-0001'))
        assert error.value.status_code==409
        assert order==['release-native','fusion']
    finally:
        path.write_bytes(original); release.set()
    assert terminal(research,active['id'])['state']=='complete'
