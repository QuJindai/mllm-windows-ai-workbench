"""Staged request/receipt contracts using synthetic PNGs and no inference."""
import copy
import importlib
import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from app import create_app
from errors import DreamApiError
from identity_contract import IdentityGenerateRequest
from identity_profiles import ProfilePreset
from identity_service import IdentityService, atomic_json, read_json
from runtime import DreamRuntime
from test_identity_visual_profiles import profile
from test_identity_visual_service import VISUAL_MODEL, generation, reference, visual_service
from test_identity_visual_polish_storage import completed, redraw_service, visual_request


DEFAULTS = dict(visualPolishMode="redraw", visualAnchorStrength=.95, visualPolishPasses=1)


def stage_module():
    assert importlib.util.find_spec("identity_stage_artifacts"), "Stage artifact storage is missing"
    return importlib.import_module("identity_stage_artifacts")


@pytest.mark.parametrize("model", ["realistic-vision-v5.1-faceid", "illustrious-xl-v2.0-faceid",
                                 VISUAL_MODEL, "illustrious-xl-v2.0-plus-face"])
def test_defaults_are_backward_compatible_and_replayable(model):
    values = dict(referenceId="ref-" + "a" * 24, faceIndex=0, prompt="portrait", modelId=model,
                  structureStrength=0., faceLoraStrength=0.)
    old = IdentityGenerateRequest(**values)
    assert {key: old.model_dump()[key] for key in DEFAULTS} == DEFAULTS
    assert IdentityGenerateRequest(**values, **DEFAULTS) == old


@pytest.mark.parametrize("field,bad", [
    ("visualPolishMode", None), ("visualPolishMode", "anchor"), ("visualPolishMode", True),
    *[("visualAnchorStrength", x) for x in [None, True, ".95", .299, 1.001, float("nan"), float("inf"), float("-inf")]],
    *[("visualPolishPasses", x) for x in [None, True, "2", 1.0, 2.0, 0, 3]],
])
def test_staged_request_rejects_coercions_and_out_of_range_values(field, bad):
    ref = {"id": "ref-" + "a" * 24}
    assert visual_request(ref, **DEFAULTS).visualPolishPasses == 1
    with pytest.raises(ValidationError):
        visual_request(ref, **{field: bad})


@pytest.mark.parametrize("strength", [.3, .95, 1.])
@pytest.mark.parametrize("model", [VISUAL_MODEL, "illustrious-xl-v2.0-plus-face"])
def test_both_visual_models_accept_staged_controls(model, strength):
    params = IdentityGenerateRequest(referenceId="ref-" + "a" * 24, faceIndex=0, prompt="portrait",
        modelId=model, structureStrength=0., faceLoraStrength=0., visualPolishMode="reference-anchor",
        visualAnchorStrength=strength, visualPolishPasses=2)
    assert params.visualAnchorStrength == strength


@pytest.mark.parametrize("model", ["realistic-vision-v5.1-faceid", "illustrious-xl-v2.0-faceid"])
@pytest.mark.parametrize("change", [{"visualPolishMode": "reference-anchor"}, {"visualPolishPasses": 2}])
@pytest.mark.parametrize("enabled", [False, True])
def test_new_flows_are_visual_only_even_when_polish_is_disabled(model, change, enabled):
    with pytest.raises(ValidationError, match="视觉"):
        generation({"id": "ref-" + "a" * 24}, model, facePolish=enabled, **change)


def install_receipt(service, control, *, mode="reference-anchor", passes=2, strength=.35, damage=None):
    def receipt(metadata):
        polish = metadata["facePolish"]
        job_id = polish["originalImageUrl"].split("/")[-2]
        polish.update(detailerVersion="staged-face-v2", processingSize=[768, 768],
                      detailPrompt="clean eyes", detailNegativePrompt="blur", polishMode=mode,
                      passes=[dict(kind="harmonize", denoiseStrength=strength, steps=int(30 * strength), durationMs=0)])
        if passes == 2:
            polish["passes"].append(dict(kind="detail", denoiseStrength=.15, steps=4, durationMs=3))
        if mode == "reference-anchor":
            polish.update(anchorStrength=.8, alignmentError=.18)
        kinds = (["anchor"] if mode == "reference-anchor" else []) + [p["kind"] for p in polish["passes"]]
        item = dict(dreamRoot=str(service.config.dream_root), jobId=job_id, width=256, height=256)
        polish["snapshots"] = [dict(kind=kind, imageUrl=stage_module().save_visual_stage(
            Image.new("RGB", (256, 256), "orange"), item, kind)) for kind in kinds]
        if damage:
            damage(polish, item)
    control.damage = receipt


