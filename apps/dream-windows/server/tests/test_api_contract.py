from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app import create_app
from config import DreamServerConfig
from research_fixtures import install_research_engine
from runtime import DreamRuntime
from models import ExperimentRequest


class FakeRuntime:
    def health(self):
        return {"ok": True, "service": "dream-web", "backend": "ready"}

    def capabilities(self):
        return {
            "native_generation": {"available": True, "truth": "observed"},
            "process_trace": {"available": True, "truth": "derived"},
            "latent_trace": {"available": False, "truth": "unavailable"},
            "semantic_experiments": {"available": False, "truth": "unavailable"},
            "attention": {"available": False, "truth": "unavailable"},
        }

    def hardware(self):
        return {"gpuName": "Test GPU", "vramTotalMiB": 6141, "cudaReady": True, "truth": "observed"}

    def models(self):
        return [{"id": "test-model", "displayName": "Test Model", "status": "ready", "truth": "observed"}]

    def history(self, query):
        return {"items": [], "total": 0, "page": query["page"], "pageSize": query["page_size"]}

    def get_model(self, model_id):
        return {"id": model_id, "displayName": "Test Model", "status": "ready", "truth": "observed"}

    def history_item(self, item_id):
        return {"id": item_id, "title": "Test image", "status": "complete", "truth": "observed"}

    def delete_history(self, item_id):
        return {"deleted": item_id}

    def favorite_history(self, item_id, value):
        return {"id": item_id, "favorite": value}

    def research_status(self):
        return {"available": False, "message": "Research Engine unavailable", "truth": "unavailable"}

    def runtime_trace(self, run_id):
        return {"runId": run_id, "totalTimeMs": 0, "nodes": []}

    def trace_runs(self):
        return [{"runId": "latest", "totalTimeMs": 0, "hasAttention": False, "hasLatent": False, "truth": "observed"}]

    def settings(self):
        return {"dreamRoot": "E:\\Dream", "precisionMode": "fp16"}

    def update_settings(self, payload):
        return {"dreamRoot": "E:\\Dream", **payload}

    def open_workspace(self, entry):
        return {"opened": True, "entry": entry, "path": f"E:\\Dream\\{entry}"}

    def export_settings(self):
        return {"dreamRoot": "E:\\Dream", "precisionMode": "fp16"}

    def run_experiment(self, payload):
        self.last_experiment_request = payload
        return {"id": "experiment-1", "kind": payload.kind, "seed": payload.seed, "lockedFields": ["seed", "modelId"], "variants": [], "status": "queued"}

    def get_experiment(self, experiment_id):
        return {"id": experiment_id, "kind": "fusion", "seed": 42, "lockedFields": ["seed", "modelId"], "variants": [], "status": "running"}


def test_dream_api_exposes_browser_contract():
    config = DreamServerConfig.for_testing()
    client = TestClient(create_app(config=config, runtime=FakeRuntime()))

    assert client.get("/api/health").json()["service"] == "dream-web"
    assert client.get("/api/capabilities").json()["attention"]["available"] is False
    assert client.get("/api/hardware").json()["gpuName"] == "Test GPU"
    assert client.get("/api/models").json()[0]["id"] == "test-model"
    history = client.get("/api/history?page=2&page_size=12&filter=favorites")
    assert history.status_code == 200
    assert history.json() == {"items": [], "total": 0, "page": 2, "pageSize": 12}
    assert client.get("/api/models/test-model").json()["id"] == "test-model"
    assert client.get("/api/history/test-history").json()["id"] == "test-history"
    assert client.delete("/api/history/test-history").json()["deleted"] == "test-history"
    assert client.post("/api/history/test-history/favorite", json={"value": True}).json()["favorite"] is True
    assert client.get("/api/research/status").json()["available"] is False
    assert client.get("/api/traces").json()[0]["runId"] == "latest"
    assert client.get("/api/traces/latest").json()["runId"] == "latest"
    assert client.get("/api/settings").json()["precisionMode"] == "fp16"
    assert client.put("/api/settings", json={"precisionMode": "fp32"}).json()["precisionMode"] == "fp32"


def test_semantic_experiment_api_preserves_same_seed_identity():
    runtime = FakeRuntime()
    client = TestClient(create_app(config=DreamServerConfig.for_testing(), runtime=runtime))

    created = client.post("/api/experiments", json={
        "kind": "fusion",
        "seed": 42,
        "modelId": "test-model",
        "prompt": "misty mountain lake",
        "negativePrompt": "text, watermark",
        "steps": 31,
        "cfg": 6.25,
    })
    current = client.get("/api/experiments/experiment-1")

    assert created.status_code == 200
    assert created.json() == {"id": "experiment-1", "kind": "fusion", "seed": 42, "lockedFields": ["seed", "modelId"], "variants": [], "status": "queued"}
    assert runtime.last_experiment_request.model_dump(by_alias=True) == {
        "kind": "fusion",
        "seed": 42,
        "modelId": "test-model",
        "prompt": "misty mountain lake",
        "negativePrompt": "text, watermark",
        "steps": 31,
        "cfg": 6.25,
    }
    assert current.status_code == 200
    assert current.json()["id"] == "experiment-1"


