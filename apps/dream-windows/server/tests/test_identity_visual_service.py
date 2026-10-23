"""Visual reference storage and queue guards, with only inference replaced."""
import copy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from app import create_app
from errors import DreamApiError
from identity_batches import BatchRequest
from identity_contract import IdentityGenerateRequest
from identity_service import IdentityService, ReferenceUpload, atomic_json, read_json
from job_runner import JobRunner
from persistent_engine import PersistentEngineClient
from runtime import DreamRuntime
from test_generation_jobs import make_config
from test_identity_api import absent_native, image_base64


VISUAL_MODEL = "cyberrealistic-xl-plus-face"
FACEID_MODEL = "realistic-vision-v5.1-faceid"


class InferenceBoundary:
    def __init__(self):
        self.calls = []
        self.prepare_result = None
        self.models = None

    def run(self, operation, payload, cancelled=None):
        self.calls.append((operation, copy.deepcopy(payload)))
        if operation == "inspect":
            return {"faces": [{"index": 0, "box": [1., 1., 5., 6.]}]}
        if operation == "prepare":
            if self.prepare_result is not None:
                return copy.deepcopy(self.prepare_result)
            kind = payload.get("referenceKind", "faceid")
            return {"ok": True, "cacheHit": False, "featureKey": ("b" if kind == "visual" else "a") * 64,
                    "featureVersion": 1 if kind == "visual" else 3, "referenceKind": kind}
        if operation == "status":
            return {"ready": True, "loras": [], "models": self.models or []}
        if operation == "generate":
            output = Path(payload["outputPath"])
            output.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (payload["width"], payload["height"])).save(output)
            atomic_json(Path(payload["metadataPath"]), {"seed": payload["seed"], "generation_time_ms": 1})
            return {"ok": True}
        if operation == "batch":
            return {"ok": True}  # No sampling: these tests check acceptance, not image quality.
        raise AssertionError(f"Unexpected inference operation: {operation}")


