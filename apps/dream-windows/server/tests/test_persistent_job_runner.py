from __future__ import annotations

import json
import time
from pathlib import Path

from config import DreamServerConfig
from job_runner import JobRunner, NativeRunResult
from models import GenerateRequest
from persistent_engine import PersistentGenerationResult, PersistentEngineUnavailable


def make_config(tmp_path: Path) -> DreamServerConfig:
    dream_root = tmp_path / "Dream"
    engine_dir = dream_root / "app" / "stable-diffusion-cpp"
    model_dir = dream_root / "models"
    engine_dir.mkdir(parents=True)
    model_dir.mkdir(parents=True)
    model_path = model_dir / "model.gguf"
    model_path.write_bytes(b"model")
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "model_id": "model",
                        "display_name": "Model",
                        "architecture": "SDXL",
                        "dmd2": {"enabled": False, "variant": "standard"},
                        "windows": {"path": str(model_path), "sha256": "ABC123"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return DreamServerConfig(
        repo_root=tmp_path,
        dream_root=dream_root,
        core_exe=dream_root / "app" / "current" / "dream-core.exe",
        engine_exe=engine_dir / "sd-cli.exe",
        wrapper=tmp_path / "wrapper.cmd",
        registry_path=registry,
        frontend_dist=tmp_path / "dist",
    )


def wait_for_terminal(runner: JobRunner, job_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        record = runner.get(job_id)
        if record["state"] in {"complete", "failed", "cancelled"}:
            return record
        time.sleep(0.01)
    raise AssertionError("job did not finish")


class FakePersistentEngine:
    available = True

    def __init__(self, unavailable: bool = False):
        self.unavailable = unavailable
        self.requests: list[GenerateRequest] = []
        self.cancelled: list[str] = []

    def generate(self, request, *, seed, model_path, on_submitted, is_cancelled):
        self.requests.append(request)
        if self.unavailable:
            raise PersistentEngineUnavailable("test unavailable")
        on_submitted("native-1")
        return PersistentGenerationResult(
            native_job_id="native-1",
            image_bytes=b"PNG-DATA",
            engine_wall_time_ms=9012,
            postprocess_time_ms=4,
        )

    def cancel(self, native_job_id: str) -> None:
        self.cancelled.append(native_job_id)


class CapturingJobRunner(JobRunner):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cli_calls = 0

    def _run_process(self, job_id, command, env, cwd, stdout_log, stderr_log):
        self.cli_calls += 1
        output = Path(command[command.index("--output") + 1])
        metadata = Path(command[command.index("--metadata") + 1])
        output.write_bytes(b"CLI-PNG")
        metadata.write_text(json.dumps({"model_id": "model", "generation_time_ms": 100}), encoding="utf-8")
        return NativeRunResult(0, '{"generation_time_ms":100}', "")


def test_basic_generation_prefers_persistent_engine_and_writes_truthful_metadata(tmp_path: Path):
    persistent = FakePersistentEngine()
    runner = CapturingJobRunner(make_config(tmp_path), persistent_engine=persistent)

    submitted = runner.submit(GenerateRequest(prompt="test", modelId="model", seed=7, traceLevel="basic"))
    record = wait_for_terminal(runner, submitted["id"])

    assert record["state"] == "complete"
    assert runner.cli_calls == 0
    assert len(persistent.requests) == 1
    metadata = json.loads(Path(record["metadataPath"]).read_text(encoding="utf-8"))
    assert metadata["execution_mode"] == "persistent-server"
    assert metadata["persistent_server_job_id"] == "native-1"
    assert metadata["generation_time_ms"] == 9016
    assert metadata["engine_wall_time_ms"] == 9012
    assert metadata["postprocess_time_ms"] == 4
    trace = json.loads(Path(record["tracePath"]).read_text(encoding="utf-8"))
    assert [node["id"] for node in trace["nodes"]] == ["native-generation"]
    assert trace["events"] == []


def test_h7_keeps_cli_trace_path(tmp_path: Path):
    persistent = FakePersistentEngine()
    runner = CapturingJobRunner(make_config(tmp_path), persistent_engine=persistent)

    submitted = runner.submit(GenerateRequest(prompt="test", modelId="model", seed=7, traceLevel="h7"))
    record = wait_for_terminal(runner, submitted["id"])

    assert record["state"] == "complete"
    assert runner.cli_calls == 1
    assert persistent.requests == []


def test_unavailable_persistent_engine_falls_back_before_submission(tmp_path: Path):
    persistent = FakePersistentEngine(unavailable=True)
    runner = CapturingJobRunner(make_config(tmp_path), persistent_engine=persistent)

    submitted = runner.submit(GenerateRequest(prompt="test", modelId="model", seed=7, traceLevel="off"))
    record = wait_for_terminal(runner, submitted["id"])

    assert record["state"] == "complete"
    assert runner.cli_calls == 1
