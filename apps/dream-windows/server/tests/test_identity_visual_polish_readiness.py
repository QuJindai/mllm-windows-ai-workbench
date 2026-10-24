"""Readiness is checked in the worker environment, before generation is saved."""
import builtins
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from errors import DreamApiError
from identity_batches import BatchRequest, BatchRetryRequest
from identity_service import IdentityService
from test_identity_protected_polish_storage import install_protected_receipt
from test_identity_staged_polish_storage import staged_request
from test_identity_visual_polish_storage import completed, redraw_service
from test_identity_visual_service import reference, visual_service


DEPENDENCIES = {"facexlib", "cv2", "insightface", "onnxruntime", "torch"}


def configured_assets(tmp_path):
    detector = tmp_path / "anime.onnx"
    parser = tmp_path / "parsing_parsenet.pth"
    alignment = tmp_path / "insightface/models/buffalo_l/det_10g.onnx"
    alignment.parent.mkdir(parents=True)
    for path in (detector, parser, alignment):
        path.write_bytes(b"synthetic asset")
    return dict(animeFaceDetector=str(detector), faceParsingModel=str(parser), insightfaceRoot=str(tmp_path / "insightface"))


@pytest.mark.parametrize("missing", [None, "faceParsingModel", "alignment-detector", *sorted(DEPENDENCIES)])
def test_anchor_readiness_is_separate_from_redraw_and_does_not_import_models(tmp_path, monkeypatch, missing):
    from identity_visual_polish import visual_polish_status
    config = configured_assets(tmp_path)
    if missing == "faceParsingModel": Path(config[missing]).unlink()
    if missing == "alignment-detector": (Path(config["insightfaceRoot"]) / "models/buffalo_l/det_10g.onnx").unlink()
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in DEPENDENCIES:
            pytest.fail(f"readiness imported model dependency: {name}")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    status = visual_polish_status(config, find_spec=lambda name: None if name == missing else object())
    assert status["ready"] is True
    assert status["referenceAnchorReady"] is (missing is None)
    assert status["referenceAnchorMessage"]
    if missing in DEPENDENCIES or missing == "faceParsingModel":
        assert missing in status["referenceAnchorMessage"]


def test_anchor_status_also_requires_common_detector(tmp_path):
    from identity_visual_polish import visual_polish_status
    config = configured_assets(tmp_path)
    Path(config["animeFaceDetector"]).unlink()
    status = visual_polish_status(config, find_spec=lambda name: object())
    assert status["ready"] is False and status["referenceAnchorReady"] is False


@pytest.mark.parametrize("ready", [False, True])
def test_service_returns_anchor_capabilities_without_private_worker_fields(visual_service, monkeypatch, ready):
    service, boundary = visual_service
    monkeypatch.setattr(boundary, "run", lambda *args: dict(ready=True, loras=[], visualPolish=dict(
        ready=True, message="redraw ready", referenceAnchorReady=ready,
        referenceAnchorMessage="component status", private="discard")))
    assert service.status()["visualPolish"] == dict(ready=True, message="redraw ready",
        referenceAnchorReady=ready, referenceAnchorMessage="component status")


@pytest.mark.parametrize("batch", [False, True])
def test_unready_anchor_is_rejected_before_any_job_or_batch_is_saved(redraw_service, batch):
    service, control = redraw_service
    control.anchor_ready = False
    request = staged_request(reference(service))
    with pytest.raises(DreamApiError) as error:
        if batch:
            service.batch_operation("submit", BatchRequest(request=request, count=1))
        else:
            service.submit(request)
    assert error.value.code == "IDENTITY_REFERENCE_ANCHOR_NOT_READY"
    assert error.value.status_code == 422
    assert "faceParsingModel" in str(error.value)
    assert service.jobs() == [] and service.batch_operation("list") == []
    assert not list((service.root / "jobs").glob("identity-*.json"))
    assert not list((service.root / "batches").glob("batch-*.json"))


@pytest.mark.parametrize("change", [dict(visualPolishMode="redraw"), dict(facePolish=False)])
def test_dormant_anchor_and_redraw_do_not_query_anchor_readiness(visual_service, monkeypatch, change):
    service, boundary = visual_service
    ref = reference(service)
    original = boundary.run
    def run(operation, *args):
        if operation == "status": pytest.fail("unused anchor readiness queried")
        return original(operation, *args)
    monkeypatch.setattr(boundary, "run", run)
    accepted = service.submit(staged_request(ref, **change))
    service._futures[accepted["id"]].result(timeout=5)
    assert service.get(accepted["id"])["id"] == accepted["id"]