def staged_request(ref, **changes):
    return visual_request(ref, **{**dict(visualPolishMode="reference-anchor", visualAnchorStrength=.8,
        visualPolishPasses=2, visualPolishPrompt="clean eyes", visualPolishNegativePrompt="blur"), **changes})


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("mode,passes", [("reference-anchor", 1), ("reference-anchor", 2), ("redraw", 2)])
def test_staged_receipt_roundtrips_with_ordered_real_snapshots(redraw_service, batch, mode, passes):
    service, control = redraw_service
    install_receipt(service, control, mode=mode, passes=passes, strength=.5)
    params = staged_request(reference(service, "visual"), visualPolishMode=mode, visualPolishPasses=passes,
                            animeDenoiseStrength=.5)
    job = completed(service, params, batch)
    assert job["state"] == "complete", job["error"]
    polish = job["result"]["metadata"]["facePolish"]
    assert polish["passes"][0] == dict(kind="harmonize", denoiseStrength=.5, steps=15, durationMs=0)
    assert [p["kind"] for p in polish["snapshots"]] == (["anchor"] if mode == "reference-anchor" else []) + ["harmonize"] + (["detail"] if passes == 2 else [])
    assert ("alignmentError" in polish) == (mode == "reference-anchor")
    assert read_json(service._job_path(job["id"]))["result"] == job["result"]
    service.close()
    restored = IdentityService(service.config, service.job_runner)
    try:
        assert restored.get(job["id"])["result"] == job["result"]
        for snapshot in polish["snapshots"]:
            assert restored.stage_image(job["id"], snapshot["kind"]).is_file()
    finally:
        restored.close()


@pytest.mark.parametrize("field,bad", [
    ("detailerVersion", "masked-face-v1"), ("detailerVersion", None), ("polishMode", "redraw"),
    ("passes", None), ("passes", []), ("passes", [dict(kind="harmonize", denoiseStrength=.35, steps=10, durationMs=1)]),
    ("anchorStrength", .95), ("anchorStrength", None), ("alignmentError", None),
    ("alignmentError", -.01), ("alignmentError", .181), ("alignmentError", float("nan")),
    ("alignmentError", float("inf")), ("alignmentError", True), ("alignmentError", ".1"),
    ("processingSize", [512, 512]), ("detailPrompt", "wrong"),
    ("referenceId", "ref-" + "f" * 24), ("featureKey", "f" * 64), ("faceIndex", 1),
    ("faceBox", [32., 32., 300., 64.]), ("cropBox", [0, 0, 20, 20]),
    ("outsideMaskUnchanged", False), ("restoreModel", "GFPGAN"), ("originalImageUrl", None),
    ("snapshots", None), ("snapshots", []),
])
def test_staged_completion_rejects_forged_or_incomplete_receipts(redraw_service, field, bad):
    service, control = redraw_service
    install_receipt(service, control, damage=lambda polish, item: polish.update({field: bad}))
    job = completed(service, staged_request(reference(service)))
    assert job["state"] == "failed" and job["result"] is None
    assert not list((service.root / "stages" / job["id"]).glob("*.png"))


@pytest.mark.parametrize("index,field,bad", [
    (0, "kind", "detail"), (1, "kind", "harmonize"), (0, "denoiseStrength", .5),
    (1, "denoiseStrength", .35), (0, "steps", 30), (1, "steps", 5), (1, "steps", 4.0),
    (0, "durationMs", -1), (0, "durationMs", True), (0, "durationMs", float("inf")),
])
def test_each_pass_is_bound_to_requested_order_strength_and_actual_steps(redraw_service, index, field, bad):
    service, control = redraw_service
    install_receipt(service, control, damage=lambda polish, item: polish["passes"][index].update({field: bad}))
    job = completed(service, staged_request(reference(service)))
    assert job["state"] == "failed", job


@pytest.mark.parametrize("damage", ["missing", "reordered", "foreign", "traversal", "size", "broken", "extra"])
def test_snapshots_require_exact_order_urls_and_valid_full_size_pngs(redraw_service, damage):
    service, control = redraw_service
    def corrupt(polish, item):
        path = Path(item["dreamRoot"]) / "data/identity/stages" / item["jobId"] / "detail.png"
        if damage == "missing": path.unlink()
        elif damage == "reordered": polish["snapshots"].reverse()
        elif damage == "foreign": polish["snapshots"][0]["imageUrl"] = "/api/identity/jobs/identity-" + "f" * 24 + "/stages/anchor"
        elif damage == "traversal": polish["snapshots"][0]["imageUrl"] = "../../private.png"
        elif damage == "size": Image.new("RGB", (8, 8)).save(path)
        elif damage == "broken": path.write_bytes(b"broken PNG")
        elif damage == "extra": polish["snapshots"].append(polish["snapshots"][0])
    install_receipt(service, control, damage=corrupt)
    job = completed(service, staged_request(reference(service)))
    assert job["state"] == "failed", job


