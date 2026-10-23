"""Visual redraw contracts and durable evidence, without inference or GPU work."""
import io
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from errors import DreamApiError
from identity_batches import BatchRequest
from identity_profiles import ProfilePreset
from identity_service import IdentityService, atomic_json, read_json
from test_identity_visual_profiles import profile
from test_identity_visual_service import VISUAL_MODEL, generation, reference, visual_service


METHOD = "visual-reference-local-redraw"


def visual_request(ref, **changes):
    return generation(ref, VISUAL_MODEL, **{"width": 256, "height": 256, "facePolish": True, **changes})


@pytest.fixture
def redraw_service(visual_service, monkeypatch):
    service, boundary = visual_service
    original = boundary.run
    control = SimpleNamespace(damage=lambda metadata: None, failed=False, original=True)

    def render(operation, payload, cancelled=None):
        if operation == "batch":
            for item in payload["items"]:
                render("generate", item, cancelled)
            return {"ok": True, "items": [{"jobId": item["jobId"]} for item in payload["items"]]}
        if operation != "generate":
            return original(operation, payload, cancelled)
        image = Image.new("RGB", (payload["width"], payload["height"]), "navy")
        polish = {"enabled": True, "status": "failed" if control.failed else "completed",
                  "durationMs": 3, "restoreStrength": payload["faceRestoreStrength"]}
        if control.original:
            path = service.root / "originals" / (payload["jobId"] + ".png")
            path.parent.mkdir(parents=True, exist_ok=True)
            image.save(path)
            polish["originalImageUrl"] = f"/api/identity/jobs/{payload['jobId']}/original"
        if control.failed:
            polish["message"] = "未检测到清晰动漫脸，保留基础图片"
        else:
            ImageDraw.Draw(image).rectangle((32, 32, 64, 64), fill="orange")
            polish.update(method=METHOD, referenceId=payload["referenceId"], faceIndex=payload["faceIndex"],
                          featureKey="b" * 64, faceBox=[32., 32., 64., 64.], cropBox=[16, 16, 96, 96],
                          denoiseStrength=payload["animeDenoiseStrength"], outsideMaskUnchanged=True,
                          restoreModel="CyberRealistic XL + Plus Face visual reference",
                          restoreDevice="CUDA sequential offload")
        metadata = {"featureKey": "b" * 64, "referenceKind": "visual", "facePolish": polish}
        control.damage(metadata)
        output = Path(payload["outputPath"])
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output)
        atomic_json(Path(payload["metadataPath"]), metadata)
        return {"ok": True}

    monkeypatch.setattr(boundary, "run", render)
    return service, control


def completed(service, request, batch=False):
    if batch:
        accepted = service.batch_operation("submit", BatchRequest(request=request, count=1))
        service._background[accepted["id"]][0].result(timeout=5)
        return service.batch_operation("get", accepted["id"])["items"][0]
    accepted = service.submit(request)
    service._futures[accepted["id"]].result(timeout=5)
    return service.get(accepted["id"])


@pytest.mark.parametrize('bad', [None, 'wrong-prompt', 'oversized', 'wrong-size', 'missing-size', 'missing-version', 'null-version'])
def test_masked_detail_receipt_roundtrip_and_request_binding(redraw_service, bad):
    service, control = redraw_service
    ref = reference(service, 'visual')
    def receipt(metadata):
        metadata['facePolish'].update(detailerVersion='masked-face-v1', processingSize=[768, 768],
                                     detailPrompt='clean eyes', detailNegativePrompt='blur')
        if bad == 'wrong-prompt': metadata['facePolish']['detailPrompt'] = 'other prompt'
        if bad == 'oversized': metadata['facePolish']['processingSize'] = [1024, 1024]
        if bad == 'wrong-size': metadata['facePolish']['processingSize'] = [512, 512]
        if bad == 'missing-size': metadata['facePolish'].pop('processingSize')
        if bad == 'missing-version': metadata['facePolish'].pop('detailerVersion')
        if bad == 'null-version': metadata['facePolish']['detailerVersion'] = None
    control.damage = receipt
    job = completed(service, visual_request(ref, visualPolishPrompt='clean eyes', visualPolishNegativePrompt='blur'), True)
    if bad:
        assert job['state'] == 'failed' and job['result'] is None
    else:
        assert job['state'] == 'complete', job['error']
        assert job['result']['metadata']['facePolish']['processingSize'] == [768, 768]
        assert read_json(service._job_path(job['id']))['result'] == job['result']
        assert job['request']['visualPolishPrompt'] == 'clean eyes'


