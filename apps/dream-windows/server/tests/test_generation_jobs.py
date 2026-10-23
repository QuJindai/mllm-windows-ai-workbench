from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import create_app
from config import DreamServerConfig
from research_fixtures import install_research_engine
from models import ExperimentRequest, GenerateRequest
from runtime import DreamApiError, DreamRuntime
from job_runner import JobRunner, NativeRunResult


def make_config(tmp_path: Path) -> DreamServerConfig:
    dream_root = tmp_path / "Dream"
    (dream_root / "app" / "current").mkdir(parents=True)
    (dream_root / "app" / "stable-diffusion-cpp").mkdir(parents=True)
    (dream_root / "models" / "windows" / "gguf").mkdir(parents=True)
    (dream_root / "data").mkdir()
    core = dream_root / "app" / "current" / "dream-core.exe"
    engine = dream_root / "app" / "stable-diffusion-cpp" / "sd-cli.exe"
    wrapper = tmp_path / "wrapper.cmd"
    core.write_bytes(b"core")
    engine.write_bytes(b"engine")
    wrapper.write_bytes(b"wrapper")
    model_path = dream_root / "models" / "windows" / "gguf" / "model.gguf"
    model_path.write_bytes(b"model")
    registry = tmp_path / "model-registry.json"
    registry.write_text(json.dumps({"models": [{"model_id": "model", "display_name": "Model", "status": "installed", "windows": {"path": str(model_path), "format": "gguf", "identity_status": "verified-local"}}]}), encoding="utf-8")
    return DreamServerConfig(
        repo_root=tmp_path,
        dream_root=dream_root,
        core_exe=core,
        engine_exe=engine,
        wrapper=wrapper,
        registry_path=registry,
        frontend_dist=tmp_path / "dist",
    )


def test_generation_rejects_unknown_model(tmp_path: Path):
    config = make_config(tmp_path)
    runtime = DreamRuntime(config, job_runner=JobRunner(config))

    with pytest.raises(DreamApiError) as error:
        runtime.generate(GenerateRequest(prompt="test", modelId="missing", seed=1))

    assert error.value.code == "MODEL_NOT_FOUND"


def test_legacy_model_alias_resolves_and_is_normalized_before_submission(tmp_path: Path):
    config = make_config(tmp_path)
    registry = json.loads(config.registry_path.read_text(encoding="utf-8"))
    registry["models"][0]["aliases"] = ["legacy-model"]
    config.registry_path.write_text(json.dumps(registry), encoding="utf-8")

    class CapturingRunner:
        def __init__(self):
            self.request = None

        def submit(self, request):
            self.request = request
            return {"id": "job-alias", "request": request.model_dump(by_alias=True)}

    runner = CapturingRunner()
    runtime = DreamRuntime(config, job_runner=runner)

    assert runtime.get_model("legacy-model")["id"] == "model"
    submitted = runtime.generate(GenerateRequest(prompt="test", modelId="legacy-model", seed=1))

    assert runner.request is not None
    assert runner.request.model_id == "model"
    assert submitted["request"]["modelId"] == "model"


def test_legacy_model_alias_uses_canonical_name_in_history(tmp_path: Path):
    config = make_config(tmp_path)
    registry = json.loads(config.registry_path.read_text(encoding="utf-8"))
    registry["models"][0]["display_name"] = "Canonical Model"
    registry["models"][0]["aliases"] = ["legacy-model"]
    config.registry_path.write_text(json.dumps(registry), encoding="utf-8")
    output_dir = config.dream_root / "outputs" / "2026-09-08"
    output_dir.mkdir(parents=True)
    (output_dir / "legacy.png").write_bytes(b"PNG")
    (output_dir / "legacy.json").write_text(
        json.dumps({"id": "legacy", "model_id": "legacy-model", "output": str(output_dir / "legacy.png")}),
        encoding="utf-8",
    )

    item = DreamRuntime(config, job_runner=JobRunner(config)).history({"page": 1, "page_size": 10, "filter": "all", "query": ""})["items"][0]

    assert item["modelId"] == "model"
    assert item["modelName"] == "Canonical Model"


