"""Protected v3 receipts and v2 history compatibility; synthetic files, no GPU."""
import copy

import pytest

from errors import DreamApiError
from identity_service import IdentityService
from test_identity_staged_polish_storage import install_receipt, staged_request
from test_identity_visual_polish_storage import completed, redraw_service
from test_identity_visual_service import reference, visual_service


def install_protected_receipt(service, control, *, mode="reference-anchor", passes=2, damage=None):
    def protect(polish, item):
        polish.update(detailerVersion="protected-face-v3", featureProtection="central-features-v1")
        if damage:
            damage(polish, item)
    install_receipt(service, control, mode=mode, passes=passes, damage=protect)


@pytest.mark.parametrize("version", ["staged-face-v2", "protected-face-v3"])
@pytest.mark.parametrize("passes", [1, 2])
@pytest.mark.parametrize("batch", [False, True])
def test_protected_v3_and_legacy_v2_history_roundtrip_without_rewriting(redraw_service, version, passes, batch):
    service, control = redraw_service
    installer = install_receipt if version == "staged-face-v2" else install_protected_receipt
    installer(service, control, passes=passes)
    job = completed(service, staged_request(reference(service), visualPolishPasses=passes), batch)
    assert job["state"] == "complete", job["error"]
    polish = job["result"]["metadata"]["facePolish"]
    assert polish["detailerVersion"] == version
    if version == "protected-face-v3":
        assert polish["featureProtection"] == "central-features-v1"
    else:
        assert "featureProtection" not in polish
    expected_passes = [dict(kind="harmonize", denoiseStrength=.35, steps=10, durationMs=0)]
    if passes == 2:
        expected_passes.append(dict(kind="detail", denoiseStrength=.15, steps=4, durationMs=3))
    assert polish["passes"] == expected_passes
    assert [entry["kind"] for entry in polish["snapshots"]] == ["anchor", "harmonize"] + (["detail"] if passes == 2 else [])
    path = service._job_path(job["id"])
    saved = path.read_bytes()
    original = service.original_image(job["id"]).read_bytes()
    service.close()
    restored = IdentityService(service.config, service.job_runner)
    try:
        assert restored.get(job["id"])["result"] == job["result"]
        assert restored.original_image(job["id"]).read_bytes() == original
        for snapshot in polish["snapshots"]:
            assert restored.stage_image(job["id"], snapshot["kind"]).is_file()
        assert path.read_bytes() == saved
    finally:
        restored.close()


@pytest.mark.parametrize("field,value", [
    ("featureProtection", None), ("featureProtection", "central-features-v2"),
    ("featureProtection", True), ("detailerVersion", "staged-face-v2"),
    ("polishMode", "redraw"), ("polishMode", None),
])
def test_protected_receipt_rejects_mismatched_version_protection_and_mode(redraw_service, field, value):
    service, control = redraw_service
    install_protected_receipt(service, control, damage=lambda polish, item: polish.update({field: value}))
    job = completed(service, staged_request(reference(service)))
    assert job["state"] == "failed" and job["result"] is None


@pytest.mark.parametrize("field", ["featureProtection", "detailerVersion", "polishMode", "passes", "snapshots"])
def test_protected_receipt_requires_all_bound_fields(redraw_service, field):
    service, control = redraw_service
    install_protected_receipt(service, control, damage=lambda polish, item: polish.pop(field))
    job = completed(service, staged_request(reference(service)))
    assert job["state"] == "failed" and job["result"] is None


def test_redraw_cannot_claim_protected_v3_even_with_otherwise_valid_two_pass_receipt(redraw_service):
    service, control = redraw_service
    install_protected_receipt(service, control, mode="redraw")
    job = completed(service, staged_request(reference(service), visualPolishMode="redraw"))
    assert job["state"] == "failed" and job["result"] is None


@pytest.mark.parametrize("damage", ["steps", "strength", "pass-order", "snapshot-order", "missing-file"])
def test_protected_v3_keeps_existing_pass_and_snapshot_validation(redraw_service, damage):
    service, control = redraw_service
    def corrupt(polish, item):
        if damage == "steps": polish["passes"][1]["steps"] = 5
        elif damage == "strength": polish["passes"][1]["denoiseStrength"] = .35
        elif damage == "pass-order": polish["passes"].reverse()
        elif damage == "snapshot-order": polish["snapshots"].reverse()
        else: (service.root / "stages" / item["jobId"] / "detail.png").unlink()
    install_protected_receipt(service, control, damage=corrupt)
    job = completed(service, staged_request(reference(service)))
    assert job["state"] == "failed" and job["result"] is None


def test_protected_v3_read_validation_rejects_missing_protection_but_not_missing_sibling_file(redraw_service):
    service, control = redraw_service
    install_protected_receipt(service, control)
    job = completed(service, staged_request(reference(service)))
    assert job["state"] == "complete", job["error"]
    service.stage_image(job["id"], "detail").unlink()
    assert service.original_image(job["id"]).is_file()
    assert service.stage_image(job["id"], "harmonize").is_file()
    with pytest.raises(DreamApiError) as error:
        service.stage_image(job["id"], "detail")
    assert error.value.status_code == 404
    metadata = copy.deepcopy(job["result"]["metadata"])
    metadata["facePolish"].pop("featureProtection")
    with pytest.raises(ValueError):
        service._validate_face_polish(job["id"], job["request"], metadata, validate_artifacts=False)


@pytest.mark.parametrize("change", [{"modelId": "realistic-vision-v5.1-faceid"}, {"facePolish": False}])
def test_protected_marker_cannot_appear_on_nonvisual_or_disabled_request(visual_service, change):
    service, _ = visual_service
    request = {**staged_request(reference(service)).model_dump(), **change}
    metadata = {"facePolish": dict(enabled=request["facePolish"],
        status="failed" if request["facePolish"] else "disabled", message="controlled failure",
        detailerVersion="protected-face-v3", polishMode="reference-anchor", featureProtection="central-features-v1")}
    with pytest.raises(ValueError):
        service._validate_face_polish("identity-" + "a" * 24, request, metadata, validate_artifacts=False)