@pytest.mark.parametrize("strength", [.15, .35, .65])
def test_visual_redraw_accepts_explicit_opt_in_and_denoise_bounds(strength):
    ref = {"id": "ref-" + "a" * 24}
    params = visual_request(ref, animeDenoiseStrength=strength)
    assert params.facePolish is True and params.animeDenoiseStrength == strength
    assert generation(ref, VISUAL_MODEL).facePolish is False
    assert visual_request(ref).animeDenoiseStrength == .35


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("kind", [None, "visual"])
def test_visual_redraw_success_requires_same_reference_and_durable_original(redraw_service, batch, kind):
    service, _ = redraw_service
    ref = reference(service, kind)
    record = completed(service, visual_request(ref, animeDenoiseStrength=.5), batch)
    assert record["state"] == "complete", record["error"]
    metadata = record["result"]["metadata"]
    polish = metadata["facePolish"]
    assert polish["method"] == METHOD and polish["status"] == "completed"
    assert (polish["referenceId"], polish["faceIndex"]) == (ref["id"], 0)
    assert polish["featureKey"] == metadata["featureKey"] == "b" * 64
    assert polish["denoiseStrength"] == .5 and polish["outsideMaskUnchanged"] is True
    assert "animeBinding" not in record or record["animeBinding"] is None
    assert read_json(service._job_path(record["id"]))["result"] == record["result"]
    with Image.open(service.original_image(record["id"])) as image:
        assert image.size == (256, 256) and image.getpixel((40, 40)) == (0, 0, 128)


@pytest.mark.parametrize("field,bad", [
    ("method", None), ("method", "anime-reference-local-redraw"),
    ("referenceId", "ref-" + "f" * 24), ("referenceId", "../bad"),
    ("faceIndex", 1), ("faceIndex", True), ("featureKey", "f" * 64), ("featureKey", "z" * 64),
    ("faceBox", [64., 32., 32., 64.]), ("faceBox", [32., 32., 300., 64.]),
    ("cropBox", [0, 0, 20, 20]), ("cropBox", [-1, 0, 96, 96]), ("cropBox", [16, 16, 96.5, 96]),
    ("denoiseStrength", .4), ("denoiseStrength", None), ("outsideMaskUnchanged", False),
    ("restoreModel", None), ("restoreModel", "GFPGAN"), ("restoreDevice", "  "),
    ("swapModel", "inswapper"), ("swapDevice", "CPU"),
    ("profileId", "anime-" + "c" * 24), ("profileName", "hybrid"),
    ("originalImageUrl", None), ("originalImageUrl", "/api/identity/jobs/identity-" + "f" * 24 + "/original"),
])
def test_visual_completion_rejects_missing_or_wrong_evidence(redraw_service, field, bad):
    service, control = redraw_service
    control.damage = lambda metadata: metadata["facePolish"].update({field: bad})
    job = completed(service, visual_request(reference(service, "visual")))
    assert job["state"] == "failed", (field, job)
    assert job["result"] is None
    assert not service._original_path(job["id"]).exists()
    assert not list((service.config.dream_root / "outputs").glob(f"*/{job['id']}.*"))


@pytest.mark.parametrize("field,bad", [("featureKey", None), ("featureKey", "bad"),
                                     ("referenceKind", "faceid"), ("model_id", "illustrious-xl-v2.0-faceid")])
def test_batch_completion_checks_visual_evidence_against_generation_metadata(redraw_service, field, bad):
    service, control = redraw_service
    control.damage = lambda metadata: metadata.update({field: bad})
    job = completed(service, visual_request(reference(service)), batch=True)
    assert job["state"] == "failed" and job["result"] is None


def test_visual_completed_redraw_cannot_omit_original_file(redraw_service):
    service, control = redraw_service
    control.original = False
    assert completed(service, visual_request(reference(service)))["state"] == "failed"


