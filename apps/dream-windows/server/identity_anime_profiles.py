"""Separate anime references linked to, never replacing, a real identity profile."""
from __future__ import annotations

import copy
import base64
import binascii
import hashlib
import io
import logging
import re
import secrets
import shutil
from pathlib import Path
from typing import Literal

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import ConfigDict, Field, model_validator

from errors import DreamApiError
from history_transactions import history_mutation_lock
from identity_profiles import PROFILE_PATTERN, ProfileName, timestamp
from identity_service import JOB_PATTERN, REFERENCE_PATTERN, MAX_BASE64, MAX_IMAGE_BYTES, MAX_IMAGE_PIXELS, Face, WorkerCancelled, atomic_json, read_json

ANIME_PATTERN = r'anime-[a-f0-9]{24}'


class AnimeProfileCreate(ProfileName):
    profileId: str = Field(pattern=f'^{PROFILE_PATTERN}$')
    jobId: str = Field(pattern=f'^{JOB_PATTERN}$')


class AnimeProfileImport(ProfileName):
    profileId: str = Field(pattern=f'^{PROFILE_PATTERN}$')
    sourceName: str = Field(min_length=1, max_length=255)
    sourceLabel: str = Field(default='外部图片', min_length=1, max_length=80)
    imageBase64: str


class AnimeProfileRecord(ProfileName):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)
    id: str = Field(pattern=f'^{ANIME_PATTERN}$')
    profileId: str = Field(pattern=f'^{PROFILE_PATTERN}$')
    referenceId: str = Field(pattern=f'^{REFERENCE_PATTERN}$')
    faceIndex: int = Field(ge=0, le=19)
    sourceJobId: str | None = Field(default=None, pattern=f'^{JOB_PATTERN}$')
    sourceKind: Literal['local-job', 'upload'] = 'local-job'
    sourceName: str | None = Field(default=None, min_length=1, max_length=255)
    sourceLabel: str | None = Field(default=None, min_length=1, max_length=80)
    sourceImageSha256: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    state: Literal['preparing', 'ready', 'failed']
    featureKey: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    parentFeatureKey: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    faceBox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    error: str | None = None
    createdAt: str
    updatedAt: str

    @model_validator(mode='after')
    def valid_ready_record(self):
        if self.sourceKind == 'local-job' and not self.sourceJobId:
            raise ValueError('本机动漫作品缺少来源任务')
        if self.sourceKind == 'upload' and (self.sourceJobId is not None or not self.sourceName
                                           or not self.sourceLabel or not self.sourceImageSha256):
            raise ValueError('外部动漫底图来源不完整')
        if self.faceBox is not None:
            Face.model_validate({'index':0,'box':self.faceBox})
        if self.state=='ready' and (not self.featureKey or not self.parentFeatureKey or self.faceBox is None):
            raise ValueError('已就绪动漫档案缺少特征或脸部区域')
        return self


