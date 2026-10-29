"""Bounded immutable experiments on the existing IdentityService serial queue."""
from __future__ import annotations

import copy
import math
import os
from pathlib import Path
import re
import secrets
from datetime import datetime, timezone
from time import perf_counter
from typing import Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator

from errors import DreamApiError
from history_transactions import validate_history_path
from research_fusion import MODES, digest
from research_image_engine import resolve_assets, file_sha256

ACTIVE = {'queued', 'running', 'cancelling'}
CONTRACT = 'diffusers-chunk-fusion-images-v1'
MAX_RECORDS = 128


class FusionImageRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)
    modelId: Literal['realistic-vision-v5.1-fusion'] = 'realistic-vision-v5.1-fusion'
    prompt: str = Field(min_length=1, max_length=2000, pattern=r'\S')
    negativePrompt: str = Field(default='', max_length=2000)
    seed: int = Field(default=42, ge=0, le=2147483647)
    steps: int = Field(default=12, ge=1, le=30)
    cfg: float = Field(default=5.5, ge=1, le=15)
    alpha: float = Field(default=.5, ge=0, le=1)
    width: int = Field(default=512, ge=256, le=512)
    height: int = Field(default=512, ge=256, le=512)
    requestId: str = Field(pattern=r'^[A-Za-z0-9_-]{16,80}$')

    @field_validator('width','height')
    @classmethod
    def aligned(cls, value):
        if value % 64: raise ValueError('尺寸必须按64对齐')
        return value


def problem(message, status=409):
    return DreamApiError('FUSION_IMAGE_UNAVAILABLE', message, status_code=status)