def test_history_exposes_registered_generation_defaults_for_quality_assessment(tmp_path: Path):
    config = make_config(tmp_path)
    registry = json.loads(config.registry_path.read_text(encoding="utf-8"))
    registry["models"][0]["generation_defaults"] = {
        "width": 768,
        "height": 768,
        "steps": 4,
        "cfg": 2.0,
        "sampling_method": "dpm++2m",
        "scheduler": "discrete",
    }
    config.registry_path.write_text(json.dumps(registry), encoding="utf-8")
    output_dir = config.dream_root / "outputs" / "2026-09-20"
    output_dir.mkdir(parents=True)
    (output_dir / "lightning.png").write_bytes(b"PNG")
    (output_dir / "lightning.json").write_text(
        json.dumps({"id": "lightning", "model_id": "model", "steps": 4, "output": str(output_dir / "lightning.png")}),
        encoding="utf-8",
    )

    item = DreamRuntime(config, job_runner=JobRunner(config)).history({"page": 1, "page_size": 10, "filter": "all", "query": ""})["items"][0]

    assert item["generationDefaults"] == {
        "width": 768,
        "height": 768,
        "steps": 4,
        "cfg": 2.0,
        "samplingMethod": "dpm++2m",
        "scheduler": "discrete",
    }


def test_cancelling_unknown_job_returns_structured_not_found(tmp_path: Path):
    runner = JobRunner(make_config(tmp_path))

    with pytest.raises(DreamApiError) as error:
        runner.cancel("job-does-not-exist")

    assert error.value.code == "JOB_NOT_FOUND"


def test_cancelling_a_queued_job_keeps_it_terminal_and_skips_native_execution(tmp_path: Path):
    config = make_config(tmp_path)
    first_started = threading.Event()
    release_first = threading.Event()
    third_started = threading.Event()
    native_job_ids: list[str] = []
    third_job_id: str | None = None

    def controlled_runner(command, env, cwd, stdout_log, stderr_log):
        output = Path(command[command.index("--output") + 1])
        metadata = Path(command[command.index("--metadata") + 1])
        job_id = output.stem
        native_job_ids.append(job_id)
        if len(native_job_ids) == 1:
            first_started.set()
            assert release_first.wait(timeout=2)
        if job_id == third_job_id:
            third_started.set()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"PNG")
        metadata.write_text(json.dumps({"model_id": "model"}), encoding="utf-8")
        return NativeRunResult(returncode=0, stdout='{"ok":true}', stderr="")

    runner = JobRunner(config, command_runner=controlled_runner)
    first = runner.submit(GenerateRequest(prompt="first", modelId="model", seed=1))
    assert first_started.wait(timeout=2)
    cancelled = runner.submit(GenerateRequest(prompt="cancel me", modelId="model", seed=2))
    assert runner.cancel(cancelled["id"])["state"] == "cancelled"
    third = runner.submit(GenerateRequest(prompt="third", modelId="model", seed=3))
    third_job_id = third["id"]

    release_first.set()
    assert third_started.wait(timeout=2)

    assert cancelled["id"] not in native_job_ids
    assert runner.get(cancelled["id"])["state"] == "cancelled"
    assert native_job_ids == [first["id"], third["id"]]


def test_cancellation_between_preparing_and_sampling_is_not_overwritten(tmp_path: Path):
    command_built = threading.Event()
    release_command = threading.Event()
    execution_finished = threading.Event()
    native_called = threading.Event()

    class PreparingBoundaryRunner(JobRunner):
        def _command(self, request, seed, output, metadata, trace_dir):
            command_built.set()
            assert release_command.wait(timeout=2)
            return super()._command(request, seed, output, metadata, trace_dir)

        def _execute(self, *args, **kwargs):
            try:
                return super()._execute(*args, **kwargs)
            finally:
                execution_finished.set()

    def native_runner(command, env, cwd, stdout_log, stderr_log):
        native_called.set()
        return NativeRunResult(returncode=1, stdout="", stderr="must not run")

    runner = PreparingBoundaryRunner(make_config(tmp_path), command_runner=native_runner)
    job = runner.submit(GenerateRequest(prompt="test", modelId="model", seed=1))
    assert command_built.wait(timeout=2)
    assert runner.get(job["id"])["state"] == "preparing"

    runner.cancel(job["id"])
    release_command.set()
    assert execution_finished.wait(timeout=2)

    assert native_called.is_set() is False
    assert runner.get(job["id"])["state"] == "cancelled"


