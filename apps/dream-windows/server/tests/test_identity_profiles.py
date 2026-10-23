"""Profiles use real routes/storage/queue; only child process IO is controlled."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import create_app
from runtime import DreamRuntime
from test_identity_api import harness, upload, submit, finished


class ProfileWorkerBoundary:
    def __init__(self, legacy):
        self.legacy = legacy
        self.calls = []
        self.children = []
        self.hold = False
        self.fail = False
        self.started = threading.Event()
        self.release = threading.Event()
        self.exit_allowed = threading.Event()
        self.exit_allowed.set()

    def spawn(self, command, **options):
        if command[3] != "prepare":
            return self.legacy.spawn(command, **options)
        assert command[2::2] == ["--operation", "--request", "--result"]
        payload = json.loads(Path(command[5]).read_text(encoding="utf-8"))
        assert set(payload) == {"imagePath", "faceIndex", "dreamRoot", "configPath"}
        assert Path(payload["imagePath"]).is_file()
        self.calls.append(payload)
        boundary = self

        class Child:
            returncode = None
            stopped = False

            def poll(self):
                return self.returncode

            def terminate(self):
                self.stopped = True

            kill = terminate

            def communicate(self, timeout=None):
                boundary.started.set()
                if self.stopped:
                    if not boundary.exit_allowed.wait(.01):
                        raise subprocess.TimeoutExpired(command, timeout)
                    self.returncode = -15
                elif boundary.hold and not boundary.release.wait(.01):
                    raise subprocess.TimeoutExpired(command, timeout)
                else:
                    result = {"ok": False, "message": "受控建档失败"} if boundary.fail else {"ok": True, "featureKey": "a" * 64, "cacheHit": False}
                    Path(command[7]).write_text(json.dumps(result), encoding="utf-8")
                    self.returncode = 1 if boundary.fail else 0
                return "", ""

            def wait(self, timeout=None):
                if timeout is None:
                    assert boundary.exit_allowed.wait(5)
                self.communicate(timeout)
                return self.returncode

        child = Child()
        self.children.append(child)
        return child


@pytest.fixture
def profile_harness(harness, monkeypatch):
    client, config, runner, legacy = harness
    boundary = ProfileWorkerBoundary(legacy)
    monkeypatch.setattr(subprocess, "Popen", boundary.spawn)
    try:
        yield client, config, runner, boundary
    finally:
        boundary.release.set()
        boundary.exit_allowed.set()


def create_profile(client, reference=None, **changes):
    reference = reference or upload(client)
    response = client.post("/api/identity/profiles", json={"name": "人物一", "referenceId": reference["id"], "faceIndex": 1, **changes})
    assert response.status_code == 200, response.text
    return response.json()


def wait_profile(client, profile_id, state="ready"):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/identity/profiles/{profile_id}")
        assert response.status_code == 200, response.text
        if response.json()["state"] == state:
            return response.json()
        time.sleep(.01)
    pytest.fail(f"profile did not become {state}: {response.text}")


def test_profile_prepares_once_and_restores_with_same_binding(profile_harness):
    client, config, runner, boundary = profile_harness
    initial = create_profile(client)
    assert re.fullmatch(r"person-[0-9a-f]{24}", initial["id"])
    assert initial["state"] == "preparing"
    ready = wait_profile(client, initial["id"])
    assert ready["featureKey"] == "a" * 64
    assert ready["error"] is None and ready["defaults"] == {}
    assert ready["faceIndex"] == 1 and ready["createdAt"] and ready["updatedAt"]
    client.__exit__(None, None, None)
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as restored:
        assert restored.get("/api/identity/profiles").json() == [ready]
        assert restored.get(f"/api/identity/profiles/{ready['id']}").json() == ready
    assert len(boundary.calls) == 1


@pytest.mark.parametrize("changes", [{"faceIndex": 19}, {"referenceId": "ref-" + "0" * 24}, {"faceIndex": True}, {"name": "  "}, {"name": "x" * 121}, {"imagePath": "C:/secret.png"}])
def test_invalid_profile_never_reaches_prepare(profile_harness, changes):
    client, _, _, boundary = profile_harness
    reference = upload(client)
    response = client.post("/api/identity/profiles", json={"name": "人物", "referenceId": reference["id"], "faceIndex": 1, **changes})
    assert response.status_code in {404, 422}
    assert boundary.calls == []
    assert client.get("/api/identity/profiles").json() == []


def test_profile_queue_archive_and_rename_preserve_reference(profile_harness):
    client, config, runner, boundary = profile_harness
    reference = upload(client)
    gate, started = threading.Event(), threading.Event()
    def blocker():
        started.set()
        gate.wait(5)
    prior = runner.submit_serial(blocker)
    assert started.wait(2)
    try:
        initial = create_profile(client, reference)
        assert boundary.calls == []
        assert client.post(f"/api/identity/profiles/{initial['id']}/archive").status_code == 409
    finally:
        gate.set()
        prior.result(timeout=3)
    ready = wait_profile(client, initial["id"])
    renamed = client.post(f"/api/identity/profiles/{ready['id']}/rename", json={"name": "新名字"}).json()
    assert renamed["name"] == "新名字" and renamed["featureKey"] == ready["featureKey"]
    archived = client.post(f"/api/identity/profiles/{ready['id']}/archive").json()
    assert archived["state"] == "archived"
    assert client.get("/api/identity/profiles").json() == []
    assert client.get(f"/api/identity/profiles/{ready['id']}").json() == archived
    assert client.get(reference["imageUrl"]).status_code == 200
    assert (config.dream_root / "data" / "identity" / "profiles" / f"{ready['id']}.json").exists()


def test_preset_only_accepts_completed_same_face_and_keeps_features(profile_harness):
    client, _, _, boundary = profile_harness
    reference = upload(client)
    profile = wait_profile(client, create_profile(client, reference)["id"])
    own = finished(client, submit(client, reference, seed=123, steps=12)["id"])
    response = client.post(f"/api/identity/profiles/{profile['id']}/preset", json={"jobId": own["id"]})
    assert response.status_code == 200, response.text
    preset = response.json()
    assert preset["featureKey"] == profile["featureKey"]
    assert preset["defaults"] == {k: v for k, v in own["request"].items() if k not in {"referenceId", "faceIndex"}}
    other = finished(client, submit(client, reference, faceIndex=0)["id"])
    assert client.post(f"/api/identity/profiles/{profile['id']}/preset", json={"jobId": other["id"]}).status_code == 409
    assert client.get(f"/api/identity/profiles/{profile['id']}").json() == preset
    assert len(boundary.calls) == 1


def test_prepare_failure_is_persisted(profile_harness):
    client, _, _, boundary = profile_harness
    boundary.fail = True
    failed = wait_profile(client, create_profile(client)["id"], "failed")
    assert "建档失败" in failed["error"]
    assert not failed.get("featureKey")


def test_close_waits_for_profile_native_release_stage(profile_harness, monkeypatch):
    client, config, runner, _ = profile_harness
    started, release = threading.Event(), threading.Event()
    def delayed_native_release():
        started.set()
        release.wait(5)
    monkeypatch.setattr(runner, "release_native_for_identity", delayed_native_release)
    profile = create_profile(client)
    assert started.wait(2)
    with ThreadPoolExecutor(max_workers=1) as pool:
        closing = pool.submit(client.__exit__, None, None, None)
        try:
            time.sleep(.1)
            assert not closing.done(), "lease must cover preparation before the worker exists"
        finally:
            release.set()
        closing.result(timeout=5)
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as restored:
        assert restored.get(f"/api/identity/profiles/{profile['id']}").json()["state"] == "failed"


def test_close_cancels_queued_profiles_without_treating_them_as_legacy_jobs(profile_harness, caplog):
    client, config, runner, boundary = profile_harness
    reference = upload(client)
    release = threading.Event()
    blocker = runner.submit_serial(lambda: release.wait(5))
    try:
        profile = create_profile(client, reference)
        client.__exit__(None, None, None)
        assert not caplog.records
        assert not boundary.calls
    finally:
        release.set()
        blocker.result(timeout=5)
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as restored:
        assert restored.get(f"/api/identity/profiles/{profile['id']}").json()["state"] == "failed"


def test_profile_runtime_disk_failure_is_visible_without_waiting_for_restart(profile_harness, monkeypatch, caplog):
    import identity_profiles
    client, _, _, boundary = profile_harness
    boundary.hold = True
    profile = create_profile(client)
    assert boundary.started.wait(2)
    original_write = identity_profiles.atomic_json
    def disk_full(path, value):
        if value.get("id") == profile["id"]:
            raise OSError(28, "controlled profile disk full")
        return original_write(path, value)
    with monkeypatch.context() as disk:
        disk.setattr(identity_profiles, "atomic_json", disk_full)
        boundary.release.set()
        failed = wait_profile(client, profile["id"], "failed")
        assert "保存" in failed["error"] and not failed.get("featureKey")
        assert profile["id"] in caplog.text and "disk full" in caplog.text
        assert boundary.children[-1].poll() is not None


def test_shutdown_waits_for_preparing_profile_before_releasing_lease(profile_harness):
    client, config, runner, boundary = profile_harness
    boundary.hold = True
    boundary.exit_allowed.clear()
    profile = create_profile(client)
    assert boundary.started.wait(2)
    with TestClient(create_app(config, DreamRuntime(config, job_runner=runner))) as contender:
        with ThreadPoolExecutor(max_workers=1) as pool:
            closing = pool.submit(client.__exit__, None, None, None)
            try:
                time.sleep(.1)
                assert not closing.done()
                assert contender.get("/api/identity/profiles").status_code == 503
            finally:
                boundary.release.set()
                boundary.exit_allowed.set()
            closing.result(timeout=5)
        assert contender.get(f"/api/identity/profiles/{profile['id']}").json()["state"] == "failed"
        assert boundary.children[-1].poll() is not None


@pytest.mark.parametrize("suffix,payload", [("", {}), ("/person-" + "a" * 24 + "/rename", {"name": "人"}), ("/person-" + "a" * 24 + "/archive", {}), ("/person-" + "a" * 24 + "/preset", {"jobId": "identity-" + "a" * 24})])
def test_all_profile_writes_reject_cross_origin(profile_harness, suffix, payload):
    client, _, _, _ = profile_harness
    response = client.post("/api/identity/profiles" + suffix, json=payload, headers={"origin": "https://evil.invalid", "sec-fetch-site": "cross-site"})
    assert response.status_code == 403
