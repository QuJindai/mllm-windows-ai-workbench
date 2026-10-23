"""Review regressions through real HTTP/storage, using only temporary fixtures."""
import copy
import json

import pytest
from fastapi.testclient import TestClient

from app import create_app
from identity_batches import BatchRecord
from runtime import DreamRuntime
from test_generation_jobs import make_config
from test_identity_api import harness, upload
from test_identity_batches import batch_harness, batch_request, submit_batch, wait_batch
from test_identity_profiles import profile_harness
from test_research_traces import INFLUENCE, SELF_INDEX, SELF_MAP


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def observations(tmp_path, request):
    source = getattr(request, "param", "diffusers-unet")
    config = make_config(tmp_path)
    run_id = "identity-" + "a" * 24
    assets = config.dream_root / "traces" / run_id
    assets.mkdir(parents=True)
    trace_path = assets.parent / f"{run_id}.json"
    trace = {"runId": run_id, "totalTimeMs": 10, "nodes": [], "evidence": {"backend": source}}
    write_json(trace_path, trace)
    influence, index, sample = map(copy.deepcopy, (INFLUENCE, SELF_INDEX, SELF_MAP))
    influence["source"] = index["source"] = sample["source"] = source
    if source == "diffusers-unet":
        influence.update(method="identity-ablation-guided", totalChunks=1, capturedChunks=1)
        influence["steps"][0]["chunks"] = influence["steps"][0]["chunks"][:1]
    write_json(assets / "conditioning-influence.json", influence)
    write_json(assets / "self-attention-index.json", index)
    write_json(assets / index["maps"][0]["fileName"], sample)
    cross = {**index, "contractVersion": "h7-attention-v1", "kind": "cross-attention",
             "tokens": [{"slot": 1, "tokenId": 123, "text": "portrait", "chunk": 0, "weight": 1}],
             "maps": [{key: value for key, value in index["maps"][0].items()
                       if key not in ("queryIndex", "queryX", "queryY")}]}
    cross["maps"][0].update(tokenSlot=1, fileName="attention-one.json")
    write_json(assets / "attention-index.json", cross)
    with TestClient(create_app(config, DreamRuntime(config)), raise_server_exceptions=False) as client:
        yield client, run_id, trace_path, trace, sample["id"]


@pytest.mark.parametrize("root_change", [
    {"evidence": {}}, {"evidence": None}, {"evidence": {"backend": "debug-unet"}},
    {"evidence": {"backend": "CUDA"}}, {"evidence": {"backend": ["diffusers-unet"]}},
    {"runId": "another-run"},
], ids=["missing-backend", "null-evidence", "native-backend", "other-backend", "invalid-backend", "wrong-run"])
@pytest.mark.parametrize("requested", ["explicit", "latest"])
def test_diffusers_sidecars_require_matching_root_provenance(observations, root_change, requested):
    client, run_id, trace_path, trace, map_id = observations
    write_json(trace_path, {**trace, **root_change})
    selected = run_id if requested == "explicit" else "latest"
    for endpoint in ("influence", "self-attention"):
        response = client.get(f"/api/traces/{selected}/{endpoint}")
        assert response.status_code == 200
        assert response.json()["available"] is False
        assert response.json()["truth"] == "unavailable"
    response = client.get(f"/api/traces/{selected}/self-attention/maps/{map_id}")
    assert response.status_code == 404
    assert response.json()["code"] == "SELF_ATTENTION_MAP_NOT_FOUND"
    row = client.get("/api/traces").json()[0]
    assert row["hasInfluence"] is False and row["hasSelfAttention"] is False


@pytest.mark.parametrize("observations", ["debug-unet"], indirect=True)
@pytest.mark.parametrize("evidence", [None, {}, {"backend": "CUDA"}, {"backend": "debug-unet"}, ["legacy"]])
def test_legacy_native_roots_do_not_require_diffusers_binding(observations, evidence):
    client, run_id, trace_path, trace, map_id = observations
    if evidence is None:
        trace.pop("evidence")
    else:
        trace["evidence"] = evidence
    write_json(trace_path, trace)
    for endpoint in ("influence", "self-attention", "attention"):
        response = client.get(f"/api/traces/{run_id}/{endpoint}")
        assert response.status_code == 200
        assert response.json()["available"] is True
        assert response.json()["source"] == "debug-unet"
    response = client.get(f"/api/traces/{run_id}/self-attention/maps/{map_id}")
    assert response.status_code == 200
    assert response.json()["values"] == [.25] * 4