def test_semantic_experiment_api_requires_an_explicit_prompt():
    client = TestClient(create_app(config=DreamServerConfig.for_testing(), runtime=FakeRuntime()))

    response = client.post("/api/experiments", json={"kind": "fusion", "seed": 42, "modelId": "test-model"})

    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"


def test_semantic_experiment_api_rejects_a_blank_prompt():
    client = TestClient(create_app(config=DreamServerConfig.for_testing(), runtime=FakeRuntime()))

    response = client.post("/api/experiments", json={"kind": "fusion", "seed": 42, "modelId": "test-model", "prompt": "   "})

    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"


def test_semantic_experiment_api_rejects_invalid_kind():
    client = TestClient(create_app(config=DreamServerConfig.for_testing(), runtime=FakeRuntime()))

    response = client.post("/api/experiments", json={"kind": "arbitrary", "seed": 42, "modelId": "test-model"})

    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"


def test_native_semantic_experiment_queues_same_seed_variants(tmp_path):
    class CapturingRunner:
        def __init__(self):
            self.requests = []

        def submit(self, request):
            self.requests.append(request)
            return {"id": f"job-{len(self.requests)}"}

        def get(self, job_id):
            return {"id": job_id, "state": "complete", "result": {"imageUrl": f"/api/history/{job_id}/image"}}

        def cancel(self, job_id):
            return {"id": job_id, "state": "cancelled"}

    config = DreamServerConfig(
        repo_root=tmp_path,
        dream_root=tmp_path / "Dream",
        core_exe=tmp_path / "core.exe",
        engine_exe=tmp_path / "engine.exe",
        wrapper=tmp_path / "wrapper.cmd",
        registry_path=tmp_path / "registry.json",
        frontend_dist=tmp_path / "dist",
    )
    config.dream_root.mkdir()
    for path in (config.core_exe, config.engine_exe, config.wrapper, config.registry_path):
        path.write_text("ready", encoding="utf-8")
    runner = CapturingRunner()
    install_research_engine(config)
    runtime = DreamRuntime(config, job_runner=runner)
    runtime.models = lambda: [{"id": "test-model", "status": "ready", "path": "model.safetensors"}]
    client = TestClient(create_app(config=config, runtime=runtime))

    response = client.post("/api/experiments", json={"kind": "steps", "seed": 42, "modelId": "test-model", "prompt": "lake", "negativePrompt": "fog", "steps": 20, "cfg": 6.25})
    result = response.json()

    assert response.status_code == 200
    assert result["status"] == "complete"
    assert len(result["variants"]) == 4
    assert len({variant["id"] for variant in result["variants"]}) == 4
    assert len({variant["jobId"] for variant in result["variants"]}) == 4
    assert [request.prompt for request in runner.requests] == ["lake"] * 4
    assert [request.negative_prompt for request in runner.requests] == ["fog"] * 4
    assert [request.model_id for request in runner.requests] == ["test-model"] * 4
    assert [request.seed for request in runner.requests] == [42, 42, 42, 42]
    assert [request.steps for request in runner.requests] == [8, 16, 24, 20]
    assert [request.cfg for request in runner.requests] == [6.25] * 4
    assert runtime.get_experiment(result["id"])["variants"][0]["imageUrl"] == "/api/history/job-1/image"
    persisted = json.loads((config.dream_root / "data" / "experiments" / f"{result['id']}.json").read_text(encoding="utf-8"))
    assert persisted["request"] == {
        "kind": "steps",
        "seed": 42,
        "modelId": "test-model",
        "prompt": "lake",
        "negativePrompt": "fog",
        "steps": 20,
        "cfg": 6.25,
    }


def test_semantic_experiment_uses_truthful_prompt_level_variant_labels(tmp_path):
    class CompletedRunner:
        def __init__(self):
            self.count = 0

        def submit(self, request):
            self.count += 1
            return {"id": f"job-{self.count}"}

        def get(self, job_id):
            return {"id": job_id, "state": "complete", "result": {"imageUrl": f"/api/history/{job_id}/image"}}

        def cancel(self, job_id):
            return {"id": job_id, "state": "cancelled"}

    config = DreamServerConfig(
        repo_root=tmp_path,
        dream_root=tmp_path / "Dream",
        core_exe=tmp_path / "core.exe",
        engine_exe=tmp_path / "engine.exe",
        wrapper=tmp_path / "wrapper.cmd",
        registry_path=tmp_path / "registry.json",
        frontend_dist=tmp_path / "dist",
    )
    config.dream_root.mkdir()
    for path in (config.core_exe, config.engine_exe, config.wrapper, config.registry_path):
        path.write_text("ready", encoding="utf-8")
    install_research_engine(config)
    runtime = DreamRuntime(config, job_runner=CompletedRunner())
    runtime.models = lambda: [{"id": "test-model", "status": "ready", "path": "model.safetensors"}]

    result = runtime.run_experiment(ExperimentRequest(kind="fusion", seed=42, modelId="test-model", prompt="lake, sunrise"))

    assert [variant["label"] for variant in result["variants"]] == [
        "完整提示词（控制组）",
        "平衡描述改写",
        "仅首段提示词",
        "重点描述改写",
    ]


