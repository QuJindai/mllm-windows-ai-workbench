from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import create_app
from job_runner import JobRunner
from models import GenerateRequest
from runtime import DreamRuntime
from research_fixtures import install_research_engine as install_manifest
from test_generation_jobs import make_config
from test_persistent_job_runner import CapturingJobRunner, FakePersistentEngine, wait_for_terminal


ALL_RESEARCH = ["h7-attention-v1", "h6-conditioning-v1", "h7-self-attention-v1"]


@pytest.fixture
def research_config(tmp_path, monkeypatch):
    monkeypatch.delenv("DREAM_H7_SDCPP_EXE", raising=False)
    return make_config(tmp_path)


@pytest.mark.parametrize("capabilities,influence,self_attention,h7", [
    ([], False, False, False), (["h7-attention-v1"], False, False, False),
    (["h6-conditioning-v1"], True, False, False),
    (["h7-self-attention-v1"], False, True, False), (ALL_RESEARCH, True, True, True),
    ("h7-attention-v1 h6-conditioning-v1 h7-self-attention-v1", False, False, False),
    ({"h7-attention-v1": True}, False, False, False), (42, False, False, False),
])
def test_capabilities_require_exact_manifest_entries(research_config, capabilities, influence, self_attention, h7):
    install_manifest(research_config, capabilities)
    client = TestClient(create_app(config=research_config, runtime=DreamRuntime(research_config)))
    response = client.get("/api/capabilities")
    assert response.status_code == 200
    for key, expected in (("conditioning_influence", influence), ("self_attention", self_attention)):
        assert response.json()[key]["available"] is expected
        assert response.json()[key]["truth"] == ("observed" if expected else "unavailable")
    assert client.get("/api/research/status").json()["available"] is h7
    assert response.json()["semantic_experiments"]["available"] is influence


@pytest.mark.parametrize("trace_level,capabilities,allowed", [
    ("h6", ["h7-attention-v1"], False), ("h7", ["h7-attention-v1"], False),
    ("h7", ["h6-conditioning-v1", "h7-self-attention-v1"], False),
    ("h6", ["h6-conditioning-v1"], True), ("h7", ALL_RESEARCH, True),
    ("basic", [], True), ("off", [], True),
])
def test_generation_enforces_research_capabilities_before_submission(research_config, trace_level, capabilities, allowed):
    install_manifest(research_config, capabilities)
    class QueueOnly:
        submitted = []

        def submit(self, request):
            self.submitted.append(request)
            return {"id": "queued", "state": "queued"}

    runner = QueueOnly()
    client = TestClient(create_app(config=research_config, runtime=DreamRuntime(research_config, job_runner=runner)))
    response = client.post("/api/generate", json={"prompt": "test", "modelId": "model", "traceLevel": trace_level})
    assert response.status_code == (200 if allowed else 503)
    assert bool(runner.submitted) is allowed
    if not allowed:
        assert response.json()["code"] == f"{trace_level.upper()}_ENGINE_MISSING"


@pytest.mark.parametrize("trace_level", ["off", "basic", "h6", "h7"])
def test_trace_levels_select_correct_cli_environment(research_config, trace_level):
    request = GenerateRequest(prompt="test", modelId="model", traceLevel=trace_level)
    environment = JobRunner(research_config)._environment(request)
    expected = research_config.h7_engine_exe if trace_level in {"h6", "h7"} else research_config.engine_exe
    assert Path(environment["DREAM_STABLE_DIFFUSION_CPP_EXE"]) == expected


@pytest.mark.parametrize("trace_level", ["h6", "h7"])
def test_research_bypasses_available_persistent_engine(research_config, trace_level):
    persistent = FakePersistentEngine()
    runner = CapturingJobRunner(research_config, persistent_engine=persistent)
    job = runner.submit(GenerateRequest(prompt="test", modelId="model", traceLevel=trace_level))
    result = wait_for_terminal(runner, job["id"])
    assert result["state"] == "complete"
    assert runner.cli_calls == 1
    assert persistent.requests == []
