from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import create_app
from runtime import DreamRuntime
from test_generation_jobs import make_config


SELF_MARKER = {
    "contractVersion": "h7-self-attention-v1", "kind": "self-attention",
    "truth": "observed", "source": "debug-unet",
}
INFLUENCE = {
    "contractVersion": "h6-conditioning-v1", "kind": "conditioning-influence",
    "truth": "observed", "source": "debug-unet", "method": "chunk-vs-full-guided",
    "chunkSize": 77, "totalChunks": 2, "capturedChunks": 2,
    "steps": [{
        "step": 0, "width": 2, "height": 2, "cfgDeltaL2": 2.5, "cfgCosine": -0.2,
        "chunks": [
            {"chunk": 0, "tokenStart": 0, "tokenEnd": 77, "meanAbs": 1.5,
             "l2": 5.5, "cosineFull": -0.3, "deltaL2": 0.2,
             "spatialDelta": [0.1, 0.2, 0.0, 0.4]},
            {"chunk": 1, "tokenStart": 77, "tokenEnd": 154, "meanAbs": 1.6,
             "l2": 5.6, "cosineFull": 0.6, "deltaL2": 0.3,
             "spatialDelta": [0.2, 0.3, 0.0, 0.5]},
        ],
    }],
}
SELF_DESCRIPTOR = {
    "id": "s00-down-q0", "step": 0, "layerId": "down-1",
    "queryIndex": 0, "queryX": 0, "queryY": 0, "width": 2, "height": 2,
    "entropy": 1.0, "peak": 0.25, "coverage": 1.0,
    "fileName": "self-attention-s000-down-q0.json",
}
SELF_INDEX = {
    **SELF_MARKER, "layers": [{"id": "down-1", "stage": "down", "label": "Down 1"}],
    "maps": [SELF_DESCRIPTOR],
}
SELF_MAP = {
    **SELF_MARKER, **{key: value for key, value in SELF_DESCRIPTOR.items() if key != "fileName"},
    "values": [0.25, 0.25, 0.25, 0.25],
}