def test_model_experiment_includes_requested_and_actual_model_identity(tmp_path):
    class CompletedRunner:
        def __init__(self):
            self.requests = []

        def submit(self, request):
            self.requests.append(request)
            return {"id": f"job-{len(self.requests)}"}

        def get(self, job_id):
            return {"id": job_id, "state": "complete", "result": {"imageUrl": f"/api/history/{job_id}/image"}}

        def cancel(self, job_id):
            return {"id": job_id, "state": "cancelled"}

    config = DreamServerConfig(
        repo_root=tmp_path,
        dream_root=tmp_path / "Dream",
        core_exe=tmp_path / "core.exe",
        engine_exe=tmp_path / "engine.exe",
        wrapper=tmp_path / "wrapper.cmd",
        registry_path=tmp_path / "registry.json",
        frontend_dist=tmp_path / "dist",
    )
    config.dream_root.mkdir()
    for path in (config.core_exe, config.engine_exe, config.wrapper, config.registry_path):
        path.write_text("ready", encoding="utf-8")
    runner = CompletedRunner()
    install_research_engine(config)
    runtime = DreamRuntime(config, job_runner=runner)
    runtime.models = lambda: [
        {"id": f"model-{index}", "displayName": f"Model {index}", "status": "ready", "path": f"model-{index}.safetensors"}
        for index in range(1, 6)
    ]

    model_result = runtime.run_experiment(ExperimentRequest(kind="model", seed=42, modelId="model-5", prompt="lake"))
    actual_model_ids = [variant["modelId"] for variant in model_result["variants"]]

    assert model_result["lockedFields"] == ["seed"]
    assert actual_model_ids == ["model-5", "model-1", "model-2", "model-3"]
    assert [request.model_id for request in runner.requests[:4]] == actual_model_ids
    assert [variant["modelId"] for variant in runtime.get_experiment(model_result["id"])["variants"]] == actual_model_ids

    fusion_result = runtime.run_experiment(ExperimentRequest(kind="fusion", seed=42, modelId="model-5", prompt="lake"))
    steps_result = runtime.run_experiment(ExperimentRequest(kind="steps", seed=42, modelId="model-5", prompt="lake"))

    assert fusion_result["lockedFields"] == ["seed", "modelId"]
    assert steps_result["lockedFields"] == ["seed", "modelId"]
    assert {variant["modelId"] for variant in fusion_result["variants"]} == {"model-5"}
    assert {variant["modelId"] for variant in steps_result["variants"]} == {"model-5"}


def test_semantic_experiment_stays_active_until_all_variant_jobs_are_terminal(tmp_path):
    class StatefulRunner:
        def __init__(self):
            self.states = {}

        def submit(self, request):
            job_id = f"job-{len(self.states) + 1}"
            self.states[job_id] = {"id": job_id, "state": "failed" if job_id == "job-1" else "queued", "error": "native failure" if job_id == "job-1" else None}
            return {"id": job_id}

        def get(self, job_id):
            return self.states[job_id]

        def cancel(self, job_id):
            return {"id": job_id, "state": "cancelled"}

    config = DreamServerConfig(
        repo_root=tmp_path,
        dream_root=tmp_path / "Dream",
        core_exe=tmp_path / "core.exe",
        engine_exe=tmp_path / "engine.exe",
        wrapper=tmp_path / "wrapper.cmd",
        registry_path=tmp_path / "registry.json",
        frontend_dist=tmp_path / "dist",
    )
    config.dream_root.mkdir()
    for path in (config.core_exe, config.engine_exe, config.wrapper, config.registry_path):
        path.write_text("ready", encoding="utf-8")
    runner = StatefulRunner()
    install_research_engine(config)
    runtime = DreamRuntime(config, job_runner=runner)
    runtime.models = lambda: [{"id": "test-model", "status": "ready", "path": "model.safetensors"}]

    created = runtime.run_experiment(ExperimentRequest(kind="steps", seed=42, modelId="test-model", prompt="lake"))

    assert created["status"] == "running"
    assert [variant["state"] for variant in created["variants"]] == ["failed", "queued", "queued", "queued"]
    for job_id in ("job-2", "job-3", "job-4"):
        runner.states[job_id] = {"id": job_id, "state": "complete", "result": {"imageUrl": f"/api/history/{job_id}/image"}}

    reloaded_runtime = DreamRuntime(config, job_runner=runner)
    terminal_response = TestClient(create_app(config=config, runtime=reloaded_runtime)).get(f"/api/experiments/{created['id']}")
    terminal = terminal_response.json()

    assert terminal_response.status_code == 200
    assert terminal["status"] == "failed"
    assert [variant["id"] for variant in terminal["variants"]] == [variant["id"] for variant in created["variants"]]
    assert [variant["jobId"] for variant in terminal["variants"]] == [variant["jobId"] for variant in created["variants"]]
    assert terminal["variants"][0]["error"] == "native failure"
    assert terminal["variants"][1]["imageUrl"] == "/api/history/job-2/image"
    assert all("metric" not in variant for variant in terminal["variants"])


