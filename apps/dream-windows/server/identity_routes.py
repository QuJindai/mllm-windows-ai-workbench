from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from config import DreamServerConfig
from errors import DreamApiError
import operations
from identity_service import IdentityGenerateRequest, IdentityService, MAX_BASE64, ReferenceUpload, WorkerCancelled
from job_runner import JobRunner
from identity_profiles import ProfileCreate, ProfileName, ProfilePreset
from identity_batches import BatchRequest, BatchRetryRequest
from identity_anime_profiles import AnimeProfileCreate, AnimeProfileImport
from history_transactions import committed_history_deletions


def create_identity_router(config: DreamServerConfig, job_runner: JobRunner) -> APIRouter:
    service = IdentityService(config, job_runner)

    def result_availability(record, deleted):
        # Decorate a detached public copy only. Frozen jobs and profile presets
        # keep their metadata so deleting an output cannot damage identity data.
        if record.get("state") == "complete" and record["id"] in deleted:
            record = {**record, "resultDeleted": True}
        return record

    def batch_availability(record, deleted):
        return {**record, "items": [result_availability(item, deleted) for item in record["items"]]}

    class IdentityRoute(APIRoute):
        def get_route_handler(self):
            original = super().get_route_handler()

            async def guarded(request: Request):
                if request.method == "POST":
                    # Check actual Host too: reflecting a forged Host into Origin
                    # comparison alone would permit DNS rebinding attacks.
                    allowed_hosts = {"localhost", "127.0.0.1", "::1", config.host} - {"0.0.0.0", "::"}
                    origin = request.headers.get("origin")
                    fetch_site = request.headers.get("sec-fetch-site")
                    trusted = request.url.hostname in allowed_hosts and fetch_site in {None, "none", "same-origin"}
                    if origin is not None:
                        try:
                            parsed = urlsplit(origin)
                            trusted = trusted and parsed.scheme == request.url.scheme and parsed.netloc == request.url.netloc and parsed.path == "" and not parsed.query and not parsed.fragment and not parsed.username
                        except ValueError:
                            trusted = False
                    if not trusted:
                        raise DreamApiError("IDENTITY_ORIGIN_FORBIDDEN", "人物操作必须来自可信的同源页面，请从 Dream 页面重试", status_code=403)
                    image_upload = request.url.path in {'/api/identity/references', '/api/identity/anime-profiles/import'}
                    limit = MAX_BASE64 + 64 * 1024 if image_upload else 64 * 1024
                    try:
                        size = int(request.headers.get("content-length", "0"))
                    except ValueError:
                        size = -1
                    if size < 0 or size > limit:
                        raise DreamApiError("IDENTITY_BODY_TOO_LARGE", "人物请求超过大小限制", status_code=413)
                    body = bytearray()
                    async for chunk in request.stream():
                        if len(body) + len(chunk) > limit:
                            raise DreamApiError("IDENTITY_BODY_TOO_LARGE", "人物请求超过大小限制", status_code=413)
                        body.extend(chunk)
                    if body and request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
                        raise DreamApiError("IDENTITY_CONTENT_TYPE", "人物请求必须使用 JSON 格式", status_code=415)
                    request._body = bytes(body)
                try:
                    return await original(request)
                except RequestValidationError as exc:
                    # Never echo a base64 image, non-finite number or exception
                    # object into the JSON error envelope.
                    return JSONResponse(status_code=422, content={"code": "REQUEST_INVALID", "message": "人物请求参数无效，请检查参考图、人脸选择和生成参数", "retryable": False, "detail": {"errors": [{"loc": error["loc"], "type": error["type"], "msg": "此字段缺失或不符合参数要求"} for error in exc.errors()]}})

            return guarded

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            await run_in_threadpool(service.close)

    router = APIRouter(prefix="/api/identity", route_class=IdentityRoute, lifespan=lifespan)

    @router.get('/anime-profiles')
    def anime_profiles():
        return service.anime_profile_operation('list')

    @router.post('/anime-profiles')
    def create_anime_profile(payload: AnimeProfileCreate):
        return service.anime_profile_operation('create', payload)

    @router.post('/anime-profiles/import')
    def import_anime_profile(payload: AnimeProfileImport):
        return service.anime_profile_operation('import_image', payload)

    @router.get('/anime-profiles/{profile_id}/image')
    def anime_image(profile_id: str):
        return FileResponse(service.anime_profile_operation('image',profile_id),media_type='image/png')

    @router.post("/batches")
    def create_batch(payload: BatchRequest):
        operations.ensure_generation_capacity(config)
        return service.batch_operation("submit", payload)

    @router.get("/batches")
    def batches():
        deleted = committed_history_deletions(config.dream_root)
        return [batch_availability(record, deleted) for record in service.batch_operation("list")]

    @router.get("/batches/{batch_id}")
    def batch(batch_id: str):
        return batch_availability(service.batch_operation("get", batch_id), committed_history_deletions(config.dream_root))

    @router.post("/batches/{batch_id}/cancel")
    def cancel_batch(batch_id: str):
        return service.batch_operation("cancel", batch_id)

    @router.post("/batches/{batch_id}/retry")
    def retry_batch(batch_id: str, payload: BatchRetryRequest):
        return batch_availability(service.batch_operation("retry", batch_id, payload), committed_history_deletions(config.dream_root))

    @router.get("/batches/{batch_id}/previews/{filename}")
    def preview(batch_id: str, filename: str):
        return FileResponse(service.batch_operation("preview", batch_id, filename), media_type="image/png")

    @router.get("/profiles")
    def profiles():
        return service.profile_operation("list")

    @router.post("/profiles")
    def create_profile(payload: ProfileCreate):
        return service.profile_operation("create", payload)

    @router.get("/profiles/{profile_id}")
    def profile(profile_id: str):
        return service.profile_operation("get", profile_id)

    @router.post("/profiles/{profile_id}/rename")
    def rename_profile(profile_id: str, payload: ProfileName):
        return service.profile_operation("rename", profile_id, payload)

    @router.post("/profiles/{profile_id}/archive")
    def archive_profile(profile_id: str):
        return service.profile_operation("archive", profile_id)

    @router.post("/profiles/{profile_id}/preset")
    def profile_preset(profile_id: str, payload: ProfilePreset):
        return service.profile_operation("preset", profile_id, payload)

    @router.get("/status")
    def status() -> dict[str, Any]:
        return service.status()

    @router.get("/references")
    def references() -> list[dict[str, Any]]:
        return service.references()

    @router.post("/references")
    async def upload(payload: ReferenceUpload, request: Request) -> dict[str, Any]:
        cancelled = threading.Event()
        task = asyncio.create_task(run_in_threadpool(service.upload, payload, cancelled))
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=0.1)
                if not task.done() and await request.is_disconnected():
                    cancelled.set()
            return await task
        except WorkerCancelled as exc:
            raise DreamApiError("IDENTITY_CANCELLED", "参考图分析已取消", status_code=499) from exc
        except asyncio.CancelledError:
            cancelled.set()
            raise

    @router.get("/references/{reference_id}/image")
    def reference_image(reference_id: str) -> FileResponse:
        return FileResponse(service.reference_image(reference_id), media_type="image/png")

    @router.post("/generate")
    def generate(payload: IdentityGenerateRequest) -> dict[str, Any]:
        operations.ensure_generation_capacity(config)
        return service.submit(payload)

    @router.get("/jobs")
    def jobs() -> list[dict[str, Any]]:
        deleted = committed_history_deletions(config.dream_root)
        return [result_availability(record, deleted) for record in service.jobs()]

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        return result_availability(service.get(job_id), committed_history_deletions(config.dream_root))

    @router.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        return service.cancel(job_id)

    @router.get("/jobs/{job_id}/original")
    def original_image(job_id: str) -> FileResponse:
        return FileResponse(service.original_image(job_id), media_type="image/png")

    return router
