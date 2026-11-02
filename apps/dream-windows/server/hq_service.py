"""Local HQ originals and durable, single-attempt generation on Dream's GPU queue.

The only network operations are bounded GETs to the owner's existing R2 Worker.
Credentials stay in the configured server-side session file. There is no cloud
queue, executor registration or result upload in this service.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import os
import re
import threading
import time
import unicodedata
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit

import httpx
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator

from config import DreamServerConfig
from errors import DreamApiError
from identity_service import IdentityService, ReferenceUpload, StorageOwnerLease, WorkerCancelled, atomic_json, read_json, hq_pixel_fingerprint
from identity_contract import IdentityGenerateRequest
from history_transactions import validate_history_path, history_deletion_flags
from job_runner import JobRunner
import hq_paired_depth as paired_depth

ORIGIN = 'https://hq-tryon-picker.qujindai1986.workers.dev'
ROLES = ('person', 'garment', 'pose')
TERMINAL = {'succeeded', 'failed', 'cancelled'}
JOB_RE = re.compile(r'^hq-[a-f0-9]{64}$')
SHA_RE = re.compile(r'^[a-f0-9]{64}$')
ASSET_RE = re.compile(r'^[A-Za-z0-9_-]{2,64}$')
MAX_IMAGE = 8 * 1024 * 1024
MAX_RESULT = 32 * 1024 * 1024
PIPELINE = paired_depth.LEGACY_PIPELINE


class HQParameters(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)
    seed: int = Field(default=20261104, ge=0, le=2147483647)
    width: int = Field(default=768, ge=256, le=1152, multiple_of=64)
    height: int = Field(default=1152, ge=256, le=1152, multiple_of=64)
    steps: int = Field(default=30, ge=1, le=50)

    @model_validator(mode='after')
    def pixel_budget(self):
        if self.width * self.height > 768 * 1152:
            raise ValueError('HQ 高清生成最多 768×1152 像素')
        return self


class HQCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    personId: str = Field(pattern=r'^[a-f0-9]{64}$')
    garmentId: str = Field(pattern=r'^[A-Za-z0-9_-]{2,64}$')
    poseId: str = Field(pattern=r'^[A-Za-z0-9_-]{2,64}$')
    idempotencyKey: str = Field(pattern=r'^[A-Za-z0-9._:-]{8,128}$')
    profileId: str | None = Field(default=None, pattern=r'^person-[a-f0-9]{24}$')
    facePolish: bool = False
    faceRestoreStrength: float = Field(default=.35, ge=0, le=1)
    parameters: HQParameters = Field(default_factory=HQParameters)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def _fail(code: str, message: str, status: int = 503):
    raise DreamApiError(code, message, status_code=status)


def _error(value: Any, fallback='PIPELINE_FAILED') -> dict[str, str]:
    value = value if isinstance(value, dict) else {}
    code = value.get('code')
    if not isinstance(code, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{1,63}', code):
        code = fallback
    message = str(value.get('message') or 'HQ 本地任务失败，请检查本地审计记录')[:600]
    message = re.sub(r'(?i)bearer\s+[^\s,;]+', 'Bearer [redacted]', message)
    message = re.sub(r'(?i)(token|secret|authorization|credential)\s*[=:]\s*[^\s,;]+', r'\1=[redacted]', message)
    return {'code': code, 'message': message}


def _public_audit(value: Any, depth=0) -> Any:
    # The CLI never receives a vault token. Defense in depth for future audit fields.
    if depth > 14:
        return None
    if isinstance(value, dict):
        return {str(k): _public_audit(v, depth + 1) for k, v in list(value.items())[:256]
                if not re.search(r'(?i)token|secret|credential|authorization|session', str(k))}
    if isinstance(value, list):
        return [_public_audit(v, depth + 1) for v in value[:512]]
    if isinstance(value, str):
        return re.sub(r'(?i)bearer\s+[^\s,;]+', 'Bearer [redacted]', value[:4000])
    return value if value is None or type(value) in (int, float, bool) else None


class HQService:
    def __init__(self, config: DreamServerConfig, job_runner: JobRunner, *,
                 identity_service: IdentityService, client: httpx.Client | None = None):
        self.config, self.job_runner = config, job_runner
        self.root = (config.dream_root / 'data' / 'hq').resolve()
        self.config_path = self.root / 'config.json'
        self.identity = identity_service
        self.client = client or httpx.Client(timeout=httpx.Timeout(30, connect=10), follow_redirects=False, trust_env=False)
        self._own_client = client is None
        self._preparation = ThreadPoolExecutor(max_workers=2, thread_name_prefix='hq-prepare')
        self._lease = StorageOwnerLease(self.root / 'owner.lock')
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._submission_lock = threading.Lock()
        self._catalog_lock = threading.Lock()
        self._started = self._closing = self._closed = False
        self._active = 0
        self._jobs: dict[str, dict] = {}
        self._futures: dict[str, Any] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._person_cache: tuple[str, float, list[dict], bool] | None = None
        self._auth_cache: tuple[str, float] | None = None

    def _safe(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            _fail('HQ_PATH_INVALID', 'HQ 文件路径无效', 400)
        return resolved

    def _folder(self, job_id: str) -> Path:
        if not isinstance(job_id, str) or not JOB_RE.fullmatch(job_id):
            _fail('HQ_JOB_NOT_FOUND', '找不到 HQ 任务', 404)
        return self._safe(self.root / 'jobs' / job_id)

    def start(self) -> None:
        with self._lock:
            if self._closing or self._closed:
                _fail('HQ_SERVICE_CLOSED', 'HQ 服务正在关闭')
            if self._started:
                return
            try:
                self._lease.acquire()
            except DreamApiError as exc:
                raise DreamApiError('HQ_STORAGE_BUSY', 'HQ 数据由另一个 Dream 实例占用', status_code=503) from exc
            try:
                # Recover/quarantine identity children before any HQ or history
                # route can observe old terminal or interrupted artifacts.
                self.identity._ensure_recovered()
                jobs = self._safe(self.root / 'jobs')
                jobs.mkdir(exist_ok=True)
                for folder in jobs.iterdir():
                    if not JOB_RE.fullmatch(folder.name):
                        continue
                    path = self._safe(folder / 'record.json')
                    if not path.is_file():
                        # A reservation without a record is never reused or regenerated.
                        continue
                    record = read_json(path)
                    if record.get('id') != folder.name or not SHA_RE.fullmatch(str(record.get('requestDigest', ''))):
                        _fail('HQ_STORAGE_INVALID', 'HQ 任务记录损坏；请保留文件供检查')
                    self._jobs[folder.name] = record
                    if record.get('state') not in TERMINAL:
                        if record.get('identityJobId'):
                            try:
                                child = self.identity.get(record['identityJobId'])
                                self._mirror_identity(record, child)
                            except DreamApiError as exc:
                                if exc.code == 'IDENTITY_STORAGE_BUSY':
                                    raise
                            if record['state'] in TERMINAL:
                                continue
                        record.update(state='failed', phase='interrupted', updatedAt=_now(), completedAt=_now(),
                                      error={'code': 'EXECUTOR_INTERRUPTED', 'message': 'Dream 已重启；此任务不会自动重新推理，原始素材与产物已保留'})
                        atomic_json(path, record)
                    self._jobs[folder.name] = record
                self._started = True
            except BaseException:
                self._lease.close()
                raise

    @contextmanager
    def _operation(self):
        with self._condition:
            self.start()
            self._active += 1
        try:
            yield
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    def _settings(self) -> dict:
        try:
            data = read_json(self.config_path, 16384)
            if data.get('origin') != ORIGIN:
                _fail('HQ_ORIGIN_INVALID', 'HQ origin 必须是已授权的自有 Cloudflare Worker', 503)
            for key in ('sessionFile', 'pipelineConfig', 'python'):
                if not isinstance(data.get(key), str) or not Path(data[key]).is_absolute():
                    _fail('HQ_CONFIG_INVALID', 'HQ 本地配置缺少有效的绝对路径')
            # Only this config file, never request payloads, selects local runtime paths.
            return data
        except (OSError, ValueError):
            _fail('HQ_NOT_CONFIGURED', '请配置本机 HQ 素材连接与推理管线')

    def _session(self, settings: dict) -> tuple[str, str]:
        try:
            data = read_json(Path(settings['sessionFile']), 4096)
            token, expires = data.get('token'), data.get('expiresAt')
            if not isinstance(token, str) or not SHA_RE.fullmatch(token) or type(expires) is not int:
                raise ValueError()
            if expires <= int(time.time() * 1000):
                _fail('HQ_AUTH_EXPIRED', 'HQ 人物图库授权已到期，请由已授权连接器更新本机会话', 401)
            return token, _sha(token.encode())
        except (OSError, ValueError):
            _fail('HQ_AUTH_REQUIRED', 'HQ 人物图库尚未授权', 401)

    def _url(self, value: str) -> str:
        url = ORIGIN + value if value.startswith('/') and not value.startswith('//') else value
        try:
            parsed = urlsplit(url)
            if (parsed.scheme != 'https' or parsed.netloc != urlsplit(ORIGIN).netloc
                    or parsed.username or parsed.password or parsed.fragment or '\\' in url):
                raise ValueError()
        except (ValueError, AttributeError):
            _fail('HQ_UPSTREAM_ORIGIN', '已拒绝非自有 R2 地址', 502)
        return url

    def _get(self, value: str, *, private=False, limit=MAX_IMAGE, settings=None, check_cancel=None) -> tuple[bytes, httpx.Headers]:
        for attempt in range(2):
            try:
                if check_cancel:
                    check_cancel()
                return self._get_once(value, private=private, limit=limit, settings=settings, check_cancel=check_cancel)
            except (httpx.TimeoutException, httpx.ConnectError):
                if attempt:
                    _fail('HQ_UPSTREAM_UNAVAILABLE', '无法连接 HQ 自有 R2 素材服务', 502)
                # Only idempotent GETs retry, once; credentials are revalidated and redirects stay disabled.
                time.sleep(.1)
            except httpx.HTTPError:
                _fail('HQ_UPSTREAM_UNAVAILABLE', '无法连接 HQ 自有 R2 素材服务', 502)
        raise AssertionError('unreachable')

    def _get_once(self, value: str, *, private=False, limit=MAX_IMAGE, settings=None, check_cancel=None) -> tuple[bytes, httpx.Headers]:
        url = self._url(value)  # Validate before obtaining or sending any credential.
        headers = {'Accept': 'application/json, image/png, image/jpeg, image/webp', 'Accept-Encoding': 'identity'}
        if private:
            if not urlsplit(url).path.startswith('/api/person/'):
                _fail('HQ_UPSTREAM_ORIGIN', '人物授权仅用于自有私有图库路径', 502)
            token, _ = self._session(settings or self._settings())
            headers['Authorization'] = 'Bearer ' + token
        try:
            with self.client.stream('GET', url, headers=headers, follow_redirects=False) as response:
                if 300 <= response.status_code < 400:
                    _fail('HQ_UPSTREAM_REDIRECT', 'R2 素材读取不接受重定向', 502)
                if response.status_code in (401, 403):
                    _fail('HQ_AUTH_REQUIRED', 'HQ 人物图库授权失效，请更新本机会话', 401)
                if response.status_code == 404:
                    _fail('HQ_ASSET_NOT_FOUND', 'R2 原图不存在', 404)
                if response.status_code != 200:
                    _fail('HQ_UPSTREAM_UNAVAILABLE', 'HQ 自有 R2 素材服务暂不可用', 502)
                length = response.headers.get('content-length')
                if length is not None and (not length.isdigit() or int(length) > limit):
                    _fail('HQ_ASSET_TOO_LARGE', 'R2 响应超过大小限制', 413)
                data = bytearray()
                for chunk in response.iter_bytes():
                    if check_cancel:
                        check_cancel()
                    if len(data) + len(chunk) > limit:
                        _fail('HQ_ASSET_TOO_LARGE', 'R2 响应超过大小限制', 413)
                    data.extend(chunk)
                return bytes(data), response.headers
        except httpx.HTTPError:
            raise

    def _json_get(self, path: str, *, private=False, settings=None, check_cancel=None) -> dict:
        data, _ = self._get(path, private=private, settings=settings, limit=2 * 1024 * 1024, check_cancel=check_cancel)
        try:
            result = json.loads(data)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (ValueError, UnicodeError):
            _fail('HQ_UPSTREAM_INVALID', 'R2 图库返回的数据无效', 502)

    def _authorized(self, settings: dict) -> str:
        _, fingerprint = self._session(settings)
        if not self._auth_cache or self._auth_cache[0] != fingerprint or time.monotonic() > self._auth_cache[1]:
            result = self._json_get('/api/person/list?limit=1', private=True, settings=settings)
            if not isinstance(result.get('items'), list):
                _fail('HQ_UPSTREAM_INVALID', '人物图库返回的数据无效', 502)
            self._auth_cache = (fingerprint, time.monotonic() + 15)
        return fingerprint

    def _ready(self, settings: dict) -> bool:
        if not Path(settings['python']).is_file():
            return False
        try:
            from hq_tryon_pipeline import readiness
            from identity_worker import load_config
            resolved = load_config({'configPath': str(self.identity.config_path), 'modelId': 'realistic-vision-v5.1-faceid'})
            return readiness(settings['pipelineConfig'], resolved).get('ready') is True
        except (ImportError, OSError, ValueError, TypeError):
            return False

    @staticmethod
    def _pipeline(settings):
        try:
            return paired_depth.pipeline_id(read_json(Path(settings['pipelineConfig']), 64 * 1024))
        except (OSError, ValueError, TypeError):
            _fail('MODEL_NOT_READY', '无法读取本机 HQ 管线配置')

    def status(self) -> dict:
        with self._operation():
            result = {'configured': False, 'authorized': False, 'modelReady': False, 'pipelineFilesPresent': False,
                      'executionValidated': False, 'pipeline': PIPELINE, 'readiness': 'not-configured', 'error': None}
            try:
                settings = self._settings()
                result['configured'] = True
                result['pipeline'] = self._pipeline(settings)
                if result['pipeline'] == paired_depth.PIPELINE:
                    result['supportedPoseIds'] = [item['id'] for item in paired_depth.catalog()['items']]
                result['modelReady'] = self._ready(settings)
                result['pipelineFilesPresent'] = result['modelReady']
                result['readiness'] = 'files-present' if result['modelReady'] else 'missing-files'
                if result['modelReady']:
                    configuration_hash = _sha(Path(settings['pipelineConfig']).read_bytes())
                    with self._lock:
                        result['executionValidated'] = any(
                            row['state'] == 'succeeded' and (row.get('audit') or {}).get('pipeline') == result['pipeline']
                            and (row.get('audit') or {}).get('configuration', {}).get('sha256') == configuration_hash
                            for row in self._jobs.values())
                self._authorized(settings)
                result['authorized'] = True
                if not result['modelReady']:
                    result['error'] = {'code': 'MODEL_NOT_READY', 'message': '本机 HQ 推理管线或模型文件尚未齐备'}
            except DreamApiError as exc:
                result['error'] = _error({'code': exc.code, 'message': exc.message})
            with self._lock:
                result['gpuReleaseBlocked'] = self.identity.gpu_release_blocked
                if result['gpuReleaseBlocked']:
                    result['error'] = {'code': 'HQ_WORKER_RELEASE_FAILED', 'message': '共享 GPU 队列正在等待已拥有子进程退出确认，后续推理已阻止'}
            return result

    @staticmethod
    def _item(row: dict, kind: str) -> dict:
        identifier = row.get('id') if isinstance(row, dict) else None
        pattern = SHA_RE if kind == 'person' else ASSET_RE
        if not isinstance(identifier, str) or not pattern.fullmatch(identifier):
            _fail('HQ_UPSTREAM_INVALID', 'R2 素材编号无效', 502)
        item = {key: row[key] for key in ('id', 'width', 'height', 'size') if key in row and type(row[key]) in (str, int)}
        for key in ('label', 'name', 'category', 'sha256', 'fullSha256', 'thumbSha256'):
            if isinstance(row.get(key), str):
                item[key] = row[key][:160]
        item['imageUrl'] = '/api/hq/asset?' + urlencode({'kind': kind, 'id': identifier})
        item['thumbnailUrl'] = item['imageUrl'] + '&thumbnail=1'
        return item

    def catalog(self, kind: str, q='', category='', page=0, limit=24) -> dict:
        with self._operation():
            settings = self._settings()
            if kind not in ROLES or type(page) is not int or not 0 <= page <= 1000 or type(limit) is not int or not 1 <= limit <= 48:
                _fail('REQUEST_INVALID', '图库查询参数无效', 422)
            if not isinstance(q, str) or len(q) > 100 or not isinstance(category, str) or len(category) > 160:
                _fail('REQUEST_INVALID', '图库筛选参数无效', 422)
            if kind != 'person':
                if kind == 'pose' and self._pipeline(settings) == paired_depth.PIPELINE:
                    manifest = paired_depth.catalog()
                    needle = unicodedata.normalize('NFKC', q).casefold()
                    poses = manifest['items']
                    matched = [item for item in poses if (not category or category == item['category']) and
                               needle in unicodedata.normalize('NFKC', item['id'] + ' ' + item['label']).casefold()]
                    start = page * limit
                    return {'kind': kind, 'items': [self._item(item, kind) for item in matched[start:start + limit]],
                            'total': len(matched), 'hasMore': start + limit < len(matched), 'page': page,
                            'limit': limit, 'categories': sorted({item['category'] for item in poses}),
                            'sourceMode': 'owned-r2-paired-depth', 'release': manifest['release']}
                result = self._json_get('/api/catalog?' + urlencode(dict(kind=kind, q=q, category=category, page=page, limit=limit)))
                if (not isinstance(result.get('items'), list) or len(result['items']) > 48
                        or type(result.get('total')) is not int or type(result.get('hasMore')) is not bool):
                    _fail('HQ_UPSTREAM_INVALID', 'R2 图库分页无效', 502)
                return {'kind': kind, 'items': [self._item(row, kind) for row in result['items']],
                        'total': result['total'], 'hasMore': result['hasMore'], 'page': page, 'limit': limit,
                        'categories': [x[:160] for x in result.get('categories', []) if isinstance(x, str)][:512],
                        'sourceMode': 'owned-r2', 'release': str(result.get('release', ''))[:64]}
            with self._catalog_lock:
                fingerprint = self._authorized(settings)
                if not self._person_cache or self._person_cache[0] != fingerprint or time.monotonic() > self._person_cache[1]:
                    rows, seen, cursor, more = {}, set(), None, False
                    for _ in range(20):  # Existing person endpoint has cursor pagination and no total.
                        query = {'limit': 24, **({'cursor': cursor} if cursor else {})}
                        data = self._json_get('/api/person/list?' + urlencode(query), private=True, settings=settings)
                        if not isinstance(data.get('items'), list) or len(data['items']) > 24:
                            _fail('HQ_UPSTREAM_INVALID', '人物图库分页无效', 502)
                        for row in data['items']:
                            item = self._item(row, kind)
                            rows[item['id']] = item
                        more = data.get('hasMore') is True
                        if not more:
                            break
                        cursor = data.get('nextCursor')
                        if not isinstance(cursor, str) or not cursor or len(cursor) > 2048 or cursor in seen:
                            _fail('HQ_UPSTREAM_INVALID', '人物图库游标无效', 502)
                        seen.add(cursor)
                    self._person_cache = (fingerprint, time.monotonic() + 30, list(rows.values()), more)
                items, bounded = self._person_cache[2:]
                needle = unicodedata.normalize('NFKC', q).casefold()
                matching = [item for item in items if not category and (not needle or needle in unicodedata.normalize(
                    'NFKC', ' '.join(str(item.get(k, '')) for k in ('id', 'name', 'label'))).casefold())]
                offset = page * limit
                return {'kind': kind, 'items': copy.deepcopy(matching[offset:offset + limit]), 'total': len(matching),
                        'hasMore': offset + limit < len(matching), 'categories': [], 'page': page, 'limit': limit,
                        'bounded': bounded, 'sourceMode': 'owned-r2-private'}

    def _image(self, raw: bytes, digest: str, declared: str | None = None) -> dict:
        if not SHA_RE.fullmatch(str(digest)) or _sha(raw) != digest:
            _fail('HQ_HASH_MISMATCH', 'R2 原图 SHA-256 校验失败', 422)
        try:
            with Image.open(io.BytesIO(raw)) as image:
                mime = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}.get(image.format)
                width, height = image.size
                if (not mime or width < 1 or height < 1 or width > 8192 or height > 8192
                        or width * height > 32_000_000 or getattr(image, 'n_frames', 1) != 1):
                    raise ValueError()
                if declared and declared.split(';')[0].strip().lower() != mime:
                    raise ValueError()
                image.verify()
        except (OSError, ValueError, Image.DecompressionBombError, SyntaxError):
            _fail('HQ_IMAGE_INVALID', '素材不是受支持的完整 PNG、JPEG 或 WebP 原图', 415)
        return {'sha256': digest, 'mime': mime, 'size': len(raw), 'width': width, 'height': height,
                'dimensions': {'width': width, 'height': height}}

    def _asset(self, kind: str, identifier: str, thumbnail=False, settings=None, check_cancel=None) -> tuple[bytes, dict]:
        if kind not in ROLES or not isinstance(identifier, str) or not (SHA_RE if kind == 'person' else ASSET_RE).fullmatch(identifier):
            _fail('REQUEST_INVALID', '素材类型或编号无效', 422)
        if kind == 'person':
            raw, headers = self._get('/api/person/image/' + identifier, private=True, settings=settings, check_cancel=check_cancel)
            expected = identifier
        else:
            data = self._json_get('/api/asset?' + urlencode({'kind': kind, 'id': identifier}), check_cancel=check_cancel)
            item = data.get('item')
            if not isinstance(item, dict) or item.get('id') != identifier:
                _fail('HQ_UPSTREAM_INVALID', 'R2 原图记录不匹配', 502)
            value = item.get('thumbUrl' if thumbnail else 'fullUrl')
            expected = item.get('thumbSha256' if thumbnail else 'fullSha256')
            if not isinstance(value, str) or not SHA_RE.fullmatch(str(expected)):
                _fail('HQ_UPSTREAM_INVALID', 'R2 原图记录缺少地址或校验值', 502)
            url = self._url(value)
            role = 'thumb' if thumbnail else 'original'
            pattern = r'/assets/[A-Za-z0-9_-]{6,64}/' + kind + '/' + re.escape(identifier) + '/' + role + r'\.(png|jpg|jpeg|webp)'
            if urlsplit(url).query or not re.fullmatch(pattern, urlsplit(url).path):
                _fail('HQ_UPSTREAM_ORIGIN', 'R2 素材地址与角色不匹配', 502)
            raw, headers = self._get(url, check_cancel=check_cancel)
        if headers.get('x-content-sha256') not in (None, expected):
            _fail('HQ_HASH_MISMATCH', 'R2 原图校验头不匹配', 422)
        return raw, self._image(raw, expected, headers.get('content-type'))

    def asset(self, kind: str, identifier: str, thumbnail=False) -> tuple[bytes, dict]:
        with self._operation():
            return self._asset(kind, identifier, thumbnail, self._settings())

    def _save(self, record: dict) -> None:
        record['updatedAt'] = _now()
        atomic_json(self._folder(record['id']) / 'record.json', record)
        self._jobs[record['id']] = record

    def _view(self, record: dict) -> dict:
        fields = ('id', 'state', 'phase', 'progress', 'cancellationRequested', 'createdAt', 'updatedAt', 'completedAt',
                  'startedAt', 'parameters', 'idempotencyKey', 'inputs', 'result', 'error', 'audit',
                  'profileId', 'facePolish', 'faceRestoreStrength', 'requestedInputIds', 'identityJobId', 'identityResult', 'referenceId', 'pipeline')
        result = {key: record.get(key) for key in fields}
        result['pipeline'] = record.get('pipeline') or (record.get('audit') or {}).get('pipeline')
        result.update(output=record.get('result'), outputSha256=(record.get('result') or {}).get('sha256'))
        deleted = history_deletion_flags(self.config.dream_root).get(record.get('identityJobId'))
        result['refinementsAvailable'] = bool(record.get('identityJobId') and record['state'] == 'succeeded' and not deleted)
        if deleted:
            result.update(historyDeleted=True, resultDeleted=deleted.get('resultDeleted', False),
                          result=None, output=None, outputSha256=None, identityResult=None)
        return copy.deepcopy(result)

    def create_job(self, payload: HQCreateRequest) -> tuple[dict, bool]:
        with self._operation(), self._submission_lock:
            payload = HQCreateRequest.model_validate(payload)
            values = payload.model_dump()
            ids = {name: 'hq-' + _sha(('local-hq-v2\0' + name + '\0' + payload.idempotencyKey).encode())
                   for name in (PIPELINE, paired_depth.PIPELINE)}
            with self._lock:
                for name, candidate in ids.items():
                    prior = self._jobs.get(candidate)
                    if not prior:
                        continue
                    if prior['requestDigest'] != _sha(_canonical({'pipeline': name, 'request': values})):
                        _fail('IDEMPOTENCY_CONFLICT', '此幂等键已用于另一组三图、档案或参数', 409)
                    return self._view(prior), True
            settings = self._settings()
            self._session(settings)
            pipeline = self._pipeline(settings)
            if pipeline == paired_depth.PIPELINE and not any(item['id'] == payload.poseId for item in paired_depth.catalog()['items']):
                _fail('HQ_DEPTH_UNAVAILABLE', '请在姿势页选择已有配对深度图的姿势', 422)
            job_id = ids[pipeline]
            digest = _sha(_canonical({'pipeline': pipeline, 'request': values}))
            if not self._ready(settings):
                _fail('MODEL_NOT_READY', '本机 HQ 人物条件模型尚未齐备')
            folder = self._folder(job_id)
            if folder.exists():
                _fail('HQ_STORAGE_INCOMPLETE', '此任务已有保留目录，禁止自动重试推理', 409)
            folder.mkdir(parents=True)
            (folder / 'inputs').mkdir()
            child_id = self.identity.hq_child_id(job_id)
            record = {'id': job_id, 'requestDigest': digest, 'idempotencyKey': payload.idempotencyKey, 'pipeline': pipeline,
                      'state': 'queued', 'phase': 'queued', 'progress': 0, 'cancellationRequested': False,
                      'createdAt': _now(), 'startedAt': None, 'completedAt': None, 'parameters': values['parameters'],
                      'requestedInputIds': {role: values[role + 'Id'] for role in ROLES},
                      'profileId': payload.profileId, 'facePolish': payload.facePolish,
                      'faceRestoreStrength': payload.faceRestoreStrength, 'identityJobId': child_id,
                      'referenceId': None, 'identityResult': None, 'inputs': [], 'result': None, 'error': None, 'audit': None}
            atomic_json(folder / 'request.json', {'requested': values, 'identityJobId': child_id})
            with self._lock:
                self._save(record)  # Includes the deterministic child ID BEFORE any background work or dispatch.
                self._cancel[job_id] = threading.Event()
                try:
                    self._futures[job_id] = self._preparation.submit(self._prepare_identity, job_id, settings)
                except RuntimeError:
                    record.update(state='failed', phase='interrupted', completedAt=_now(),
                                  error={'code': 'EXECUTOR_INTERRUPTED', 'message': 'HQ 准备服务正在停止'})
                    self._save(record)
                return self._view(record), False

    def _check_cancel(self, job_id):
        with self._lock:
            if self._closing or self._cancel[job_id].is_set() or self._jobs[job_id]['state'] in TERMINAL:
                raise WorkerCancelled()

    def _prepare_identity(self, job_id, settings):
        try:
            with self._operation():
                folder = self._folder(job_id)
                record = self._jobs[job_id]
                check = lambda: self._check_cancel(job_id)
                try:
                    check()
                    with self._lock:
                        record['phase'] = 'downloading'
                        self._save(record)
                    inputs = {}
                    for role in ROLES:
                        check()
                        identifier = record['requestedInputIds'][role]
                        raw, info = self._asset(role, identifier, settings=settings, check_cancel=check)
                        check()
                        extension = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}[info['mime']]
                        path = self._safe(folder / 'inputs' / (role + extension))
                        with path.open('xb') as stream:
                            stream.write(raw)
                            stream.flush()
                            os.fsync(stream.fileno())
                        if _sha(path.read_bytes()) != info['sha256']:
                            _fail('HQ_INPUT_WRITE_FAILED', '本地原图副本校验失败')
                        inputs[role] = {'path': str(path), 'id': identifier, 'sha256': info['sha256']}
                        with self._lock:
                            record['inputs'].append({'role': role, 'id': identifier, **info,
                                                     'imageUrl': f'/api/hq/jobs/{job_id}/inputs/{role}'})
                            record['progress'] = len(inputs)
                            self._save(record)
                    check()
                    with self._lock:
                        record['phase'] = 'identifying'
                        self._save(record)
                    request = self._identity_request(record, Path(inputs['person']['path']), self._cancel[job_id])
                    check()
                    conditioning = {'jobId': job_id, 'pipeline': record['pipeline'], 'configPath': str(Path(settings['pipelineConfig']).resolve()), 'inputs': inputs,
                                    'auditPath': str(self._safe(folder / 'audit.json')),
                                    'eventPath': str(self._safe(folder / 'events.jsonl')),
                                    'cancelPath': str(self._safe(folder / 'cancel.flag'))}
                    atomic_json(folder / 'request.json', {'identityJobId': record['identityJobId'],
                                'identityRequest': request.model_dump(), 'hqConditioning': conditioning})
                    with self._lock:
                        check()
                        record.update(referenceId=request.referenceId, phase='identity_queued')
                        self._save(record)
                        # The trusted method persists its child before scheduling the shared GPU queue.
                        child = self.identity.submit_hq(hq_job_id=job_id, request_digest=record['requestDigest'],
                                                        request=request, conditioning=conditioning)
                    while True:
                        if self._cancel[job_id].is_set() or self._closing:
                            self._cancel_child(record)
                        child = self.identity.get(record['identityJobId'])
                        self._mirror_identity(record, child)
                        if child['state'] in {'complete', 'failed', 'cancelled'}:
                            break
                        self._cancel[job_id].wait(.15)
                except Exception as exc:
                    with self._lock:
                        if record['state'] not in TERMINAL:
                            cancelled = self._cancel[job_id].is_set() or isinstance(exc, WorkerCancelled)
                            error = {'code': getattr(exc, 'code', 'HQ_PREPARATION_FAILED'),
                                     'message': getattr(exc, 'message', 'HQ 人物任务准备失败；已有原图保留')}
                            record.update(state='cancelled' if cancelled else 'failed', phase='cancelled' if cancelled else 'failed',
                                          error=None if cancelled else _error(error), completedAt=_now())
                            self._save(record)
        except DreamApiError as exc:
            if exc.code != 'HQ_SERVICE_CLOSED':
                raise

    def _identity_request(self, record, original: Path, cancelled: threading.Event) -> IdentityGenerateRequest:
        defaults = {}
        if record['profileId']:
            profile = self.identity.profile_operation('get', record['profileId'])
            if profile.get('state') != 'ready' or profile.get('referenceKind', 'faceid') != 'faceid':
                _fail('HQ_PROFILE_INVALID', '请选择已就绪的 FaceID 人物档案', 409)
            reference_id, face_index = profile['referenceId'], profile['faceIndex']
            if hq_pixel_fingerprint(original) != hq_pixel_fingerprint(self.identity.reference_image(reference_id)):
                _fail('HQ_PERSON_MISMATCH', 'R2 人物原图与所选档案参考图像素不一致，未自动替换人物', 409)
            saved = profile.get('defaults', {})
            if saved.get('modelId', 'realistic-vision-v5.1-faceid') != 'realistic-vision-v5.1-faceid':
                _fail('HQ_PROFILE_MODEL_UNSUPPORTED', '所选档案预设不是 RV FaceID；请使用兼容档案，未移植其他底模或风格 LoRA', 409)
            if record.get('pipeline') != paired_depth.PIPELINE:
                defaults = {k: saved[k] for k in ('cfg', 'identityStrength', 'structureStrength', 'faceLoraStrength') if k in saved}
        else:
            # upload() schedules and awaits face inspection; this method runs on the I/O pool, never the GPU queue.
            reference = self.identity.upload(ReferenceUpload(name='HQ person ' + record['requestedInputIds']['person'][:12],
                    imageBase64=base64.b64encode(original.read_bytes()).decode('ascii'), referenceKind='faceid'), cancelled)
            if len(reference['faces']) != 1:
                _fail('HQ_PERSON_AMBIGUOUS', '人物原图必须只有一张可识别的人脸；请先建立并选择明确人脸的档案', 422)
            reference_id, face_index = reference['id'], reference['faces'][0]['index']
        defaults.update(modelId='realistic-vision-v5.1-faceid', referenceId=reference_id, faceIndex=face_index,
                        prompt='full body fashion photograph of one person, wearing the reference garment, natural proportions, detailed fabric, neutral studio background',
                        negativePrompt='low quality, blurry, deformed anatomy, extra limbs, duplicate person, text, watermark',
                        loraId=None,
                        animeProfileId=None, traceLevel='off', researchCoverage='representative',
                        facePolish=record['facePolish'], faceRestoreStrength=record['faceRestoreStrength'], **record['parameters'])
        return IdentityGenerateRequest.model_validate(defaults)

    def _cancel_child(self, record):
        try:
            child = self.identity.get(record['identityJobId'])
            if child.get('hqBinding', {}).get('hqJobId') == record['id'] and child['state'] not in {'complete', 'failed', 'cancelled'}:
                self.identity.cancel(record['identityJobId'])
        except DreamApiError as exc:
            if exc.code != 'IDENTITY_JOB_NOT_FOUND':
                raise

    def _mirror_identity(self, record, child):
        if (child.get('hqBinding', {}) != {'hqJobId': record['id'], 'requestDigest': record['requestDigest']}
                or child.get('id') != record['identityJobId']):
            _fail('HQ_BINDING_INVALID', '人物子任务归属不匹配')
        with self._lock:
            audit_path = self._safe(self._folder(record['id']) / 'audit.json')
            if child['state'] in {'complete', 'failed', 'cancelled'} and audit_path.is_file():
                try:
                    audit = read_json(audit_path)
                    if (audit.get('jobId') == record['identityJobId'] and audit.get('pipeline') == record.get('pipeline', PIPELINE)
                            and audit.get('parentJobId') == record['id']):
                        record['audit'] = _public_audit(audit)
                except (OSError, ValueError):
                    pass  # An incomplete audit never turns a failed attempt into success.
            if record['state'] in TERMINAL:
                self._save(record)
                return
            state = child['state']
            if state == 'complete':
                if record['identityJobId'] in history_deletion_flags(self.config.dream_root):
                    record.update(state='succeeded', phase='complete', progress=100, completedAt=_now(),
                                  result=None, identityResult=None, error=None)
                    self._save(record)
                    return
                path, metadata = self._identity_result_path(record, child)
                audit = metadata.get('hq')
                if not isinstance(audit, dict) or audit.get('pipeline') != record.get('pipeline', PIPELINE) or audit.get('status') != 'completed':
                    _fail('HQ_AUDIT_INVALID', '人物子任务缺少真实三图绑定审计')
                info = self._image(path.read_bytes(), audit['output']['sha256'], 'image/png')
                record.update(state='succeeded', phase='complete', progress=100, completedAt=_now(),
                              identityResult=_public_audit(child['result']), audit=_public_audit(audit),
                              result={**info, 'imageUrl': f"/api/hq/jobs/{record['id']}/result", 'metadata': _public_audit(metadata)})
            elif state in {'failed', 'cancelled'}:
                record.update(state=state, phase=state, completedAt=_now(),
                              error=None if state == 'cancelled' else _error({'code': child.get('errorCode', 'IDENTITY_WORKER_FAILED'),
                                                                            'message': child.get('error') or '人物子任务失败'}))
            else:
                record.update(state='queued' if state == 'queued' else 'running', phase='identity_queued' if state == 'queued' else state,
                              progress=child.get('progress', 0))
                if record.get('cancellationRequested'):
                    record['phase'] = 'cancelling'
                if state != 'queued' and not record['startedAt']:
                    record['startedAt'] = _now()
            self._save(record)

    def _identity_result_path(self, record, child=None):
        if record['identityJobId'] in history_deletion_flags(self.config.dream_root):
            _fail('HQ_RESULT_DELETED', '此人物作品已从历史删除，HQ 不再提供成片或精修版本', 404)
        child = child or self.identity.get(record['identityJobId'])
        if child['state'] != 'complete' or child.get('hqBinding', {}).get('hqJobId') != record['id']:
            _fail('HQ_RESULT_NOT_READY', '人物成片尚未完成', 409)
        result = child['result']
        metadata = result['metadata']
        path = validate_history_path(self.config.dream_root, Path(metadata['output']))
        relative = path.relative_to(self.config.dream_root.resolve())
        if (metadata.get('id') != record['identityJobId'] or result.get('imageUrl') != f"/api/history/{record['identityJobId']}/image"
                or len(relative.parts) != 3 or relative.parts[0] != 'outputs' or path.name != record['identityJobId'] + '.png'
                or not path.is_file() or not 0 < path.stat().st_size <= MAX_RESULT):
            _fail('HQ_OUTPUT_INVALID', '人物成片路径或归属无效')
        return path, metadata

    def jobs(self) -> dict:
        with self._operation(), self._lock:
            return {'jobs': [self._view(row) for row in sorted(self._jobs.values(), key=lambda x: x['createdAt'], reverse=True)]}

    def get_job(self, job_id: str) -> dict:
        with self._operation(), self._lock:
            self._folder(job_id)
            if job_id not in self._jobs:
                _fail('HQ_JOB_NOT_FOUND', '找不到 HQ 任务', 404)
            return self._view(self._jobs[job_id])

    def cancel(self, job_id: str) -> dict:
        with self._operation(), self._lock:
            folder = self._folder(job_id)
            record = self._jobs.get(job_id)
            if record is None:
                _fail('HQ_JOB_NOT_FOUND', '找不到 HQ 任务', 404)
            if record['state'] not in TERMINAL:
                self._safe(folder / 'cancel.flag').write_text('cancel\n', encoding='ascii')
                record.update(phase='cancelling', cancellationRequested=True)
                self._save(record)
                self._cancel[job_id].set()
                future = self._futures.get(job_id)
                if future and future.cancel():
                    # No preparation ran, therefore no identity child or owned
                    # process can exist. Otherwise the monitor awaits release.
                    record.update(state='cancelled', phase='cancelled', completedAt=_now())
                    self._save(record)
            return self._view(record)

    def image_path(self, job_id: str, role: str | None = None) -> tuple[Path, dict]:
        with self._operation(), self._lock:
            folder = self._folder(job_id)
            record = self._jobs.get(job_id)
            if record is None:
                _fail('HQ_JOB_NOT_FOUND', '找不到 HQ 任务', 404)
            if role is None:
                if record.get('identityJobId') in history_deletion_flags(self.config.dream_root):
                    _fail('HQ_RESULT_DELETED', '此人物作品已从历史删除', 404)
                if record['state'] != 'succeeded' or not record.get('result'):
                    _fail('HQ_RESULT_NOT_READY', 'HQ 成片尚未完成', 409)
                info = record['result']
                path = self._identity_result_path(record)[0] if record.get('identityJobId') else folder / 'result.png'
                limit = MAX_RESULT
            else:
                if role not in ROLES:
                    _fail('HQ_INPUT_NOT_FOUND', '找不到此角色的原图', 404)
                info = next((x for x in record['inputs'] if x['role'] == role), None)
                if not info:
                    _fail('HQ_INPUT_NOT_FOUND', '找不到此角色的原图', 404)
                ext = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}.get(info['mime'])
                path, limit = folder / 'inputs' / (role + (ext or '.invalid')), MAX_IMAGE
            path = validate_history_path(self.config.dream_root, path) if role is None else self._safe(path)
            if not path.is_file() or not 0 < path.stat().st_size <= limit:
                _fail('HQ_ARTIFACT_INVALID', '本地图片缺失或大小无效', 404)
            self._image(path.read_bytes(), info['sha256'], info['mime'])
            return path, copy.deepcopy(info)

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closing = True
            for record in list(self._jobs.values()):
                if record['state'] not in TERMINAL:
                    self._safe(self._folder(record['id']) / 'cancel.flag').write_text('shutdown\n', encoding='ascii')
                    record.update(state='failed', phase='interrupted', completedAt=_now(),
                                  error={'code': 'EXECUTOR_INTERRUPTED', 'message': 'Dream 已停止；任务不会自动重新推理，已有文件保留'})
                    self._save(record)
            for event in self._cancel.values():
                event.set()
            futures = list(self._futures.values())
            for future in futures:
                future.cancel()
        for future in futures:
            try:
                future.result()
            except Exception:
                pass
        self._preparation.shutdown(wait=True, cancel_futures=True)
        with self._condition:
            self._condition.wait_for(lambda: self._active == 0)
            self._lease.close()
            self._closed = True
        if self._own_client:
            self.client.close()
