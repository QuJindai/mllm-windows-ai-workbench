"""Kind-aware profile persistence, recovery and binding at the service boundary."""
import threading

import pytest

from errors import DreamApiError
from identity_batches import BatchRequest
from identity_profiles import ProfileCreate, ProfilePreset
from identity_service import IdentityService, atomic_json, read_json
from test_identity_visual_service import (
    FACEID_MODEL, VISUAL_MODEL, assert_no_jobs, generation, persisted_visual_reference,
    reference, visual_service,
)


def profile(service, ref, kind=None):
    fields = {} if kind is None else {"referenceKind": kind}
    initial = service.profile_operation("create", ProfileCreate(name="character", referenceId=ref["id"], faceIndex=0, **fields))
    service._background[initial["id"]][0].result(timeout=5)
    return service.profile_operation("get", initial["id"])


def test_visual_only_reference_cannot_create_default_faceid_profile(visual_service):
    service, boundary = visual_service
    ref = persisted_visual_reference(service)
    with pytest.raises(DreamApiError) as error:
        profile(service, ref)
    assert error.value.code == "IDENTITY_REFERENCE_KIND_CONFLICT"
    assert service.profile_operation("list") == []
    assert not list((service.root / "profiles").glob("person-*.json"))
    assert_no_jobs(service)
    assert [op for op, _ in boundary.calls] == ["inspect"]


@pytest.mark.parametrize("reference_kind", [None, "visual"])
def test_visual_profile_prepares_kind_and_persists_visual_defaults(visual_service, reference_kind):
    service, boundary = visual_service
    ref = reference(service, reference_kind)
    ready = profile(service, ref, "visual")
    assert ready["state"] == "ready", ready["error"]
    assert ready["referenceKind"] == "visual"
    assert ready["featureKey"] == "b" * 64
    assert ready["featureVersion"] == 1
    for field, want in {"modelId": VISUAL_MODEL, "identityStrength": .8, "structureStrength": 0,
                        "faceLoraStrength": 0, "facePolish": False, "width": 768, "height": 768,
                        "steps": 30, "cfg": 5, "animeProfileId": None, "loraId": ""}.items():
        assert ready["defaults"][field] == want
    assert read_json(service.profiles.path(ready["id"])) == ready
    assert [p for op, p in boundary.calls if op == "prepare"][0]["referenceKind"] == "visual"


def test_faceid_profile_keeps_legacy_defaults_and_accepts_versioned_prepare(visual_service):
    service, _ = visual_service
    ready = profile(service, reference(service))
    assert ready["state"] == "ready"
    assert ready["defaults"] == {}
    assert ready.get("referenceKind", "faceid") == "faceid"
    assert ready["featureVersion"] == 3


def test_legacy_worker_prepare_result_remains_accepted(visual_service):
    service, boundary = visual_service
    boundary.prepare_result = {"ok": True, "cacheHit": True, "featureKey": "a" * 64}
    ready = profile(service, reference(service))
    assert ready["state"] == "ready"
    assert ready.get("featureVersion") is None


@pytest.mark.parametrize("changes", [{"referenceKind": "visual"}, {"featureVersion": True},
                                    {"featureVersion": 0}, {"featureVersion": "3"}])
def test_malformed_prepare_metadata_does_not_publish_ready_profile(visual_service, changes):
    service, boundary = visual_service
    boundary.prepare_result = {"ok": True, "cacheHit": False, "featureKey": "a" * 64, **changes}
    failed = profile(service, reference(service))
    assert failed["state"] == "failed"
    assert not failed.get("featureKey")
    assert read_json(service.profiles.path(failed["id"]))["state"] == "failed"


def test_old_profile_load_is_read_only_and_prepare_refreshes_feature_key(visual_service):
    service, boundary = visual_service
    ready = profile(service, reference(service))
    path = service.profiles.path(ready["id"])
    old = {k: v for k, v in ready.items() if k not in {"referenceKind", "featureVersion"}}
    old["featureKey"] = "c" * 64
    old["defaults"] = {"prompt": "saved portrait", "identityStrength": .73}
    atomic_json(path, old)
    original = path.read_bytes()
    service.close()
    restored = IdentityService(service.config, service.job_runner)
    try:
        recovered = restored.profile_operation("get", ready["id"])
        assert recovered["featureKey"] == "c" * 64
        assert recovered["defaults"]["prompt"] == "saved portrait"
        assert recovered["defaults"]["identityStrength"] == .73
        assert recovered["defaults"]["facePolish"] is False
        assert path.read_bytes() == original
        assert len([op for op, _ in boundary.calls if op == "prepare"]) == 1
        restored.profiles._prepare(ready["id"], threading.Event())
        updated = restored.profile_operation("get", ready["id"])
        assert updated["featureKey"] == "a" * 64 and updated["featureVersion"] == 3
        assert updated["defaults"] == recovered["defaults"]
    finally:
        restored.close()


def test_visual_profile_with_partial_defaults_recovers_without_worker(visual_service):
    service, boundary = visual_service
    ready = profile(service, reference(service), "visual")
    path = service.profiles.path(ready["id"])
    original = path.read_bytes()
    before = len(boundary.calls)
    service.close()
    restored = IdentityService(service.config, service.job_runner)
    try:
        assert restored.profile_operation("get", ready["id"]) == ready
        assert path.read_bytes() == original
        assert len(boundary.calls) == before
    finally:
        restored.close()


@pytest.mark.parametrize("profile_kind,model", [("visual", FACEID_MODEL), ("faceid", VISUAL_MODEL)])
def test_batch_profile_kind_must_match_model_before_any_child_is_saved(visual_service, profile_kind, model):
    service, _ = visual_service
    ref = reference(service)
    ready = profile(service, ref, profile_kind)
    assert ready["state"] == "ready"
    previous_background = set(service._background)
    with pytest.raises(DreamApiError) as error:
        service.batch_operation("submit", BatchRequest(profileId=ready["id"], request=generation(ref, model), count=1))
    assert error.value.code == "IDENTITY_PROFILE_CONFLICT"
    assert service.jobs() == [] and service.batch_operation("list") == []
    assert set(service._background) == previous_background
    assert not list((service.root / "jobs").glob("identity-*.json"))


@pytest.mark.parametrize("profile_kind,model", [("visual", FACEID_MODEL), ("faceid", VISUAL_MODEL)])
def test_preset_cannot_switch_profile_kind_even_with_same_reference_face(visual_service, profile_kind, model):
    service, _ = visual_service
    ref = reference(service)
    ready = profile(service, ref, profile_kind)
    path = service.profiles.path(ready["id"])
    original = path.read_bytes()
    job = service.submit(generation(ref, model))
    service._futures[job["id"]].result(timeout=5)
    assert service.get(job["id"])["state"] == "complete"
    with pytest.raises(DreamApiError) as error:
        service.profile_operation("preset", ready["id"], ProfilePreset(jobId=job["id"]))
    assert error.value.code == "IDENTITY_PRESET_CONFLICT"
    assert path.read_bytes() == original