@pytest.mark.parametrize("mode,passes", [("reference-anchor", 1), ("redraw", 2)])
def test_legacy_receipts_never_satisfy_staged_requests(redraw_service, mode, passes):
    service, _ = redraw_service
    job = completed(service, staged_request(reference(service), visualPolishMode=mode, visualPolishPasses=passes))
    assert job["state"] == "failed" and job["result"] is None


@pytest.mark.parametrize("field,value", [("anchorStrength", .8), ("alignmentError", .1)])
def test_redraw_must_not_claim_anchor_evidence(redraw_service, field, value):
    service, control = redraw_service
    install_receipt(service, control, mode="redraw", damage=lambda polish, item: polish.update({field: value}))
    job = completed(service, staged_request(reference(service), visualPolishMode="redraw"))
    assert job["state"] == "failed"


@pytest.mark.parametrize("alignment", [0., .18])
def test_alignment_fit_accepts_zero_and_maximum_without_becoming_identity_score(redraw_service, alignment):
    service, control = redraw_service
    install_receipt(service, control, damage=lambda polish, item: polish.update(alignmentError=alignment))
    job = completed(service, staged_request(reference(service)))
    assert job["state"] == "complete", job["error"]
    assert job["result"]["metadata"]["facePolish"]["alignmentError"] == alignment


def test_optional_failure_keeps_original_without_claiming_partial_success(redraw_service):
    service, control = redraw_service
    control.failed = True
    job = completed(service, staged_request(reference(service)))
    assert job["state"] == "complete", job["error"]
    polish = job["result"]["metadata"]["facePolish"]
    assert polish["status"] == "failed" and "passes" not in polish and "snapshots" not in polish
    assert service.original_image(job["id"]).is_file()
    with pytest.raises(DreamApiError) as error:
        service.stage_image(job["id"], "harmonize")
    assert error.value.status_code == 404


def test_profile_defaults_and_explicit_staged_preset_survive_read_only_recovery(redraw_service):
    service, control = redraw_service
    ref = reference(service, "visual")
    person = profile(service, ref, "visual")
    assert {key: person["defaults"][key] for key in DEFAULTS} == DEFAULTS
    install_receipt(service, control)
    job = completed(service, staged_request(ref))
    assert job["state"] == "complete", job["error"]
    preset = service.profile_operation("preset", person["id"], ProfilePreset(jobId=job["id"]))
    path = service.profiles.path(person["id"])
    saved = path.read_bytes()
    service.close()
    restored = IdentityService(service.config, service.job_runner)
    try:
        defaults = restored.profile_operation("get", person["id"])["defaults"]
        assert defaults == preset["defaults"]
        assert (defaults["visualPolishMode"], defaults["visualPolishPasses"], defaults["visualAnchorStrength"]) == ("reference-anchor", 2, .8)
        assert path.read_bytes() == saved
    finally:
        restored.close()


def test_legacy_visual_profile_exposes_dormant_defaults_without_rewriting_source(visual_service):
    service, _ = visual_service
    person = profile(service, reference(service), "visual")
    path = service.profiles.path(person["id"])
    legacy = read_json(path)
    for key in DEFAULTS:
        legacy["defaults"].pop(key)
    atomic_json(path, legacy)
    saved = path.read_bytes()
    service.close()
    restored = IdentityService(service.config, service.job_runner)
    try:
        defaults = restored.profile_operation("get", person["id"])["defaults"]
        assert {key: defaults[key] for key in DEFAULTS} == DEFAULTS
        assert path.read_bytes() == saved
    finally:
        restored.close()


def test_failed_staged_receipt_cannot_publish_successful_partial_passes(redraw_service):
    service, control = redraw_service
    control.failed = True
    control.damage = lambda metadata: metadata["facePolish"].update(
        passes=[dict(kind="harmonize", denoiseStrength=.35, steps=10, durationMs=1)])
    job = completed(service, staged_request(reference(service)))
    assert job["state"] == "failed" and job["result"] is None