@pytest.fixture
def visual_service(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    boundary = InferenceBoundary()
    monkeypatch.setattr(IdentityService, "_worker", lambda self, *args: boundary.run(*args))
    runner = JobRunner(config, persistent_engine=PersistentEngineClient(config, transport=absent_native))
    service = IdentityService(config, runner)
    try:
        yield service, boundary
    finally:
        service.close()
        runner._executor.shutdown(wait=True, cancel_futures=True)


def reference(service, kind=None):
    fields = {} if kind is None else {"referenceKind": kind}
    return service.upload(ReferenceUpload(name="art.png", imageBase64=image_base64(), **fields))


def persisted_visual_reference(service):
    record = reference(service)
    record["referenceKind"] = "visual"
    atomic_json(service._asset(record["id"], ".json"), record)
    return record


def generation(ref, model=FACEID_MODEL, **changes):
    visual = {"width": 768, "height": 768, "steps": 30, "cfg": 5.0, "identityStrength": .8,
              "structureStrength": 0, "faceLoraStrength": 0} if model == VISUAL_MODEL else {}
    return IdentityGenerateRequest(referenceId=ref["id"], faceIndex=0, prompt="portrait", seed=12,
                                   modelId=model, **{**visual, **changes})


def assert_no_jobs(service):
    assert service.jobs() == []
    assert service.batch_operation("list") == []
    assert not list((service.root / "jobs").glob("identity-*.json"))
    assert not list((service.root / "batches").glob("batch-*.json"))
    assert not service._futures and not service._background


def test_visual_upload_persists_kind_and_selects_detection_payload(visual_service):
    service, boundary = visual_service
    record = reference(service, "visual")
    assert record["referenceKind"] == "visual"
    assert read_json(service._asset(record["id"], ".json"))["referenceKind"] == "visual"
    assert service.references() == [record]
    assert boundary.calls[0][0] == "inspect"
    assert boundary.calls[0][1]["referenceKind"] == "visual"


def test_omitted_reference_kind_keeps_faceid_behavior_without_rewriting_old_file(visual_service):
    service, boundary = visual_service
    record = reference(service)
    path = service._asset(record["id"], ".json")
    original = path.read_bytes()
    assert service.references()[0].get("referenceKind", "faceid") == "faceid"
    assert boundary.calls[0][1].get("referenceKind", "faceid") == "faceid"
    assert path.read_bytes() == original
    job = service.submit(generation(record))
    service._futures[job["id"]].result(timeout=5)
    assert service.get(job["id"])["state"] == "complete"


@pytest.mark.parametrize("model", [FACEID_MODEL, "illustrious-xl-v2.0-faceid"])
@pytest.mark.parametrize("batch", [False, True])
def test_visual_only_reference_rejected_before_faceid_job_is_saved(visual_service, model, batch):
    service, boundary = visual_service
    ref = persisted_visual_reference(service)
    request = generation(ref, model)
    with pytest.raises(DreamApiError) as error:
        if batch:
            service.batch_operation("submit", BatchRequest(request=request, count=1))
        else:
            service.submit(request)
    assert error.value.status_code == 422
    assert error.value.code == "IDENTITY_REFERENCE_KIND_CONFLICT"
    assert_no_jobs(service)
    assert [op for op, _ in boundary.calls] == ["inspect"]


@pytest.mark.parametrize("kind", [None, "visual"])
def test_visual_model_accepts_existing_faceid_and_visual_references(visual_service, kind):
    service, boundary = visual_service
    ref = reference(service, kind)
    job = service.submit(generation(ref, VISUAL_MODEL))
    service._futures[job["id"]].result(timeout=5)
    ready = service.get(job["id"])
    assert ready["state"] == "complete", ready["error"]
    assert ready["request"]["modelId"] == VISUAL_MODEL
    assert "referenceKind" not in ready["request"]
    assert [p for op, p in boundary.calls if op == "generate"][0]["modelId"] == VISUAL_MODEL


def test_status_exposes_optional_worker_catalog_kind(visual_service):
    service, boundary = visual_service
    boundary.models = [{"id": FACEID_MODEL, "name": "FaceID", "architecture": "SD1.5",
                        "ready": True, "message": "ready", "referenceKind": "faceid", "loras": []}]
    assert service.status()["models"][0]["referenceKind"] == "faceid"
    boundary.models[0].pop("referenceKind")
    assert "referenceKind" not in service.status()["models"][0]


@pytest.mark.parametrize("invalid", [None, "unknown", 1])
def test_upload_rejects_invalid_kind_before_inspection(visual_service, invalid):
    service, boundary = visual_service
    with pytest.raises(ValidationError):
        service.upload(ReferenceUpload(name="art", imageBase64=image_base64(), referenceKind=invalid))
    assert boundary.calls == []
    assert not list((service.root / "references").glob("*"))


@pytest.mark.parametrize("changes", [{"animeProfileId": "anime-"+"b"*24},
    {"traceLevel": "h6", "researchCoverage": "extended"}, {"traceLevel": "h7", "researchCoverage": "extended"}])
@pytest.mark.parametrize("batch", [False, True])
def test_visual_unsupported_options_rejected_at_api_before_queue(tmp_path, monkeypatch, changes, batch):
    config = make_config(tmp_path)
    boundary = InferenceBoundary()
    monkeypatch.setattr(IdentityService, "_worker", lambda self, *args: boundary.run(*args))
    runner = JobRunner(config, persistent_engine=PersistentEngineClient(config, transport=absent_native))
    try:
        with TestClient(create_app(config, DreamRuntime(config, job_runner=runner)), base_url="http://127.0.0.1:8866") as client:
            uploaded = client.post("/api/identity/references", json={"name": "art", "imageBase64": image_base64()})
            assert uploaded.status_code == 200, uploaded.text
            ref = uploaded.json()
            payload = {"modelId": VISUAL_MODEL, "referenceId": ref["id"], "faceIndex": 0, "prompt": "portrait",
                       "structureStrength": 0, "faceLoraStrength": 0, **changes}
            if batch:
                response = client.post("/api/identity/batches", json={"request": payload, "count": 1})
            else:
                response = client.post("/api/identity/generate", json=payload)
            assert response.status_code == 422
            assert client.get("/api/identity/jobs").json() == []
            assert client.get("/api/identity/batches").json() == []
            assert [op for op, _ in boundary.calls] == ["inspect"]
            # Prove the failure concerns the option, not an unsupported model ID.
            valid = {**payload, "facePolish": False, "traceLevel": "basic", "animeProfileId": None,
                     "researchCoverage": "representative"}
            accepted = client.post("/api/identity/batches", json={"request": valid, "count": 1}) if batch else client.post("/api/identity/generate", json=valid)
            assert accepted.status_code == 200, accepted.text
    finally:
        runner._executor.shutdown(wait=True, cancel_futures=True)
