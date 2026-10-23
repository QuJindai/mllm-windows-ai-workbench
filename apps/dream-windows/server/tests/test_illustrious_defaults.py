"""Protect the measured anime profile at the public API / persisted-job boundary."""
import json
import pytest

from test_dreamshaper_defaults import client  # real API fixture, inference scheduling only is stopped


EXPECTED = dict(width=1024, height=1024, steps=30, cfg=7.0,
                samplingMethod="euler_a", scheduler="discrete")


@pytest.mark.parametrize("model_id", ["illustrious-xl-v2.0", "illustrious-xl-v2.0-stable"])
def test_anime_profile_is_exposed_and_survives_job_persistence(client, tmp_path, model_id):
    model = client.get(f"/api/models/{model_id}").json()
    response = client.post("/api/generate", json={
        "modelId": model_id, "prompt": "anime countryside, clean lineart",
        "seed": 202610101, "traceLevel": "basic", **model["generationDefaults"],
    })
    assert response.status_code == 200
    job = client.get(f"/api/jobs/{response.json()['id']}").json()
    assert {key: job["request"][key] for key in EXPECTED} == EXPECTED
    assert job["request"]["modelId"] == "illustrious-xl-v2.0"
    persisted = json.loads((tmp_path / "Dream" / "data" / "jobs" / f"{job['id']}.json").read_text("utf-8"))
    assert persisted["request"] == job["request"]


def test_old_anime_requests_are_not_silently_rewritten(client):
    explicit = dict(modelId="illustrious-xl-v2.0", prompt="an anime landscape",
                    width=768, height=768, steps=20, cfg=5,
                    samplingMethod="dpm++2m", scheduler="karras", seed=0)
    response = client.post("/api/generate", json=explicit)
    assert response.status_code == 200
    saved = client.get(f"/api/jobs/{response.json()['id']}").json()["request"]
    assert {key: saved[key] for key in explicit} == explicit
