import threading

import pytest
from errors import DreamApiError
from hq_repair_version import VERSION
from test_hq_service import hq, complete
import hq_paired_depth


def test_version_request_is_idempotent_and_preserves_base(hq,monkeypatch):
    service=hq.service; first,_=service.create_job(hq.payload)
    parent=complete(hq,first['id'])
    record=service._jobs[parent['id']]
    # Install a synthetic completed paired-depth ledger at the worker seam;
    # the legacy fixture deliberately only implements OpenPose generation.
    record['pipeline']=hq_paired_depth.PIPELINE;record['autoRepairEnabled']=False
    source=record['result']['sha256']; calls=[]; started=threading.Event(); release=threading.Event()
    manifest={role:{'sha256':source} for role in ('photo','depth','pose','garment')}
    monkeypatch.setattr(service,'_repair_manifest',lambda r,f:(manifest,f/'manifest.json'))
    def work(op,payload,stop):
        calls.append(op);started.set();assert release.wait(5)
        return {'version':VERSION,'state':'unchanged','regions':[],'changedPixels':0,
                'sourceHashes':{k:source for k in manifest}}
    monkeypatch.setattr(service.identity,'_worker',work)
    assert service.request_repair(parent['id'])['bodyRepair']['state']=='queued'
    assert started.wait(5)
    future=service._repair_futures[parent['id']]
    try:assert service.request_repair(parent['id'])['bodyRepair']['state']=='running'
    finally:release.set()
    future.result(timeout=5)
    job=service.request_repair(parent['id'])
    assert calls==['hq_body_repair'] and job['bodyRepairCurrent']
    assert job['bodyRepair']['state']=='unchanged' and job['outputSha256']==source
    with pytest.raises(DreamApiError) as err:service.repair_image(parent['id'],'result')
    assert err.value.status_code==404


def test_old_request_digest_and_disabled_preference_do_not_resubmit(hq):
    job,reused=hq.service.create_job(hq.payload.model_copy(update={'autoRepairEnabled':False}))
    assert not reused and job['autoRepairEnabled'] is False
    parent=complete(hq,job['id'])
    replay,reused=hq.service.create_job(hq.payload)
    assert reused and replay['id']==parent['id'] and replay['autoRepairEnabled'] is False
    assert not replay['bodyRepair'] and len(hq.boundary.calls)==1


def test_receipt_with_another_source_or_broken_output_is_refused(hq):
    tmp_path=hq.service.root/'derived-test';tmp_path.mkdir(parents=True)
    m={k:{'sha256':'a'*64} for k in ('photo','garment','depth','pose')}
    report={'version':VERSION,'state':'unchanged','sourceHashes':{k:'b'*64 for k in m}}
    with pytest.raises(ValueError,match='binding'):hq.service._accept_report(report,m,tmp_path)
    report.update(state='applied',sourceHashes={k:'a'*64 for k in m},sha256='c'*64)
    (tmp_path/'result.png').write_bytes(b'wrong')
    with pytest.raises(ValueError,match='integrity'):hq.service._accept_report(report,m,tmp_path)
