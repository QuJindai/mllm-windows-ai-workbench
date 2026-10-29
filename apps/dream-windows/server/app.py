from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from config import DreamServerConfig
from errors import DreamApiError
from identity_routes import create_identity_router, require_local_origin
from identity_service import IdentityService
from job_runner import JobRunner
from models import ExperimentRequest, FavoriteRequest, GenerateRequest, SettingsUpdateRequest, WorkspaceOpenRequest
from operations import ensure_generation_capacity, get_operations
from runtime import DreamRuntime
from research_experiment_routes import create_research_experiment_router


def create_app(config: DreamServerConfig | None = None, runtime: DreamRuntime | Any | None = None) -> FastAPI:
    resolved_config = config or DreamServerConfig.from_environment()
    resolved_runtime = runtime or DreamRuntime(resolved_config)
    app = FastAPI(title="Dream Windows Web", version="0.2.0")
    app.include_router(create_research_experiment_router(resolved_runtime))

    @app.exception_handler(DreamApiError)
    async def dream_error_handler(_: Request, exc: DreamApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "message": exc.message, "retryable": exc.retryable, "detail": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"code": "REQUEST_INVALID", "message": "Request validation failed", "retryable": False, "detail": {"errors": exc.errors()}})

    identity_runner = getattr(resolved_runtime, "job_runner", None)
    identity_service = None
    if isinstance(identity_runner, JobRunner):
        identity_service = IdentityService(resolved_config, identity_runner)
        app.include_router(create_identity_router(resolved_config, identity_runner, service=identity_service))

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return resolved_runtime.health()

    @app.get("/api/operations")
    def operations() -> JSONResponse:
        return JSONResponse(content=get_operations(resolved_config), headers={"Cache-Control": "no-store"})

    @app.get("/api/capabilities")
    def capabilities() -> dict[str, Any]:
        return resolved_runtime.capabilities()

    @app.get("/api/hardware")
    def hardware() -> dict[str, Any]:
        return resolved_runtime.hardware()

    @app.get("/api/models")
    def models() -> list[dict[str, Any]]:
        return resolved_runtime.models()

    @app.get("/api/models/{model_id}")
    def get_model(model_id: str) -> dict[str, Any]:
        return resolved_runtime.get_model(model_id)

    @app.post("/api/models/{model_id}/verify")
    def verify_model(model_id: str) -> dict[str, Any]:
        return resolved_runtime.verify_model(model_id)

    @app.post("/api/models/reindex")
    def reindex_models() -> list[dict[str, Any]]:
        return resolved_runtime.models()

    @app.get("/api/history")
    def history(page: int = Query(1, ge=1), page_size: int = Query(24, ge=1, le=100), search: str = "", filter: str = "all") -> dict[str, Any]:
        return resolved_runtime.history({"page": page, "page_size": page_size, "search": search, "filter": filter})

    @app.get("/api/history/{item_id}")
    def get_history_item(item_id: str) -> dict[str, Any]:
        return resolved_runtime.history_item(item_id)

    @app.get("/api/history/{item_id}/image")
    def history_image(item_id: str) -> FileResponse:
        path = resolved_runtime.history_image(item_id)
        return FileResponse(path)

    @app.delete("/api/history/{item_id}")
    def delete_history(item_id: str, request: Request) -> dict[str, Any]:
        if identity_service is not None and re.fullmatch(r'identity-[a-f0-9]{24}', item_id):
            require_local_origin(request, resolved_config)
            try:
                return {**identity_service.delete_history(item_id), 'truth': 'observed'}
            except DreamApiError as exc:
                if exc.code == 'IDENTITY_JOB_NOT_FOUND':
                    return identity_service.refinement_operation('delete_legacy', item_id, resolved_runtime.delete_history)
                raise
        return resolved_runtime.delete_history(item_id)

    @app.post("/api/history/{item_id}/favorite")
    def favorite_history(item_id: str, payload: FavoriteRequest) -> dict[str, Any]:
        return resolved_runtime.favorite_history(item_id, payload.value)

    @app.post("/api/experiments")
    def run_experiment(payload: ExperimentRequest) -> dict[str, Any]:
        ensure_generation_capacity(resolved_config)
        return resolved_runtime.run_experiment(payload)

    @app.get("/api/experiments/{experiment_id}")
    def get_experiment(experiment_id: str) -> dict[str, Any]:
        return resolved_runtime.get_experiment(experiment_id)

    @app.get("/api/research/status")
    def research_status() -> dict[str, Any]:
        return resolved_runtime.research_status()

    @app.get("/api/traces")
    def trace_runs() -> list[dict[str, Any]]:
        return resolved_runtime.trace_runs()

    @app.get("/api/traces/{run_id}/latent")
    def latent_trace(run_id: str) -> dict[str, Any]:
        return resolved_runtime.latent_trace(run_id)

    @app.get("/api/traces/{run_id}/latent/frames/{file_name}")
    def latent_trace_frame(run_id: str, file_name: str) -> FileResponse:
        return FileResponse(resolved_runtime.latent_trace_frame(run_id, file_name))

    @app.get("/api/traces/{run_id}/attention")
    def attention_index(run_id: str) -> dict[str, Any]:
        return resolved_runtime.attention_index(run_id)

    @app.get("/api/traces/{run_id}/attention/maps/{map_id}")
    def attention_map(run_id: str, map_id: str) -> dict[str, Any]:
        return resolved_runtime.attention_map(run_id, map_id)

    @app.get("/api/traces/{run_id}")
    def runtime_trace(run_id: str) -> dict[str, Any]:
        return resolved_runtime.runtime_trace(run_id)

    @app.get("/api/traces/{run_id}/influence")
    def influence(run_id: str) -> dict[str, Any]:
        return resolved_runtime.influence(run_id)

    @app.get("/api/traces/{run_id}/self-attention")
    def self_attention_index(run_id: str) -> dict[str, Any]:
        return resolved_runtime.self_attention_index(run_id)

    @app.get("/api/traces/{run_id}/self-attention/maps/{map_id}")
    def self_attention_map(run_id: str, map_id: str) -> dict[str, Any]:
        return resolved_runtime.self_attention_map(run_id, map_id)

    @app.get("/api/settings")
    def settings() -> dict[str, Any]:
        return resolved_runtime.settings()

    @app.put("/api/settings")
    def update_settings(payload: SettingsUpdateRequest) -> dict[str, Any]:
        return resolved_runtime.update_settings(payload.model_dump(by_alias=True, exclude_none=True))

    @app.post("/api/workspace/open")
    def open_workspace(payload: WorkspaceOpenRequest) -> dict[str, Any]:
        return resolved_runtime.open_workspace(payload.entry)

    @app.get("/api/settings/export")
    def export_settings() -> Response:
        content = json.dumps(resolved_runtime.export_settings(), ensure_ascii=False, indent=2)
        return Response(content=content, media_type="application/json", headers={"Content-Disposition": 'attachment; filename="dream-settings.json"'})

    @app.post("/api/generate")
    def generate(payload: GenerateRequest) -> dict[str, Any]:
        ensure_generation_capacity(resolved_config)
        return resolved_runtime.generate(payload)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        return resolved_runtime.get_job(job_id)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        return resolved_runtime.cancel_job(job_id)

    frontend_dist = Path(resolved_config.frontend_dist)
    assets = frontend_dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/", response_model=None)
    def root() -> FileResponse | JSONResponse:
        index = frontend_dist / "index.html"
        if not index.exists():
            return JSONResponse(status_code=503, content={"code": "FRONTEND_BUILD_MISSING", "message": "Run the frontend build before opening Dream Web", "retryable": False, "detail": {"path": str(index)}})
        # Entry HTML points at a specific hashed bundle: never keep an older
        # release's entry document across a local server upgrade.
        return FileResponse(index, headers={"Cache-Control": "no-store"})

    @app.get("/release.json", response_model=None)
    def release_manifest() -> FileResponse | JSONResponse:
        manifest = frontend_dist / "release.json"
        if not manifest.is_file():
            return JSONResponse(status_code=404, content={"code": "RELEASE_MANIFEST_NOT_FOUND", "message": "This frontend build has no release manifest", "retryable": False})
        return FileResponse(manifest, media_type="application/json", headers={"Cache-Control": "no-store"})

    @app.get("/favicon.svg", response_model=None)
    def favicon() -> FileResponse | JSONResponse:
        icon = frontend_dist / "favicon.svg"
        if not icon.exists():
            return JSONResponse(status_code=404, content={"code": "FAVICON_NOT_FOUND", "message": "Favicon is not built", "retryable": False})
        return FileResponse(icon, media_type="image/svg+xml")

    return app


app = create_app()
