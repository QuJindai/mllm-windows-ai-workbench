"""Task 1: exercise registered defaults through the public API, without inference."""
from __future__ import annotations

import json
from concurrent.futures import Future
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import create_app
from config import DreamServerConfig
from job_runner import JobRunner
from research_fixtures import install_research_engine
from runtime import DreamRuntime


REPO_ROOT = Path(__file__).resolve().parents[4]
MODEL_ID = "dreamshaper-xl-lightning"
LEGACY_ALIAS = "dreamshaper-xl-lightning-4step"
EXPECTED_DEFAULTS = {
    "width": 768,
    "height": 768,
    "steps": 8,
    "cfg": 2.0,
    "samplingMethod": "dpm++2m_sde",
    "scheduler": "karras",
}


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    # Keep the real registry's profiles and identities; replace only disk paths
    # so no test needs the installed multi-GB models or writes into user data.
    registry = json.loads((REPO_ROOT / "config/dream/model-registry.json").read_text(encoding="utf-8"))
    for model in registry["models"]:
        model_path = tmp_path / f"{model['model_id']}.gguf"
        model_path.write_bytes(b"test-only-never-loaded")
        model["windows"]["path"] = str(model_path)
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    config = DreamServerConfig(
        repo_root=REPO_ROOT,
        dream_root=tmp_path / "Dream",
        core_exe=tmp_path / "core.exe",
        engine_exe=tmp_path / "engine.exe",
        wrapper=tmp_path / "wrapper.cmd",
        registry_path=registry_path,
        frontend_dist=tmp_path / "dist",
    )
    for dependency in (config.core_exe, config.engine_exe, config.wrapper):
        dependency.write_bytes(b"test-only-never-executed")
    monkeypatch.delenv("DREAM_H7_SDCPP_EXE", raising=False)
    install_research_engine(config, ("h6-conditioning-v1", "h7-attention-v1", "h7-self-attention-v1"))
    runner = JobRunner(config)
    # Retain actual API validation, runtime normalization, queue serialization
    # and persistence. Stop only scheduling: no worker, process or GPU is run.
    monkeypatch.setattr(runner, "submit_serial", lambda *args: Future())
    with TestClient(create_app(config=config, runtime=DreamRuntime(config, job_runner=runner))) as api:
        yield api
    runner._executor.shutdown(wait=True)


@pytest.mark.parametrize("endpoint", ["/api/models", f"/api/models/{MODEL_ID}", f"/api/models/{LEGACY_ALIAS}"])
def test_model_api_exposes_corrected_dreamshaper_profile(client, endpoint):
    response = client.get(endpoint)
    assert response.status_code == 200
    body = response.json()
    model = next(item for item in body if item["id"] == MODEL_ID) if isinstance(body, list) else body
    assert model["id"] == MODEL_ID
    assert model["generationDefaults"] == EXPECTED_DEFAULTS


@pytest.mark.parametrize("trace_level", ["off", "basic", "h6", "h7"])
def test_public_model_defaults_survive_generation_submission(client, trace_level):
    model = client.get(f"/api/models/{MODEL_ID}").json()
    response = client.post("/api/generate", json={
        "modelId": MODEL_ID,
        "prompt": "an astronaut in a garden",
        "seed": 20260920,
        "traceLevel": trace_level,
        **model["generationDefaults"],
    })
    assert response.status_code == 200
    job = response.json()
    assert job["state"] == "queued"
    assert {key: job["request"][key] for key in EXPECTED_DEFAULTS} == EXPECTED_DEFAULTS
    assert job["request"]["traceLevel"] == trace_level
    assert job["request"]["seed"] == 20260920
    assert client.get(f"/api/jobs/{job['id']}").json()["request"] == job["request"]


@pytest.mark.parametrize("trace_level", ["off", "basic", "h6", "h7"])
def test_explicit_legacy_alias_request_is_not_replaced_by_registered_defaults(client, trace_level):
    # Historical four-step requests must remain valid even though they are no
    # longer the recommendation. CFG=0 also catches truthiness-based fallback.
    explicit = {
        "modelId": LEGACY_ALIAS,
        "prompt": "a red ceramic teapot",
        "negativePrompt": "text, watermark",
        "width": 512,
        "height": 640,
        "steps": 4,
        "cfg": 0,
        "samplingMethod": "dpm++2m",
        "scheduler": "discrete",
        "seed": 0,
        "fusionMode": "none",
        "traceLevel": trace_level,
    }
    response = client.post("/api/generate", json=explicit)
    assert response.status_code == 200
    job = response.json()
    assert job["request"] == {**explicit, "modelId": MODEL_ID}
    assert client.get(f"/api/jobs/{job['id']}").json()["request"] == job["request"]