def test_cancellation_between_decoding_and_completion_is_not_overwritten(tmp_path: Path):
    decoding_reached = threading.Event()
    release_decoding = threading.Event()
    execution_finished = threading.Event()

    class DecodingBoundaryRunner(JobRunner):
        def _write_process_trace(self, *args, **kwargs):
            decoding_reached.set()
            assert release_decoding.wait(timeout=2)

        def _execute(self, *args, **kwargs):
            try:
                return super()._execute(*args, **kwargs)
            finally:
                execution_finished.set()

    def native_runner(command, env, cwd, stdout_log, stderr_log):
        output = Path(command[command.index("--output") + 1])
        metadata = Path(command[command.index("--metadata") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"PNG")
        metadata.write_text(json.dumps({"model_id": "model"}), encoding="utf-8")
        return NativeRunResult(returncode=0, stdout='{"ok":true}', stderr="")

    runner = DecodingBoundaryRunner(make_config(tmp_path), command_runner=native_runner)
    job = runner.submit(GenerateRequest(prompt="test", modelId="model", seed=1, traceLevel="h6"))
    assert decoding_reached.wait(timeout=2)
    assert runner.get(job["id"])["state"] == "decoding"

    runner.cancel(job["id"])
    release_decoding.set()
    assert execution_finished.wait(timeout=2)

    assert runner.get(job["id"])["state"] == "cancelled"


def test_cancel_after_pre_native_check_prevents_a_new_command_runner_start(tmp_path: Path):
    pre_native_check_passed = threading.Event()
    release_pre_native_boundary = threading.Event()
    execution_finished = threading.Event()
    native_started = threading.Event()

    class LastCheckBoundaryRunner(JobRunner):
        def _is_cancelled(self, job_id):
            cancelled = super()._is_cancelled(job_id)
            if not cancelled and not pre_native_check_passed.is_set():
                pre_native_check_passed.set()
                assert release_pre_native_boundary.wait(timeout=2)
            return cancelled

        def _execute(self, *args, **kwargs):
            try:
                return super()._execute(*args, **kwargs)
            finally:
                execution_finished.set()

    def native_runner(command, env, cwd, stdout_log, stderr_log):
        native_started.set()
        return NativeRunResult(returncode=1, stdout="", stderr="must not start")

    runner = LastCheckBoundaryRunner(make_config(tmp_path), command_runner=native_runner)
    job = runner.submit(GenerateRequest(prompt="test", modelId="model", seed=1))
    assert pre_native_check_passed.wait(timeout=2)

    cancelled = runner.cancel(job["id"])
    release_pre_native_boundary.set()
    assert execution_finished.wait(timeout=2)

    assert cancelled["state"] == "cancelled"
    assert native_started.is_set() is False
    assert runner.get(job["id"])["state"] == "cancelled"


def test_cancel_waits_for_a_committed_command_runner_handoff_before_returning(tmp_path: Path):
    invocation_committed = threading.Event()
    allow_runner_entry = threading.Event()
    native_entered = threading.Event()
    cancel_marked = threading.Event()
    cancel_returned = threading.Event()
    repeated_cancel_returned = threading.Event()
    execution_finished = threading.Event()
    cancelled_records: list[dict] = []
    repeated_cancelled_records: list[dict] = []

    class CommandRunnerHandoff(JobRunner):
        def _invoke_command_runner(self, runner, command, env, cwd, stdout_log, stderr_log):
            invocation_committed.set()
            assert allow_runner_entry.wait(timeout=2)
            return super()._invoke_command_runner(runner, command, env, cwd, stdout_log, stderr_log)

        def _update(self, job_id, **changes):
            record = super()._update(job_id, **changes)
            if changes.get("state") == "cancelled":
                cancel_marked.set()
            return record

        def _execute(self, *args, **kwargs):
            try:
                return super()._execute(*args, **kwargs)
            finally:
                execution_finished.set()

    def native_runner(command, env, cwd, stdout_log, stderr_log):
        native_entered.set()
        return NativeRunResult(returncode=1, stdout="", stderr="cancelled handoff")

    runner = CommandRunnerHandoff(make_config(tmp_path), command_runner=native_runner)
    job = runner.submit(GenerateRequest(prompt="test", modelId="model", seed=1))
    assert invocation_committed.wait(timeout=2)

    def cancel_job() -> None:
        cancelled_records.append(runner.cancel(job["id"]))
        cancel_returned.set()

    cancellation = threading.Thread(target=cancel_job)
    cancellation.start()
    assert cancel_marked.wait(timeout=2)
    assert cancel_returned.wait(timeout=0.1) is False
    assert native_entered.is_set() is False

    def cancel_job_again() -> None:
        repeated_cancelled_records.append(runner.cancel(job["id"]))
        repeated_cancel_returned.set()

    repeated_cancellation = threading.Thread(target=cancel_job_again)
    repeated_cancellation.start()
    assert repeated_cancel_returned.wait(timeout=0.1) is False

    allow_runner_entry.set()
    assert native_entered.wait(timeout=2)
    assert cancel_returned.wait(timeout=2)
    assert repeated_cancel_returned.wait(timeout=2)
    assert execution_finished.wait(timeout=2)
    cancellation.join(timeout=2)
    repeated_cancellation.join(timeout=2)

    assert cancelled_records[0]["state"] == "cancelled"
    assert repeated_cancelled_records[0]["state"] == "cancelled"
    assert runner.get(job["id"])["state"] == "cancelled"


def test_cancelling_an_active_process_terminates_it_without_waiting_for_generation(tmp_path: Path, monkeypatch):
    communicating = threading.Event()
    terminated = threading.Event()
    execution_finished = threading.Event()

    class ControlledProcess:
        returncode = -15

        def __init__(self, *args, **kwargs):
            pass

        def communicate(self):
            communicating.set()
            assert terminated.wait(timeout=2)
            return "", "terminated"

        def poll(self):
            return -15 if terminated.is_set() else None

        def terminate(self):
            terminated.set()

    class ProcessRunner(JobRunner):
        def _execute(self, *args, **kwargs):
            try:
                return super()._execute(*args, **kwargs)
            finally:
                execution_finished.set()

    monkeypatch.setattr("job_runner.subprocess.Popen", ControlledProcess)
    runner = ProcessRunner(make_config(tmp_path))
    job = runner.submit(GenerateRequest(prompt="test", modelId="model", seed=1))
    assert communicating.wait(timeout=2)

    cancelled = runner.cancel(job["id"])
    assert execution_finished.wait(timeout=2)

    assert cancelled["state"] == "cancelled"
    assert terminated.is_set()
    assert runner.get(job["id"])["state"] == "cancelled"


def test_generation_defaults_use_balanced_standard_model_profile():
    request = GenerateRequest(prompt="test", modelId="model", seed=1)

    assert request.width == 768
    assert request.height == 768
    assert request.steps == 20
    assert request.cfg == 4.0
    assert request.sampling_method == "dpm++2m_sde"
    assert request.scheduler == "karras"
    assert request.trace_level == "basic"


def test_job_command_propagates_sampling_profile(tmp_path: Path):
    config = make_config(tmp_path)
    runner = JobRunner(config)
    request = GenerateRequest(
        prompt="test",
        modelId="model",
        seed=1,
        width=256,
        height=256,
        steps=20,
        cfg=7.0,
        samplingMethod="dpm++2m",
        scheduler="karras",
    )

    command = runner._command(request, 1, tmp_path / "out.png", tmp_path / "out.json", config.dream_root / "traces" / "job-1")

    assert command[command.index("--sampling-method") + 1] == "dpm++2m"
    assert command[command.index("--scheduler") + 1] == "karras"


def test_job_command_propagates_microscope_capture_options(tmp_path: Path):
    config = make_config(tmp_path)
    runner = JobRunner(config)
    request = GenerateRequest(prompt="test", modelId="model", seed=1, traceLevel="h6")

    command = runner._command(request, 1, tmp_path / "out.png", tmp_path / "out.json", config.dream_root / "traces" / "job-1")

    assert command[command.index("--trace-level") + 1] == "h6"
    assert Path(command[command.index("--trace-dir") + 1]) == config.dream_root / "traces" / "job-1"


def test_h7_generation_uses_isolated_attention_engine_without_changing_production_engine(tmp_path: Path):
    config = make_config(tmp_path)
    h7_engine = config.dream_root / "app" / "stable-diffusion-cuda-h7" / "sd-cli.exe"
    h7_engine.parent.mkdir(parents=True)
    h7_engine.write_bytes(b"h7-engine")
    (h7_engine.parent / "build-manifest.json").write_text(json.dumps({
        "schemaVersion": 1,
        "executable": "sd-cli.exe",
        "capabilities": ["h7-attention-v1"],
        "source": "debug-unet",
    }), encoding="utf-8")
    runner = JobRunner(config)

    normal_env = runner._environment(GenerateRequest(prompt="test", modelId="model", seed=1, traceLevel="basic"))
    h7_env = runner._environment(GenerateRequest(prompt="test", modelId="model", seed=1, traceLevel="h7"))

    assert Path(normal_env["DREAM_STABLE_DIFFUSION_CPP_EXE"]) == config.engine_exe
    assert Path(h7_env["DREAM_STABLE_DIFFUSION_CPP_EXE"]) == h7_engine
    assert config.engine_exe != h7_engine


def test_h7_capability_requires_manifest_and_is_reported_as_observed(tmp_path: Path):
    config = make_config(tmp_path)
    runtime = DreamRuntime(config, job_runner=JobRunner(config))

    assert runtime.capabilities()["attention"]["available"] is False
    assert runtime.research_status()["available"] is False

    h7_engine = config.dream_root / "app" / "stable-diffusion-cuda-h7" / "sd-cli.exe"
    h7_engine.parent.mkdir(parents=True)
    h7_engine.write_bytes(b"h7-engine")
    (h7_engine.parent / "build-manifest.json").write_text(json.dumps({
        "schemaVersion": 1,
        "executable": "sd-cli.exe",
        "capabilities": ["h7-attention-v1"],
        "source": "debug-unet",
    }), encoding="utf-8")

    assert runtime.capabilities()["attention"] == {
        "available": True,
        "truth": "observed",
        "message": "H7 Debug UNet cross-attention 采集已就绪",
    }
    assert runtime.research_status() == {
        "available": False,
        "message": "H7 研究引擎未安装或构建清单无效",
        "truth": "unavailable",
    }


def test_generation_profile_is_not_hardcoded_to_lcm():
    wrapper = Path(__file__).resolve().parents[4] / "scripts" / "run_stable_diffusion_wrapper.ps1"
    text = wrapper.read_text(encoding="utf-8")

    assert "New-DreamStableDiffusionArguments" in text
    assert '"dpm++2m_sde"' in text
    assert '"exponential"' in text
    assert '"--sampling-method", "lcm"' not in text
    assert '"--scheduler", "exponential"' not in text


def test_wrapper_uses_a_computed_safe_vram_budget():
    wrapper = Path(__file__).resolve().parents[4] / "scripts" / "run_stable_diffusion_wrapper.ps1"
    text = wrapper.read_text(encoding="utf-8")

    assert "-MaxVramGb $maxVramGb" in text
    assert '"--max-vram", "5.2"' not in text
    assert "DREAM_CUDA_MAX_VRAM_GB" in text


def test_wrapper_records_total_vram_and_selected_budget():
    wrapper = Path(__file__).resolve().parents[4] / "scripts" / "run_stable_diffusion_wrapper.ps1"
    text = wrapper.read_text(encoding="utf-8")

    assert "total_vram_mib" in text
    assert "cuda_budget_gb" in text


def test_wrapper_records_dream_process_vram_separately():
    wrapper = Path(__file__).resolve().parents[4] / "scripts" / "run_stable_diffusion_wrapper.ps1"
    text = wrapper.read_text(encoding="utf-8")

    assert "query-compute-apps=pid,used_gpu_memory" in text
    assert "dream_vram_mib" in text
    assert "peak_dream_vram_mib" in text


def test_wrapper_captures_real_projection_previews_for_microscope_levels():
    wrapper = Path(__file__).resolve().parents[4] / "scripts" / "run_stable_diffusion_wrapper.ps1"
    support = Path(__file__).resolve().parents[4] / "scripts" / "DreamEngineSupport.psm1"
    text = wrapper.read_text(encoding="utf-8")
    support_text = support.read_text(encoding="utf-8")

    assert "$traceLevel" in text
    assert "New-DreamStableDiffusionArguments" in text
    assert '"--preview", "proj"' in support_text
    assert '"--preview-interval", "1"' in support_text
    assert "latent-step-%03d.png" in support_text


def test_wrapper_routes_h7_to_native_attention_trace_artifact():
    wrapper = Path(__file__).resolve().parents[4] / "scripts" / "run_stable_diffusion_wrapper.ps1"
    support = Path(__file__).resolve().parents[4] / "scripts" / "DreamEngineSupport.psm1"
    text = wrapper.read_text(encoding="utf-8")
    support_text = support.read_text(encoding="utf-8")

    assert "--attention-trace-path" in text
    assert "attention-index.json" in text
    assert "-AttentionTraceSupported $attentionTraceSupported" in text
    assert '"--attention-trace-path"' in support_text


def test_generation_job_persists_real_artifact_and_metadata(tmp_path: Path):
    config = make_config(tmp_path)

    def fake_runner(command, env, cwd, stdout_log, stderr_log):
        output = Path(command[command.index("--output") + 1])
        metadata = Path(command[command.index("--metadata") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"PNG")
        metadata.write_text(json.dumps({"model_id": "model", "prompt": "test", "width": 256, "height": 256}), encoding="utf-8")
        return NativeRunResult(returncode=0, stdout='{"ok":true}', stderr="")

    runtime = DreamRuntime(config, job_runner=JobRunner(config, command_runner=fake_runner))
    record = runtime.generate(GenerateRequest(prompt="test", modelId="model", seed=1, width=256, height=256))

    deadline = time.time() + 2
    while time.time() < deadline:
        record = runtime.get_job(record["id"])
        if record["state"] in {"complete", "failed"}:
            break
        time.sleep(0.01)

    assert record["state"] == "complete"
    assert Path(record["result"]["filePath"]).read_bytes() == b"PNG"
    assert Path(record["result"]["metadataPath"]).exists()


def test_experiment_variants_use_the_one_worker_queue_in_order_and_reload_stably(tmp_path: Path):
    config = make_config(tmp_path)
    install_research_engine(config)
    gate = threading.Semaphore(0)
    lock = threading.Lock()
    started: list[str] = []
    finished: list[str] = []
    active = 0
    max_active = 0

    def controlled_runner(command, env, cwd, stdout_log, stderr_log):
        nonlocal active, max_active
        output = Path(command[command.index("--output") + 1])
        metadata = Path(command[command.index("--metadata") + 1])
        job_id = output.stem
        with lock:
            active += 1
            max_active = max(max_active, active)
            started.append(job_id)
        if not gate.acquire(timeout=5):
            return NativeRunResult(returncode=1, stdout="", stderr="test gate timed out")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(f"PNG-{job_id}".encode())
        metadata.write_text(json.dumps({
            "id": job_id,
            "output": str(output),
            "model_id": command[command.index("--model") + 1],
            "prompt": command[command.index("--prompt") + 1],
            "negative_prompt": command[command.index("--negative") + 1],
            "seed": int(command[command.index("--seed") + 1]),
            "steps": int(command[command.index("--steps") + 1]),
            "cfg": float(command[command.index("--cfg") + 1]),
        }), encoding="utf-8")
        with lock:
            active -= 1
            finished.append(job_id)
        return NativeRunResult(returncode=0, stdout='{"ok":true}', stderr="")

    runner = JobRunner(config, command_runner=controlled_runner)
    runtime = DreamRuntime(config, job_runner=runner)
    created = runtime.run_experiment(ExperimentRequest(
        kind="steps",
        seed=987654,
        modelId="model",
        prompt="misty mountain lake",
        negativePrompt="text, watermark",
        steps=31,
        cfg=6.25,
    ))
    variant_ids = [variant["id"] for variant in created["variants"]]
    job_ids = [variant["jobId"] for variant in created["variants"]]

    deadline = time.time() + 2
    while time.time() < deadline and len(started) < 1:
        time.sleep(0.01)
    assert started == [job_ids[0]]
    assert max_active == 1
    assert [runner.get(job_id)["state"] for job_id in job_ids[1:]] == ["queued", "queued", "queued"]

    for index in range(4):
        gate.release()
        expected_finished = index + 1
        expected_started = min(index + 2, 4)
        deadline = time.time() + 2
        while time.time() < deadline:
            with lock:
                if len(finished) >= expected_finished and len(started) >= expected_started:
                    break
            time.sleep(0.01)

    assert started == job_ids
    assert finished == job_ids
    assert max_active == 1
    records = [runner.get(job_id) for job_id in job_ids]
    assert [record["request"]["prompt"] for record in records] == ["misty mountain lake"] * 4
    assert [record["request"]["negativePrompt"] for record in records] == ["text, watermark"] * 4
    assert [record["request"]["modelId"] for record in records] == ["model"] * 4
    assert [record["request"]["seed"] for record in records] == [987654] * 4
    assert [record["request"]["steps"] for record in records] == [8, 16, 24, 31]
    assert [record["request"]["cfg"] for record in records] == [6.25] * 4

    reloaded_runtime = DreamRuntime(config, job_runner=JobRunner(config))
    client = TestClient(create_app(config=config, runtime=reloaded_runtime))
    reloaded_response = client.get(f"/api/experiments/{created['id']}")
    reloaded = reloaded_response.json()

    assert reloaded_response.status_code == 200
    assert reloaded["status"] == "complete"
    assert [variant["id"] for variant in reloaded["variants"]] == variant_ids
    assert [variant["jobId"] for variant in reloaded["variants"]] == job_ids
    assert [variant["imageUrl"] for variant in reloaded["variants"]] == [f"/api/history/{job_id}/image" for job_id in job_ids]
    assert all("metric" not in variant for variant in reloaded["variants"])
    assert [client.get(variant["imageUrl"]).content for variant in reloaded["variants"]] == [f"PNG-{job_id}".encode() for job_id in job_ids]


def test_generation_job_persists_observed_latent_telemetry_and_channel_frames(tmp_path: Path):
    config = make_config(tmp_path)
    install_research_engine(config)

    def fake_runner(command, env, cwd, stdout_log, stderr_log):
        output = Path(command[command.index("--output") + 1])
        metadata = Path(command[command.index("--metadata") + 1])
        trace_dir = Path(command[command.index("--trace-dir") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        trace_dir.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"PNG")
        metadata.write_text(json.dumps({"model_id": "model", "backend": "cuda", "generation_time_ms": 3000}), encoding="utf-8")
        (trace_dir / "latent-metrics.jsonl").write_text(json.dumps({
            "step": 0,
            "shape": [64, 64, 4, 1],
            "mean": -0.0031,
            "std": 1.0276,
            "l2": 65.43,
            "delta_l2": None,
            "delta_mean_abs": None,
            "cosine": None,
            "truth": "observed",
            "kind": "latent-state",
            "channels": [{
                "channel": channel,
                "min": -2.3,
                "max": 2.2,
                "mean": -0.01,
                "std": 1.02,
                "l2": 65.4,
                "histogram": [1] * 32,
                "file_name": f"latent-step-000-ch{channel}.png",
            } for channel in range(4)],
        }) + "\n", encoding="utf-8")
        for channel in range(4):
            (trace_dir / f"latent-step-000-ch{channel}.png").write_bytes(f"CHANNEL-{channel}".encode())
        return NativeRunResult(returncode=0, stdout='{"generation_time_ms":3000}', stderr="")

    runtime = DreamRuntime(config, job_runner=JobRunner(config, command_runner=fake_runner))
    record = runtime.generate(GenerateRequest(prompt="test", modelId="model", seed=1, steps=1, traceLevel="h6"))

    deadline = time.time() + 2
    while time.time() < deadline:
        record = runtime.get_job(record["id"])
        if record["state"] in {"complete", "failed"}:
            break
        time.sleep(0.01)

    trace = json.loads((config.dream_root / "traces" / f"{record['id']}.json").read_text(encoding="utf-8"))
    assert record["state"] == "complete"
    assert trace["latentTelemetry"][0]["truth"] == "observed"
    assert trace["latentTelemetry"][0]["shape"] == [64, 64, 4, 1]
    assert trace["latentTelemetry"][0]["channels"][3]["fileName"] == "latent-step-000-ch3.png"
    assert trace["evidence"]["backend"] == "CUDA"


def test_latent_sample_rejects_channels_outside_the_declared_tensor_shape(tmp_path: Path):
    config = make_config(tmp_path)
    runner = JobRunner(config, command_runner=lambda *args: NativeRunResult(0, "", ""))
    trace_dir = config.dream_root / "traces" / "invalid-channels"
    trace_dir.mkdir(parents=True)
    channels = []
    for channel in range(4, 8):
        file_name = f"latent-step-000-ch{channel}.png"
        (trace_dir / file_name).write_bytes(b"CHANNEL")
        channels.append({
            "channel": channel,
            "min": -2.3,
            "max": 2.2,
            "mean": -0.01,
            "std": 1.02,
            "l2": 65.4,
            "histogram": [1] * 32,
            "file_name": file_name,
        })

    sample = runner._validated_latent_sample({
        "step": 0,
        "shape": [64, 64, 4, 1],
        "mean": -0.0031,
        "std": 1.0276,
        "l2": 65.43,
        "truth": "observed",
        "kind": "latent-state",
        "channels": channels,
    }, trace_dir)

    assert sample is None


def test_generation_job_persists_observed_process_trace(tmp_path: Path):
    config = make_config(tmp_path)

    def fake_runner(command, env, cwd, stdout_log, stderr_log):
        output = Path(command[command.index("--output") + 1])
        metadata = Path(command[command.index("--metadata") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"PNG")
        metadata.write_text(json.dumps({
            "model_id": "model",
            "backend": "cuda",
            "generation_time_ms": 1234,
            "peak_vram_mib": 2800,
            "peak_ram_bytes": 4_000_000_000,
        }), encoding="utf-8")
        return NativeRunResult(returncode=0, stdout='{"generation_time_ms":1234}', stderr="")

    runtime = DreamRuntime(config, job_runner=JobRunner(config, command_runner=fake_runner))
    record = runtime.generate(GenerateRequest(prompt="test", modelId="model", seed=1, width=256, height=256))

    deadline = time.time() + 2
    while time.time() < deadline:
        record = runtime.get_job(record["id"])
        if record["state"] in {"complete", "failed"}:
            break
        time.sleep(0.01)

    trace_path = config.dream_root / "traces" / f"{record['id']}.json"
    assert record["state"] == "complete"
    assert trace_path.exists()
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["available"] is True
    assert trace["runId"] == record["id"]
    assert trace["totalTimeMs"] == 1234
    assert trace["nodes"] == [{
        "id": "native-generation",
        "name": "Native generation",
        "backend": "CUDA",
        "shape": "256 × 256",
        "observedCalls": 1,
        "durationMs": 1234,
        "status": "executed",
        "truth": "observed",
    }]
    assert trace["evidence"]["peakVramMiB"] == 2800


def test_generation_trace_exposes_measured_native_phase_timings(tmp_path: Path):
    config = make_config(tmp_path)
    wrapper_log = config.dream_root / "logs" / "native-wrapper.log"
    wrapper_log.parent.mkdir(parents=True, exist_ok=True)
    wrapper_log.write_text(
        "\n".join([
            "[INFO ] stable-diffusion.cpp:5317 - get_learned_condition completed, taking 3.59s",
            "[INFO ] stable-diffusion.cpp:5733 - sampling completed, taking 8.94s",
            "[INFO ] stable-diffusion.cpp:5412 - decode_first_stage completed, taking 1.19s",
            "[INFO ] stable-diffusion.cpp:5884 - generate_image completed in 13.75s",
        ]),
        encoding="utf-8",
    )

    def fake_runner(command, env, cwd, stdout_log, stderr_log):
        output = Path(command[command.index("--output") + 1])
        metadata = Path(command[command.index("--metadata") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"PNG")
        metadata.write_text(json.dumps({
            "model_id": "model",
            "backend": "cuda",
            "generation_time_ms": 16000,
        }), encoding="utf-8")
        return NativeRunResult(returncode=0, stdout=json.dumps({"wrapper_log": str(wrapper_log)}), stderr="")

    runtime = DreamRuntime(config, job_runner=JobRunner(config, command_runner=fake_runner))
    record = runtime.generate(GenerateRequest(prompt="test", modelId="model", seed=1, width=256, height=256, steps=8))

    deadline = time.time() + 2
    while time.time() < deadline:
        record = runtime.get_job(record["id"])
        if record["state"] in {"complete", "failed"}:
            break
        time.sleep(0.01)

    trace = json.loads((config.dream_root / "traces" / f"{record['id']}.json").read_text(encoding="utf-8"))
    assert trace["events"] == [
        {"phase": "conditioning", "label": "Conditioning", "durationMs": 3590, "truth": "observed"},
        {"phase": "unet_sampling", "label": "UNet sampling", "durationMs": 8940, "truth": "observed"},
        {"phase": "vae_decode", "label": "VAE decode", "durationMs": 1190, "truth": "observed"},
        {"phase": "generate_image", "label": "Image generation", "durationMs": 13750, "truth": "observed"},
    ]
    assert [node["name"] for node in trace["nodes"]] == ["Conditioning", "UNet sampling", "VAE decode", "Image generation"]
    assert trace["nodes"][1]["durationMs"] == 8940
    assert trace["evidence"]["wrapperLogPath"] == str(wrapper_log)


def test_generation_trace_records_observed_latent_projection_frames(tmp_path: Path):
    config = make_config(tmp_path)
    install_research_engine(config)

    def fake_runner(command, env, cwd, stdout_log, stderr_log):
        output = Path(command[command.index("--output") + 1])
        metadata = Path(command[command.index("--metadata") + 1])
        trace_dir = Path(command[command.index("--trace-dir") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        trace_dir.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"PNG")
        metadata.write_text(json.dumps({"model_id": "model", "backend": "cuda", "generation_time_ms": 3000}), encoding="utf-8")
        (trace_dir / "latent-step-000.png").write_bytes(b"FRAME-0")
        (trace_dir / "latent-step-001.png").write_bytes(b"FRAME-1")
        return NativeRunResult(returncode=0, stdout='{"generation_time_ms":3000}', stderr="")

    runtime = DreamRuntime(config, job_runner=JobRunner(config, command_runner=fake_runner))
    record = runtime.generate(GenerateRequest(prompt="test", modelId="model", seed=1, steps=2, traceLevel="h6"))

    deadline = time.time() + 2
    while time.time() < deadline:
        record = runtime.get_job(record["id"])
        if record["state"] in {"complete", "failed"}:
            break
        time.sleep(0.01)

    trace = json.loads((config.dream_root / "traces" / f"{record['id']}.json").read_text(encoding="utf-8"))
    assert record["state"] == "complete"
    assert trace["latentPreviewFrames"] == [
        {"step": 0, "fileName": "latent-step-000.png", "truth": "observed", "kind": "latent-projection"},
        {"step": 1, "fileName": "latent-step-001.png", "truth": "observed", "kind": "latent-projection"},
    ]


def test_latest_runtime_trace_uses_newest_file_not_filename_order(tmp_path: Path):
    config = make_config(tmp_path)
    traces = config.dream_root / "traces"
    traces.mkdir(parents=True)
    old = traces / "z-old.json"
    new = traces / "a-new.json"
    old.write_text(json.dumps({"available": True, "runId": "old", "totalTimeMs": 1, "nodes": []}), encoding="utf-8")
    new.write_text(json.dumps({"available": True, "runId": "new", "totalTimeMs": 2, "nodes": []}), encoding="utf-8")
    os.utime(old, (100, 100))
    os.utime(new, (200, 200))

    assert DreamRuntime(config).runtime_trace("latest")["runId"] == "a-new"
