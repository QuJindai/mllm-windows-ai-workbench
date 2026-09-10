from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from config import DreamServerConfig
from errors import DreamApiError
from models import ExperimentRequest, FavoriteRequest, GenerateRequest, SettingsUpdateRequest, WorkspaceOpenRequest
from runtime import DreamRuntime


def create_app(config: DreamServerConfig | None = None, runtime: DreamRuntime | Any | None = None) -> FastAPI:
    resolved_config = config or DreamServerConfig.from_environment()
    resolved_runtime = runtime or DreamRuntime(resolved_config)
    app = FastAPI(title="Dream Windows Web", version="0.2.0")

    @app.exception_handler(DreamApiError)
    async def dream_error_handler(_: Request, exc: DreamApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "message": exc.message, "retryable": exc.retryable, "detail": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"code": "REQUEST_INVALID", "message": "Request validation failed", "retryable": False, "detail": {"errors": exc.errors()}})

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return resolved_runtime.health()

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
    def delete_history(item_id: str) -> dict[str, Any]:
        return resolved_runtime.delete_history(item_id)

    @app.post("/api/history/{item_id}/favorite")
    def favorite_history(item_id: str, payload: FavoriteRequest) -> dict[str, Any]:
        return resolved_runtime.favorite_history(item_id, payload.value)

    @app.post("/api/experiments")
    def run_experiment(payload: ExperimentRequest) -> dict[str, Any]:
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
        return FileResponse(index)

    @app.get("/favicon.svg", response_model=None)
    def favicon() -> FileResponse | JSONResponse:
        icon = frontend_dist / "favicon.svg"
        if not icon.exists():
            return JSONResponse(status_code=404, content={"code": "FAVICON_NOT_FOUND", "message": "Favicon is not built", "retryable": False})
        return FileResponse(icon, media_type="image/svg+xml")

    return app


app = create_app()
