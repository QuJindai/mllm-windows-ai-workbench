"""Backend storage contract tests; inference stays behind controlled boundaries."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import create_app
from identity_contract import IdentityGenerateRequest
from identity_service import IdentityService
from runtime import DreamRuntime
from test_identity_api import harness, upload, submit, finished
from test_identity_profiles import profile_harness, create_profile, wait_profile
from test_identity_batches import (
    batch_harness, batch_request, submit_batch, wait_batch,
    crash_before_completion_consumed,
)


def original_path(config, job_id):
    return config.dream_root / "data" / "identity" / "originals" / f"{job_id}.png"


def save_original(config, item):
    path = original_path(config, item["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (item["request"]["width"], item["request"]["height"]), "red").save(path)
    return path


def polish_metadata(job_id, status="completed"):
    return {"enabled": True, "status": status,
            "originalImageUrl": f"/api/identity/jobs/{job_id}/original",
            "restoreStrength": .7,
            **({"message": "受控修复失败，保留基础图片"} if status == "failed" else {})}


def install_polish_worker(monkeypatch, config, *, status="completed", damage=None):
    worker = IdentityService._worker

    def generate(service, operation, payload, cancelled=None):
        if operation != "generate":
            return worker(service, operation, payload, cancelled)
        Image.new("RGB", (payload["width"], payload["height"]), "navy").save(payload["outputPath"])
        original = save_original(config, {"id": payload["jobId"], "request": payload})
        metadata = polish_metadata(payload["jobId"], status)
        if damage == "missing":
            original.unlink()
        elif damage == "broken":
            original.write_bytes(b"incomplete PNG")
        elif damage == "dimensions":
            Image.new("RGB", (8, 8)).save(original)
        elif damage == "url":
            metadata["originalImageUrl"] = "/api/identity/jobs/identity-" + "f" * 24 + "/original"
        Path(payload["metadataPath"]).write_text(json.dumps({"facePolish": metadata}), encoding="utf-8")
        return {"ok": True}

    monkeypatch.setattr(IdentityService, "_worker", generate)


def test_defaults_are_off_in_legacy_generate_and_batch_even_with_example(batch_harness):
    client, _, _, boundary = batch_harness
    reference = upload(client)
    job = finished(client, submit(client, reference, loraId="Example")["id"])
    assert job["request"]["facePolish"] is False
    assert job["request"]["faceRestoreStrength"] == 1.0
    assert job["result"]["metadata"]["facePolish"] == {"enabled": False, "status": "disabled"}
    request = batch_request(reference)
    request["request"]["loraId"] = "Example"
    result = wait_batch(client, submit_batch(client, request)["id"])
    assert result["state"] == "complete"
    assert all(item["facePolish"] is False and item["faceRestoreStrength"] == 1.0 for item in boundary.calls[-1]["items"])
    assert all(item["result"]["metadata"]["facePolish"]["status"] == "disabled" for item in result["items"])


@pytest.mark.parametrize("changes", [
    {"facePolish": 1}, {"facePolish": "true"}, {"facePolish": None},
    {"faceRestoreStrength": True}, {"faceRestoreStrength": "0.5"},
    {"faceRestoreStrength": None}, {"faceRestoreStrength": -0.01},
    {"faceRestoreStrength": 1.01}, {"faceRestoreStrength": float("nan")},
    {"faceRestoreStrength": float("inf")}, {"faceRestoreStrength": float("-inf")},
    {"originalPath": "C:/private.png"},
])
@pytest.mark.parametrize("endpoint", ["generate", "batches"])
def test_polish_contract_rejects_invalid_json_without_echo_or_enqueue(batch_harness, changes, endpoint):
    client, _, _, boundary = batch_harness
    request = batch_request(upload(client))
    request["request"].update(changes)
    body = request if endpoint == "batches" else request["request"]
    response = client.post(f"/api/identity/{endpoint}", content=json.dumps(body), headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"
    assert "NaN" not in response.text and "Infinity" not in response.text and "C:/private" not in response.text
    assert client.get("/api/identity/jobs").json() == []
    assert not boundary.calls


@pytest.mark.parametrize("strength", [0.0, .7, 1.0])
def test_contract_accepts_explicit_polish_and_finite_strength(strength):
    request = IdentityGenerateRequest(referenceId="ref-" + "a" * 24, faceIndex=0, prompt="portrait", facePolish=True, faceRestoreStrength=strength)
    assert request.model_dump()["facePolish"] is True
    assert request.faceRestoreStrength == strength


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_original_and_truthful_result_survive_completion_cancel_and_restart(harness, monkeypatch, status):
    client, config, runner, _ = harness
    install_polish_worker(monkeypatch, config, status=status)
    job = finished(client, submit(client, upload(client), facePolish=True, faceRestoreStrength=.7)["id"])
    assert job["state"] == "complete", job
    assert job["result"]["metadata"]["facePolish"] == polish_metadata(job["id"], status)
    url = f"/api/identity/jobs/{job['id']}/original"
    raw = original_path(config, job["id"]).read_bytes()
    assert client.get(url).content == raw
    assert client.get(job["result"]["imageUrl"]).status_code == 200
    assert client.post(f"/api/identity/jobs/{job['id']}/cancel").json() == job
    client.__exit__(None, None, None)
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as restored:
        assert restored.get(url).status_code == 200
        assert restored.get(url).content == raw
        assert restored.get(f"/api/identity/jobs/{job['id']}").json()["result"] == job["result"]
        assert original_path(config, job["id"]).read_bytes() == raw


@pytest.mark.parametrize("damage", ["missing", "broken", "dimensions", "url"])
def test_invalid_original_cannot_claim_durable_polished_completion(harness, monkeypatch, damage):
    client, config, _, _ = harness
    install_polish_worker(monkeypatch, config, damage=damage)
    job = finished(client, submit(client, upload(client), facePolish=True, faceRestoreStrength=.7)["id"])
    assert job["state"] == "failed", job
    assert job["result"] is None
    assert not original_path(config, job["id"]).exists()
    assert client.get("/api/history").json()["total"] == 0


@pytest.mark.parametrize("state", ["sampling", "failed", "cancelled"])
def test_restart_cleans_only_exact_uncompleted_original(harness, state):
    client, config, runner, _ = harness
    reference = upload(client)
    job = finished(client, submit(client, reference)["id"])
    client.__exit__(None, None, None)
    root = config.dream_root / "data" / "identity"
    job.update(state=state, result=None)
    (root / "jobs" / f"{job['id']}.json").write_text(json.dumps(job), encoding="utf-8")
    own = save_original(config, job)
    neighbor = own.with_name("identity-" + "f" * 24 + ".png")
    neighbor.write_bytes(b"unrelated")
    sidecar = own.with_suffix(".json")
    sidecar.write_bytes(b"not-owned")
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as restored:
        assert restored.get(f"/api/identity/jobs/{job['id']}").json()["state"] in {"failed", "cancelled"}
        assert not own.exists()
        assert neighbor.read_bytes() == b"unrelated"
        assert sidecar.read_bytes() == b"not-owned"


@pytest.mark.parametrize("omitted", ["all", "batch", "child", "items"])
def test_old_batch_requests_normalize_before_membership_and_replay(batch_harness, omitted):
    _, config, runner, _ = batch_harness
    batch, payload, image, root = crash_before_completion_consumed(batch_harness)
    records = [root / "batches" / f"{batch['id']}.json", *(root / "jobs" / f"{item['id']}.json" for item in batch["items"])]
    for path in records:
        record = json.loads(path.read_text(encoding="utf-8"))
        requests = []
        if path.parent.name == "batches":
            if omitted in {"all", "batch"}:
                requests.append(record["request"]["request"])
            if omitted in {"all", "items"}:
                requests.extend(item["request"] for item in record["items"])
        elif omitted in {"all", "child"}:
            requests.append(record["request"])
        for request in requests:
            request.pop("facePolish", None)
            request.pop("faceRestoreStrength", None)
        path.write_text(json.dumps(record), encoding="utf-8")
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as restored:
        result = restored.get(f"/api/identity/batches/{batch['id']}")
        assert result.status_code == 200, result.text
        record = result.json()
        assert [item["state"] for item in record["items"]] == ["complete", "failed"]
        assert restored.get(record["items"][0]["result"]["imageUrl"]).content == image
        for item in record["items"]:
            assert item["request"]["facePolish"] is False
            assert item["request"]["faceRestoreStrength"] == 1.0


@pytest.mark.parametrize("stage", ["身份回贴", "面部细节修复"])
def test_post_stage_reports_no_eta_or_fake_completion(batch_harness, stage):
    client, _, _, boundary = batch_harness
    boundary.hold = True

    def events(payload):
        for step in (1, 10):
            boundary.emit(payload, {"type": "step", "itemIndex": 0, "step": step, "totalSteps": 10, "elapsedMs": step})
        boundary.emit(payload, {"type": "stage", "stage": stage, "itemIndex": 0, "elapsedMs": 11})

    boundary.custom_events = events
    batch = submit_batch(client, batch_request(upload(client), count=1))
    record = wait_batch(client, batch["id"], lambda value: value["stage"] == stage)
    assert record["progress"] < 100 and record["items"][0]["progress"] < 100
    assert record["etaMs"] is None
    assert record["items"][0]["message"] == stage
    assert record["items"][0]["result"] is None
    client.post(f"/api/identity/batches/{batch['id']}/cancel")


def test_profile_preset_recovers_old_defaults_and_propagates_explicit_polish(profile_harness, monkeypatch):
    client, config, runner, _ = profile_harness
    reference = upload(client)
    profile = wait_profile(client, create_profile(client, reference)["id"])
    install_polish_worker(monkeypatch, config)
    job = finished(client, submit(client, reference, facePolish=True, faceRestoreStrength=.7)["id"])
    preset = client.post(f"/api/identity/profiles/{profile['id']}/preset", json={"jobId": job["id"]}).json()
    assert preset["defaults"]["facePolish"] is True
    assert preset["defaults"]["faceRestoreStrength"] == .7
    client.__exit__(None, None, None)
    path = config.dream_root / "data" / "identity" / "profiles" / f"{profile['id']}.json"
    preset["defaults"].pop("facePolish")
    preset["defaults"].pop("faceRestoreStrength")
    path.write_text(json.dumps(preset), encoding="utf-8")
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as restored:
        defaults = restored.get(f"/api/identity/profiles/{profile['id']}").json()["defaults"]
        assert defaults["facePolish"] is False
        assert defaults["faceRestoreStrength"] == 1.0


def crash_polish_batch(batch_harness):
    _, config, _, _ = batch_harness
    batch, payload, image, root = crash_before_completion_consumed(batch_harness)
    batch["request"]["request"].update(facePolish=True, faceRestoreStrength=.7)
    for item in batch["items"]:
        item["request"].update(facePolish=True, faceRestoreStrength=.7)
        (root / "jobs" / f"{item['id']}.json").write_text(json.dumps(item), encoding="utf-8")
        save_original(config, item)
    (root / "batches" / f"{batch['id']}.json").write_text(json.dumps(batch), encoding="utf-8")
    path = Path(payload["items"][0]["metadataPath"])
    metadata = json.loads(path.read_text(encoding="utf-8"))
    metadata["facePolish"] = polish_metadata(batch["items"][0]["id"])
    path.write_text(json.dumps(metadata), encoding="utf-8")
    return batch, payload, image, root


def test_batch_replay_keeps_completed_original_and_cleans_uncompleted_original(batch_harness):
    _, config, runner, _ = batch_harness
    batch, _, image, _ = crash_polish_batch(batch_harness)
    first, second = batch["items"]
    raw = original_path(config, first["id"]).read_bytes()
    for _ in range(2):
        with TestClient(create_app(config, DreamRuntime(config, job_runner=runner)), base_url="http://127.0.0.1") as restored:
            record = restored.get(f"/api/identity/batches/{batch['id']}").json()
            assert [item["state"] for item in record["items"]] == ["complete", "failed"]
            assert restored.get(f"/api/identity/jobs/{first['id']}/original").content == raw
            assert restored.get(record["items"][0]["result"]["imageUrl"]).content == image
            assert not original_path(config, second["id"]).exists()
            assert restored.post(f"/api/identity/batches/{batch['id']}/cancel").json() == record


@pytest.mark.parametrize("point", ["metadata", "job"])
def test_pending_completion_retains_original_but_never_publishes_100_or_original_url(batch_harness, monkeypatch, point):
    import identity_batches
    import identity_service

    _, config, runner, _ = batch_harness
    batch, payload, _, root = crash_polish_batch(batch_harness)
    first = batch["items"][0]
    target = Path(payload["items"][0]["metadataPath"]) if point == "metadata" else root / "jobs" / f"{first['id']}.json"
    module = identity_batches if point == "metadata" else identity_service
    write = module.atomic_json

    def full_disk(path, value):
        if path == target:
            raise OSError("controlled completion write failure")
        return write(path, value)

    with monkeypatch.context() as disk:
        disk.setattr(module, "atomic_json", full_disk)
        with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as restored:
            record = restored.get(f"/api/identity/batches/{batch['id']}").json()
            assert record["items"][0]["progress"] < 100
            assert record["progress"] < 100
            assert original_path(config, first["id"]).exists()
            assert restored.get(f"/api/identity/jobs/{first['id']}/original").status_code == 404
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as restored:
        record = restored.get(f"/api/identity/batches/{batch['id']}").json()
        assert record["items"][0]["progress"] == 100
        assert restored.get(f"/api/identity/jobs/{first['id']}/original").status_code == 200


@pytest.mark.parametrize("damage", ["missing", "broken"])
def test_batch_replay_rejects_incomplete_original(batch_harness, damage):
    _, config, runner, _ = batch_harness
    batch, _, _, _ = crash_polish_batch(batch_harness)
    path = original_path(config, batch["items"][0]["id"])
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"unfinished")
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as restored:
        record = restored.get(f"/api/identity/batches/{batch['id']}").json()
        assert record["completedItems"] == 0
        assert restored.get("/api/history").json()["total"] == 0
        assert all(not original_path(config, item["id"]).exists() for item in batch["items"])


@pytest.mark.parametrize("damage", ["unregistered", "disabled", "missing-result", "bad-metadata", "wrong-metadata-id", "bad-enabled", "bad-strength", "bad-status", "wrong-url"])
def test_original_requires_registered_valid_completed_result(harness, monkeypatch, damage):
    client, config, runner, _ = harness
    install_polish_worker(monkeypatch, config)
    job = finished(client, submit(client, upload(client), facePolish=True, faceRestoreStrength=.7)["id"])
    raw = original_path(config, job["id"]).read_bytes()
    client.__exit__(None, None, None)
    path = config.dream_root / "data" / "identity" / "jobs" / f"{job['id']}.json"
    metadata = job["result"]["metadata"]
    if damage == "unregistered":
        path.unlink()
    else:
        if damage == "disabled":
            metadata["facePolish"] = {"enabled": False, "status": "disabled"}
        elif damage == "missing-result":
            job["result"] = None
        elif damage == "bad-metadata":
            job["result"]["metadata"] = []
        elif damage == "wrong-metadata-id":
            metadata["id"] = "identity-" + "f" * 24
        elif damage == "bad-enabled":
            metadata["facePolish"]["enabled"] = "true"
        elif damage == "bad-strength":
            metadata["facePolish"]["restoreStrength"] = float("nan")
        elif damage == "bad-status":
            metadata["facePolish"]["status"] = "disabled"
        else:
            metadata["facePolish"]["originalImageUrl"] = "file:///private.png"
        path.write_text(json.dumps(job), encoding="utf-8")
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as restored:
        response = restored.get(f"/api/identity/jobs/{job['id']}/original")
        assert response.status_code == 404
        assert raw not in response.content and str(config.dream_root) not in response.text
        assert original_path(config, job["id"]).read_bytes() == raw


@pytest.mark.parametrize("job_id", ["..%2Fsecret", "..%5Csecret", "identity-x", "identity-" + "f" * 24 + ".png", "identity-" + "f" * 24 + "%3Asecret"])
def test_original_route_rejects_traversal_and_unsafe_ids(harness, job_id):
    client, _, _, _ = harness
    assert client.get(f"/api/identity/jobs/{job_id}/original").status_code in {404, 422}


@pytest.mark.parametrize("inside", [False, True])
def test_original_links_cannot_serve_or_delete_another_path(harness, monkeypatch, tmp_path, inside):
    client, config, runner, _ = harness
    install_polish_worker(monkeypatch, config)
    job = finished(client, submit(client, upload(client), facePolish=True, faceRestoreStrength=.7)["id"])
    path = original_path(config, job["id"])
    other = (config.dream_root if inside else tmp_path) / "private.png"
    other.write_bytes(path.read_bytes())
    path.unlink()
    try:
        path.symlink_to(other)
    except OSError as exc:
        pytest.skip(f"Symlinks unavailable: {exc}")
    assert client.get(f"/api/identity/jobs/{job['id']}/original").status_code == 404
    client.__exit__(None, None, None)
    job.update(state="sampling", result=None)
    job_path = config.dream_root / "data" / "identity" / "jobs" / f"{job['id']}.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    raw = other.read_bytes()
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as restored:
        assert restored.get(f"/api/identity/jobs/{job['id']}").json()["state"] == "failed"
        assert other.read_bytes() == raw


@pytest.mark.parametrize("outcome", ["cancel", "failure"])
def test_running_legacy_job_cleans_its_original_after_child_exit(harness, outcome):
    client, config, _, boundary = harness
    reference = upload(client)
    boundary.hold = "generate"
    job = submit(client, reference, facePolish=True)
    assert boundary.started.wait(2)
    path = save_original(config, job)
    assert client.get(f"/api/identity/jobs/{job['id']}/original").status_code == 404
    if outcome == "cancel":
        result = client.post(f"/api/identity/jobs/{job['id']}/cancel").json()
        assert result["state"] == "cancelled"
    else:
        boundary.fail = "generate"
        boundary.release.set()
        assert finished(client, job["id"])["state"] == "failed"
    assert boundary.children[-1].poll() is not None
    assert not path.exists()


def test_queued_cancel_cleans_only_its_original(harness):
    import threading

    client, config, runner, _ = harness
    reference = upload(client)
    release = threading.Event()
    blocker = runner.submit_serial(lambda: release.wait(5))
    try:
        job = submit(client, reference, facePolish=True)
        path = save_original(config, job)
        assert client.post(f"/api/identity/jobs/{job['id']}/cancel").json()["state"] == "cancelled"
        assert not path.exists()
    finally:
        release.set()
        blocker.result(timeout=5)


@pytest.mark.parametrize("ready", [False, True])
def test_status_passes_optional_worker_availability_without_changing_base_readiness(harness, monkeypatch, ready):
    client, _, _, _ = harness
    worker = IdentityService._worker

    def status(service, operation, payload, cancelled=None):
        result = worker(service, operation, payload, cancelled)
        if operation == "status":
            result["facePolish"] = {"ready": ready, "message": "可选修复资源检查"}
        return result

    monkeypatch.setattr(IdentityService, "_worker", status)
    result = client.get("/api/identity/status").json()
    assert result["ready"] is True
    assert result["facePolish"] == {"ready": ready, "message": "可选修复资源检查"}


def test_polish_failure_before_original_save_still_keeps_valid_base(harness, monkeypatch):
    client, config, _, _ = harness
    install_polish_worker(monkeypatch, config, status="failed")
    worker = IdentityService._worker

    def failed_original(service, operation, payload, cancelled=None):
        result = worker(service, operation, payload, cancelled)
        if operation == "generate":
            original_path(config, payload["jobId"]).unlink()
            path = Path(payload["metadataPath"])
            value = json.loads(path.read_text(encoding="utf-8"))
            value["facePolish"].pop("originalImageUrl")
            path.write_text(json.dumps(value), encoding="utf-8")
        return result

    monkeypatch.setattr(IdentityService, "_worker", failed_original)
    job = finished(client, submit(client, upload(client), facePolish=True, faceRestoreStrength=.7)["id"])
    assert job["state"] == "complete"
    assert job["result"]["metadata"]["facePolish"]["status"] == "failed"
    assert client.get(job["result"]["imageUrl"]).status_code == 200
    assert client.get(f"/api/identity/jobs/{job['id']}/original").status_code == 404


@pytest.mark.parametrize("outcome", ["cancel", "failure"])
def test_batch_terminal_cleanup_keeps_only_durably_completed_originals(batch_harness, monkeypatch, outcome):
    client, config, _, boundary = batch_harness
    boundary.hold = True

    def complete_item(payload, index):
        item = payload["items"][index]
        assert item["facePolish"] is True and item["faceRestoreStrength"] == .7
        save_original(config, {"id": item["jobId"], "request": item})
        Image.new("RGB", (item["width"], item["height"]), "navy").save(item["outputPath"])
        Path(item["metadataPath"]).write_text(json.dumps({"facePolish": polish_metadata(item["jobId"])}), encoding="utf-8")
        boundary.emit(payload, {"type": "item_complete", "itemIndex": index, "jobId": item["jobId"], "elapsedMs": 100 * (index + 1)})

    monkeypatch.setattr(boundary, "complete_item", complete_item)
    request = batch_request(upload(client))
    request["request"].update(facePolish=True, faceRestoreStrength=.7)
    batch = submit_batch(client, request)
    record = wait_batch(client, batch["id"], lambda item: item["step"] == 5)
    first, second = record["items"]
    second_original = save_original(config, second)
    raw = original_path(config, first["id"]).read_bytes()
    if outcome == "cancel":
        record = client.post(f"/api/identity/batches/{batch['id']}/cancel").json()
        assert record["state"] == "cancelled"
    else:
        boundary.fail = True
        boundary.release.set()
        record = wait_batch(client, batch["id"])
        assert record["state"] == "failed"
    assert record["completedItems"] == 1
    assert client.get(f"/api/identity/jobs/{first['id']}/original").content == raw
    assert not second_original.exists()


def test_original_uses_registered_metadata_not_arbitrary_output_json(harness):
    client, config, _, boundary = harness
    job = finished(client, submit(client, upload(client))["id"])
    save_original(config, job)
    payload = next(call[2] for call in boundary.calls if call[1] == "generate")
    Path(payload["metadataPath"]).write_text(json.dumps({"facePolish": polish_metadata(job["id"])}), encoding="utf-8")
    assert client.get(f"/api/identity/jobs/{job['id']}/original").status_code == 404


@pytest.mark.parametrize("succeeds", [True, False], ids=["success", "failure"])
def test_actual_optional_face_polish_metadata_passes_storage_validation(harness, succeeds):
    from identity_face_polish import FacePolisher, optional_face_polish

    _, config, runner, _ = harness
    request = IdentityGenerateRequest(referenceId="ref-" + "a" * 24, faceIndex=0,
                                      prompt="portrait", width=256, height=256,
                                      facePolish=True, faceRestoreStrength=.7)
    job_id = "identity-" + "a" * 24
    image = Image.new("RGB", (256, 256), "navy")
    # Exercise the real metadata producer; only costly inference is substituted.
    class Processor(FacePolisher):
        def __init__(self):
            self.hashes = {"faceSwapModel": "a" * 64, "faceRestoreModel": "b" * 64}

        def apply(self, image, item, strength, stage):
            if not succeeds:
                raise ValueError("受控修复失败")
            return image.copy(), self.details()

    output, info = optional_face_polish(image, request,
                                       {"jobId": job_id, "dreamRoot": str(config.dream_root)},
                                       Processor, lambda stage: None)
    assert info["status"] == ("completed" if succeeds else "failed")
    assert type(info["durationMs"]) is int and info["durationMs"] >= 0
    if succeeds:
        assert info["swapModel"] == "inswapper_128.onnx"
        assert info["restoreModel"] == "GFPGANv1.4.pth"
        assert info["swapDevice"] == "CPU" and info["restoreDevice"] == "CUDA FP32"
        assert info["assetHashes"] == {"faceSwapModel": "a" * 64, "faceRestoreModel": "b" * 64}
    else:
        assert output is image and info["message"]
    metadata = {"facePolish": info}
    service = IdentityService(config, runner)
    try:
        service._validate_face_polish(job_id, request.model_dump(), metadata)
        assert metadata["facePolish"] == info
    finally:
        service.close()


@pytest.mark.parametrize("invalid", [
    {"durationMs": -1}, {"durationMs": True}, {"durationMs": "10"}, {"durationMs": 1.5},
    {"swapModel": 1}, {"restoreModel": []}, {"swapDevice": False}, {"restoreDevice": {}},
    {"assetHashes": {"faceSwapModel": "not-hex"}}, {"assetHashes": {"faceSwapModel": 123}},
    {"assetHashes": {1: "abc"}}, {"assetHashes": {"faceSwapModel": ""}},
    {"unknownEngineField": "must remain forbidden"},
])
def test_engine_metadata_fields_remain_strict(invalid):
    from identity_service import FacePolishMetadata

    with pytest.raises(ValueError):
        FacePolishMetadata.model_validate({"enabled": True, "status": "completed", **invalid})


@pytest.mark.parametrize("outcome", ["failure", "cancel"])
@pytest.mark.parametrize("locked", ["original", "image", "metadata", "all"])
def test_cleanup_permission_error_still_persists_terminal_job(harness, monkeypatch, outcome, locked):
    client, config, runner, boundary = harness
    reference = upload(client)
    boundary.hold = "generate"
    job = submit(client, reference, facePolish=True)
    assert boundary.started.wait(2)
    payload = next(call[2] for call in boundary.calls if call[1] == "generate")
    paths = {"original": save_original(config, job), "image": Path(payload["outputPath"]),
             "metadata": Path(payload["metadataPath"])}
    for key in ("image", "metadata"):
        paths[key].write_bytes(b"partial output")
    protected = set(paths.values()) if locked == "all" else {paths[locked]}
    unlink = Path.unlink

    def locked_unlink(path, *args, **kwargs):
        if path in protected:
            raise PermissionError("controlled file remains locked")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked_unlink)
    if outcome == "failure":
        boundary.fail = "generate"
        boundary.release.set()
    else:
        try:
            client.post(f"/api/identity/jobs/{job['id']}/cancel")
        except PermissionError:
            pass  # RED must expose the stranded job, not stop at the API exception.
    runner.submit_serial(lambda: None).result(timeout=5)
    result = client.get(f"/api/identity/jobs/{job['id']}").json()
    expected = "failed" if outcome == "failure" else "cancelled"
    assert result["state"] == expected, result
    assert result["result"] is None and result["progress"] == 0
    assert "清理" in result["error"] and "权限" in result["error"]
    if outcome == "failure":
        assert "controlled worker failure" in result["error"]
    durable = config.dream_root / "data" / "identity" / "jobs" / f"{job['id']}.json"
    assert json.loads(durable.read_text(encoding="utf-8")) == result
    assert boundary.children[-1].poll() is not None
    for path in paths.values():
        assert path.exists() == (path in protected)
    assert client.get(f"/api/identity/jobs/{job['id']}/original").status_code == 404


@pytest.mark.parametrize("operation", ["cancel", "close"])
def test_pending_job_cleanup_permission_error_does_not_prevent_terminal_save(harness, monkeypatch, operation):
    client, config, runner, boundary = harness
    reference = upload(client)
    boundary.hold = "generate"
    running = submit(client, reference)
    assert boundary.started.wait(2)
    queued = submit(client, reference, facePolish=True)
    original = save_original(config, queued)
    unlink = Path.unlink

    def locked_unlink(path, *args, **kwargs):
        if path == original:
            raise PermissionError("controlled pending original lock")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked_unlink)
    if operation == "close":
        client.__exit__(None, None, None)
    else:
        try:
            client.post(f"/api/identity/jobs/{queued['id']}/cancel")
        except PermissionError:
            pass
        client.post(f"/api/identity/jobs/{running['id']}/cancel")
    path = config.dream_root / "data" / "identity" / "jobs" / f"{queued['id']}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["state"] == "cancelled", record
    assert "清理" in record["error"] and "权限" in record["error"]
    assert record["result"] is None and original.exists()
    assert len([call for call in boundary.calls if call[1] == "generate"]) == 1
    assert boundary.children[-1].poll() is not None
    if operation == "close":
        with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as restored:
            assert restored.get(f"/api/identity/jobs/{queued['id']}").json()["state"] == "cancelled"


@pytest.mark.parametrize("locked", ["original", "metadata"])
def test_batch_cleanup_permission_error_persists_child_and_reports_remaining_files(batch_harness, monkeypatch, locked):
    client, config, _, boundary = batch_harness
    boundary.hold = True
    batch = submit_batch(client, batch_request(upload(client)))
    record = wait_batch(client, batch["id"], lambda item: item["step"] == 5)
    first, second = record["items"]
    keep = save_original(config, first)
    keep_bytes = keep.read_bytes()
    item = boundary.calls[0]["items"][1]
    paths = {"original": save_original(config, second), "metadata": Path(item["metadataPath"]),
             "image": Path(item["outputPath"])}
    for key in ("metadata", "image"):
        paths[key].write_bytes(b"partial output")
    unlink = Path.unlink

    def locked_unlink(path, *args, **kwargs):
        if path == paths[locked]:
            raise PermissionError("controlled batch partial output lock")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked_unlink)
    result = client.post(f"/api/identity/batches/{batch['id']}/cancel").json()
    path = config.dream_root / "data" / "identity" / "jobs" / f"{second['id']}.json"
    child = json.loads(path.read_text(encoding="utf-8"))
    assert child["state"] == "cancelled", child
    assert "清理" in child["error"] and "清理" in result["error"]
    assert child == result["items"][1]
    assert keep.read_bytes() == keep_bytes
    for key, path in paths.items():
        assert path.exists() == (key == locked)