def write_json(path: Path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def research(tmp_path):
    config = make_config(tmp_path)
    trace_root = config.dream_root / "traces"
    assets = trace_root / "run-research"
    assets.mkdir(parents=True)
    write_json(trace_root / "run-research.json", {"runId": "run-research", "totalTimeMs": 3, "nodes": []})
    runtime = DreamRuntime(config)
    with TestClient(create_app(config=config, runtime=runtime)) as client:
        yield client, assets, runtime


def write_self(assets, index=None, map_document=None):
    write_json(assets / "self-attention-index.json", SELF_INDEX if index is None else index)
    write_json(assets / SELF_DESCRIPTOR["fileName"], SELF_MAP if map_document is None else map_document)


def changed(document, keys, value):
    result = copy.deepcopy(document)
    target = result
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    return result


@pytest.mark.parametrize("endpoint", ["influence", "self-attention"])
def test_missing_research_is_truthfully_unavailable(research, endpoint):
    client, _, _ = research
    for run_id in ("run-research", "not-found"):
        response = client.get(f"/api/traces/{run_id}/{endpoint}")
        assert response.status_code == 200
        assert response.json()["available"] is False
        assert response.json()["truth"] == "unavailable"
        assert response.json()["runId"] == run_id
        assert response.json()["message"]


def test_influence_returns_raw_observed_metrics_and_strips_unknown_paths(research):
    client, assets, _ = research
    document = copy.deepcopy(INFLUENCE)
    document["path"] = str(assets)
    document["steps"][0]["chunks"][0]["fileName"] = "private.json"
    write_json(assets / "conditioning-influence.json", document)
    response = client.get("/api/traces/latest/influence")
    assert response.status_code == 200
    assert response.json() == {"available": True, "runId": "run-research", **INFLUENCE}
    assert client.get("/api/traces").json()[0]["hasInfluence"] is True


@pytest.mark.parametrize(("keys", "value"), [
    (("truth",), "derived"), (("source",), "demo"), (("contractVersion",), "h6-v0"),
    (("kind",), "other"), (("method",), "average"), (("chunkSize",), 76),
    (("totalChunks",), True), (("totalChunks",), 0), (("capturedChunks",), 4),
    (("capturedChunks",), 1), (("steps",), []), (("steps",), INFLUENCE["steps"] * 6),
    (("steps", 0, "step"), True), (("steps", 0, "step"), -1), (("steps", 0, "step"), 50),
    (("steps", 0, "width"), 129), (("steps", 0, "height"), False),
    (("steps", 0, "cfgDeltaL2"), -1), (("steps", 0, "cfgDeltaL2"), float("inf")),
    (("steps", 0, "cfgCosine"), 1.01), (("steps", 0, "cfgCosine"), "0"),
    (("steps", 0, "chunks"), []),
    (("steps", 0, "chunks", 0, "chunk"), 2),
    (("steps", 0, "chunks", 0, "tokenStart"), -1),
    (("steps", 0, "chunks", 0, "tokenEnd"), False),
    (("steps", 0, "chunks", 0, "meanAbs"), -0.1),
    (("steps", 0, "chunks", 0, "l2"), float("nan")),
    (("steps", 0, "chunks", 0, "cosineFull"), -1.01),
    (("steps", 0, "chunks", 0, "deltaL2"), True),
    (("steps", 0, "chunks", 0, "spatialDelta"), [0, 0, 0]),
    (("steps", 0, "chunks", 0, "spatialDelta"), [0, 0, 0, -0.1]),
    (("steps", 0, "chunks", 0, "spatialDelta"), [0, 0, 0, float("nan")]),
    (("steps", 0, "chunks", 0, "spatialDelta"), [0, 0, 0, True]),
    (("steps", 0, "chunks", 1), INFLUENCE["steps"][0]["chunks"][0]),
])
def test_influence_rejects_entire_malformed_artifact(research, keys, value):
    client, assets, _ = research
    write_json(assets / "conditioning-influence.json", changed(INFLUENCE, keys, value))
    response = client.get("/api/traces/run-research/influence")
    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["truth"] == "unavailable"
    assert client.get("/api/traces").json()[0]["hasInfluence"] is False


def test_self_attention_preserves_probabilities_and_uses_map_urls(research):
    client, assets, _ = research
    write_self(assets)
    response = client.get("/api/traces/latest/self-attention")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["runId"] == "run-research"
    assert body["layers"] == SELF_INDEX["layers"]
    assert body["maps"] == [{
        **{key: value for key, value in SELF_DESCRIPTOR.items() if key != "fileName"},
        "mapUrl": "/api/traces/run-research/self-attention/maps/s00-down-q0",
    }]
    selected = client.get(body["maps"][0]["mapUrl"])
    assert selected.status_code == 200
    assert selected.json() == {"available": True, "runId": "run-research", **SELF_MAP}
    assert client.get("/api/traces").json()[0]["hasSelfAttention"] is True


@pytest.mark.parametrize(("keys", "value"), [
    (("truth",), "demo"), (("source",), "derived"), (("contractVersion",), "h7-attention-v1"),
    (("layers",), []), (("layers",), SELF_INDEX["layers"] * 2),
    (("layers", 0, "id"), "../down"), (("layers", 0, "stage"), "other"),
    (("layers", 0, "stage"), {}), (("layers", 0, "label"), "x" * 129),
    (("maps",), []), (("maps",), [SELF_DESCRIPTOR] * 513),
    (("maps", 0, "id"), ".."), (("maps", 0, "layerId"), "unknown"),
    (("maps", 0, "step"), False), (("maps", 0, "step"), 50),
    (("maps", 0, "width"), 129), (("maps", 0, "height"), 0),
    (("maps", 0, "queryIndex"), True), (("maps", 0, "queryIndex"), -1),
    (("maps", 0, "queryIndex"), 1),
    (("maps", 0, "queryX"), 2), (("maps", 0, "queryY"), -1),
    (("maps", 0, "entropy"), float("nan")), (("maps", 0, "peak"), 1.01),
    (("maps", 0, "coverage"), -0.1),
    (("maps", 0, "fileName"), "../secret.json"),
    (("maps", 0, "fileName"), "E:\\private.json"),
    (("maps", 0, "fileName"), "self-attention.json:secret"),
])
def test_self_index_rejects_malformed_records(research, keys, value):
    client, assets, _ = research
    write_self(assets, index=changed(SELF_INDEX, keys, value))
    response = client.get("/api/traces/run-research/self-attention")
    assert response.status_code == 200
    assert response.json()["available"] is False
    assert client.get("/api/traces").json()[0]["hasSelfAttention"] is False


@pytest.mark.parametrize(("keys", "value"), [
    (("truth",), "derived"), (("kind",), "cross-attention"),
    (("step",), True), (("width",), 3), (("queryX",), 1),
    (("entropy",), 0.2), (("values",), [0, 0, 0]),
    (("values",), [0, 0, 0, 1.01]), (("values",), [0, 0, 0, -0.1]),
    (("values",), [0, 0, 0, True]), (("values",), [0, 0, 0, float("nan")]),
])
def test_self_map_rejects_invalid_values_and_identity_mismatch(research, keys, value):
    client, assets, _ = research
    write_self(assets, map_document=changed(SELF_MAP, keys, value))
    response = client.get("/api/traces/run-research/self-attention/maps/s00-down-q0")
    assert response.status_code == 422
    assert response.json()["code"] == "SELF_ATTENTION_MAP_INVALID"
    assert str(assets) not in response.text


def test_self_map_missing_or_unindexed_is_not_found(research):
    client, assets, _ = research
    write_json(assets / "self-attention-index.json", SELF_INDEX)
    for map_id in ("s00-down-q0", "unknown", "..%5Csecret"):
        response = client.get(f"/api/traces/run-research/self-attention/maps/{map_id}")
        assert response.status_code == 404
        assert response.json()["code"] == "SELF_ATTENTION_MAP_NOT_FOUND"


@pytest.mark.parametrize("file_name,endpoint", [
    ("conditioning-influence.json", "influence"), ("self-attention-index.json", "self-attention"),
])
@pytest.mark.parametrize("payload", [b"{bad", b"\xff", b'{"truth":"observed","truth":"demo"}', b"[" * 1500],
                         ids=["syntax", "encoding", "duplicate-keys", "deep-nesting"])
def test_invalid_json_fails_closed_without_leaking_paths(research, file_name, endpoint, payload):
    client, assets, _ = research
    (assets / file_name).write_bytes(payload)
    response = client.get(f"/api/traces/run-research/{endpoint}")
    assert response.status_code == 200
    assert response.json()["available"] is False
    assert str(assets) not in response.text


@pytest.mark.parametrize("file_name,endpoint", [
    ("conditioning-influence.json", "influence"), ("self-attention-index.json", "self-attention"),
])
def test_oversized_artifacts_are_not_parsed(research, file_name, endpoint):
    client, assets, _ = research
    # A sparse oversized file exercises the read budget without allocating its contents.
    with (assets / file_name).open("wb") as stream:
        stream.truncate(16 * 1024 * 1024)
    response = client.get(f"/api/traces/run-research/{endpoint}")
    assert response.status_code == 200
    assert response.json()["available"] is False


@pytest.mark.parametrize("endpoint", ["influence", "self-attention"])
def test_invalid_base_trace_and_run_path_fail_closed(research, endpoint):
    client, assets, _ = research
    write_json(assets / "conditioning-influence.json", INFLUENCE)
    write_self(assets)
    (assets.parent / "run-research.json").write_text("broken", encoding="utf-8")
    response = client.get(f"/api/traces/run-research/{endpoint}")
    assert response.status_code == 200
    assert response.json()["available"] is False
    assert str(assets.parent) not in response.text
    response = client.get(f"/api/traces/..%5Crun-research/{endpoint}")
    assert response.status_code == 200
    assert response.json()["available"] is False


def test_listing_keeps_basic_and_cross_fields_with_unavailable_new_artifacts(research):
    client, _, _ = research
    row = client.get("/api/traces").json()[0]
    assert row["runId"] == "run-research"
    assert row["hasAttention"] is False
    assert row["hasLatent"] is False
    assert row["hasInfluence"] is False
    assert row["hasSelfAttention"] is False


@pytest.mark.parametrize("mutation", ["duplicate-id", "duplicate-file", "duplicate-selection", "six-steps", "ten-anchors"])
def test_self_index_enforces_unique_bounded_sampling(research, mutation):
    client, assets, _ = research
    document = copy.deepcopy(SELF_INDEX)
    second = {**SELF_DESCRIPTOR, "id": "second", "fileName": "self-attention-second.json",
              "queryX": 1, "queryIndex": 1}
    if mutation == "duplicate-id":
        second["id"] = SELF_DESCRIPTOR["id"]
    elif mutation == "duplicate-file":
        second["fileName"] = SELF_DESCRIPTOR["fileName"]
    elif mutation == "duplicate-selection":
        second.update(queryX=0, queryIndex=0)
    document["maps"].append(second)
    if mutation == "six-steps":
        document["maps"] = [{**SELF_DESCRIPTOR, "id": f"s{i}", "fileName": f"self-attention-s{i}.json", "step": i}
                            for i in range(6)]
    elif mutation == "ten-anchors":
        document["maps"] = [{**SELF_DESCRIPTOR, "id": f"q{i}", "fileName": f"self-attention-q{i}.json",
                             "width": 4, "height": 4, "queryIndex": i, "queryX": i % 4, "queryY": i // 4}
                            for i in range(10)]
    write_self(assets, index=document)
    response = client.get("/api/traces/run-research/self-attention")
    assert response.status_code == 200
    assert response.json()["available"] is False


def test_influence_accepts_partial_final_chunk_and_zero_single_chunk_delta(research):
    client, assets, _ = research
    document = changed(INFLUENCE, ("steps", 0, "chunks", 1, "tokenEnd"), 100)
    write_json(assets / "conditioning-influence.json", document)
    assert client.get("/api/traces/run-research/influence").json()["available"] is True
    document.update(totalChunks=1, capturedChunks=1)
    sample = document["steps"][0]
    sample["cfgDeltaL2"] = 0
    sample["cfgCosine"] = 1
    sample["chunks"] = [sample["chunks"][0]]
    sample["chunks"][0].update(deltaL2=0, spatialDelta=[0, 0, 0, 0])
    write_json(assets / "conditioning-influence.json", document)
    response = client.get("/api/traces/run-research/influence")
    assert response.json()["available"] is True
    assert response.json()["steps"][0]["chunks"][0]["spatialDelta"] == [0, 0, 0, 0]


@pytest.mark.parametrize("mutation", ["token-start", "short-nonfinal", "long-final", "empty-final", "duplicate-step", "single-nonzero"])
def test_influence_enforces_chunk_ranges_and_sample_identity(research, mutation):
    client, assets, _ = research
    document = copy.deepcopy(INFLUENCE)
    chunks = document["steps"][0]["chunks"]
    if mutation == "token-start":
        chunks[1]["tokenStart"] = 76
    elif mutation == "short-nonfinal":
        chunks[0]["tokenEnd"] = 50
    elif mutation == "long-final":
        chunks[1]["tokenEnd"] = 155
    elif mutation == "empty-final":
        chunks[1]["tokenEnd"] = 77
    elif mutation == "duplicate-step":
        document["steps"] *= 2
    elif mutation == "single-nonzero":
        document.update(totalChunks=1, capturedChunks=1)
        document["steps"][0]["chunks"] = chunks[:1]
    write_json(assets / "conditioning-influence.json", document)
    response = client.get("/api/traces/run-research/influence")
    assert response.status_code == 200
    assert response.json()["available"] is False


@pytest.mark.parametrize("target", ["artifact", "run-directory", "map"])
def test_symlink_cannot_serve_another_runs_artifacts(research, target):
    client, assets, _ = research
    other = assets.parent / "other-run"
    other.mkdir()
    write_json(other / "conditioning-influence.json", INFLUENCE)
    write_self(other)
    try:
        if target == "run-directory":
            # The fixture run directory is empty and created only by this test.
            assets.rmdir()
            assets.symlink_to(other, target_is_directory=True)
        elif target == "artifact":
            (assets / "conditioning-influence.json").symlink_to(other / "conditioning-influence.json")
        else:
            write_json(assets / "self-attention-index.json", SELF_INDEX)
            (assets / SELF_DESCRIPTOR["fileName"]).symlink_to(other / SELF_DESCRIPTOR["fileName"])
    except OSError as exc:
        pytest.skip(f"Symlinks unavailable in this test environment: {exc.winerror if hasattr(exc, 'winerror') else exc.errno}")
    if target == "map":
        response = client.get("/api/traces/run-research/self-attention/maps/s00-down-q0")
        assert response.status_code == 404
    else:
        assert client.get("/api/traces/run-research/influence").json()["available"] is False


@pytest.mark.parametrize("mutation", ["duplicate-key", "oversized", "invalid-encoding", "huge-number"])
def test_self_map_reader_rejects_unsafe_json(research, mutation):
    client, assets, _ = research
    write_self(assets)
    path = assets / SELF_DESCRIPTOR["fileName"]
    if mutation == "duplicate-key":
        path.write_text(json.dumps(SELF_MAP).replace('"step": 0', '"step": 0, "step": 0'), encoding="utf-8")
    elif mutation == "oversized":
        with path.open("wb") as stream:
            stream.truncate(2 * 1024 * 1024)
    elif mutation == "invalid-encoding":
        path.write_bytes(b"\xff")
    else:
        write_json(path, changed(SELF_MAP, ("values",), [0, 0, 0, 10**400]))
    response = client.get("/api/traces/run-research/self-attention/maps/s00-down-q0")
    assert response.status_code == 422
    assert response.json()["code"] == "SELF_ATTENTION_MAP_INVALID"


def test_corrupt_sibling_trace_does_not_break_discovery(research):
    client, assets, _ = research
    (assets.parent / "bad-encoding.json").write_bytes(b"\xff")
    response = client.get("/api/traces")
    assert response.status_code == 200
    assert [row["runId"] for row in response.json()] == ["run-research"]
    assert client.get("/api/traces/latest/influence").json()["runId"] == "run-research"


def test_maximum_native_h6_shape_fits_reader_budget(research):
    _, assets, runtime = research
    # Native nlohmann writer emits indent=2, including indentation per scalar.
    document = copy.deepcopy(INFLUENCE)
    document.update(totalChunks=3, capturedChunks=3)
    sample = document["steps"][0]
    sample.update(width=128, height=128)
    sample["chunks"] = [{**sample["chunks"][0], "chunk": i, "tokenStart": i * 77,
                         "tokenEnd": (i + 1) * 77, "spatialDelta": [1.2345678901234568e-30] * 16384}
                        for i in range(3)]
    document["steps"] = [{**sample, "step": i} for i in range(5)]
    (assets / "conditioning-influence.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
    response = runtime.influence("run-research")
    assert response["available"] is True
    assert len(response["steps"]) == 5
    assert len(response["steps"][4]["chunks"][2]["spatialDelta"]) == 16384