def test_workspace_actions_are_fixed_key_and_downloadable():
    client = TestClient(create_app(config=DreamServerConfig.for_testing(), runtime=FakeRuntime()))

    opened = client.post("/api/workspace/open", json={"entry": "models"})
    exported = client.get("/api/settings/export")

    assert opened.status_code == 200
    assert opened.json() == {"opened": True, "entry": "models", "path": "E:\\Dream\\models"}
    assert exported.status_code == 200
    assert exported.headers["content-disposition"] == 'attachment; filename="dream-settings.json"'
    assert exported.json() == {"dreamRoot": "E:\\Dream", "precisionMode": "fp16"}


def test_workspace_action_rejects_arbitrary_paths():
    client = TestClient(create_app(config=DreamServerConfig.for_testing(), runtime=FakeRuntime()))

    response = client.post("/api/workspace/open", json={"entry": "C:\\Users"})

    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"


def test_missing_runtime_trace_is_an_explicit_unavailable_state(tmp_path):
    config = DreamServerConfig(
        repo_root=tmp_path,
        dream_root=tmp_path / "Dream",
        core_exe=tmp_path / "core.exe",
        engine_exe=tmp_path / "engine.exe",
        wrapper=tmp_path / "wrapper.cmd",
        registry_path=tmp_path / "registry.json",
        frontend_dist=tmp_path / "dist",
    )
    client = TestClient(create_app(config=config, runtime=DreamRuntime(config)))

    response = client.get("/api/traces/latest")

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "runId": "latest",
        "message": "No native runtime trace is available",
        "truth": "unavailable",
    }


def test_runtime_trace_list_returns_only_valid_top_level_runs_newest_first(tmp_path: Path):
    config = DreamServerConfig(
        repo_root=tmp_path,
        dream_root=tmp_path / "Dream",
        core_exe=tmp_path / "core.exe",
        engine_exe=tmp_path / "engine.exe",
        wrapper=tmp_path / "wrapper.cmd",
        registry_path=tmp_path / "registry.json",
        frontend_dist=tmp_path / "dist",
    )
    traces = config.dream_root / "traces"
    traces.mkdir(parents=True)
    older = traces / "run-basic.json"
    newer = traces / "run-h7.json"
    older.write_text(json.dumps({
        "runId": "run-basic",
        "totalTimeMs": 12500,
        "nodes": [],
        "events": [],
        "evidence": {"modelId": "model-basic", "steps": 12, "backend": "CUDA"},
    }), encoding="utf-8")
    newer.write_text(json.dumps({
        "runId": "run-h7",
        "totalTimeMs": 22000,
        "nodes": [],
        "events": [],
        "evidence": {"modelId": "model-h7", "steps": 20, "backend": "CUDA"},
        "latentTelemetry": [{"not": "public"}],
    }), encoding="utf-8")
    (traces / "invalid.json").write_text("not json", encoding="utf-8")
    (traces / "empty.json").write_text("{}", encoding="utf-8")
    h7_dir = traces / "run-h7"
    h7_dir.mkdir()
    (h7_dir / "attention-index.json").write_text(json.dumps({"contractVersion": "wrong"}), encoding="utf-8")
    os.utime(older, (10, 10))
    os.utime(newer, (20, 20))
    os.utime(traces / "invalid.json", (30, 30))
    os.utime(h7_dir / "attention-index.json", (40, 40))
    os.utime(traces / "empty.json", (50, 50))
    client = TestClient(create_app(config=config, runtime=DreamRuntime(config)))

    response = client.get("/api/traces")

    assert response.status_code == 200
    assert response.json() == [
        {
            "runId": "run-h7",
            "totalTimeMs": 22000.0,
            "modelId": "model-h7",
            "steps": 20,
            "backend": "CUDA",
            "hasAttention": False,
            "hasLatent": False,
            "hasInfluence": False,
            "hasSelfAttention": False,
            "modifiedAt": "1970-01-01T00:00:20+00:00",
            "truth": "observed",
        },
        {
            "runId": "run-basic",
            "totalTimeMs": 12500.0,
            "modelId": "model-basic",
            "steps": 12,
            "backend": "CUDA",
            "hasAttention": False,
            "hasLatent": False,
            "hasInfluence": False,
            "hasSelfAttention": False,
            "modifiedAt": "1970-01-01T00:00:10+00:00",
            "truth": "observed",
        },
    ]
    assert client.get("/api/traces/latest").json()["runId"] == "run-h7"