@pytest.mark.parametrize("observations", ["debug-unet"], indirect=True)
def test_explicit_diffusers_root_cannot_publish_native_self_or_influence(observations):
    client, run_id, trace_path, trace, map_id = observations
    write_json(trace_path, {**trace, "evidence": {"backend": "diffusers-unet"}})
    for endpoint in ("influence", "self-attention"):
        assert client.get(f"/api/traces/{run_id}/{endpoint}").json()["available"] is False
    assert client.get(f"/api/traces/{run_id}/self-attention/maps/{map_id}").status_code == 404


@pytest.mark.parametrize("evidence", [["bad"], "bad", 1, True, [], None])
def test_malformed_attention_evidence_does_not_break_trace_listing(observations, evidence):
    client, run_id, trace_path, trace, _ = observations
    write_json(trace_path, {**trace, "evidence": evidence})
    response = client.get(f"/api/traces/{run_id}/attention")
    assert response.status_code == 200
    assert response.json()["available"] is False
    response = client.get("/api/traces")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["runId"] == run_id
    assert response.json()[0]["hasAttention"] is False


def test_bound_diffusers_sidecars_remain_observed(observations):
    client, run_id, _, _, map_id = observations
    for endpoint in ("influence", "self-attention", "attention"):
        response = client.get(f"/api/traces/{run_id}/{endpoint}")
        assert response.status_code == 200
        assert response.json()["available"] is True
        assert response.json()["source"] == "diffusers-unet"
    response = client.get(f"/api/traces/{run_id}/self-attention/maps/{map_id}")
    assert response.status_code == 200
    assert response.json()["values"] == [.25] * 4


@pytest.mark.parametrize("trace_level", ["h6", "h7"])
def test_invalid_expanded_research_request_is_rejected_before_persistence(batch_harness, trace_level):
    client, config, _, boundary = batch_harness
    reference = upload(client)
    request = batch_request(reference, count=1, stepValues=[8, 50])
    request["request"].update(steps=8, traceLevel=trace_level, researchCoverage="extended")
    root = config.dream_root / "data" / "identity"
    response = client.post("/api/identity/batches", json=request)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "REQUEST_INVALID"
    assert not list((root / "batches").glob("batch-*.json"))
    assert not list((root / "jobs").glob("identity-*.json"))
    assert not boundary.calls
    assert client.get("/api/identity/batches").json() == []


def test_expanded_research_request_rechecks_artifact_budget(batch_harness):
    client, config, _, boundary = batch_harness
    request = batch_request(upload(client), count=1, stepValues=[1, 12])
    # The short run fits the budget; the expanded 12-step full-text run does not.
    request["request"].update(width=512, height=512, steps=1, prompt="portrait " * 10,
                              traceLevel="h7", researchCoverage="extended")
    response = client.post("/api/identity/batches", json=request)
    assert response.status_code == 422, response.text
    assert not list((config.dream_root / "data" / "identity" / "batches").glob("batch-*.json"))
    assert not boundary.calls


@pytest.mark.parametrize("research,step_values", [
    ({"traceLevel": "h7", "researchCoverage": "extended"}, [8, 12]),
    ({}, [8, 50]),
])
def test_valid_expanded_requests_remain_recoverable(batch_harness, research, step_values):
    client, config, runner, _ = batch_harness
    request = batch_request(upload(client), count=1, stepValues=step_values)
    request["request"].update(steps=8, **research)
    batch = submit_batch(client, request)
    assert [item["request"]["steps"] for item in batch["items"]] == step_values
    BatchRecord.model_validate(batch)
    completed = wait_batch(client, batch["id"])
    assert completed["state"] == "complete"
    client.__exit__(None, None, None)
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as restarted:
        restored = restarted.get(f"/api/identity/batches/{batch['id']}")
        assert restored.status_code == 200
        assert restored.json()["state"] == "complete"
        assert [item["request"]["steps"] for item in restored.json()["items"]] == step_values
