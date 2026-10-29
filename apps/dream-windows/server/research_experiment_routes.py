"""Research endpoints: read-only/CPU tools and shared identity-queue image jobs."""
import json
import threading

from fastapi import APIRouter, Query, Request
from starlette.concurrency import run_in_threadpool

from errors import DreamApiError
from research_comparison import compare_latent_runs
from research_fusion import MAX_BODY_BYTES, fusion_capability, replay_fusion

_replay_slot = threading.BoundedSemaphore(1)


def create_research_image_router(service):
    from identity_routes import require_local_origin
    from fastapi.routing import APIRoute
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import FileResponse, JSONResponse
    from operations import ensure_generation_capacity
    from research_image_service import ResearchImageService, FusionImageRequest
    images = ResearchImageService(service)

    class ImageResearchRoute(APIRoute):
        def get_route_handler(self):
            original=super().get_route_handler()
            async def guarded(request):
                if request.method=='POST':
                    require_local_origin(request,service.config)
                    data=bytearray()
                    async for chunk in request.stream():
                        if len(data)+len(chunk)>32768: raise DreamApiError('FUSION_BODY_TOO_LARGE','实验请求超过大小限制',status_code=413)
                        data.extend(chunk)
                    if data:
                        if request.headers.get('content-type','').split(';')[0].lower()!='application/json':
                            raise DreamApiError('FUSION_CONTENT_TYPE','实验请求必须使用JSON',status_code=415)
                        try: request._json=json.loads(data.decode('utf-8'),object_pairs_hook=_unique,parse_constant=_nonfinite)
                        except (ValueError,RecursionError) as exc:
                            raise DreamApiError('FUSION_REQUEST_INVALID','实验JSON无效',status_code=422) from exc
                    request._body=bytes(data)
                try: return await original(request)
                except RequestValidationError:
                    return JSONResponse(status_code=422,content={'code':'FUSION_REQUEST_INVALID','message':'实验参数缺失、超限或包含不支持字段'})
            return guarded

    router=APIRouter(prefix='/research/images',route_class=ImageResearchRoute)

    @router.get('/capability')
    def image_capability():
        return images.operation('capability')

    @router.post('')
    def create_image_experiment(payload: FusionImageRequest):
        ensure_generation_capacity(service.config)
        return images.operation('submit',payload)

    @router.get('/{job_id}')
    def image_experiment(job_id: str):
        return images.operation('get',job_id)

    @router.post('/{job_id}/cancel')
    def cancel_image_experiment(job_id: str):
        return images.operation('cancel',job_id)

    @router.get('/{job_id}/{mode}/image')
    def experiment_image(job_id: str,mode: str):
        return FileResponse(images.operation('image',job_id,mode),media_type='image/png',headers={'Cache-Control':'private, no-store'})

    return router


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('JSON 包含重复字段')
        result[key] = value
    return result


def _nonfinite(_value):
    raise ValueError('JSON 包含非有限数值')


def create_research_experiment_router(runtime):
    router = APIRouter(prefix='/api/research')

    @router.get('/fusion/capability')
    def capability():
        return fusion_capability()

    @router.post('/fusion/replay')
    async def replay(request: Request):
        if not _replay_slot.acquire(blocking=False):
            raise DreamApiError('REPLAY_BUSY', 'CPU 重放正在运行，请稍后重试', status_code=429)
        try:
            data = bytearray()
            async for chunk in request.stream():
                if len(data) + len(chunk) > MAX_BODY_BYTES:
                    raise DreamApiError('REPLAY_TOO_LARGE', '预测文件超过 12 MiB 上限', status_code=413)
                data.extend(chunk)
            document = json.loads(data.decode('utf-8-sig'), object_pairs_hook=_unique, parse_constant=_nonfinite)
            return await run_in_threadpool(replay_fusion, document)
        except (ValueError, RecursionError) as exc:
            raise DreamApiError('REPLAY_INVALID', str(exc), status_code=422) from exc
        finally:
            _replay_slot.release()

    @router.get('/comparison')
    def comparison(left: str = Query(pattern=r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
                   right: str = Query(pattern=r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')):
        try:
            if 'latest' in (left, right) or left == right:
                raise ValueError('请选择两个不同的固定运行 ID')
            a, b = runtime.runtime_trace(left), runtime.runtime_trace(right)
            if a.get('runId') != left or b.get('runId') != right:
                raise ValueError('返回的运行来源与请求不一致')
            return compare_latent_runs(a, b)
        except ValueError as exc:
            raise DreamApiError('COMPARISON_INCOMPATIBLE', str(exc), status_code=422) from exc

    return router