class AnimeProfiles:
    def __init__(self, service):
        self.service = service
        self.records = {}

    def path(self, profile_id, suffix='.json'):
        s = self.service
        s._validate_id(profile_id, ANIME_PATTERN)
        path = s._safe(s.root/'anime-profiles'/f'{profile_id}{suffix}')
        if path.resolve() != s.config.dream_root.resolve()/'data'/'identity'/'anime-profiles'/path.name:
            raise DreamApiError('ANIME_PATH_INVALID', '动漫档案路径不允许重定向', status_code=422)
        return path

    def public(self, record):
        return {**copy.deepcopy(record), 'imageUrl':f"/api/identity/anime-profiles/{record['id']}/image"}

    def save(self, record):
        value = AnimeProfileRecord.model_validate({**record,'updatedAt':timestamp()}).model_dump()
        atomic_json(self.path(value['id']), value)
        self.records[value['id']] = value
        return self.public(value)

    def recover(self):
        for path in (self.service.root/'anime-profiles').glob('anime-*.json'):
            try:
                value = AnimeProfileRecord.model_validate(read_json(self.path(path.stem))).model_dump()
                if value['id'] != path.stem: raise ValueError('档案编号与文件不一致')
                if value['state']=='preparing':
                    self.save({**value,'state':'failed','error':'动漫建档被服务重启中断，请重新建档并使用新名称'})
                else: self.records[path.stem] = value
            except (ValueError, OSError, DreamApiError):
                logging.getLogger(__name__).exception('动漫档案恢复失败，保留原文件：%s', path.stem)

    def list(self):
        return [self.public(p) for p in sorted(self.records.values(),key=lambda x:x['createdAt'],reverse=True)]

    def get(self, profile_id):
        self.path(profile_id)
        if profile_id not in self.records:
            raise DreamApiError('ANIME_PROFILE_NOT_FOUND','动漫档案不存在',status_code=404)
        return self.public(self.records[profile_id])

    def image(self, profile_id):
        record = self.get(profile_id)
        path = self.path(profile_id,'.png')
        if not path.is_file():
            raise DreamApiError('ANIME_IMAGE_NOT_FOUND','动漫档案图片不存在',status_code=404)
        if record.get('sourceImageSha256') and (path.stat().st_size > 64*1024**2
                or hashlib.sha256(path.read_bytes()).hexdigest() != record['sourceImageSha256']):
            raise DreamApiError('ANIME_IMAGE_CHANGED','动漫底图校验失败，请重新导入建档',status_code=409)
        return path

    def import_image(self, request):
        s = self.service
        if any(p['name'].casefold() == request.name.casefold() for p in self.records.values()):
            raise DreamApiError('ANIME_NAME_CONFLICT','此动漫档案名称已存在，请使用新名称',status_code=409)
        parent = s.profiles.get(request.profileId)
        if parent['state'] != 'ready' or parent.get('referenceKind', 'faceid') != 'faceid':
            raise DreamApiError('ANIME_SOURCE_CONFLICT','请先选择已就绪的真人档案',status_code=409)
        # Never run biometric enrollment on an uploaded cartoon. The existing
        # anime worker combines the parent's ID vector with the cartoon's CLIP.
        if len(request.imageBase64) > MAX_BASE64:
            raise DreamApiError('ANIME_IMAGE_TOO_LARGE','动漫底图不能超过 10 MiB',status_code=413)
        try:
            raw = base64.b64decode(request.imageBase64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise DreamApiError('ANIME_IMAGE_INVALID','动漫底图编码无效',status_code=422) from exc
        if len(raw) > MAX_IMAGE_BYTES:
            raise DreamApiError('ANIME_IMAGE_TOO_LARGE','动漫底图不能超过 10 MiB',status_code=413)
        try:
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {'PNG','JPEG','WEBP'} or getattr(source,'n_frames',1) != 1:
                    raise ValueError('Only single-frame PNG/JPEG/WebP supported')
                if source.width * source.height > MAX_IMAGE_PIXELS:
                    raise DreamApiError('ANIME_IMAGE_TOO_LARGE','动漫底图不能超过 1600 万像素',status_code=413)
                source.load()
                oriented = ImageOps.exif_transpose(source).convert('RGBA')
                image = Image.alpha_composite(Image.new('RGBA',oriented.size,'white'),oriented).convert('RGB')
                image.info.clear()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
            raise DreamApiError('ANIME_IMAGE_INVALID','请选择完好的单张 PNG、JPEG 或 WebP 动漫底图',status_code=422) from exc
        profile_id = 'anime-' + secrets.token_hex(12)
        destination = self.path(profile_id,'.png')
        if any(self.path(profile_id,suffix).exists() for suffix in ('.png','.json','.safetensors')):
            raise DreamApiError('ANIME_ID_CONFLICT','动漫档案编号冲突，请重试',status_code=409)
        destination.parent.mkdir(parents=True,exist_ok=True)
        created_image = False
        try:
            with destination.open('xb') as stream:
                created_image = True
                image.save(stream,format='PNG')
            record = self.save({'id':profile_id,'name':request.name,'profileId':parent['id'],
                'referenceId':parent['referenceId'],'faceIndex':parent['faceIndex'],
                'sourceJobId':None,'sourceKind':'upload',
                'sourceName':re.split(r'[/\\]',request.sourceName)[-1].strip() or 'image',
                'sourceLabel':request.sourceLabel.strip() or '外部图片',
                'sourceImageSha256':hashlib.sha256(destination.read_bytes()).hexdigest(),
                'state':'preparing','createdAt':timestamp()})
            s._submit_background(profile_id,lambda event:self.prepare(profile_id,event),
                                 lambda:self.failed(profile_id,'建档已取消'))
            return record
        except BaseException:
            # Only remove files created for this new, unpublished archive.
            if created_image:
                destination.unlink(missing_ok=True)
                self.path(profile_id).unlink(missing_ok=True)
                self.records.pop(profile_id,None)
            raise

    def create(self, request):
        s = self.service
        if any(p['name'].casefold()==request.name.casefold() for p in self.records.values()):
            raise DreamApiError('ANIME_NAME_CONFLICT','此动漫档案名称已存在，请使用新名称',status_code=409)
        parent = s.profiles.get(request.profileId)
        job = s.get(request.jobId)
        if (parent['state']!='ready' or parent.get('referenceKind', 'faceid') != 'faceid' or job['state']!='complete'
            or job['request']['modelId']!='illustrious-xl-v2.0-faceid'
            or any(parent[k]!=job['request'][k] for k in ('referenceId','faceIndex'))):
            raise DreamApiError('ANIME_SOURCE_CONFLICT','请选择本人物档案已完成的 Illustrious 单人作品',status_code=409)
        profile_id = 'anime-'+secrets.token_hex(12)
        destination = self.path(profile_id,'.png')
        with history_mutation_lock(s.config.dream_root):
            # The output must still exist even if an original happens to remain.
            source = s._safe(Path(job['result']['metadata']['output']))
            expected_root = s.config.dream_root.resolve()/'outputs'
            if (source.name!=job['id']+'.png' or source.resolve().parent.parent!=expected_root
                or not source.is_file() or source.resolve()!=source.absolute()):
                raise DreamApiError('ANIME_SOURCE_DELETED','原作品已删除或不可用，无法建档',status_code=409)
            if job['request'].get('facePolish'):
                source = s._validate_original(job['id'],job['request'])
            with Image.open(source) as image:
                if image.size!=(job['request']['width'],job['request']['height']) or image.format!='PNG':
                    raise DreamApiError('ANIME_SOURCE_INVALID','动漫作品格式无效',status_code=409)
                image.verify()
            destination.parent.mkdir(parents=True,exist_ok=True)
            with source.open('rb') as src, destination.open('xb') as dst:
                shutil.copyfileobj(src,dst)
        record = self.save({'id':profile_id,'name':request.name,'profileId':parent['id'],
            'referenceId':parent['referenceId'],'faceIndex':parent['faceIndex'],'sourceJobId':job['id'],
            'state':'preparing','createdAt':timestamp()})
        s._submit_background(profile_id, lambda event:self.prepare(profile_id,event), lambda:self.failed(profile_id,'建档已取消'))
        return record

    def failed(self, profile_id, message):
        return self.save({**self.records[profile_id],'state':'failed','error':message})

    def prepare(self, profile_id, cancelled):
        s = self.service
        try:
            if cancelled.is_set(): raise WorkerCancelled()
            s.job_runner.release_native_for_identity()
            record = self.get(profile_id)
            result = s._worker('anime_prepare',{'configPath':str(s.config_path),'dreamRoot':str(s.config.dream_root),
                'imagePath':str(s.reference_image(record['referenceId'])),'faceIndex':record['faceIndex'],
                'animeImagePath':str(self.image(profile_id)),'animeFeaturesPath':str(self.path(profile_id,'.safetensors'))},cancelled)
            box = Face.model_validate({'index':0,'box':result['faceBox']}).box
            with Image.open(self.image(profile_id)) as image:
                if box[2]>image.width or box[3]>image.height: raise ValueError('动漫脸区域超出图片')
            if result.get('ok') is not True: raise ValueError('动漫特征提取失败')
            self.verify_features(profile_id,result['featureKey'])
            with s._lock:
                if cancelled.is_set(): raise WorkerCancelled()
                self.save({**self.records[profile_id],'state':'ready','featureKey':result['featureKey'],
                           'faceBox':box,'parentFeatureKey':result['parentFeatureKey'],'error':None})
        except Exception as exc:
            with s._lock:
                self.failed(profile_id,'动漫建档取消或中断' if cancelled.is_set() else f'动漫建档失败：{exc}')

    def verify_features(self, profile_id, digest):
        path = self.path(profile_id,'.safetensors')
        if (not path.is_file() or not 0<path.stat().st_size<=8*1024**2
            or hashlib.sha256(path.read_bytes()).hexdigest()!=digest):
            raise DreamApiError('ANIME_FEATURES_INVALID','动漫特征缺失或校验失败，请重新建档',status_code=409)
        return path

    def resolve_request(self, request):
        if not request.get('facePolish') or not request.get('animeProfileId'): return {}
        with self.service._lock:
            record = self.get(request['animeProfileId'])
            parent = self.service.profiles.get(record['profileId'])
            if (record['state']!='ready' or parent['state']!='ready'
                or parent.get('referenceKind', 'faceid') != 'faceid'
                or request['modelId']!='illustrious-xl-v2.0-faceid'
                or any(record[k]!=request[k] or parent[k]!=record[k] for k in ('referenceId','faceIndex'))):
                raise DreamApiError('ANIME_PROFILE_CONFLICT','动漫档案尚未就绪或不属于当前参考人物',status_code=409)
            features = self.verify_features(record['id'],record['featureKey'])
            return {'animeProfile':record,'animeImagePath':str(self.image(record['id'])),'animeFeaturesPath':str(features)}
