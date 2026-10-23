"""A visual profile must never supply the real identity for a hybrid archive."""
import copy
import hashlib
from pathlib import Path

import pytest
from PIL import Image

from errors import DreamApiError
from identity_anime_profiles import AnimeProfileCreate, AnimeProfileImport
from identity_batches import BatchRequest
from identity_service import atomic_json
from test_identity_api import image_base64
from test_identity_visual_profiles import profile
from test_identity_visual_service import generation, reference, visual_service


XL = "illustrious-xl-v2.0-faceid"


@pytest.fixture
def hybrid_service(visual_service, monkeypatch):
    service, boundary = visual_service
    original = boundary.run

    def inference(operation, payload, cancelled=None):
        if operation != "anime_prepare":
            return original(operation, payload, cancelled)
        boundary.calls.append((operation, copy.deepcopy(payload)))
        # Only tensor extraction is replaced; persistence and hash checks are real.
        features = Path(payload["animeFeaturesPath"])
        features.write_bytes(b"controlled-hybrid-features")
        return {"ok": True, "featureKey": hashlib.sha256(features.read_bytes()).hexdigest(),
                "parentFeatureKey": "a" * 64, "faceBox": [1., 1., 5., 6.]}

    monkeypatch.setattr(boundary, "run", inference)
    return service, boundary


def archive_request(service, ref, parent, operation):
    if operation == "import_image":
        return AnimeProfileImport(name="hybrid", profileId=parent["id"], sourceName="art.png",
                                  imageBase64=image_base64())
    job = service.submit(generation(ref, XL))
    service._futures[job["id"]].result(timeout=5)
    assert service.get(job["id"])["state"] == "complete"
    return AnimeProfileCreate(name="hybrid", profileId=parent["id"], jobId=job["id"])


@pytest.mark.parametrize("operation", ["import_image", "create"])
def test_visual_parent_rejected_before_hybrid_archive_is_saved_or_enqueued(hybrid_service, operation):
    service, boundary = hybrid_service
    ref = reference(service)  # Reusing a FaceID reference must not bypass the profile guard.
    parent = profile(service, ref, "visual")
    assert parent["state"] == "ready"
    request = archive_request(service, ref, parent, operation)
    queued = set(service._background)
    calls = copy.deepcopy(boundary.calls)
    jobs = service.jobs()
    parent_path = service.profiles.path(parent["id"])
    parent_bytes = parent_path.read_bytes()

    with pytest.raises(DreamApiError) as error:
        service.anime_profile_operation(operation, request)

    assert error.value.code == "ANIME_SOURCE_CONFLICT"
    assert error.value.status_code == 409
    assert service.anime_profile_operation("list") == []
    assert not list((service.root / "anime-profiles").glob("*"))
    assert set(service._background) == queued
    assert service.jobs() == jobs
    assert boundary.calls == calls
    assert parent_path.read_bytes() == parent_bytes


def seed_previously_accepted_hybrid(service, parent):
    """A valid on-disk archive accepted before the missing parent-kind guard."""
    library = service.anime_profiles
    identifier = "anime-" + "c" * 24
    image = library.path(identifier, ".png")
    image.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (12, 8)).save(image)
    features = library.path(identifier, ".safetensors")
    features.write_bytes(b"legacy-hybrid-features")
    return library.save({"id": identifier, "name": "old hybrid", "profileId": parent["id"],
                         "referenceId": parent["referenceId"], "faceIndex": parent["faceIndex"],
                         "sourceKind": "upload", "sourceName": "art.png", "sourceLabel": "external",
                         "sourceImageSha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                         "state": "ready", "featureKey": hashlib.sha256(features.read_bytes()).hexdigest(),
                         "parentFeatureKey": parent["featureKey"], "faceBox": [1., 1., 5., 6.],
                         "createdAt": "2026-10-11T12:00:00+08:00"})


@pytest.mark.parametrize("operation", ["resolve", "submit", "batch"])
def test_old_hybrid_with_visual_parent_cannot_bind_or_enqueue_faceid_generation(hybrid_service, operation):
    service, boundary = hybrid_service
    ref = reference(service)
    parent = profile(service, ref, "visual")
    archive = seed_previously_accepted_hybrid(service, parent)
    request = generation(ref, XL, facePolish=True, animeProfileId=archive["id"])
    queued = set(service._background)
    calls = copy.deepcopy(boundary.calls)
    files = {path.name: path.read_bytes() for path in (service.root / "anime-profiles").iterdir()}

    with pytest.raises(DreamApiError) as error:
        if operation == "resolve":
            service.anime_profiles.resolve_request(request.model_dump())
        elif operation == "submit":
            service.submit(request)
        else:
            service.batch_operation("submit", BatchRequest(request=request, count=1))

    assert error.value.code == "ANIME_PROFILE_CONFLICT"
    assert error.value.status_code == 409
    assert service.jobs() == [] and service.batch_operation("list") == []
    assert not service._futures
    assert not list((service.root / "jobs").glob("identity-*.json"))
    assert not list((service.root / "batches").glob("batch-*.json"))
    assert set(service._background) == queued
    assert boundary.calls == calls
    assert {path.name: path.read_bytes() for path in (service.root / "anime-profiles").iterdir()} == files


@pytest.mark.parametrize("operation", ["import_image", "create"])
@pytest.mark.parametrize("kind", [None, "faceid"])
def test_legacy_and_explicit_faceid_parents_still_prepare_and_bind_hybrid(hybrid_service, operation, kind):
    service, _ = hybrid_service
    ref = reference(service)
    parent = profile(service, ref, "faceid")
    if kind is None:
        # Model a saved pre-kind profile, without changing any production fixture.
        parent.pop("referenceKind")
        atomic_json(service.profiles.path(parent["id"]), parent)
        service.profiles.records[parent["id"]] = copy.deepcopy(parent)
    parent_path = service.profiles.path(parent["id"])
    parent_bytes = parent_path.read_bytes()
    initial = service.anime_profile_operation(operation, archive_request(service, ref, parent, operation))
    service._background[initial["id"]][0].result(timeout=5)
    archive = service.anime_profile_operation("get", initial["id"])
    assert archive["state"] == "ready", archive["error"]
    binding = service.anime_profiles.resolve_request(generation(
        ref, XL, facePolish=True, animeProfileId=archive["id"]).model_dump())
    assert binding["animeProfile"]["profileId"] == parent["id"]
    assert binding["animeProfile"]["referenceId"] == ref["id"]
    assert Path(binding["animeFeaturesPath"]).read_bytes() == b"controlled-hybrid-features"
    assert parent_path.read_bytes() == parent_bytes