def test_ready_anchor_history_remains_readable_after_components_become_unready(redraw_service, monkeypatch):
    service, control = redraw_service
    install_protected_receipt(service, control)
    job = completed(service, staged_request(reference(service)))
    assert job["state"] == "complete", job["error"]
    control.anchor_ready = False
    monkeypatch.setattr(service, "status", lambda: pytest.fail("history queried runtime readiness"))
    assert service.get(job["id"])["result"] == job["result"]
    assert service.original_image(job["id"]).is_file()
    assert service.stage_image(job["id"], "detail").is_file()
    service.close()
    restored = IdentityService(service.config, service.job_runner)
    try:
        monkeypatch.setattr(restored, "status", lambda: pytest.fail("recovered history queried runtime readiness"))
        assert restored.original_image(job["id"]).is_file()
        assert restored.stage_image(job["id"], "detail").is_file()
    finally:
        restored.close()


def test_retry_preflight_rejects_unready_anchor_without_creating_children(redraw_service, monkeypatch):
    service, control = redraw_service
    request = staged_request(reference(service))
    original = service._worker
    def worker(operation, *args):
        if operation == "batch": raise RuntimeError("controlled generation failure")
        return original(operation, *args)
    monkeypatch.setattr(service, "_worker", worker)
    accepted = service.batch_operation("submit", BatchRequest(request=request, count=1))
    service._background[accepted["id"]][0].result(timeout=5)
    control.anchor_ready = False
    with pytest.raises(DreamApiError) as error:
        service.batch_operation("retry", accepted["id"], BatchRetryRequest(mode="failed", idempotencyKey="unready-retry"))
    assert error.value.code == "IDENTITY_REFERENCE_ANCHOR_NOT_READY"
    assert len(service.jobs()) == 1 and len(service.batch_operation("list")) == 1


def failed_anchor_batch(service, monkeypatch):
    request = staged_request(reference(service))
    original = service._worker
    def worker(operation, *args):
        if operation == "batch": raise RuntimeError("controlled generation failure")
        return original(operation, *args)
    monkeypatch.setattr(service, "_worker", worker)
    accepted = service.batch_operation("submit", BatchRequest(request=request, count=1))
    service._background[accepted["id"]][0].result(timeout=5)
    assert service.batch_operation("get", accepted["id"])["state"] == "failed"
    return accepted


@pytest.mark.parametrize("recovered", [False, True])
@pytest.mark.parametrize("unavailable", ["missing-parser", "status-failure"])
def test_accepted_retry_replays_same_child_when_anchor_becomes_unavailable(redraw_service, monkeypatch, recovered, unavailable):
    service, control = redraw_service
    parent = failed_anchor_batch(service, monkeypatch)
    request = BatchRetryRequest(mode="failed", idempotencyKey="accepted-anchor-retry")
    child = service.batch_operation("retry", parent["id"], request)
    service._background[child["id"]][0].result(timeout=5)
    child = service.batch_operation("get", child["id"])
    before = {path: path.read_bytes() for folder in ("jobs", "batches")
              for path in (service.root / folder).glob("*.json")}
    control.anchor_ready = False
    active = service
    if recovered:
        service.close()
        active = IdentityService(service.config, service.job_runner)
    original_status = active.status
    status_calls = []
    def status():
        status_calls.append(True)
        if unavailable == "status-failure":
            return {"ready": False, "message": "controlled worker status failure", "loras": []}
        return original_status()
    monkeypatch.setattr(active, "status", status)
    try:
        replay = active.batch_operation("retry", parent["id"], request)
        assert replay == child
        assert status_calls == []
        assert {path: path.read_bytes() for path in before} == before
        assert len(active.jobs()) == 2 and len(active.batch_operation("list")) == 2
        with pytest.raises(DreamApiError) as error:
            active.batch_operation("retry", parent["id"], BatchRetryRequest(mode="failed", idempotencyKey="new-anchor-retry"))
        assert error.value.code == "IDENTITY_REFERENCE_ANCHOR_NOT_READY"
        assert status_calls == [True]
        assert len(active.jobs()) == 2 and len(active.batch_operation("list")) == 2
    finally:
        if recovered:
            active.close()


def test_concurrent_same_key_retry_checks_readiness_once_under_submission_lock(redraw_service, monkeypatch):
    service, _ = redraw_service
    parent = failed_anchor_batch(service, monkeypatch)
    status_calls = []
    def status():
        status_calls.append(True)
        return {"visualPolish": {"referenceAnchorReady": len(status_calls) == 1,
                                 "referenceAnchorMessage": "components became unavailable after first acceptance"}}
    monkeypatch.setattr(service, "status", status)
    request = BatchRetryRequest(mode="failed", idempotencyKey="concurrent-anchor-retry")
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(service.batch_operation, "retry", parent["id"], request) for _ in range(3)]
        children = [future.result(timeout=5) for future in futures]
    assert len({child["id"] for child in children}) == 1
    assert status_calls == [True]
    child_id = children[0]["id"]
    service._background[child_id][0].result(timeout=5)
    assert len(service.jobs()) == 2 and len(service.batch_operation("list")) == 2