@pytest.mark.parametrize("original", [False, True])
def test_failed_optional_visual_redraw_preserves_base_and_recovers_truthfully(redraw_service, original):
    service, control = redraw_service
    control.failed, control.original = True, original
    job = completed(service, visual_request(reference(service)))
    assert job["state"] == "complete", job["error"]
    assert job["result"]["metadata"]["facePolish"]["status"] == "failed"
    assert "未检测到" in job["result"]["metadata"]["facePolish"]["message"]
    service.close()
    restored = IdentityService(service.config, service.job_runner)
    try:
        assert restored.get(job["id"])["result"] == job["result"]
        if original:
            assert restored.original_image(job["id"]).is_file()
        else:
            with pytest.raises(DreamApiError):
                restored.original_image(job["id"])
    finally:
        restored.close()


def test_visual_polish_preset_keeps_explicit_opt_in_across_restart(redraw_service):
    service, _ = redraw_service
    ref = reference(service, "visual")
    person = profile(service, ref, "visual")
    assert person["defaults"]["facePolish"] is False
    job = completed(service, visual_request(ref, animeDenoiseStrength=.55))
    assert job["state"] == "complete", job["error"]
    preset = service.profile_operation("preset", person["id"], ProfilePreset(jobId=job["id"]))
    path = service.profiles.path(person["id"])
    before = path.read_bytes()
    original = service.original_image(job["id"]).read_bytes()
    service.close()
    restored = IdentityService(service.config, service.job_runner)
    try:
        recovered = restored.profile_operation("get", person["id"])
        assert recovered["defaults"]["facePolish"] is True
        assert recovered["defaults"]["animeDenoiseStrength"] == .55
        assert recovered["defaults"] == preset["defaults"]
        assert path.read_bytes() == before
        assert restored.original_image(job["id"]).read_bytes() == original
    finally:
        restored.close()


@pytest.mark.parametrize("model", ["realistic-vision-v5.1-faceid", "illustrious-xl-v2.0-faceid"])
def test_visual_redraw_metadata_cannot_be_reported_for_faceid_job(redraw_service, model):
    service, _ = redraw_service
    job = completed(service, generation(reference(service), model, facePolish=True, width=256, height=256))
    assert job["state"] == "failed" and job["result"] is None


@pytest.mark.parametrize("ready", [False, True])
def test_service_exposes_visual_polish_status_without_changing_other_capabilities(visual_service, monkeypatch, ready):
    service, boundary = visual_service
    monkeypatch.setattr(boundary, "run", lambda *args: {"ready": True, "loras": [],
                        "visualPolish": {"ready": ready, "message": "复用当前视觉底模", "private": "discard"}})
    status = service.status()
    assert status["ready"] is True
    assert status["visualPolish"] == {"ready": ready, "message": "复用当前视觉底模"}


@pytest.mark.parametrize("detector_ready,model_ready", [(False, False), (False, True), (True, False), (True, True)])
def test_worker_visual_status_requires_detector_and_visual_model(tmp_path, monkeypatch, detector_ready, model_ready):
    import identity_worker
    import identity_models

    detector = tmp_path / "anime-detector.onnx"
    if detector_ready:
        detector.write_bytes(b"local detector")
    config = tmp_path / "runtime.json"
    atomic_json(config, {"animeFaceDetector": str(detector)})
    request, result = tmp_path / "request.json", tmp_path / "result.json"
    atomic_json(request, {"configPath": str(config)})
    monkeypatch.setattr(identity_worker, "require_dependencies", lambda: None)
    monkeypatch.setattr(identity_models, "identity_model_catalog", lambda config: [
        {"id": VISUAL_MODEL, "name": "Visual", "architecture": "SDXL", "referenceKind": "visual",
         "ready": model_ready, "message": "local model state", "loras": []}])
    monkeypatch.setitem(sys.modules, "identity_visual_polish", SimpleNamespace(
        visual_polish_status=lambda config: {"ready": Path(config["animeFaceDetector"]).is_file(), "message": "复用当前视觉底模"}))
    monkeypatch.setattr(sys, "argv", ["identity_worker.py", "--operation", "status", "--request", str(request), "--result", str(result)])
    # Exercise the real CLI without replacing its JSON file protocol.
    with io.TextIOWrapper(io.BytesIO(), encoding="utf-8") as stdout, io.TextIOWrapper(io.BytesIO(), encoding="utf-8") as stderr:
        with monkeypatch.context() as streams:
            streams.setattr(sys, "stdout", stdout)
            streams.setattr(sys, "stderr", stderr)
            assert identity_worker.main() == 0
    status = read_json(result)
    assert status["visualPolish"]["ready"] is (detector_ready and model_ready)
    assert status["visualPolish"]["message"]