def test_runtime_trace_exposes_only_observed_graph_data_and_known_fields(tmp_path: Path):
    config = DreamServerConfig(
        repo_root=tmp_path,
        dream_root=tmp_path / "Dream",
        core_exe=tmp_path / "core.exe",
        engine_exe=tmp_path / "engine.exe",
        wrapper=tmp_path / "wrapper.cmd",
        registry_path=tmp_path / "registry.json",
        frontend_dist=tmp_path / "dist",
    )
    traces = config.dream_root / "traces"
    traces.mkdir(parents=True)
    (traces / "run-truth.json").write_text(json.dumps({
        "available": True,
        "runId": "spoofed-run-id",
        "totalTimeMs": 2000,
        "nodes": [
            {"id": "unet", "name": "UNet", "backend": "CUDA", "expectedCalls": 99, "observedCalls": 2, "durationMs": 1500, "status": "executed", "truth": "observed"},
            {"id": "scheduler-derived", "name": "Scheduler estimate", "backend": "CPU", "durationMs": 300, "status": "executed", "truth": "derived"},
            {"id": "attention-demo", "name": "Attention demo", "backend": "Demo", "durationMs": 200, "status": "executed", "truth": "demo"},
        ],
        "events": [
            {"phase": "unet", "label": "UNet", "durationMs": 1500, "truth": "observed"},
            {"phase": "scheduler-derived", "label": "Scheduler estimate", "durationMs": 300, "truth": "derived"},
        ],
        "evidence": {"modelId": "model-1", "peakVramMiB": 2800, "peakRamBytes": 4_000_000_000},
        "tokenTrace": {"truth": "derived", "tokens": [1, 2, 3]},
        "conditioningInfluence": [{"truth": "demo", "deltaL2": 1.0}],
        "attentionTelemetry": [{"truth": "demo", "imageUrl": "/fake-heatmap.png"}],
    }), encoding="utf-8")
    client = TestClient(create_app(config=config, runtime=DreamRuntime(config)))

    response = client.get("/api/traces/run-truth")

    assert response.status_code == 200
    body = response.json()
    assert body["runId"] == "run-truth"
    assert body["nodes"] == [{
        "id": "unet",
        "name": "UNet",
        "backend": "CUDA",
        "expectedCalls": 99,
        "expectedCallsTruth": "derived",
        "observedCalls": 2,
        "observedCallsTruth": "observed",
        "durationMs": 1500,
        "status": "executed",
        "truth": "observed",
    }]
    assert body["events"] == [{"phase": "unet", "label": "UNet", "durationMs": 1500, "truth": "observed"}]
    assert body["evidence"]["peakVramMiB"] == 2800
    assert "tokenTrace" not in body
    assert "conditioningInfluence" not in body
    assert "attentionTelemetry" not in body
    assert client.get("/api/traces/latest").json()["runId"] == "run-truth"


def test_runtime_trace_sanitizes_overflow_and_unbounded_numeric_evidence(tmp_path: Path):
    config = DreamServerConfig(
        repo_root=tmp_path,
        dream_root=tmp_path / "Dream",
        core_exe=tmp_path / "core.exe",
        engine_exe=tmp_path / "engine.exe",
        wrapper=tmp_path / "wrapper.cmd",
        registry_path=tmp_path / "registry.json",
        frontend_dist=tmp_path / "dist",
    )
    traces = config.dream_root / "traces"
    traces.mkdir(parents=True)
    trace_assets = traces / "run-invalid-numbers"
    trace_assets.mkdir()
    (trace_assets / "latent-step-000.png").write_bytes(b"PNG")
    (trace_assets / "latent-step-000-ch0.png").write_bytes(b"PNG")
    overflowing = 10 ** 400
    huge_finite = 10 ** 300
    (traces / "run-invalid-numbers.json").write_text(json.dumps({
        "available": True,
        "runId": "run-invalid-numbers",
        "totalTimeMs": overflowing,
        "nodes": [{"id": "unet", "name": "UNet", "backend": "CUDA", "durationMs": overflowing, "status": "executed", "truth": "observed"}],
        "events": [{"phase": "unet", "label": "UNet", "durationMs": overflowing, "truth": "observed"}],
        "evidence": {
            "modelId": "model-1",
            "backend": "CUDA FP16",
            "steps": 51,
            "cfg": float("inf"),
            "peakVramMiB": -1,
            "peakRamBytes": 2 ** 53,
        },
        "latentTelemetry": [{
            "step": float("inf"),
            "shape": [64, 64, 4, 1],
            "mean": 0.0,
            "std": 1.0,
            "l2": 64.0,
            "truth": "observed",
            "kind": "latent-state",
            "channels": [{
                "channel": 0,
                "fileName": "latent-step-000-ch0.png",
                "min": -1.0,
                "max": 1.0,
                "mean": 0.0,
                "std": 1.0,
                "l2": 64.0,
                "histogram": [float("inf")] + [0] * 31,
                "truth": "observed",
                "kind": "latent-channel",
            }],
        }, {
            "step": 0,
            "shape": [64, huge_finite, 4, 1],
            "mean": 0.0,
            "std": 1.0,
            "l2": 64.0,
            "truth": "observed",
            "kind": "latent-state",
            "channels": [{
                "channel": 0,
                "fileName": "latent-step-000-ch0.png",
                "min": -1.0,
                "max": 1.0,
                "mean": 0.0,
                "std": 1.0,
                "l2": 64.0,
                "histogram": [0] * 32,
            }],
        }, {
            "step": 0,
            "shape": [64, 64, 4, 1],
            "mean": 0.0,
            "std": 1.0,
            "l2": 64.0,
            "truth": "observed",
            "kind": "latent-state",
            "channels": [{
                "channel": huge_finite,
                "fileName": "latent-step-000-ch0.png",
                "min": -1.0,
                "max": 1.0,
                "mean": 0.0,
                "std": 1.0,
                "l2": 64.0,
                "histogram": [0] * 32,
            }],
        }, {
            "step": 0,
            "shape": [64, 64, 4, 1],
            "mean": 0.0,
            "std": 1.0,
            "l2": 64.0,
            "truth": "observed",
            "kind": "latent-state",
            "channels": [{
                "channel": 0,
                "fileName": "latent-step-000-ch0.png",
                "min": -1.0,
                "max": 1.0,
                "mean": 0.0,
                "std": 1.0,
                "l2": 64.0,
                "histogram": [huge_finite] + [0] * 31,
            }],
        }],
        "latentPreviewFrames": [
            {"step": float("inf"), "fileName": "latent-step-000.png"},
            {"step": huge_finite, "fileName": "latent-step-000.png"},
        ],
    }), encoding="utf-8")
    client = TestClient(create_app(config=config, runtime=DreamRuntime(config)), raise_server_exceptions=False)

    response = client.get("/api/traces/run-invalid-numbers")

    assert response.status_code == 200
    body = response.json()
    assert body["totalTimeMs"] == 0
    assert "durationMs" not in body["nodes"][0]
    assert body["events"] == []
    assert body["latentTelemetry"] == []
    assert body["latentPreviewFrames"] == []
    assert body["evidence"] == {
        "modelId": "model-1",
        "backend": "CUDA FP16",
        "backendTruth": "observed",
        "truth": "observed",
    }


