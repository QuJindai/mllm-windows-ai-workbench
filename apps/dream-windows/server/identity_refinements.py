"""Durable, immutable one-pass edits of completed identity images."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import secrets
from time import perf_counter
from typing import Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from errors import DreamApiError
from history_transactions import history_mutation_lock, validate_history_path
from identity_models import is_visual_model_id

EDIT_PATTERN = r'refine-([a-f0-9]{24})-[a-f0-9]{24}'
VERSION_PATTERN = rf'^(result|original|{EDIT_PATTERN})$'
ACTIVE = {'queued', 'running'}


class RefinementRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)
    sourceJobId: str = Field(pattern=r'^identity-[a-f0-9]{24}$')
    parentVersionId: str = Field(default='result', pattern=VERSION_PATTERN)
    mode: Literal['restore', 'redraw', 'reference-anchor', 'edge-lighting'] = 'restore'
    strength: float = Field(default=.3, ge=.15, le=.65)
    prompt: str = Field(default='', max_length=2000)
    negativePrompt: str = Field(default='', max_length=2000)
    seed: int = Field(default=42, ge=0, le=2147483647)
    requestId: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9_-]{16,80}$')


class VersionSelection(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    versionId: str = Field(pattern=VERSION_PATTERN)


def problem(message, status=409):
    return DreamApiError('IDENTITY_REFINEMENT_UNAVAILABLE', message, status_code=status)


class IdentityRefinements:
    def __init__(self, service):
        self.service = service

    def folder(self, source):
        self.service._validate_id(source, r'identity-[a-f0-9]{24}')
        # The common guard validates files; a non-existent sentinel also checks
        # every parent directory for symlinks and Windows reparse points.
        return validate_history_path(self.service.config.dream_root, self.service.root / 'refinements' / source / '.boundary').parent

    def path(self, source, version, suffix='.json'):
        match = re.fullmatch(EDIT_PATTERN, version)
        if match is None or source != 'identity-' + match[1]:
            raise problem('精修版本与原图不匹配', 422)
        return validate_history_path(self.service.config.dream_root, self.folder(source) / (version + suffix))

    def source_id(self, version):
        match = re.fullmatch(EDIT_PATTERN, version)
        if match is None:
            raise problem('精修版本编号无效', 422)
        return 'identity-' + match[1]

    def save(self, record):
        from identity_service import atomic_json
        atomic_json(self.path(record['sourceJobId'], record['id']), record)
        return copy.deepcopy(record)

    def read(self, source, version):
        from identity_service import read_json
        path = self.path(source, version)
        if not path.is_file():
            raise problem('精修版本不存在', 404)
        row = read_json(path)
        settings = RefinementRequest.model_validate(row['settings']).model_dump()
        if row.get('id') != version or row.get('sourceJobId') != source or settings['sourceJobId'] != source:
            raise problem('精修版本归属无效')
        if row.get('state') not in ACTIVE | {'complete', 'failed', 'cancelled'}:
            raise problem('精修版本状态无效')
        task = self.service._background.get(version)
        if row['state'] in ACTIVE and (task is None or task[0].done()):
            row.update(state='failed', message='精修被服务中断，原图和已完成版本保留', error='INTERRUPTED', imageUrl=None)
            self.save(row)
        return row

    def records(self, source):
        paths = list(self.folder(source).glob('refine-*.json'))
        if len(paths) > 128:
            raise problem('单张原图的精修版本超过限制')
        return sorted((self.read(source, p.stem) for p in paths), key=lambda row:(row['createdAt'], row['id']))

    def source(self, source, deleted):
        if source in deleted:
            raise problem('原图已删除，精修版本不可用', 404)
        job = self.service.get(source)
        if job['state'] != 'complete' or not job.get('result'):
            raise problem('请先完成原图生成')
        result = job['result']
        metadata = result['metadata']
        root = self.service.config.dream_root
        image = validate_history_path(root, Path(metadata['output']))
        relative = image.relative_to(root)
        if (result['imageUrl'] != f'/api/history/{source}/image' or metadata.get('id') != source
                or len(relative.parts) != 3 or relative.parts[0] != 'outputs' or relative.name != source + '.png'):
            raise problem('原图文件归属无效')
        if not image.is_file():
            raise problem('原图文件已不存在', 404)
        return job, image

    def version_image(self, job, output, version):
        source = job['id']
        if version == 'result':
            return output
        if version == 'original':
            if job['result']['metadata'].get('facePolish', {}).get('originalImageUrl'):
                return self.service._validate_original(source, job['request'])
            return output
        row = self.read(source, version)
        if row['state'] != 'complete':
            raise problem('该版本尚未完成，不能作为底图')
        path = self.path(source, version, '.png')
        if not path.is_file():
            raise problem('精修图片缺失，原图仍可用', 404)
        return path

    def workspace(self, source):
        s = self.service
        with s._lock, history_mutation_lock(s.config.dream_root) as deleted:
            job, output = self.source(source, deleted)
            modes = (['redraw', 'reference-anchor'] if is_visual_model_id(job['request']['modelId']) else ['restore']) + ['edge-lighting']
            versions = [{'id':'result','state':'complete','message':'生成结果','imageUrl':job['result']['imageUrl'],
                         'parentVersionId':None,'createdAt':'','settings':{}},
                        {'id':'original','state':'complete','message':'生成原图','imageUrl':(
                            f'/api/identity/jobs/{source}/original' if job['result']['metadata'].get('facePolish',{}).get('originalImageUrl')
                            else job['result']['imageUrl']), 'parentVersionId':None,'createdAt':'','settings':{}}]
            versions += self.records(source)
            from identity_service import read_json
            selection_path = validate_history_path(s.config.dream_root, self.folder(source) / 'selection.json')
            selected = read_json(selection_path).get('versionId', 'result') if selection_path.is_file() else 'result'
            if selected not in {r['id'] for r in versions if r['state']=='complete'}:
                selected = 'result'
            return {'sourceJobId':source, 'selectedVersionId':selected,'versions':versions,'modes':modes,'defaultMode':modes[0],
                    'usesDiffusion': is_visual_model_id(job['request']['modelId']) or bool(job['request'].get('animeProfileId'))}

    def select(self, source, payload):
        s = self.service
        with s._lock, history_mutation_lock(s.config.dream_root) as deleted:
            job, output = self.source(source, deleted)
            self.version_image(job, output, payload.versionId)
            from identity_service import atomic_json
            atomic_json(validate_history_path(s.config.dream_root,self.folder(source)/'selection.json'), payload.model_dump())
        return self.workspace(source)

    def submit(self, payload):
        s = self.service
        with s._lock, history_mutation_lock(s.config.dream_root) as deleted:
            job, output = self.source(payload.sourceJobId, deleted)
            visual = is_visual_model_id(job['request']['modelId'])
            if payload.mode != 'edge-lighting' and (payload.mode == 'restore') == visual:
                raise problem('所选精修模式与底模不兼容', 422)
            s._require_model_enabled(job['request']['modelId'])
            self.version_image(job, output, payload.parentVersionId)
            rows = self.records(payload.sourceJobId)
            settings = payload.model_dump()
            if payload.requestId:
                old = next((r for r in rows if r['settings'].get('requestId') == payload.requestId),None)
                if old:
                    if old['settings'] != settings:
                        raise problem('重试标识对应的参数已改变，请重新提交')
                    return old
            if any(r['state'] in ACTIVE for r in rows):
                raise problem('这张原图仍在精修，请等待或取消当前任务')
            if len(rows) >= 128:
                raise problem('单张原图最多保留128个精修版本')
            version = f"refine-{payload.sourceJobId.removeprefix('identity-')}-{secrets.token_hex(12)}"
            row = {'id':version,'sourceJobId':payload.sourceJobId,'parentVersionId':payload.parentVersionId,
                   'state':'queued','message':'等待精修队列','error':None,'imageUrl':None,'settings':settings,
                   'createdAt':datetime.now(timezone.utc).isoformat()}
            self.save(row)
            def queued_cancel():
                current=self.read(payload.sourceJobId,version)
                current.update(state='cancelled',message='已取消精修',error=None)
                self.save(current)
            s._submit_background(version, lambda cancelled:self.execute(payload.sourceJobId,version,cancelled), queued_cancel)
            return copy.deepcopy(row)

    def execute(self, source, version, cancelled):
        s = self.service
        started=perf_counter()
        temporary=self.path(source,version,'.pending.png')
        try:
            with s._lock, history_mutation_lock(s.config.dream_root) as deleted:
                job, output=self.source(source,deleted)
                row=self.read(source,version)
                base=self.version_image(job,output,row['parentVersionId'])
                scene=self.version_image(job,output,'original')
                if cancelled.is_set():
                    raise problem('已取消精修')
                row.update(state='running',message='正在处理选中版本，仅执行一轮')
                self.save(row)
            s.job_runner.release_native_for_identity()
            payload={**job['request'], 'sourcePath':str(base),'outputPath':str(temporary),
                     'scenePath':str(scene),
                     'imagePath':str(s.reference_image(job['request']['referenceId'])), 'editSettings':row['settings'],
                     'jobId':'identity-'+version[-24:], 'dreamRoot':str(s.config.dream_root),
                     'configPath':str(s.config_path)}
            if row['settings']['mode'] != 'edge-lighting':
                # The frozen base task may have disabled optional polishing.
                # Resolve the archive for this new edit without mutating it.
                payload.update(s.anime_profiles.resolve_request({**job['request'], 'facePolish': True}))
            details=s._worker('refine',payload,cancelled)
            with s._lock, history_mutation_lock(s.config.dream_root) as deleted:
                self.source(source,deleted)
                if cancelled.is_set():
                    raise problem('已取消精修')
                with Image.open(temporary) as image:
                    if image.format!='PNG' or image.size!=(job['request']['width'],job['request']['height']):
                        raise ValueError('精修结果尺寸或格式不正确')
                    image.verify()
                final=self.path(source,version,'.png')
                os.link(temporary,final)
                row.update(state='complete',message='精修完成，请对比后选择版本',error=None,
                           imageUrl=f'/api/identity/refinements/{version}/image',metrics=details,
                           elapsedMs=round((perf_counter()-started)*1000))
                self.save(row)
        except Exception as exc:
            with s._lock:
                # A failed attempt never becomes the selected version.
                row=self.read(source,version)
                row.update(state='cancelled' if cancelled.is_set() else 'failed',
                           message='已取消精修' if cancelled.is_set() else '精修失败，已保留原图和既有版本',
                           error=None if cancelled.is_set() else str(exc)[:300],imageUrl=None,
                           elapsedMs=round((perf_counter()-started)*1000))
                self.save(row)
        finally:
            temporary.unlink(missing_ok=True)

    def cancel(self, version):
        s=self.service
        source=self.source_id(version)
        with s._lock:
            row=self.read(source,version)
            task=s._background.get(version)
            if row['state'] not in ACTIVE or task is None:
                return row
            future,event,queued_cancel=task
            event.set()
            if future.cancel():
                queued_cancel()
        if not future.cancelled():
            future.result()
        with s._lock:
            return self.read(source,version)

    def image(self, version):
        s=self.service
        source=self.source_id(version)
        with s._lock,history_mutation_lock(s.config.dream_root) as deleted:
            job,output=self.source(source,deleted)
            return self.version_image(job,output,version)

    def artifact_paths(self, source):
        """Called under the parent's deletion transaction; never nest its lock."""
        rows=self.records(source)
        if any(r['state'] in ACTIVE for r in rows):
            raise problem('原图正在精修，请先取消精修再删除')
        paths=[]
        for row in rows:
            paths.extend(self.path(source,row['id'],ext) for ext in ('.json','.png','.pending.png'))
        paths.append(validate_history_path(self.service.config.dream_root,self.folder(source)/'selection.json'))
        return paths

    def delete_legacy(self, source, delete):
        """Older output-only records have no job; never bypass a version ledger."""
        s = self.service
        with s._lock:
            if s._job_path(source).exists():
                raise problem('人物任务记录已变化，请刷新后重试')
            folder = self.folder(source)
            if folder.exists() and any(folder.iterdir()):
                raise problem('精修记录的原任务缺失，已保留文件供恢复')
            return delete(source)
