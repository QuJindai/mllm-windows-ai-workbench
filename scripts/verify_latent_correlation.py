"""CPU-only native writer artifact -> validator -> saved trace -> HTTP roundtrip.

Pass the fixtures directory printed by build_latent_correlation.ps1. No engine,
model, live service, or user record is opened. Temporary API records are scoped
to a fresh directory beside the generated test fixtures.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "dream-windows" / "server"))

from fastapi.testclient import TestClient
from PIL import Image

from app import create_app
from config import DreamServerConfig
from job_runner import JobRunner
from runtime import DreamRuntime


def verify(fixtures: Path) -> dict:
    paths = sorted(fixtures.glob("*/latent-metrics.jsonl"))
    assert len(paths) == 7, f"Expected seven CPU writer cases, found {len(paths)}"
    with tempfile.TemporaryDirectory(prefix="api-roundtrip-", dir=fixtures.parent) as scratch:
        root = Path(scratch)
        config = replace(DreamServerConfig.for_testing(), dream_root=root)
        runner = JobRunner(config)
        client = TestClient(create_app(config=config, runtime=DreamRuntime(config)))
        for path in paths:
            raw = json.loads(path.read_text(encoding="utf-8"))
            run_id = f"run-{path.parent.name}"
            directory = root / "traces" / run_id
            directory.mkdir(parents=True)
            for channel in raw["channels"]:
                source = path.parent / channel["file_name"]
                with Image.open(source) as image:
                    image.load()
                    assert image.size == tuple(raw["shape"][:2])
                shutil.copy2(source, directory / source.name)
            public = runner._validated_latent_sample(raw, directory)
            assert public is not None, path
            assert public["channelCorrelation"] == raw["channel_correlation"], path
            assert public["correlationMethod"] == "pearson", path
            trace = dict(runId=run_id, totalTimeMs=0, nodes=[], latentTelemetry=[public])
            (directory.parent / f"{run_id}.json").write_text(json.dumps(trace), encoding="utf-8")
            for route, field in ((f"/api/traces/{run_id}", "latentTelemetry"),
                                 (f"/api/traces/{run_id}/latent", "telemetry")):
                response = client.get(route)
                assert response.status_code == 200, response.text
                saved = response.json()[field][0]
                assert saved["channelCorrelation"] == raw["channel_correlation"], route
                assert saved["correlationMethod"] == "pearson", route
                assert saved["truth"] == "observed", route
    return {"passed": True, "fixtures": str(fixtures), "nativeCases": len(paths),
            "httpRoundtrips": len(paths) * 2, "gpuRuntime": False}


def verify_delta(fixtures: Path) -> dict:
    raw_samples = [json.loads(line) for line in (fixtures / "latent-metrics.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [sample["step"] for sample in raw_samples] == [2, 7, 9, 10, 11, 12, 13]
    expected_pixels = {7: [0, 111, 255], 9: [0, 0, 0], 10: [255, 255, 255]}
    with tempfile.TemporaryDirectory(prefix="delta-api-", dir=fixtures.parent) as scratch:
        root = Path(scratch)
        directory = root / "traces" / "run-delta"
        directory.mkdir(parents=True)
        config = replace(DreamServerConfig.for_testing(), dream_root=root)
        runner = JobRunner(config)
        samples = []
        for raw in raw_samples:
            names = [channel["file_name"] for channel in raw["channels"]]
            if "delta_file_name" in raw:
                names.append(raw["delta_file_name"])
            for name in names:
                shutil.copy2(fixtures / name, directory / name)
            sample = runner._validated_latent_sample(raw, directory)
            assert sample is not None, raw["step"]
            samples.append(sample)
        (directory.parent / "run-delta.json").write_text(json.dumps(dict(
            runId="run-delta", nodes=[], totalTimeMs=0, latentTelemetry=samples)), encoding="utf-8")
        client = TestClient(create_app(config=config, runtime=DreamRuntime(config)))
        response = client.get("/api/traces/run-delta/latent")
        assert response.status_code == 200
        for public in response.json()["telemetry"]:
            if public["step"] not in expected_pixels:
                assert "deltaImageUrl" not in public
                continue
            image_response = client.get(public["deltaImageUrl"])
            assert image_response.status_code == 200
            with Image.open(io.BytesIO(image_response.content)) as image:
                assert image.size == (3, 1)
                assert image.mode == "L" and list(image.tobytes()) == expected_pixels[public["step"]]
    return {"passed": True, "nativeSteps": 7, "deltaImagesDecodedThroughHTTP": 3, "gpuRuntime": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixtures", type=Path)
    parser.add_argument("--delta-fixtures", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(verify(arguments.fixtures.resolve()), indent=2))
    if arguments.delta_fixtures:
        print(json.dumps(verify_delta(arguments.delta_fixtures.resolve()), indent=2))
