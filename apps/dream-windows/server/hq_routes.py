"""Same-origin-only local HQ API, including image and status reads."""
from __future__ import annotations

from contextlib import asynccontextmanager
from ipaddress import ip_address
from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders

from config import DreamServerConfig
from errors import DreamApiError
from hq_service import HQCreateRequest, HQService
from identity_routes import require_local_origin

PRIVATE_HEADERS = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
                   'Referrer-Policy': 'no-referrer', 'Cross-Origin-Resource-Policy': 'same-origin'}


def _loopback(value: str | None, *, allow_hostname=False) -> bool:
    if allow_hostname and value == 'localhost':
        return True
    try:
        address = ip_address(value or '')
        mapped = getattr(address, 'ipv4_mapped', None)
        return (mapped or address).is_loopback
    except ValueError:
        return False


def require_hq_local_transport(request: Request, config: DreamServerConfig) -> None:
    """HQ supports a direct loopback listener, never LAN or forwarded requests.

    Uvicorn may rewrite scope.client using trusted proxy headers. Reject those
    headers even after rewriting so a forwarded loopback value is never proof
    of the socket peer. No client-supplied Host/Origin authorizes a remote peer.
    """
    if not _loopback(config.host, allow_hostname=True):
        raise DreamApiError('HQ_LOOPBACK_REQUIRED', 'HQ 私人素材与生成仅允许本机回环地址监听', status_code=403)
    forwarded = {'forwarded', 'x-forwarded-for', 'x-forwarded-host', 'x-forwarded-proto', 'x-real-ip'}
    if forwarded.intersection(request.headers):
        raise DreamApiError('HQ_PEER_FORBIDDEN', 'HQ 仅接受本机直接连接，不接受代理转发', status_code=403)
    peer, server = request.scope.get('client'), request.scope.get('server')
    if not peer or not _loopback(peer[0]) or (server and not _loopback(server[0], allow_hostname=True)):
        raise DreamApiError('HQ_PEER_FORBIDDEN', 'HQ 私人素材与生成仅允许本机连接', status_code=403)


class HQPrivateAliasesMiddleware:
    """Guard imported private assets without buffering bodies or disconnects."""
    def __init__(self, app, config: DreamServerConfig):
        self.app, self.config = app, config

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        root = self.config.dream_root / 'data' / 'hq'
        protected = (path == '/api/identity' or path.startswith('/api/identity/')
                     or path == '/api/history' or path.startswith('/api/history/'))
        if (scope['type'] != 'http' or not protected
                or not ((root / 'config.json').is_file() or (root / 'jobs').is_dir())):
            return await self.app(scope, receive, send)
        try:
            request = Request(scope, receive=receive)
            require_hq_local_transport(request, self.config)
            require_local_origin(request, self.config)
        except DreamApiError as exc:
            error = {'code': exc.code, 'message': exc.message}
            response = JSONResponse({'error': error, **error, 'retryable': False},
                                    status_code=exc.status_code, headers=PRIVATE_HEADERS)
            return await response(scope, receive, send)

        async def private_send(message):
            if message['type'] == 'http.response.start':
                MutableHeaders(scope=message).update(PRIVATE_HEADERS)
            await send(message)

        return await self.app(scope, receive, private_send)


def create_hq_router(config: DreamServerConfig, service: HQService) -> APIRouter:
    class HQRoute(APIRoute):
        def get_route_handler(self):
            original = super().get_route_handler()

            async def guarded(request: Request):
                try:
                    require_hq_local_transport(request, config)
                    require_local_origin(request, config)  # GET/HEAD are private too.
                    if request.method == 'POST':
                        length = request.headers.get('content-length', '0')
                        if not length.isdigit() or int(length) > 16384:
                            raise DreamApiError('HQ_BODY_TOO_LARGE', 'HQ 请求超过大小限制', status_code=413)
                        data = bytearray()
                        async for chunk in request.stream():
                            if len(data) + len(chunk) > 16384:
                                raise DreamApiError('HQ_BODY_TOO_LARGE', 'HQ 请求超过大小限制', status_code=413)
                            data.extend(chunk)
                        if data and request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                            raise DreamApiError('HQ_CONTENT_TYPE', 'HQ 请求必须使用 JSON', status_code=415)
                        request._body = bytes(data)
                    response = await original(request)
                    response.headers.update(PRIVATE_HEADERS)
                    return response
                except RequestValidationError:
                    error = {'code': 'REQUEST_INVALID', 'message': 'HQ 请求参数无效，请检查素材编号和生成参数'}
                    return JSONResponse({'error': error, **error, 'retryable': False}, status_code=422, headers=PRIVATE_HEADERS)
                except DreamApiError as exc:
                    error = {'code': exc.code, 'message': exc.message}
                    return JSONResponse({'error': error, **error, 'retryable': exc.retryable}, status_code=exc.status_code, headers=PRIVATE_HEADERS)

            return guarded

    @asynccontextmanager
    async def lifespan(app):
        # An unused optional HQ feature must not acquire storage or prevent the
        # existing native/identity app from being constructed by local tools.
        if (_loopback(config.host, allow_hostname=True)
                and (service.config_path.is_file() or (service.root / 'jobs').is_dir())):
            await run_in_threadpool(service.start)
        try:
            yield
        finally:
            await run_in_threadpool(service.close)

    router = APIRouter(prefix='/api/hq', route_class=HQRoute, lifespan=lifespan)

    @router.get('/status')
    def status():
        return service.status()

    @router.get('/catalog')
    def catalog(kind: Literal['person', 'garment', 'pose'], q: str = Query('', max_length=100),
                category: str = Query('', max_length=160), page: int = Query(0, ge=0, le=1000),
                limit: int = Query(24, ge=1, le=48)):
        return service.catalog(kind, q, category, page, limit)

    @router.get('/asset')
    def asset(kind: Literal['person', 'garment', 'pose'], id: str = Query(..., max_length=64),
              thumbnail: Literal['0', '1'] = '0'):
        raw, info = service.asset(kind, id, thumbnail == '1')
        return Response(raw, media_type=info['mime'], headers={'X-Content-SHA256': info['sha256']})

    @router.post('/jobs')
    def create_job(payload: HQCreateRequest):
        job, reused = service.create_job(payload)
        return JSONResponse(job, status_code=200 if reused else 201)

    @router.get('/jobs')
    def jobs():
        return service.jobs()

    @router.get('/jobs/{job_id}')
    def job(job_id: str):
        return service.get_job(job_id)

    @router.post('/jobs/{job_id}/cancel')
    def cancel(job_id: str):
        return service.cancel(job_id)

    @router.get('/jobs/{job_id}/inputs/{role}')
    def input_image(job_id: str, role: Literal['person', 'garment', 'pose'], download: Literal['0', '1'] = '0'):
        path, info = service.image_path(job_id, role)
        return FileResponse(path, media_type=info['mime'], filename=path.name if download == '1' else None,
                            headers={**PRIVATE_HEADERS, 'X-Content-SHA256': info['sha256']})

    @router.get('/jobs/{job_id}/result')
    def result(job_id: str, download: Literal['0', '1'] = '0'):
        path, info = service.image_path(job_id)
        return FileResponse(path, media_type='image/png', filename=job_id + '.png' if download == '1' else None,
                            headers={**PRIVATE_HEADERS, 'X-Content-SHA256': info['sha256']})

    return router
