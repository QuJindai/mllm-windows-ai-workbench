from __future__ import annotations

import base64
from pathlib import Path

import pytest

from config import DreamServerConfig
from models import GenerateRequest
from persistent_engine import PersistentEngineClient, PersistentEngineUnavailable


def make_config(tmp_path: Path) -> DreamServerConfig:
    dream_root = tmp_path / "Dream"
    engine_dir = dream_root / "app" / "stable-diffusion-cpp"
    engine_dir.mkdir(parents=True)
    server_exe = engine_dir / "sd-server.exe"
    server_exe.write_bytes(b"server")
    return DreamServerConfig(
        repo_root=tmp_path,
        dream_root=dream_root,
        core_exe=dream_root / "app" / "current" / "dream-core.exe",
        engine_exe=engine_dir / "sd-cli.exe",
        wrapper=tmp_path / "wrapper.cmd",
        registry_path=tmp_path / "registry.json",
        frontend_dist=tmp_path / "dist",
    )


def test_native_request_mapping_and_completed_png_decode(tmp_path: Path):
    model_path = tmp_path / "model.gguf"
    calls: list[tuple[str, str, dict | None]] = []
    status_responses = iter(
        [
            {"id": "native-1", "status": "running", "result": None, "error": None},
            {
                "id": "native-1",
                "status": "completed",
                "result": {"output_format": "png", "images": [{"index": 0, "b64_json": base64.b64encode(b"\x89PNG\r\n\x1a\nDATA").decode()}]},
                "error": None,
            },
        ]
    )

    def transport(method: str, path: str, payload: dict | None, timeout: float):
        calls.append((method, path, payload))
        if path == "/sdcpp/v1/capabilities":
            return {"model": {"path": str(model_path)}, "supported_modes": ["img_gen"]}
        if path == "/sdcpp/v1/img_gen":
            return {"id": "native-1", "status": "queued", "poll_url": "/sdcpp/v1/jobs/native-1"}
        return next(status_responses)

    client = PersistentEngineClient(make_config(tmp_path), transport=transport, sleep=lambda _: None)
    submitted: list[str] = []
    result = client.generate(
        GenerateRequest(
            prompt="a mountain lake",
            negativePrompt="blurry",
            modelId="model",
            width=768,
            height=512,
            steps=20,
            cfg=4,
            samplingMethod="dpm++2m_sde",
            scheduler="karras",
            seed=123,
            traceLevel="basic",
        ),
        seed=123,
        model_path=model_path,
        on_submitted=submitted.append,
        is_cancelled=lambda: False,
    )

    assert submitted == ["native-1"]
    assert result.native_job_id == "native-1"
    assert result.image_bytes == b"\x89PNG\r\n\x1a\nDATA"
    request_payload = next(payload for method, path, payload in calls if method == "POST" and path == "/sdcpp/v1/img_gen")
    assert request_payload == {
        "prompt": "a mountain lake",
        "negative_prompt": "blurry",
        "width": 768,
        "height": 512,
        "seed": 123,
        "batch_count": 1,
        "output_format": "png",
        "output_compression": 100,
        "sample_params": {
            "sample_method": "dpm++2m_sde",
            "scheduler": "karras",
            "sample_steps": 20,
            "guidance": {"txt_cfg": 4.0},
        },
    }


def test_refuses_to_reuse_server_with_different_model(tmp_path: Path):
    calls: list[tuple[str, str]] = []

    def transport(method: str, path: str, payload: dict | None, timeout: float):
        calls.append((method, path))
        return {"model": {"path": str(tmp_path / "other.gguf")}, "supported_modes": ["img_gen"]}

    client = PersistentEngineClient(make_config(tmp_path), transport=transport, sleep=lambda _: None)

    with pytest.raises(PersistentEngineUnavailable, match="different model"):
        client.generate(
            GenerateRequest(prompt="test", modelId="model", seed=1),
            seed=1,
            model_path=tmp_path / "expected.gguf",
            on_submitted=lambda _: None,
            is_cancelled=lambda: False,
        )

    assert calls == [("GET", "/sdcpp/v1/capabilities")]


def test_cancel_forwards_to_native_job(tmp_path: Path):
    calls: list[tuple[str, str, dict | None]] = []

    def transport(method: str, path: str, payload: dict | None, timeout: float):
        calls.append((method, path, payload))
        return {"id": "native-7", "status": "cancelled"}

    client = PersistentEngineClient(make_config(tmp_path), transport=transport)

    client.cancel("native-7")

    assert calls == [("POST", "/sdcpp/v1/jobs/native-7/cancel", None)]