def test_hardware_snapshot_labels_the_detected_backend_as_derived(tmp_path: Path, monkeypatch):
    import subprocess
    from types import SimpleNamespace
    import psutil

    config = DreamServerConfig(
        repo_root=tmp_path,
        dream_root=tmp_path / "Dream",
        core_exe=tmp_path / "core.exe",
        engine_exe=tmp_path / "engine.exe",
        wrapper=tmp_path / "wrapper.cmd",
        registry_path=tmp_path / "registry.json",
        frontend_dist=tmp_path / "dist",
    )
    for dependency in (config.core_exe, config.engine_exe, config.wrapper, config.registry_path):
        dependency.write_text("ready", encoding="utf-8")
    runtime = DreamRuntime(config)
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(
        command, 0, "Test GPU, 6144, 1024, 12, 57, 32.5, 595.95\n", "",
    ))
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(total=64 * 1024**3, available=56 * 1024**3))
    client = TestClient(create_app(config=config, runtime=runtime))

    response = client.get("/api/hardware")

    assert response.status_code == 200
    assert response.json()["truth"] == "observed"
    assert response.json()["backend"] == "stable-diffusion.cpp + CUDA"
    assert response.json()["backendTruth"] == "derived"
    assert response.json()["vramUsedMiB"] == 1024
    assert response.json()["ramUsedBytes"] == 8 * 1024 ** 3
    assert response.json()["gpuTempC"] == 57


def test_latent_trace_serves_only_observed_projection_frames(tmp_path: Path):
    config = DreamServerConfig(
        repo_root=tmp_path,
        dream_root=tmp_path / "Dream",
        core_exe=tmp_path / "core.exe",
        engine_exe=tmp_path / "engine.exe",
        wrapper=tmp_path / "wrapper.cmd",
        registry_path=tmp_path / "registry.json",
        frontend_dist=tmp_path / "dist",
    )
    trace_dir = config.dream_root / "traces" / "run-1"
    trace_dir.mkdir(parents=True)
    (trace_dir / "latent-step-000.png").write_bytes(b"FRAME")
    (config.dream_root / "traces" / "run-1.json").write_text(json.dumps({
        "available": True,
        "runId": "run-1",
        "totalTimeMs": 1000,
        "nodes": [],
        "latentPreviewFrames": [{
            "step": 0,
            "fileName": "latent-step-000.png",
            "truth": "observed",
            "kind": "latent-projection",
        }],
    }), encoding="utf-8")
    client = TestClient(create_app(config=config, runtime=DreamRuntime(config)))

    latent = client.get("/api/traces/run-1/latent")
    frame = client.get("/api/traces/run-1/latent/frames/latent-step-000.png")

    assert latent.status_code == 200
    assert latent.json() == {
        "available": True,
        "runId": "run-1",
        "truth": "observed",
        "kind": "latent-projection",
        "telemetry": [],
        "frames": [{
            "step": 0,
            "fileName": "latent-step-000.png",
            "truth": "observed",
            "kind": "latent-projection",
            "imageUrl": "/api/traces/run-1/latent/frames/latent-step-000.png",
        }],
    }
    assert frame.status_code == 200
    assert frame.content == b"FRAME"