@pytest.mark.parametrize("damage", ["missing", "size", "unregistered", "pending", "missing-job"])
def test_stage_access_fails_closed_after_artifact_or_registration_damage(redraw_service, damage):
    service, control = redraw_service
    install_receipt(service, control)
    job = completed(service, staged_request(reference(service)))
    assert job["state"] == "complete", job["error"]
    stage = service.stage_image(job["id"], "harmonize")
    if damage == "missing": stage.unlink()
    elif damage == "size": Image.new("RGB", (8, 8)).save(stage)
    elif damage == "missing-job": service._job_path(job["id"]).unlink()
    else:
        record = read_json(service._job_path(job["id"]))
        if damage == "pending": record["state"] = "sampling"
        else: record["result"]["metadata"]["facePolish"]["snapshots"] = []
        atomic_json(service._job_path(job["id"]), record)
    with pytest.raises(DreamApiError) as error:
        service.stage_image(job["id"], "harmonize")
    assert error.value.status_code == 404


@pytest.mark.parametrize("missing", ["original", "anchor", "harmonize", "detail"])
@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_artifact_read_endpoints_do_not_depend_on_other_artifact_files(redraw_service, missing, damage):
    service, control = redraw_service
    install_receipt(service, control)
    job = completed(service, staged_request(reference(service)))
    assert job["state"] == "complete", job["error"]
    original = service.original_image(job["id"])
    stages = {kind: service.stage_image(job["id"], kind) for kind in ("anchor", "harmonize", "detail")}
    artifacts = {"original": original, **stages}
    saved = {kind: path.read_bytes() for kind, path in artifacts.items()}
    if damage == "missing":
        artifacts[missing].unlink()
    else:
        artifacts[missing].write_bytes(b"corrupt PNG")
    # Publication/replay validation stays strict even though reads are independent.
    with pytest.raises((ValueError, OSError)):
        service._validate_face_polish(job["id"], job["request"], copy.deepcopy(job["result"]["metadata"]))
    service.close()
    with TestClient(create_app(service.config, DreamRuntime(service.config, job_runner=service.job_runner))) as client:
        for kind in artifacts:
            suffix = "original" if kind == "original" else f"stages/{kind}"
            response = client.get(f"/api/identity/jobs/{job['id']}/{suffix}")
            assert response.status_code == (404 if kind == missing else 200), (missing, kind, response.text)
            if kind != missing:
                assert response.content == saved[kind]


@pytest.mark.parametrize("damage", ["reference", "passes", "snapshot-url", "request"])
def test_independent_reads_still_enforce_metadata_request_binding(redraw_service, damage):
    service, control = redraw_service
    install_receipt(service, control)
    job = completed(service, staged_request(reference(service)))
    assert job["state"] == "complete", job["error"]
    record = read_json(service._job_path(job["id"]))
    polish = record["result"]["metadata"]["facePolish"]
    if damage == "reference": polish["referenceId"] = "ref-" + "f" * 24
    elif damage == "passes": polish["passes"][1]["denoiseStrength"] = .35
    elif damage == "snapshot-url": polish["snapshots"][2]["imageUrl"] = "../../private.png"
    else: record["request"]["visualAnchorStrength"] = .7
    atomic_json(service._job_path(job["id"]), record)
    service.close()
    with TestClient(create_app(service.config, DreamRuntime(service.config, job_runner=service.job_runner))) as client:
        for suffix in ("original", "stages/harmonize"):
            assert client.get(f"/api/identity/jobs/{job['id']}/{suffix}").status_code == 404


def test_stage_route_validates_durable_owned_receipts_and_deletion(redraw_service):
    service, control = redraw_service
    install_receipt(service, control)
    job = completed(service, staged_request(reference(service)))
    assert job["state"] == "complete", job["error"]
    service.close()
    with TestClient(create_app(service.config, DreamRuntime(service.config, job_runner=service.job_runner)), base_url='http://127.0.0.1:8866') as client:
        url = f"/api/identity/jobs/{job['id']}/stages/harmonize"
        assert client.get(url).status_code == 200
        assert client.get(url).headers["content-type"] == "image/png"
        assert client.get(url.replace("harmonize", "unknown")).status_code == 404
        assert client.get(url.replace(job["id"], "identity-" + "f" * 24)).status_code == 404
        durable = read_json(service._job_path(job["id"]))
        changed = copy.deepcopy(durable)
        changed["result"]["metadata"]["facePolish"]["snapshots"] = []
        atomic_json(service._job_path(job["id"]), changed)
        assert client.get(url).status_code == 404
        atomic_json(service._job_path(job["id"]), durable)
        assert client.delete(f"/api/history/{job['id']}").status_code == 200
        assert client.get(url).status_code == 404
        assert not list((service.root / "stages" / job["id"]).glob("*.png"))