class ResearchImageService:
    def __init__(self, service):
        self.service = service

    def operation(self, method, *args):
        # Same lease, shutdown accounting and recovery boundary as identity APIs.
        with self.service._operation():
            self.service._require_open()
            return getattr(self, method)(*args)

    def path(self, job_id, name='record.json'):
        if re.fullmatch(r'fusion-[a-f0-9]{24}',job_id) is None:
            raise problem('实验编号无效',422)
        return validate_history_path(self.service.config.dream_root,
            self.service.root/'fusion-images'/job_id/name)

    def _save(self,row):
        from identity_service import atomic_json
        atomic_json(self.path(row['id']), row)

    def _load_record(self,job_id):
        from identity_service import read_json
        try:
            path=self.path(job_id)
            if not path.is_file(): raise problem('图像实验不存在',404)
            return read_json(path)
        except (OSError,ValueError) as exc:
            raise problem('图像实验记录无法读取',422) from exc

    def _read(self,job_id,*,recover=True):
        return self._validate_record(job_id,self._load_record(job_id),recover=recover)

    def _validate_record(self,job_id,row,*,recover=True):
        try:
            if row.get('id') != job_id or row.get('state') not in ACTIVE | {'complete','failed','cancelled'}:
                raise ValueError('图像实验记录无效')
            FusionImageRequest.model_validate(row['settings'])
            if row['state']=='complete': self._validate_result(row,row.get('result'))
            elif row.get('result') is not None: raise ValueError('未完成实验不能包含公开结果')
        except (ValueError,KeyError,TypeError,AttributeError) as exc:
            raise problem('图像实验记录来源无效',422) from exc
        task=self.service._background.get(job_id)
        if recover and row['state'] in ACTIVE and (task is None or task[0].done()):
            row.update(state='failed',message='实验被中断，未发布部分结果',error='INTERRUPTED',result=None)
            self._save(row)
        return row

    @staticmethod
    def _public(row):
        value=copy.deepcopy(row)
        value.pop('assetBinding',None)
        if value.get('result'):
            value['result']['provenance'].pop('assetBinding',None)
        return value

    def _assets(self):
        from identity_service import read_json
        return resolve_assets(read_json(self.service.config_path,64*1024))

    def capability(self):
        try:
            self._assets()
            return {'available':True,'engine':'diffusers-sd15-paired-chunk-cfg','truth':'derived',
                    'message':'本地RV文件就绪；受控Diffusers四模式出图，实际CUDA可用性由工作进程检查',
                    'maxSteps':30,'maxDimension':512,'maxChunks':4,'modes':list(MODES),
                    'deviceParity':False,'requiresWorkerOperation':'fusion'}
        except (OSError,ValueError) as exc:
            return {'available':False,'message':str(exc),'truth':'unavailable','deviceParity':False}

    def submit(self, settings):
        s=self.service
        with s._lock:
            root=validate_history_path(s.config.dream_root,s.root/'fusion-images'/'.boundary').parent
            # Count damaged/missing records too, without discarding their files.
            paths=[path for path in root.iterdir() if path.name.startswith('fusion-')] if root.exists() else []
            requested=settings.model_dump()
            rows=[]
            for path in paths:
                raw=None
                try:
                    raw=self._load_record(path.name)
                    previous=self._validate_record(path.name,raw)
                except DreamApiError:
                    # A known request identity may not be reused to bypass its
                    # corrupt result. Unrelated invalid history stays isolated.
                    if isinstance(raw,dict) and isinstance(raw.get('settings'),dict) and raw['settings'].get('requestId')==settings.requestId:
                        raise problem('该重试标识的实验记录已损坏，无法安全重试',422)
                    continue
                rows.append(previous)
                if previous['settings']['requestId']==settings.requestId:
                    if previous['settings']!=requested: raise problem('重试标识的参数已变化，请新建实验')
                    return self._public(previous)
            # The shared registry is authoritative even if an active record was
            # removed, corrupted or incorrectly marked terminal on disk.
            if any(job.startswith('fusion-') and not task[0].done() for job,task in s._background.items()) or any(row['state'] in ACTIVE for row in rows):
                raise problem('仍有图像融合实验在队列中，请等待或取消')
            if len(paths)>=MAX_RECORDS: raise problem('最多保留128次实验，请先整理已保存结果')
            try: binding=self._assets()
            except (OSError,ValueError) as exc: raise problem(str(exc),422) from exc
            job='fusion-'+secrets.token_hex(12)
            row={'id':job,'state':'queued','message':'已加入现有串行生成队列','progress':0,
                 'settings':requested,'assetBinding':binding,'createdAt':datetime.now(timezone.utc).isoformat(),
                 'error':None,'result':None}
            self._save(row)
            def cancel_queued():
                current=self._read(job,recover=False)
                current.update(state='cancelled',message='已取消排队实验',result=None,error=None)
                self._save(current)
            try:
                s._submit_background(job,lambda event:self._execute(job,event),cancel_queued)
            except Exception:
                row.update(state='failed',message='加入生成队列失败',error='SUBMIT_FAILED')
                self._save(row)
                raise
            return self._public(row)

    def get(self,job):
        with self.service._lock: return self._public(self._read(job))

    def cancel(self,job):
        s=self.service
        with s._lock:
            row=self._read(job)
            if row['state'] not in ACTIVE: return self._public(row)
            future,event,cancel_queued=s._background[job]
            event.set()
            if future.cancel():
                cancel_queued()
                return self._public(self._read(job,recover=False))
            row.update(state='cancelling',message='正在取消；等待工作进程释放后结束')
            self._save(row)
            return self._public(row)

    def _validate_result(self,row,result,pending=None):
        if (not isinstance(result,dict) or result.get('contractVersion')!=CONTRACT or result.get('jobId')!=row['id']
                or result.get('settingsSha256')!=digest(row['settings'])):
            raise ValueError('图像实验返回来源不匹配')
        provenance=result.get('provenance',{})
        if (provenance.get('engine')!='diffusers-sd15-paired-chunk-cfg' or provenance.get('settings')!=row['settings']
                or provenance.get('assetBinding')!=row['assetBinding'] or provenance.get('scheduler')!='EulerDiscreteScheduler'
                or provenance.get('predictionType')!='epsilon' or provenance.get('nativeDeviceParity') is not False
                or provenance.get('negativeEncodingPerformed') is not (row['settings']['cfg']!=1)
                or provenance.get('pipelineConfigSha256')!=digest(row['assetBinding']['files'])
                or any(not isinstance(provenance.get(k),str) or not 1<=len(provenance[k])<=100 for k in ('torchVersion','diffusersVersion'))):
            raise ValueError('图像实验引擎/资产来源不匹配')
        for key in ('modelSha256','pipelineConfigSha256','initialLatentSha256','engineRevision'):
            if not isinstance(provenance.get(key),str) or not re.fullmatch('[a-f0-9]{64}',provenance[key]):
                raise ValueError('图像实验缺少来源摘要')
        counts=provenance.get('chunkCounts')
        if not isinstance(counts,list) or not 1<=len(counts)<=4 or any(
            not isinstance(c,dict) or any(type(c.get(k)) is not int or not 0<=c[k]<=75 for k in ('positive','negative')) for c in counts):
            raise ValueError('编码chunk来源无效')
        encoded=provenance.get('encodedTokenIds')
        if not isinstance(encoded,list) or len(encoded)!=len(counts) or any(
                not isinstance(c,dict) or any(not isinstance(c.get(side),list) or len(c[side])!=77
                    or any(type(v) is not int or not 0<=v<=100000 for v in c[side]) for side in ('positive','negative')) for c in encoded):
            raise ValueError('实际编码token记录缺失或无效')
        effective=[max(1,c['positive'],0 if row['settings']['cfg']==1 else c['negative']) for c in counts]
        n=len(effective); alpha=row['settings']['alpha']
        expected_weights={'first_only':[1.]+[0.]*(n-1),'equal_mean':[1/n]*n,
            'token_weighted':[v/sum(effective) for v in effective],
            'anchor_residual':[1.] if n==1 else [1-alpha]+[alpha*v/sum(effective[1:]) for v in effective[1:]]}
        variants=result.get('variants')
        if not isinstance(variants,list) or [v.get('mode') for v in variants]!=list(MODES):
            raise ValueError('实验必须完整返回四种模式')
        for variant in variants:
            mode=variant['mode']
            weights=variant.get('effectiveWeights')
            if not isinstance(weights,list) or len(weights)!=len(counts) or any(type(w) not in (float,int) or not math.isfinite(w) or not 0<=w<=1 for w in weights) or abs(sum(weights)-1)>1e-5:
                raise ValueError('融合权重记录无效')
            if any(abs(a-b)>1e-6 for a,b in zip(weights,expected_weights[mode])):
                raise ValueError('融合权重与实际编码计数不匹配')
            if type(variant.get('durationMs')) not in (int,float) or not math.isfinite(variant['durationMs']) or variant['durationMs']<0:
                raise ValueError('实验时长记录无效')
            if not isinstance(variant.get('imageSha256'),str) or not re.fullmatch('[a-f0-9]{64}',variant['imageSha256']):
                raise ValueError('实验图片摘要无效')
            if pending is None:
                if variant.get('imageUrl')!=f"/api/identity/research/images/{row['id']}/{mode}/image":
                    raise ValueError('实验图片URL来源不匹配')
                continue
            path=pending[mode]
            if not path.is_file() or path.stat().st_size>4*1024*1024 or file_sha256(path)!=variant.get('imageSha256'):
                raise ValueError('实验图片缺失或摘要不匹配')
            with Image.open(path) as image:
                if image.format!='PNG' or image.size!=(row['settings']['width'],row['settings']['height']):
                    raise ValueError('实验图片尺寸或格式无效')
                image.verify()

    def _execute(self,job,cancelled):
        s=self.service; started=perf_counter(); published=[]
        pending={mode:self.path(job,mode+'.pending.png') for mode in MODES}
        event_path=self.path(job,'events.jsonl')
        try:
            with s._lock:
                row=self._read(job,recover=False)
                if cancelled.is_set(): raise RuntimeError('cancelled')
                if self._assets()!=row['assetBinding']: raise ValueError('排队后模型配置或文件已改变，请重新提交')
                row.update(state='running',message='正在加载受控Diffusers实验',progress=1)
                self._save(row)
            s.job_runner.release_native_for_identity()
            if cancelled.is_set(): raise RuntimeError('cancelled')
            def progress(event):
                if (event.get('type')!='fusion-progress' or event.get('jobId')!=job or event.get('mode') not in MODES
                        or type(event.get('step')) is not int or not 0<=event['step']<=row['settings']['steps']
                        or event.get('totalSteps')!=row['settings']['steps']): return
                with s._lock:
                    current=self._read(job,recover=False)
                    if current['state']!='running': return
                    value=int(5+90*(MODES.index(event['mode'])*row['settings']['steps']+event['step'])/(4*row['settings']['steps']))
                    if value<current['progress']: return
                    current.update(progress=value,message=f"{event['mode']} · {event['step']}/{event['totalSteps']} 步")
                    self._save(current)
            s._event_callbacks[str(event_path)]=progress
            payload={'jobId':job,'dreamRoot':str(s.config.dream_root),'configPath':str(s.config_path),
                     'settings':row['settings'],'assetBinding':row['assetBinding'],
                     'outputPaths':{mode:str(path) for mode,path in pending.items()},'eventPath':str(event_path)}
            result=s._worker('fusion',payload,cancelled)
            with s._lock:
                if cancelled.is_set(): raise RuntimeError('cancelled')
                self._validate_result(row,result,pending)
                for variant in result['variants']:
                    mode=variant['mode']; final=self.path(job,mode+'.png')
                    os.link(pending[mode],final); published.append(final)
                    variant['imageUrl']=f'/api/identity/research/images/{job}/{mode}/image'
                row.update(state='complete',message='四种受控融合图像已完成',progress=100,result=result,error=None,
                           elapsedMs=round((perf_counter()-started)*1000))
                self._save(row)
        except Exception as exc:
            for path in published: path.unlink(missing_ok=True)
            with s._lock:
                row=self._read(job,recover=False)
                row.update(state='cancelled' if cancelled.is_set() else 'failed',result=None,
                           message='已取消图像实验' if cancelled.is_set() else '图像实验失败，未发布部分结果',
                           error=None if cancelled.is_set() else str(exc)[:500],elapsedMs=round((perf_counter()-started)*1000))
                self._save(row)
        finally:
            s._event_callbacks.pop(str(event_path),None)
            for path in pending.values(): path.unlink(missing_ok=True)

    def image(self,job,mode):
        if mode not in MODES: raise problem('实验模式无效',422)
        with self.service._lock:
            row=self._read(job)
            if row['state']!='complete' or not row.get('result'): raise problem('图像实验尚未完成',404)
            variant=next((v for v in row['result']['variants'] if v['mode']==mode),None)
            path=self.path(job,mode+'.png')
            if variant is None or not path.is_file() or path.stat().st_size>4*1024*1024 or file_sha256(path)!=variant['imageSha256']:
                raise problem('实验图片缺失或已改变',404)
            return path
