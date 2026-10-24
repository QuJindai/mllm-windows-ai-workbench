"""Isolated browser fixture: real Dream routes/storage, synthetic inference only.

  python -B scripts/qa_identity_deletion.py prepare
  python -B scripts/qa_identity_deletion.py check
  python -B scripts/qa_identity_deletion.py serve --port 8877
  python -B scripts/qa_identity_deletion.py verify

No production data, model weights, native engine, GPU, or subprocess worker is
used. prepare refuses to overwrite a nonempty unmarked directory. serve never
reseeds deleted results. Only this process replaces the inference boundary;
history deletion, recovery, HTTP responses, and resultDeleted are production code.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import sys
import threading
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
SERVER = REPO / "apps/dream-windows/server"
ROOT = Path("E:/Dream/test-runs/identity-deletion-20261025")
FRONTEND = ROOT / "frontend"
MODEL = "cyberrealistic-xl-plus-face"
FEATURE = hashlib.sha256(b"QA synthetic visual feature; no embedding").hexdigest()
sys.path.insert(0, str(SERVER))
sys.dont_write_bytecode = True

from PIL import Image, ImageDraw
from app import create_app
from config import DreamServerConfig
from errors import DreamApiError
from history_transactions import history_deletion_flags
from identity_batches import BatchRequest
from identity_contract import IdentityGenerateRequest
from identity_profiles import ProfileCreate, ProfilePreset
from identity_service import IdentityService, ReferenceUpload, atomic_json, read_json
from identity_stage_artifacts import save_visual_stage
from identity_visual_polish import detail_prompts, detail_size
from job_runner import JobRunner
from runtime import DreamRuntime


def isolated_root(value: Path) -> Path:
    value = value.absolute()
    value.relative_to(ROOT.absolute())  # Only the named QA root or its children.
    for path in (value, *value.parents):
        if path.is_symlink() or path.is_junction():
            raise ValueError(f"Refusing redirected fixture path: {path}")
    if value.resolve() != value:
        raise ValueError("Fixture path must be canonical")
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture_config(root: Path, port: int = 8877) -> DreamServerConfig:
    # IdentityService has a legacy absolute default: override it explicitly.
    os.environ["DREAM_IDENTITY_CONFIG"] = str(root / "data/identity/runtime.json")
    os.environ["DREAM_HOME"] = str(root)
    disabled = root / "disabled-engines"
    return DreamServerConfig(
        repo_root=REPO, dream_root=root, core_exe=disabled / "dream-core.exe",
        engine_exe=disabled / "sd-cli.exe", wrapper=disabled / "wrapper.cmd",
        registry_path=root / "model-registry.json", frontend_dist=FRONTEND,
        host="127.0.0.1", port=port,
    )


def blocked(*args, **kwargs):
    raise DreamApiError("QA_INFERENCE_DISABLED", "隔离删除验收：禁止真实推理和进程启动", status_code=409)


class NoNativeEngine:
    available = False

    def release_for_identity(self):
        pass  # Never probe or release the user's real resident engine.

    ensure_ready = generate = cancel = blocked


def runner_for(config):
    return JobRunner(config, command_runner=blocked, persistent_engine=NoNativeEngine())


class FixtureRuntime(DreamRuntime):
    # History and deletion are inherited unchanged. Avoid hardware subprocesses.
    def hardware(self):
        return dict(gpuName="QA fixture / GPU disabled", vramTotalMiB=0, vramUsedMiB=0,
                    gpuUtil=0, gpuTempC=None, gpuPowerW=None, ramTotalBytes=0,
                    ramUsedBytes=0, cudaReady=False, backend="CPU synthetic fixture",
                    backendTruth="unavailable", truth="unavailable", isMock=True,
                    dreamRoot=str(self.config.dream_root), cpuName="Not probed",
                    cpuCores=None, cpuThreads=None, driverVersion=None,
                    eDriveTotalBytes=None, eDriveFreeBytes=None, sampledAt=None,
                    telemetrySource="disabled for isolated QA")

    generate = run_experiment = _run_core = blocked


def synthetic_image(seed: int, label: str) -> Image.Image:
    image = Image.new("RGB", (256, 256), (35 + seed % 80, 65, 105))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 247, 247), outline="white", width=3)
    draw.ellipse((50, 55, 205, 210), fill=(210, 140 + seed % 70, 90))
    draw.rectangle((80, 100, 100, 118), fill="navy")
    draw.rectangle((155, 100, 175, 118), fill="navy")
    draw.line((100, 165, 155, 165), fill="navy", width=4)
    draw.text((16, 20), "SYNTHETIC QA - NO PERSON", fill="white")
    draw.text((16, 225), label[:32], fill="white")
    return image


class SyntheticBoundary:
    def __init__(self, root, *, seeding=False):
        self.root, self.seeding = root, seeding

    def status(self):
        message = "隔离删除验收：合成数据，真实推理已禁用"
        return dict(ready=self.seeding, modelName="QA Synthetic / Cyber visual schema",
                    message=message, loras=[], models=[dict(id=MODEL, name="QA 合成结果（无 GPU）",
                    architecture="SDXL", referenceKind="visual", ready=self.seeding,
                    message=message, loras=[])], visualPolish=dict(ready=self.seeding,
                    message=message, referenceAnchorReady=self.seeding,
                    referenceAnchorMessage=message))

    def run(self, service, operation, payload, cancelled=None):
        if service.config.dream_root != self.root:
            raise AssertionError("Synthetic boundary cannot touch another root")
        if operation == "status":
            return self.status()
        if not self.seeding:
            return blocked()
        if operation == "inspect":
            return {"faces": [{"index": 0, "box": [50., 55., 205., 210.]}]}
        if operation == "prepare":
            return dict(ok=True, cacheHit=False, featureKey=FEATURE,
                        featureVersion=1, referenceKind="visual")
        if operation == "batch":
            for item in payload["items"]:
                self.render(item)
            return {"ok": True, "items": [{"jobId": item["jobId"]} for item in payload["items"]]}
        if operation == "generate":
            if "QA_FAIL_NO_OUTPUT" in payload["prompt"]:
                raise ValueError("QA synthetic controlled failure; no image created")
            self.render(payload)
            return {"ok": True}
        raise AssertionError(f"Unexpected fixture operation: {operation}")

    def render(self, item):
        output, metadata = Path(item["outputPath"]), Path(item["metadataPath"])
        for path in (output, metadata):
            path.resolve().relative_to(self.root)
        image = synthetic_image(item["seed"], f"seed {item['seed']} FINAL")
        original = self.root / "data/identity/originals" / (item["jobId"] + ".png")
        original.parent.mkdir(parents=True, exist_ok=True)
        synthetic_image(item["seed"], "ORIGINAL").save(original)
        box, crop = [32., 32., 64., 64.], [16, 16, 96, 96]
        prompt, negative = detail_prompts(item)
        polish = dict(enabled=True, status="completed", durationMs=3,
                      restoreStrength=item["faceRestoreStrength"],
                      originalImageUrl=f"/api/identity/jobs/{item['jobId']}/original",
                      method="visual-reference-local-redraw", referenceId=item["referenceId"],
                      faceIndex=0, featureKey=FEATURE, faceBox=box, cropBox=crop,
                      denoiseStrength=item["animeDenoiseStrength"], outsideMaskUnchanged=True,
                      restoreModel="CyberRealistic XL + Plus Face visual reference",
                      restoreDevice="CPU synthetic QA / no inference", detailerVersion="protected-face-v3",
                      featureProtection="central-features-v1", processingSize=list(detail_size(crop, box)),
                      detailPrompt=prompt, detailNegativePrompt=negative,
                      polishMode="reference-anchor", anchorStrength=item["visualAnchorStrength"],
                      alignmentError=.04, passes=[dict(kind="harmonize", denoiseStrength=.25, steps=7, durationMs=1),
                                                dict(kind="detail", denoiseStrength=.15, steps=4, durationMs=2)])
        polish["snapshots"] = [dict(kind=kind, imageUrl=save_visual_stage(
            image if kind == "detail" else synthetic_image(item["seed"], kind.upper()), item, kind))
            for kind in ("anchor", "harmonize", "detail")]
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output)
        atomic_json(metadata, dict(featureKey=FEATURE, referenceKind="visual", facePolish=polish,
                                  model_name="QA synthetic fixture", generation_time_ms=3,
                                  qaSynthetic=True))


@contextmanager
def inference_boundary(boundary):
    with patch.object(IdentityService, "_worker", lambda service, *args: boundary.run(service, *args)):
        yield


def load_manifest(root):
    value = read_json(root / "fixture.json")
    if value.get("fixture") != "identity-deletion-20261025-v1" or Path(value["root"]) != root:
        raise ValueError("Not this isolated fixture")
    return value


def prepare(root):
    if (root / "fixture.json").is_file():
        # Refresh only build provenance; never restore browser-deleted files.
        manifest = load_manifest(root)
        manifest.update(frontend=str(FRONTEND), frontendIndexSha256=digest(FRONTEND / "index.html"))
        atomic_json(root / "fixture.json", manifest)
        return manifest
    if root.exists() and any(root.iterdir()):
        raise ValueError("Refusing to overwrite a nonempty directory without fixture.json")
    root.mkdir(parents=True, exist_ok=True)
    atomic_json(root / "model-registry.json", {"models": []})
    atomic_json(root / "data/identity/runtime.json", {"python": sys.executable, "persistentWorker": False,
                                                     "qaSynthetic": True})
    config = fixture_config(root)
    runner = runner_for(config)
    service = IdentityService(config, runner)
    release = threading.Event()
    try:
        with inference_boundary(SyntheticBoundary(root, seeding=True)):
            png = io.BytesIO()
            synthetic_image(1, "REFERENCE - KEEP").save(png, format="PNG")
            ref = service.upload(ReferenceUpload(name="QA synthetic reference.png", referenceKind="visual",
                                                imageBase64=base64.b64encode(png.getvalue()).decode()))
            profile = service.profile_operation("create", ProfileCreate(name="QA 保留档案（合成）",
                referenceId=ref["id"], faceIndex=0, referenceKind="visual"))
            service._background[profile["id"]][0].result(timeout=15)
            assert service.profile_operation("get", profile["id"])["state"] == "ready"
            def request(prompt, seed=101):
                return IdentityGenerateRequest(modelId=MODEL, referenceId=ref["id"], faceIndex=0,
                    prompt=prompt, seed=seed, width=256, height=256, steps=30, cfg=5.,
                    identityStrength=.8, structureStrength=0., faceLoraStrength=0., facePolish=True,
                    visualPolishMode="reference-anchor", visualAnchorStrength=.8,
                    visualPolishPasses=2, animeDenoiseStrength=.25)
            def finish(params):
                job = service.submit(params)
                service._futures[job["id"]].result(timeout=15)
                return service.get(job["id"])
            single = finish(request("QA SINGLE - delete this synthetic result"))
            assert single["state"] == "complete", single
            service.profile_operation("preset", profile["id"], ProfilePreset(jobId=single["id"]))
            batch = service.batch_operation("submit", BatchRequest(profileId=profile["id"], count=2,
                request=request("QA BATCH - delete first, preserve sibling", 201)))
            service._background[batch["id"]][0].result(timeout=15)
            batch = service.batch_operation("get", batch["id"])
            assert batch["state"] == "complete", batch
            failed = finish(request("QA_FAIL_NO_OUTPUT", 301))
            assert failed["state"] == "failed" and failed["result"] is None
            entered = threading.Event()
            def hold_queue():
                entered.set()
                if not release.wait(15):
                    raise TimeoutError("QA queue gate timed out")
            held = runner.submit_serial(hold_queue)
            assert entered.wait(5)
            cancelled = service.submit(request("QA CANCELLED - no result", 401))
            cancelled = service.cancel(cancelled["id"])
            release.set()
            held.result(timeout=5)
            assert cancelled["state"] == "cancelled" and cancelled["result"] is None
            jobs = {"single": single["id"], "batch-first": batch["items"][0]["id"],
                    "batch-sibling": batch["items"][1]["id"], "failed": failed["id"],
                    "cancelled": cancelled["id"]}
            completed = [single, *batch["items"]]
    finally:
        release.set()
        service.close()
        runner._executor.shutdown(wait=True, cancel_futures=True)
    protected = [root / "data/identity/references" / (ref["id"] + suffix) for suffix in (".png", ".json")]
    protected.append(root / "data/identity/profiles" / (profile["id"] + ".json"))
    protected += [root / "data/identity/jobs" / (job_id + ".json") for job_id in jobs.values()]
    protected.append(root / "data/identity/batches" / (batch["id"] + ".json"))
    artifacts = {}
    for job in completed:
        output = Path(job["result"]["metadata"]["output"])
        paths = [output, output.with_suffix(".json"), root / "data/identity/originals" / (job["id"] + ".png")]
        paths += [root / "data/identity/stages" / job["id"] / (kind + ".png") for kind in ("anchor", "harmonize", "detail")]
        artifacts[job["id"]] = {str(path.relative_to(root)): digest(path) for path in paths}
    manifest = dict(fixture="identity-deletion-20261025-v1", root=str(root), frontend=str(FRONTEND),
                    synthetic=True, jobs=jobs, batchId=batch["id"], profileId=profile["id"],
                    referenceId=ref["id"], preservedHashes={str(p.relative_to(root)): digest(p) for p in protected},
                    resultArtifacts=artifacts, expected=dict(complete=3, failed=1, cancelled=1, batches=1),
                    frontendIndexSha256=digest(FRONTEND / "index.html"))
    atomic_json(root / "fixture.json", manifest)
    return manifest


def verify(root):
    manifest = load_manifest(root)
    deletion_flags = history_deletion_flags(root)
    deleted = set(deletion_flags)
    results_deleted = {job_id for job_id, flags in deletion_flags.items() if flags.get("resultDeleted")}
    errors = []
    for name, expected in manifest["preservedHashes"].items():
        path = root / name
        if not path.is_file() or digest(path) != expected:
            errors.append(f"Preserved file changed/missing: {name}")
    for job_id, paths in manifest["resultArtifacts"].items():
        for name, expected in paths.items():
            path = root / name
            if job_id in results_deleted:
                if path.exists():
                    errors.append(f"Deleted result remains live: {name}")
            elif not path.is_file() or digest(path) != expected:
                errors.append(f"Undeleted result changed/missing: {name}")
    for key in ("failed", "cancelled"):
        job_id = manifest["jobs"][key]
        record = read_json(root / "data/identity/jobs" / (job_id + ".json"))
        if record["result"] is not None or list((root / "outputs").rglob(job_id + ".png")):
            errors.append(f"Unexpected result for {key}")
    result = dict(ok=not errors, deleted=sorted(deleted), resultDeleted=sorted(results_deleted),
                  preservedFiles=len(manifest["preservedHashes"]), errors=errors)
    if errors:
        raise ValueError(json.dumps(result, ensure_ascii=False))
    return result


@contextmanager
def application(root, port=8877):
    load_manifest(root)
    config = fixture_config(root, port)
    runner = runner_for(config)
    try:
        with inference_boundary(SyntheticBoundary(root)):
            yield create_app(config, FixtureRuntime(config, job_runner=runner))
    finally:
        runner._executor.shutdown(wait=True, cancel_futures=True)


def check(root):
    """Read-only ASGI route smoke check; no socket server and no deletion."""
    from fastapi.testclient import TestClient
    manifest = load_manifest(root)
    deletion_flags = history_deletion_flags(root)
    deleted = set(deletion_flags)
    with application(root) as app, TestClient(app, base_url="http://127.0.0.1:8877") as client:
        for path in ("/", "/api/health", "/api/identity/status", "/api/identity/profiles", "/api/identity/references"):
            response = client.get(path)
            assert response.status_code == 200, (path, response.text[:300])
        history = client.get("/api/history").json()
        assert history["total"] == 3 - len(deleted.intersection(manifest["resultArtifacts"]))
        jobs = client.get("/api/identity/jobs").json()
        assert len(jobs) == 5
        batches = client.get("/api/identity/batches").json()
        assert len(batches) == 1 and len(batches[0]["items"]) == 2
        for job in [*jobs, *batches[0]["items"]]:
            flags = deletion_flags.get(job["id"], {})
            assert job.get("historyDeleted", False) == flags.get("historyDeleted", False), job["id"]
            expected_result_deleted = job["state"] == "complete" and flags.get("resultDeleted", False)
            assert job.get("resultDeleted", False) == expected_result_deleted, job["id"]
        for job in jobs:
            if job["state"] != "complete":
                continue
            status = 404 if job["id"] in deleted else 200
            paths = [job["result"]["imageUrl"], f"/api/identity/jobs/{job['id']}/original"]
            paths += [f"/api/identity/jobs/{job['id']}/stages/{kind}" for kind in ("anchor", "harmonize", "detail")]
            for path in paths:
                assert client.get(path).status_code == status, path
    return {"routeCheck": "passed", **verify(root)}


def serve(root, port):
    import uvicorn
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as exc:
            if exc.errno not in (errno.EADDRINUSE, 10048):
                raise
            listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        actual = listener.getsockname()[1]
        with application(root, actual) as app:
            receipt = dict(url=f"http://127.0.0.1:{actual}", pid=os.getpid(), root=str(root), synthetic=True)
            atomic_json(root / "server.json", receipt)
            print(json.dumps(receipt), flush=True)
            uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=actual, log_level="info")).run(sockets=[listener])
    finally:
        listener.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("prepare", "check", "serve", "verify"))
    parser.add_argument("--root", type=Path, default=ROOT, help="Only the named QA root or a child directory")
    parser.add_argument("--port", type=int, default=8877)
    args = parser.parse_args()
    root = isolated_root(args.root)
    if not (FRONTEND / "index.html").is_file():
        raise ValueError("Requested real frontend build is missing")
    if args.command == "serve":
        serve(root, args.port)
    else:
        result = {"prepare": prepare, "check": check, "verify": verify}[args.command](root)
        if args.command == "prepare":
            result = {key: result[key] for key in ("root", "jobs", "batchId", "profileId", "referenceId")}
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