def test_latent_trace_serves_observed_telemetry_and_channel_frames(tmp_path: Path):
    config = DreamServerConfig(
        repo_root=tmp_path,
        dream_root=tmp_path / "Dream",
        core_exe=tmp_path / "core.exe",
        engine_exe=tmp_path / "engine.exe",
        wrapper=tmp_path / "wrapper.cmd",
        registry_path=tmp_path / "registry.json",
        frontend_dist=tmp_path / "dist",
    )
    trace_dir = config.dream_root / "traces" / "run-telemetry"
    trace_dir.mkdir(parents=True)
    (trace_dir / "latent-step-000-ch0.png").write_bytes(b"CHANNEL")
    (config.dream_root / "traces" / "run-telemetry.json").write_text(json.dumps({
        "available": True,
        "runId": "run-telemetry",
        "totalTimeMs": 1000,
        "nodes": [],
        "latentPreviewFrames": [],
        "latentTelemetry": [{
            "step": 0,
            "shape": [64, 64, 4, 1],
            "mean": 0.0,
            "std": 1.0,
            "l2": 64.0,
            "deltaL2": 0.75,
            "deltaMeanAbs": 0.0,
            "cosine": 0.98,
            "truth": "observed",
            "kind": "latent-state",
            "channels": [{
                "channel": 0,
                "fileName": "latent-step-000-ch0.png",
                "min": -2.0,
                "max": 2.0,
                "mean": 0.0,
                "std": 1.0,
                "l2": 32.0,
                "histogram": [1] * 32,
                "truth": "observed",
                "kind": "latent-channel",
            }],
        }],
    }), encoding="utf-8")
    client = TestClient(create_app(config=config, runtime=DreamRuntime(config)))

    latent = client.get("/api/traces/run-telemetry/latent")
    frame = client.get("/api/traces/run-telemetry/latent/frames/latent-step-000-ch0.png")

    assert latent.status_code == 200
    assert latent.json()["telemetry"][0]["channels"][0]["imageUrl"] == "/api/traces/run-telemetry/latent/frames/latent-step-000-ch0.png"
    assert latent.json()["telemetry"][0]["deltaL2"] == 0.75
    assert latent.json()["telemetry"][0]["deltaMeanAbs"] == 0.0
    assert latent.json()["telemetry"][0]["cosine"] == 0.98
    assert frame.status_code == 200
    assert frame.content == b"CHANNEL"


def test_latent_trace_rejects_a_frame_outside_the_run(tmp_path: Path):
    config = DreamServerConfig(
        repo_root=tmp_path,
        dream_root=tmp_path / "Dream",
        core_exe=tmp_path / "core.exe",
        engine_exe=tmp_path / "engine.exe",
        wrapper=tmp_path / "wrapper.cmd",
        registry_path=tmp_path / "registry.json",
        frontend_dist=tmp_path / "dist",
    )
    trace_dir = config.dream_root / "traces" / "run-1"
    trace_dir.mkdir(parents=True)
    (config.dream_root / "traces" / "run-1.json").write_text(json.dumps({
        "available": True,
        "runId": "run-1",
        "totalTimeMs": 1000,
        "nodes": [],
        "latentPreviewFrames": [],
    }), encoding="utf-8")
    client = TestClient(create_app(config=config, runtime=DreamRuntime(config)))

    response = client.get("/api/traces/run-1/latent/frames/../run-2/secret.png")

    assert response.status_code == 404


def test_h7_attention_api_serves_only_validated_observed_index_and_selected_map(tmp_path: Path):
    config = DreamServerConfig(
        repo_root=tmp_path,
        dream_root=tmp_path / "Dream",
        core_exe=tmp_path / "core.exe",
        engine_exe=tmp_path / "engine.exe",
        wrapper=tmp_path / "wrapper.cmd",
        registry_path=tmp_path / "registry.json",
        frontend_dist=tmp_path / "dist",
    )
    traces = config.dream_root / "traces"
    trace_dir = traces / "run-h7"
    trace_dir.mkdir(parents=True)
    (traces / "run-h7.json").write_text(json.dumps({
        "available": True,
        "runId": "run-h7",
        "totalTimeMs": 1000,
        "nodes": [],
    }), encoding="utf-8")
    (trace_dir / "attention-index.json").write_text(json.dumps({
        "contractVersion": "h7-attention-v1",
        "kind": "cross-attention",
        "truth": "observed",
        "source": "debug-unet",
        "tokens": [
            {"slot": 0, "tokenId": 49406, "text": "<start>", "chunk": 0, "weight": 1.0},
            {"slot": 1, "tokenId": 320, "text": "lake", "chunk": 0, "weight": 1.0},
        ],
        "layers": [
            {"id": "down-1", "stage": "down", "label": "Down 1"},
        ],
        "maps": [{
            "id": "s00-down-1-t01",
            "step": 0,
            "layerId": "down-1",
            "tokenSlot": 1,
            "width": 2,
            "height": 2,
            "fileName": "attention-s000-down-1-t001.json",
            "entropy": 0.71,
            "peak": 0.83,
            "coverage": 0.25,
        }],
    }), encoding="utf-8")
    (trace_dir / "attention-s000-down-1-t001.json").write_text(json.dumps({
        "contractVersion": "h7-attention-v1",
        "kind": "cross-attention",
        "truth": "observed",
        "source": "debug-unet",
        "id": "s00-down-1-t01",
        "step": 0,
        "layerId": "down-1",
        "tokenSlot": 1,
        "width": 2,
        "height": 2,
        "values": [0.0, 0.25, 0.5, 1.0],
        "entropy": 0.71,
        "peak": 0.83,
        "coverage": 0.25,
    }), encoding="utf-8")
    client = TestClient(create_app(config=config, runtime=DreamRuntime(config)))

    index_response = client.get("/api/traces/run-h7/attention")
    map_response = client.get("/api/traces/run-h7/attention/maps/s00-down-1-t01")

    assert index_response.status_code == 200
    assert index_response.json() == {
        "available": True,
        "runId": "run-h7",
        "contractVersion": "h7-attention-v1",
        "kind": "cross-attention",
        "truth": "observed",
        "source": "debug-unet",
        "tokens": [
            {"slot": 0, "tokenId": 49406, "text": "<start>", "chunk": 0, "weight": 1.0},
            {"slot": 1, "tokenId": 320, "text": "lake", "chunk": 0, "weight": 1.0},
        ],
        "layers": [{"id": "down-1", "stage": "down", "label": "Down 1"}],
        "maps": [{
            "id": "s00-down-1-t01",
            "step": 0,
            "layerId": "down-1",
            "tokenSlot": 1,
            "width": 2,
            "height": 2,
            "entropy": 0.71,
            "peak": 0.83,
            "coverage": 0.25,
            "mapUrl": "/api/traces/run-h7/attention/maps/s00-down-1-t01",
        }],
    }
    assert map_response.status_code == 200
    assert map_response.json()["values"] == [0.0, 0.25, 0.5, 1.0]
    assert map_response.json()["truth"] == "observed"


