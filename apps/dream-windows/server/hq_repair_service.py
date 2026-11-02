"""Local-only versioned HQ repair jobs. The source generation is immutable and is never re-submitted."""
from __future__ import annotations

import hashlib
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from errors import DreamApiError
from history_transactions import history_deletion_flags
from identity_service import WorkerCancelled, atomic_json, read_json
from operations import ensure_generation_capacity
import hq_paired_depth

from hq_repair_version import VERSION
READY = {'applied','partial','unchanged','rejected'}
BUSY = {'queued','running'}


def now():
    return datetime.now(timezone.utc).isoformat()


class HQRepairService:
    def _repair_dir(self, job_id):
        return self._safe(self._folder(job_id)/'body-repair'/VERSION)

    def _require_repair_source(self, record):
        if record is None:
            raise DreamApiError('HQ_JOB_NOT_FOUND','找不到试衣任务',status_code=404)
        if record.get('identityJobId') in history_deletion_flags(self.config.dream_root):
            raise DreamApiError('HQ_RESULT_DELETED','原作品已删除，此修整版本不可使用',status_code=404)
        if record.get('state')!='succeeded' or not record.get('result'):
            raise DreamApiError('HQ_RESULT_NOT_READY','原成片尚未完成',status_code=409)
        if record.get('pipeline')!=hq_paired_depth.PIPELINE:
            raise DreamApiError('HQ_REPAIR_UNSUPPORTED','此任务没有配对深度条件，无法可靠识别此类伪影',status_code=409)

    def _schedule_repair(self,record):
        # Lock held. No CPU/GPU inference while holding the controller lock.
        self._require_repair_source(record)
        jid=record['id']; prev=record.get('bodyRepair') or {}
        if prev.get('version')==VERSION and prev.get('sourceSha256')==record['result']['sha256'] and (
                prev.get('state') in READY or jid in self._repair_futures):
            return
        ensure_generation_capacity(self.config)
        record['bodyRepair']={'version':VERSION,'state':'queued','sourceSha256':record['result']['sha256'],'updatedAt':now()}
        self._save(record)
        stop=threading.Event()
        self._repair_stops[jid]=stop
        try:
            self._repair_futures[jid]=self.job_runner.submit_serial(self._run_body_repair,jid,stop)
        except RuntimeError:
            self._repair_stops.pop(jid,None)
            record['bodyRepair'].update(state='failed',message='服务正在停止，原成片仍可用。',updatedAt=now())
            self._save(record)

    def request_repair(self,jid):
        with self._operation(),self._lock:
            self._folder(jid)
            record=self._jobs.get(jid)
            self._require_repair_source(record)
            self._schedule_repair(record)
            return self._view(record)

    def _repair_manifest(self,record,folder):
        jid=record['id']; audit=record['audit']; ctl=audit['conditioning']['pose']['controlImage']
        path,meta=self.image_path(jid)
        entries={'photo':{'path':str(path),'sha256':meta['sha256']}}
        for role in ('pose','garment'):
            path,meta=self.image_path(jid,role)
            entries[role]={'path':str(path),'sha256':meta['sha256']}
        depth=self._safe(self._folder(jid)/'audit.conditioning'/'paired-depth-control.png')
        if depth!=Path(ctl['path']).resolve() or depth.stat().st_size>32*1024*1024:
            raise ValueError('Unbound depth control')
        entries['depth']={'path':str(depth),'sha256':ctl['sha256']}
        models=audit['models']; adapter=models['garmentAdapter']
        cfg=read_json(Path(self._settings()['pipelineConfig']))
        if Path(adapter['path']).resolve()!=Path(cfg['garmentAdapter']).resolve():
            raise ValueError('Configured garment adapter changed')
        manifest={**entries,'adapterPath':adapter['path'],'adapterSha256':adapter['sha256'],
                  'checkpointSha256':models['checkpoint']['sha256'],'seed':record['parameters']['seed']}
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/'manifest.json';atomic_json(path,manifest)
        return manifest,path

    def _accept_report(self,report,manifest,folder):
        if (report.get('version')!=VERSION or report.get('state') not in READY or
            report.get('sourceHashes')!={k:manifest[k]['sha256'] for k in ('photo','depth','pose','garment')}):
            raise ValueError('Repair output binding mismatch')
        if report['state'] in {'applied','partial'}:
            for key,name in [('sha256','result.png'),('maskSha256','mask.png')]:
                path=self._safe(folder/name)
                if not path.is_file() or not 0<path.stat().st_size<=32*1024*1024 or hashlib.sha256(path.read_bytes()).hexdigest()!=report.get(key):
                    raise ValueError('Repair output integrity check failed')
        return {k:report[k] for k in ('state','regions','changedPixels','sha256','maskSha256','rejected','passes','sourceHashes') if k in report}

    def _run_body_repair(self,jid,stop):
        try:
            with self._lock:
                record=self._jobs[jid]; self._require_repair_source(record)
                if self._closing or stop.is_set():raise WorkerCancelled()
                record['bodyRepair'].update(state='running',updatedAt=now());self._save(record)
            folder=self._repair_dir(jid);manifest,path=self._repair_manifest(record,folder)
            # Handles a server stop between atomic worker publication and recording the receipt.
            if (folder/'report.json').is_file():
                accepted=self._accept_report(read_json(folder/'report.json'),manifest,folder)
            else:
                self.job_runner.release_native_for_identity()
                report=self.identity._worker('hq_body_repair',{'manifestPath':str(path)},stop)
                accepted=self._accept_report(report,manifest,folder)
            with self._lock:
                self._require_repair_source(record)
                record['bodyRepair'].update(**accepted,updatedAt=now());self._save(record)
        except Exception as exc:
            with self._lock:
                record=self._jobs[jid]
                code=getattr(exc,'code','HQ_REPAIR_FAILED')
                record['bodyRepair'].update(state='failed',updatedAt=now(),
                    errorCode=code if isinstance(code,str) and re.fullmatch(r'[A-Z_0-9]+',code) else 'HQ_REPAIR_FAILED',
                    message='局部修整未完成，原图已保留。可在任务中重新检查。')
                self._save(record)
        finally:
            with self._lock:
                self._repair_stops.pop(jid,None);self._repair_futures.pop(jid,None)

    def repair_image(self,jid,kind):
        with self._operation(),self._lock:
            folder=self._repair_dir(jid);record=self._jobs.get(jid)
            self._require_repair_source(record);r=record.get('bodyRepair') or {}
            if kind not in ('result','mask') or r.get('state') not in {'applied','partial'} or r.get('sourceSha256')!=record['result']['sha256']:
                raise DreamApiError('HQ_REPAIR_NOT_READY','没有可下载的修整版本',status_code=404)
            # Preserve private prior releases after an algorithm update.
            version=r.get('version','')
            if not re.fullmatch(r'paired-surface-v[1-9][0-9]{0,2}',version):
                raise DreamApiError('HQ_REPAIR_INVALID','修整版本编号无效',status_code=409)
            folder=self._safe(self._folder(jid)/'body-repair'/version)
            path=self._safe(folder/(kind+'.png'));digest=r['sha256' if kind=='result' else 'maskSha256']
            if not path.is_file() or not 0<path.stat().st_size<=32*1024*1024 or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                raise DreamApiError('HQ_REPAIR_INVALID','修整文件未通过完整性校验，原图未变',status_code=409)
            return path,digest
