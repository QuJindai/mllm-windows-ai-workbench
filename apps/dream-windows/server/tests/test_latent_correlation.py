from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json

import pytest
from fastapi.testclient import TestClient

from app import create_app
from config import DreamServerConfig
from job_runner import JobRunner
from runtime import DreamRuntime


@pytest.fixture
def latent_case(tmp_path):
    config = replace(DreamServerConfig.for_testing(), dream_root=tmp_path)
    directory = tmp_path / "traces" / "run-correlation"
    directory.mkdir(parents=True)
    channels = []
    for channel in range(3):
        filename = f"latent-step-004-ch{channel}.png"
        (directory / filename).touch()
        channels.append(dict(channel=channel, file_name=filename, min=-1, max=1,
                             mean=0, std=1 if channel < 2 else 0, l2=2,
                             histogram=[4] + [0] * 31))
    raw = dict(step=4, shape=[2, 2, 3, 1], mean=0, std=1, l2=3,
               truth="observed", kind="latent-state", channels=channels)
    return config, directory, raw


@pytest.mark.parametrize("method", [None, "correlation_method", "correlationMethod"])
def test_raw_pearson_roundtrips_through_saved_trace_and_http(latent_case, method):
    config, directory, raw = latent_case
    raw["channel_correlation"] = [[1, -1, None], [-1, 1, None], [None, None, None]]
    if method:
        raw[method] = "pearson"
    sample = JobRunner(config)._validated_latent_sample(raw, directory)
    assert sample is not None
    assert sample.get("channelCorrelation") == [[1.0, -1.0, None], [-1.0, 1.0, None], [None, None, None]]
    assert sample.get("correlationMethod") == "pearson"
    (directory.parent / "run-correlation.json").write_text(json.dumps(dict(
        runId="run-correlation", totalTimeMs=0, nodes=[], latentTelemetry=[sample]
    )), encoding="utf-8")
    client = TestClient(create_app(config=config, runtime=DreamRuntime(config)))
    for route in ("/api/traces/run-correlation", "/api/traces/run-correlation/latent"):
        response = client.get(route)
        assert response.status_code == 200
        body = response.json()
        actual = body.get("latentTelemetry", body.get("telemetry"))[0]
        assert actual["channelCorrelation"] == raw["channel_correlation"]
        assert actual["correlationMethod"] == "pearson"


@pytest.mark.parametrize("matrix", [
    None, [], [[1]], [[1, 0, 0]] * 2, [[1, 0], [0, 1], [0, 0]],
    [[1, .5, None], [-.5, 1, None], [None, None, None]],
    [[1, None, None], [0, 1, None], [None, None, None]],
    [[1, 1.000001, None], [1.000001, 1, None], [None, None, None]],
    [[1, -1.000001, None], [-1.000001, 1, None], [None, None, None]],
    [[1, float("nan"), None], [float("nan"), 1, None], [None, None, None]],
    [[1, float("inf"), None], [float("inf"), 1, None], [None, None, None]],
    [[1, True, None], [True, 1, None], [None, None, None]],
    [[1, "0.5", None], ["0.5", 1, None], [None, None, None]],
    [[0, 0, None], [0, 1, None], [None, None, None]],
    [[1, 0, 0], [0, 1, None], [0, None, None]],
    [[1, None, None], [None, 1, None], [None, None, None]],
])
def test_rejects_malformed_or_incoherent_correlation(latent_case, matrix):
    config, directory, raw = latent_case
    raw["channel_correlation"] = matrix
    assert JobRunner(config)._validated_latent_sample(raw, directory) is None


def test_absent_old_correlation_stays_absent(latent_case):
    config, directory, raw = latent_case
    sample = JobRunner(config)._validated_latent_sample(raw, directory)
    assert sample is not None
    assert "channelCorrelation" not in sample
    assert "correlationMethod" not in sample


def test_accepts_floating_roundoff_on_pearson_diagonal_without_changing_measurements(latent_case):
    config, directory, raw = latent_case
    raw["channel_correlation"] = [[.9999999999999998, .5, None], [.5, 1, None], [None, None, None]]
    raw["correlation_method"] = "pearson"
    sample = JobRunner(config)._validated_latent_sample(raw, directory)
    assert sample is not None
    assert sample["channelCorrelation"] == raw["channel_correlation"]


def test_actual_identity_cpu_collector_accepts_snake_fields_and_roundtrips_public(latent_case):
    import torch
    from identity_research import latent_sample

    config, directory, _ = latent_case
    latent = torch.tensor([[[[1., 2.], [3., 4.]], [[4., 3.], [2., 1.]],
                            [[2., 2.], [2., 2.]], [[2., 4.], [6., 8.]]]], device="cpu")
    raw = latent_sample(latent, None, 0, directory)
    runner = JobRunner(config)
    public = runner._validated_latent_sample(raw, directory)
    assert public is not None
    assert public["truth"] == "observed" and public["correlationMethod"] == "pearson"
    assert public["channelCorrelation"] == raw["channel_correlation"]
    assert public["channelCorrelation"][2] == [None] * 4
    assert runner._validated_latent_sample(public, directory) == public


@pytest.mark.parametrize("mutation", ["method", "missing_channel", "shape", "aliases"])
def test_rejects_wrong_method_channel_count_or_conflicting_aliases(latent_case, mutation):
    config, directory, raw = latent_case
    raw["channelCorrelation"] = [[1, 0, None], [0, 1, None], [None, None, None]]
    raw["correlationMethod"] = "pearson"
    if mutation == "method":
        raw["correlationMethod"] = "cosine"
    elif mutation == "missing_channel":
        raw["channels"].pop()
    elif mutation == "shape":
        raw["shape"][2] = 17
    else:
        raw["channel_correlation"] = deepcopy(raw["channelCorrelation"])
        raw["channel_correlation"][0][1] = .5
    assert JobRunner(config)._validated_latent_sample(raw, directory) is None