def test_h7_attention_index_rejects_duplicate_representative_stages(tmp_path: Path):
    config = DreamServerConfig(
        repo_root=tmp_path,
        dream_root=tmp_path / "Dream",
        core_exe=tmp_path / "core.exe",
        engine_exe=tmp_path / "engine.exe",
        wrapper=tmp_path / "wrapper.cmd",
        registry_path=tmp_path / "registry.json",
        frontend_dist=tmp_path / "dist",
    )
    traces = config.dream_root / "traces"
    trace_dir = traces / "run-duplicate-stage"
    trace_dir.mkdir(parents=True)
    (traces / "run-duplicate-stage.json").write_text(json.dumps({"runId": "run-duplicate-stage", "totalTimeMs": 1, "nodes": []}), encoding="utf-8")
    (trace_dir / "attention-index.json").write_text(json.dumps({
        "contractVersion": "h7-attention-v1",
        "kind": "cross-attention",
        "truth": "observed",
        "source": "debug-unet",
        "tokens": [{"slot": 0, "tokenId": 1, "text": "lake", "chunk": 0, "weight": 1.0}],
        "layers": [
            {"id": "down-1", "stage": "down", "label": "Down 1"},
            {"id": "down-2", "stage": "down", "label": "Down 2"},
        ],
        "maps": [{
            "id": "s00-down-1-t00",
            "step": 0,
            "layerId": "down-1",
            "tokenSlot": 0,
            "width": 1,
            "height": 1,
            "fileName": "attention-s000-down-1-t000.json",
            "entropy": 0.0,
            "peak": 1.0,
            "coverage": 1.0,
        }],
    }), encoding="utf-8")
    client = TestClient(create_app(config=config, runtime=DreamRuntime(config)))

    response = client.get("/api/traces/run-duplicate-stage/attention")

    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["truth"] == "unavailable"


def test_h7_attention_index_rejects_ambiguous_duplicate_map_selection(tmp_path: Path):
    config = DreamServerConfig(
        repo_root=tmp_path,
        dream_root=tmp_path / "Dream",
        core_exe=tmp_path / "core.exe",
        engine_exe=tmp_path / "engine.exe",
        wrapper=tmp_path / "wrapper.cmd",
        registry_path=tmp_path / "registry.json",
        frontend_dist=tmp_path / "dist",
    )
    traces = config.dream_root / "traces"
    trace_dir = traces / "run-duplicate-map"
    trace_dir.mkdir(parents=True)
    (traces / "run-duplicate-map.json").write_text(json.dumps({"runId": "run-duplicate-map", "totalTimeMs": 1, "nodes": []}), encoding="utf-8")
    descriptor = {
        "step": 0,
        "layerId": "mid-1",
        "tokenSlot": 0,
        "width": 1,
        "height": 1,
        "entropy": 0.0,
        "peak": 1.0,
        "coverage": 1.0,
    }
    (trace_dir / "attention-index.json").write_text(json.dumps({
        "contractVersion": "h7-attention-v1",
        "kind": "cross-attention",
        "truth": "observed",
        "source": "debug-unet",
        "tokens": [{"slot": 0, "tokenId": 1, "text": "lake", "chunk": 0, "weight": 1.0}],
        "layers": [{"id": "mid-1", "stage": "mid", "label": "Mid 1"}],
        "maps": [
            {"id": "map-a", "fileName": "attention-map-a.json", **descriptor},
            {"id": "map-b", "fileName": "attention-map-b.json", **descriptor},
        ],
    }), encoding="utf-8")
    client = TestClient(create_app(config=config, runtime=DreamRuntime(config)))

    response = client.get("/api/traces/run-duplicate-map/attention")

    assert response.status_code == 200
    assert response.json()["available"] is False
