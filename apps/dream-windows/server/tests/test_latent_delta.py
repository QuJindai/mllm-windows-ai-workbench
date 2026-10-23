from dataclasses import replace
import json

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from app import create_app
from config import DreamServerConfig
from job_runner import JobRunner
from runtime import DreamRuntime


@pytest.fixture
def delta_case(tmp_path):
    config = replace(DreamServerConfig.for_testing(), dream_root=tmp_path)
    directory = tmp_path / "traces" / "run-delta"
    directory.mkdir(parents=True)
    channel_name = "latent-step-007-ch0.png"
    Image.new("L", (3, 1), 127).save(directory / channel_name)
    raw = dict(step=7, shape=[3, 1, 1, 1], mean=1, std=1, l2=2,
               truth="observed", kind="latent-state", channels=[dict(
                   channel=0, file_name=channel_name, min=0, max=2, mean=1,
                   std=1, l2=2, histogram=[3] + [0] * 31)])
    return config, directory, raw


@pytest.mark.parametrize("key", ["delta_file_name", "deltaFileName"])
def test_delta_file_roundtrips_via_validated_existing_frame_route(delta_case, key):
    config, directory, raw = delta_case
    name = "latent-step-007-delta.png"
    image = Image.new("L", (3, 1))
    image.putdata([0, 111, 255])
    image.save(directory / name)
    raw[key] = name
    raw["deltaImageUrl"] = "https://untrusted.invalid/image.png"
    sample = JobRunner(config)._validated_latent_sample(raw, directory)
    assert sample is not None and sample.get("deltaFileName") == name
    assert "deltaImageUrl" not in sample
    (directory.parent / "run-delta.json").write_text(json.dumps(dict(
        runId="run-delta", nodes=[], totalTimeMs=0, latentTelemetry=[sample]
    )), encoding="utf-8")
    client = TestClient(create_app(config=config, runtime=DreamRuntime(config)))
    for route, field in (("/api/traces/run-delta", "latentTelemetry"),
                         ("/api/traces/run-delta/latent", "telemetry")):
        public = client.get(route).json()[field][0]
        assert public["deltaFileName"] == name
        assert public["deltaImageUrl"] == f"/api/traces/run-delta/latent/frames/{name}"
        response = client.get(public["deltaImageUrl"])
        assert response.status_code == 200
        assert response.content == (directory / name).read_bytes()
    Image.new("L", (3, 1)).save(directory / "latent-step-006-delta.png")
    assert client.get("/api/traces/run-delta/latent/frames/latent-step-006-delta.png").status_code == 404


@pytest.mark.parametrize("name", [None, 4, "../latent-step-007-delta.png",
    "latent-step-006-delta.png", "latent-step-007-ch0.png", "latent-step-007-delta.png"])
def test_rejects_unsafe_wrong_step_or_missing_declared_delta_file(delta_case, name):
    config, directory, raw = delta_case
    raw["delta_file_name"] = name
    assert JobRunner(config)._validated_latent_sample(raw, directory) is None


def test_undeclared_legacy_delta_stays_unavailable(delta_case):
    config, directory, raw = delta_case
    Image.new("L", (3, 1)).save(directory / "latent-step-007-delta.png")
    raw["deltaImageUrl"] = "/unvalidated.png"
    sample = JobRunner(config)._validated_latent_sample(raw, directory)
    assert sample is not None and "deltaFileName" not in sample and "deltaImageUrl" not in sample


def test_rejects_conflicting_delta_aliases(delta_case):
    config, directory, raw = delta_case
    Image.new("L", (3, 1)).save(directory / "latent-step-007-delta.png")
    raw.update(delta_file_name="latent-step-007-delta.png", deltaFileName="latent-step-008-delta.png")
    assert JobRunner(config)._validated_latent_sample(raw, directory) is None
