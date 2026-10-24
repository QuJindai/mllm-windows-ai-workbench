from __future__ import annotations

import json
import math
import os
import re
import subprocess
import hashlib
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from config import DreamServerConfig
from errors import DreamApiError
from hardware_telemetry import HardwareTelemetry
from history_transactions import (delete_history_files, history_mutation_lock, recover_history_transactions,
                                  committed_history_deletions)
from identity_models import is_visual_model_id
from job_runner import JobRunner
from models import ExperimentRequest, GenerateRequest
from research_traces import (ResearchTraceStore, read_bounded_json, validate_research_provenance,
                             InvalidArtifact, INDEX_BYTES, MAP_BYTES)

class DreamRuntime:
    H7_ATTENTION_CONTRACT_VERSION = "h7-attention-v1"
    MAX_ATTENTION_TOKENS = 77
    MAX_ATTENTION_LAYERS = 3
    MAX_ATTENTION_MAPS = 512
    MAX_ATTENTION_STEP = 49
    MAX_ATTENTION_DIMENSION = 128
    MAX_ATTENTION_VALUES = 16_384

    def __init__(self, config: DreamServerConfig, job_runner: JobRunner | None = None, workspace_launcher: Callable[[Path], None] | None = None):
        self.config = config
        recover_history_transactions(config.dream_root)
        self.job_runner = job_runner or JobRunner(config)
        self.workspace_launcher = workspace_launcher
        self.research_traces = ResearchTraceStore(config.dream_root)
        self._experiments: dict[str, dict[str, Any]] = {}
        self._experiments_lock = threading.RLock()
        self._hardware_telemetry = HardwareTelemetry(config)

    def _environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "DREAM_HOME": str(self.config.dream_root),
                "DREAM_MODEL_REGISTRY": str(self.config.registry_path),
                "DREAM_STABLE_DIFFUSION_CPP_EXE": str(self.config.engine_exe),
                "DREAM_SDCPP_GENERATE_WRAPPER": str(self.config.wrapper),
            }
        )
        return env

    def _run_core(self, *args: str, timeout: int = 20) -> str:
        if not self.config.core_exe.exists():
            raise DreamApiError("DREAM_CORE_MISSING", "dream-core.exe is not available", detail={"path": str(self.config.core_exe)})
        try:
            result = subprocess.run(
                [str(self.config.core_exe), *args],
                cwd=str(self.config.dream_root),
                env=self._environment(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise DreamApiError("DREAM_CORE_START_FAILED", str(exc), detail={"path": str(self.config.core_exe)}) from exc
        if result.returncode != 0:
            raise DreamApiError(
                "DREAM_CORE_FAILED",
                result.stderr.strip() or result.stdout.strip() or "dream-core failed",
                detail={"returncode": result.returncode},
            )
        return result.stdout

    @staticmethod
    def _json_from_output(output: str) -> dict[str, Any]:
        for line in reversed(output.splitlines()):
            candidate = line.strip().lstrip("\ufeff")
            if not candidate:
                continue
            try:
                value = json.loads(candidate)
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                continue
        try:
            value = json.loads(output.lstrip("\ufeff"))
        except json.JSONDecodeError as exc:
            raise DreamApiError("DREAM_CORE_INVALID_JSON", "dream-core returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise DreamApiError("DREAM_CORE_INVALID_JSON", "dream-core response must be an object")
        return value

    def health(self) -> dict[str, Any]:
        native = self.config.core_exe.exists()
        engine = self.config.engine_exe.exists()
        wrapper = self.config.wrapper.exists()
        registry = self.config.registry_path.exists()
        return {
            "ok": self.config.dream_root.exists(),
            "service": "dream-web",
            "bind_policy": "localhost-default",
            "dreamRoot": str(self.config.dream_root),
            "backend": "ready" if native and engine and wrapper and registry else "blocked",
            "checks": {"dreamCore": native, "engine": engine, "wrapper": wrapper, "registry": registry},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def capabilities(self) -> dict[str, Any]:
        native = self.config.core_exe.exists() and self.config.engine_exe.exists() and self.config.wrapper.exists() and self.config.registry_path.exists()
        h7_ready = native and self.config.h7_attention_ready()
        influence_ready = native and self.config.h6_conditioning_ready()
        self_attention_ready = native and self.config.h7_self_attention_ready()
        return {
            "native_generation": {"available": native, "truth": "observed" if native else "unavailable"},
            "process_trace": {"available": native, "truth": "derived" if native else "unavailable"},
            "latent_trace": {"available": native, "truth": "observed" if native else "unavailable", "message": "Per-step latent RGB projections are captured; raw tensor telemetry depends on native binary support" if native else "Native Windows engine is unavailable"},
            "semantic_experiments": {"available": influence_ready, "truth": "observed" if influence_ready else "unavailable", "message": "Controlled same-seed experiments use the native H6 generation queue" if influence_ready else "Native H6 generation dependencies are not ready"},
            "attention": {
                "available": h7_ready,
                "truth": "observed" if h7_ready else "unavailable",
                "message": "H7 Debug UNet cross-attention 采集已就绪" if h7_ready else "独立 H7 Debug UNet 引擎尚未安装或清单无效",
            },
            "conditioning_influence": {
                "available": influence_ready,
                "truth": "observed" if influence_ready else "unavailable",
                "message": "H6 conditioning influence capture is ready" if influence_ready else "The native h6-conditioning-v1 capability is unavailable",
            },
            "self_attention": {
                "available": self_attention_ready,
                "truth": "observed" if self_attention_ready else "unavailable",
                "message": "H7 self-attention capture is ready" if self_attention_ready else "The native h7-self-attention-v1 capability is unavailable",
            },
        }

    def hardware(self) -> dict[str, Any]:
        return self._hardware_telemetry.read()

    def _registry(self) -> dict[str, Any]:
        if not self.config.registry_path.exists():
            raise DreamApiError("MODEL_REGISTRY_MISSING", "Dream model registry is not available", detail={"path": str(self.config.registry_path)})
        try:
            return json.loads(self.config.registry_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise DreamApiError("MODEL_REGISTRY_INVALID", "Dream model registry is invalid") from exc

    def models(self) -> list[dict[str, Any]]:
        registry = self._registry()
        result: list[dict[str, Any]] = []
        for item in registry.get("models", []):
            windows = item.get("windows") or {}
            generation_defaults = item.get("generation_defaults") or {}
            path = Path(str(windows.get("path") or ""))
            exists = path.exists()
            verified = exists and str(windows.get("identity_status") or "").lower().startswith("verified")
            result.append(
                {
                    "id": item.get("model_id"),
                    "aliases": [str(alias) for alias in item.get("aliases", []) if str(alias).strip()],
                    "displayName": item.get("display_name"),
                    "architecture": item.get("architecture", "OTHER"),
                    "format": str(windows.get("format") or "GGUF").upper(),
                    "dmd2": bool((item.get("dmd2") or {}).get("enabled")),
                    "path": str(path),
                    "sha256": windows.get("sha256"),
                    "verified": verified,
                    "sizeBytes": path.stat().st_size if exists else 0,
                    "tags": [],
                    "description": f"{item.get('display_name', 'Dream model')} · {windows.get('backend', 'native')}",
                    "kind": "Checkpoint",
                    "status": "ready" if exists and item.get("status") == "installed" else "unavailable",
                    "imageUrl": "",
                    "truth": "observed",
                    "source": item.get("source", {}),
                    "generationDefaults": {
                        "width": generation_defaults.get("width"),
                        "height": generation_defaults.get("height"),
                        "steps": generation_defaults.get("steps"),
                        "cfg": generation_defaults.get("cfg"),
                        "samplingMethod": generation_defaults.get("sampling_method"),
                        "scheduler": generation_defaults.get("scheduler"),
                    } if generation_defaults else None,
                }
            )
        return result

    def get_model(self, model_id: str) -> dict[str, Any]:
        model = next(
            (
                item
                for item in self.models()
                if item["id"] == model_id or model_id in item.get("aliases", [])
            ),
            None,
        )
        if model is None:
            raise DreamApiError("MODEL_NOT_FOUND", f"Model was not found: {model_id}", status_code=404)
        return model

    def verify_model(self, model_id: str) -> dict[str, Any]:
        model = self.get_model(model_id)
        path = Path(model["path"])
        if not path.exists():
            raise DreamApiError("MODEL_FILE_MISSING", "Selected model file is not available", detail={"path": str(path)})
        expected = str(model.get("sha256") or "").lower()
        observed: str | None = None
        # Large GGUF files are intentionally not re-hashed on every button click.
        # The registry identity is retained as the observed verification source.
        if path.stat().st_size <= 64 * 1024 * 1024:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            observed = digest.hexdigest()
        return {
            **model,
            "verified": bool(model["verified"] and (observed is None or observed == expected)),
            "verification": "registry-identity" if observed is None else "sha256",
            "observedSha256": observed,
        }

    def _scan_history(self, *, deleted: set[str] | None = None) -> list[dict[str, Any]]:
        if deleted is None:
            deleted = committed_history_deletions(self.config.dream_root)
        roots = [self.config.dream_root / "outputs", self.config.dream_root / "history", self.config.dream_root / "exports"]
        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        try:
            model_names: dict[str, str] = {}
            canonical_model_ids: dict[str, str] = {}
            generation_defaults_by_id: dict[str, dict[str, Any] | None] = {}
            for model in self.models():
                canonical_id = str(model["id"])
                for identity in [canonical_id, *model.get("aliases", [])]:
                    identity_text = str(identity)
                    model_names[identity_text] = str(model["displayName"])
                    canonical_model_ids[identity_text] = canonical_id
                    generation_defaults_by_id[identity_text] = model.get("generationDefaults")
        except DreamApiError:
            model_names = {}
            canonical_model_ids = {}
            generation_defaults_by_id = {}
        for root in roots:
            if not root.exists():
                continue
            for metadata_path in root.rglob("*.json"):
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
                except (OSError, json.JSONDecodeError):
                    continue
                output = Path(str(metadata.get("output") or metadata.get("image_path") or metadata_path.with_suffix(".png")))
                if not output.is_absolute():
                    output = metadata_path.parent / output
                if not output.exists():
                    continue
                output_key = str(output.resolve()).lower()
                if output_key in seen:
                    continue
                seen.add(output_key)
                title = str(metadata.get("title") or output.stem)
                tags = list(metadata.get("tags") or [])
                favorite = bool(metadata.get("favorite", False))
                item_id = str(metadata.get("id") or output.stem)
                if item_id in deleted:
                    continue
                stored_model_id = str(metadata.get("model_id") or "")
                model_id = canonical_model_ids.get(stored_model_id, stored_model_id)
                entries.append({
                        "id": item_id,
                        "title": title,
                        "prompt": metadata.get("prompt", ""),
                        "negativePrompt": metadata.get("negative_prompt", ""),
                        "modelId": model_id,
                        "modelName": model_names.get(stored_model_id, str(metadata.get("model_name") or model_id or "Unknown model")),
                        "generationDefaults": generation_defaults_by_id.get(stored_model_id),
                        "width": int(metadata.get("width") or 0),
                        "height": int(metadata.get("height") or 0),
                        "steps": int(metadata.get("steps") or 0),
                        "cfg": float(metadata.get("cfg") or 0),
                        "seed": int(metadata.get("seed") or 0),
                        "generationTimeMs": int(metadata.get("generation_time_ms") or 0),
                        "createdAt": metadata.get("generated_at") or datetime.fromtimestamp(output.stat().st_mtime, timezone.utc).isoformat(),
                        "imageUrl": f"/api/history/{item_id}/image",
                        "filePath": str(output),
                        "metadataPath": str(metadata_path),
                        "tags": tags,
                        "favorite": favorite,
                        "status": "complete",
                        "truth": "observed",
                    })
        entries.sort(key=lambda item: item["createdAt"], reverse=True)
        return entries

    @staticmethod
    def _public_history_item(item: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in item.items() if key != "metadataPath"}

    def history(self, query: dict[str, Any]) -> dict[str, Any]:
        needle = str(query.get("search") or "").strip().lower()
        filter_name = str(query.get("filter") or "all")
        entries = []
        for item in self._scan_history():
            text = " ".join([item["title"], item["prompt"], item["modelId"], *map(str, item["tags"])]).lower()
            if needle and needle not in text:
                continue
            if filter_name == "favorites" and not item["favorite"]:
                continue
            if filter_name == "tagged" and not item["tags"]:
                continue
            if filter_name == "failed" and item["status"] != "failed":
                continue
            if filter_name == "today" and not item["createdAt"].startswith(datetime.now(timezone.utc).date().isoformat()):
                continue
            entries.append(item)
        page = max(1, int(query.get("page") or 1))
        page_size = max(1, min(100, int(query.get("page_size") or 24)))
        start = (page - 1) * page_size
        return {"items": [self._public_history_item(item) for item in entries[start : start + page_size]], "total": len(entries), "page": page, "pageSize": page_size}

    def _find_history_item(self, item_id: str, *, deleted: set[str] | None = None) -> dict[str, Any]:
        item = next((entry for entry in self._scan_history(deleted=deleted) if entry["id"] == item_id), None)
        if item is None:
            raise DreamApiError("HISTORY_NOT_FOUND", f"History item was not found: {item_id}", status_code=404)
        return item

    def history_item(self, item_id: str) -> dict[str, Any]:
        return self._public_history_item(self._find_history_item(item_id))

    def history_image(self, item_id: str) -> Path:
        item = self._find_history_item(item_id)
        path = Path(item["filePath"])
        if not self.config.path_under_dream(path) or not path.exists():
            raise DreamApiError("HISTORY_IMAGE_MISSING", "History image is not available", detail={"path": str(path)})
        return path

    def delete_history(self, item_id: str) -> dict[str, Any]:
        def paths():
            # Already under the deletion OS lock, after its receipt lookup.
            # Never reacquire that lock through the normal history read path.
            item = self._find_history_item(item_id, deleted=set())
            files = [Path(item["filePath"]), Path(item["metadataPath"])]
            if re.fullmatch(r"identity-[a-f0-9]{24}", item_id):
                files.insert(0, self.config.dream_root / "data/identity/originals" / f"{item_id}.png")
            return files

        delete_history_files(self.config.dream_root, item_id, paths, idempotent=True)
        return {"deleted": item_id, "truth": "observed"}

    def favorite_history(self, item_id: str, value: bool) -> dict[str, Any]:
        with history_mutation_lock(self.config.dream_root) as deleted:
            item = self._find_history_item(item_id, deleted=deleted)
            metadata_path = Path(item["metadataPath"])
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
                metadata["favorite"] = value
                metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            except (OSError, json.JSONDecodeError) as exc:
                raise DreamApiError("HISTORY_METADATA_WRITE_FAILED", str(exc), detail={"path": str(metadata_path)}) from exc
            return self._public_history_item(self._find_history_item(item_id, deleted=deleted))

    def _experiment_path(self, experiment_id: str) -> Path:
        return self.config.dream_root / "data" / "experiments" / f"{experiment_id}.json"

    def _persist_experiment(self, record: dict[str, Any]) -> None:
        path = self._experiment_path(str(record["id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def _experiment_variants(self, payload: ExperimentRequest) -> list[dict[str, Any]]:
        if payload.kind == "steps":
            steps = [max(1, min(50, value)) for value in (8, 16, 24, payload.steps)]
            return [{"label": f"{value} 步", "prompt": payload.prompt, "steps": value} for value in steps]
        if payload.kind == "model":
            available_models = [model for model in self.models() if model.get("status") == "ready"]
            requested_model = next((model for model in available_models if model.get("id") == payload.model_id), None)
            if requested_model is None:
                raise DreamApiError("MODEL_COMPARISON_UNAVAILABLE", "请求的模型当前不可用于模型对照")
            comparison_models = [requested_model, *[model for model in available_models if model.get("id") != payload.model_id]][:4]
            return [{"label": str(model["displayName"]), "modelId": str(model["id"]), "prompt": payload.prompt, "steps": payload.steps} for model in comparison_models]
        prompt = payload.prompt
        first_sentence = prompt.split(",", 1)[0].strip()
        return [
            {"label": "完整提示词（控制组）", "prompt": prompt, "steps": payload.steps},
            {"label": "平衡描述改写", "prompt": f"{first_sentence}, balanced composition, natural detail", "steps": payload.steps},
            {"label": "仅首段提示词", "prompt": first_sentence, "steps": payload.steps},
            {"label": "重点描述改写", "prompt": f"{first_sentence}, cinematic lighting, ultra detailed, photorealistic", "steps": payload.steps},
        ]

    def _public_experiment(self, record: dict[str, Any]) -> dict[str, Any]:
        variants: list[dict[str, Any]] = []
        states: list[str] = []
        for variant in record["variants"]:
            job = self.job_runner.get(str(variant["jobId"]))
            state = str(job.get("state") or "queued")
            states.append(state)
            job_request = job.get("request") if isinstance(job.get("request"), dict) else {}
            actual_model_id = variant.get("modelId") or job_request.get("modelId") or record.get("modelId")
            public_variant = {"id": variant["id"], "label": variant["label"], "jobId": variant["jobId"], "modelId": str(actual_model_id), "state": state}
            if state == "complete" and isinstance(job.get("result"), dict):
                public_variant["imageUrl"] = job["result"].get("imageUrl")
            if job.get("error"):
                public_variant["error"] = job["error"]
            variants.append(public_variant)
        terminal_states = {"complete", "failed", "cancelled"}
        if states and all(state in terminal_states for state in states):
            if any(state == "failed" for state in states):
                status = "failed"
                message = "实验队列已结束，至少一个变体生成失败"
            elif any(state == "cancelled" for state in states):
                status = "failed"
                message = "实验队列已结束，至少一个变体被取消"
            else:
                status = "complete"
                message = "变体均已通过 native 生成队列完成；提示词层变体仅使用文本改写，不代表 embedding 或 token 融合"
        elif states and all(state == "queued" for state in states):
            status = "queued"
            message = "实验变体已进入现有单 worker native 队列"
        else:
            status = "running"
            message = "实验变体正在按现有单 worker native 队列顺序生成"
        locked_fields = ["seed"] if record["kind"] == "model" else ["seed", "modelId"]
        result = {"id": record["id"], "kind": record["kind"], "seed": record["seed"], "lockedFields": locked_fields, "variants": variants, "status": status, "message": message}
        record["status"] = status
        record["message"] = message
        self._persist_experiment(record)
        return result

    def run_experiment(self, payload: ExperimentRequest) -> dict[str, Any]:
        canonical_model_id = str(self.get_model(payload.model_id)["id"])
        if canonical_model_id != payload.model_id:
            payload = payload.model_copy(update={"model_id": canonical_model_id})
        if payload.kind == "model" and len([model for model in self.models() if model.get("status") == "ready"]) < 2:
            raise DreamApiError("MODEL_COMPARISON_UNAVAILABLE", "模型对照至少需要两个已安装且可用的模型")
        experiment_id = f"experiment-{uuid.uuid4().hex[:12]}"
        variants: list[dict[str, Any]] = []
        try:
            for index, spec in enumerate(self._experiment_variants(payload)):
                request = GenerateRequest(
                    prompt=spec["prompt"] or "a serene mountain lake at sunrise",
                    negative_prompt=payload.negative_prompt,
                    model_id=str(spec.get("modelId") or payload.model_id),
                    steps=int(spec["steps"]),
                    cfg=payload.cfg,
                    seed=payload.seed,
                    trace_level="h6",
                )
                job = self.generate(request)
                variants.append({"id": f"{experiment_id}-variant-{index + 1}", "label": spec["label"], "jobId": job["id"], "modelId": request.model_id})
        except Exception:
            for variant in variants:
                try:
                    self.cancel_job(str(variant["jobId"]))
                except DreamApiError:
                    pass
            raise
        record = {
            "id": experiment_id,
            "kind": payload.kind,
            "seed": payload.seed,
            "modelId": payload.model_id,
            "request": payload.model_dump(by_alias=True),
            "variants": variants,
            "status": "queued",
            "message": "实验已加入 native 生成队列；提示词层变体仅使用文本改写",
        }
        with self._experiments_lock:
            self._experiments[experiment_id] = record
            self._persist_experiment(record)
        return self._public_experiment(record)

    def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        with self._experiments_lock:
            record = self._experiments.get(experiment_id)
            if record is None:
                path = self._experiment_path(experiment_id)
                if not path.exists():
                    raise DreamApiError("EXPERIMENT_NOT_FOUND", f"Experiment was not found: {experiment_id}", status_code=404)
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise DreamApiError("EXPERIMENT_INVALID", "Experiment record is invalid", status_code=500) from exc
                self._experiments[experiment_id] = record
            return self._public_experiment(record)

    def research_status(self) -> dict[str, Any]:
        ready = self.config.h7_research_ready()
        return {
            "available": ready,
            "message": "H7 研究引擎已就绪（独立 Debug UNet）" if ready else "H7 研究引擎未安装或构建清单无效",
            "truth": "observed" if ready else "unavailable",
        }

    @staticmethod
    def _is_runtime_trace_document(value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        exported_run_id = value.get("runId")
        total_time = value.get("totalTimeMs")
        return (
            isinstance(exported_run_id, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", exported_run_id) is not None
            and isinstance(total_time, (int, float))
            and not isinstance(total_time, bool)
            and isinstance(value.get("nodes"), list)
        )

    def _trace_location(self, run_id: str) -> tuple[str, Path]:
        resolved_id = run_id
        if run_id == "latest":
            trace_root = self.config.dream_root / "traces"
            trace_files = [path for path in trace_root.glob("*.json") if path.is_file()] if trace_root.exists() else []
            for candidate in sorted(trace_files, key=lambda path: path.stat().st_mtime_ns, reverse=True):
                if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", candidate.stem) is None:
                    continue
                try:
                    value = json.loads(candidate.read_text(encoding="utf-8-sig"))
                    if self._is_runtime_trace_document(value):
                        resolved_id = candidate.stem
                        break
                except (OSError, ValueError, RecursionError):
                    continue
        return resolved_id, self.config.dream_root / "traces" / f"{resolved_id}.json"

    def _read_trace_document(self, run_id: str) -> tuple[str, Path, dict[str, Any] | None]:
        resolved_id, trace_path = self._trace_location(run_id)
        if not self.config.path_under_dream(trace_path) or not trace_path.exists():
            return resolved_id, trace_path, None
        try:
            value = json.loads(trace_path.read_text(encoding="utf-8-sig"))
            if not self._is_runtime_trace_document(value):
                raise DreamApiError("TRACE_INVALID", "Runtime trace has an invalid structure", detail={"path": str(trace_path)})
            return resolved_id, trace_path, value
        except (OSError, ValueError, RecursionError) as exc:
            raise DreamApiError("TRACE_INVALID", "Runtime trace is invalid", detail={"path": str(trace_path)}) from exc

    def _public_latent_frames(self, run_id: str, trace_path: Path, trace: dict[str, Any]) -> list[dict[str, Any]]:
        raw_frames = trace.get("latentPreviewFrames")
        if not isinstance(raw_frames, list):
            return []
        frames: list[dict[str, Any]] = []
        frame_dir = trace_path.parent / run_id
        for raw_frame in raw_frames:
            if not isinstance(raw_frame, dict):
                continue
            file_name = str(raw_frame.get("fileName") or "")
            if Path(file_name).name != file_name or re.fullmatch(r"latent-step-\d{3,}\.png", file_name, re.IGNORECASE) is None:
                continue
            frame_path = frame_dir / file_name
            if not self.config.path_under_dream(frame_path) or not frame_path.is_file():
                continue
            step = self.job_runner._bounded_int(
                raw_frame.get("step"),
                minimum=0,
                maximum=self.job_runner.MAX_LATENT_STEP,
            )
            if step is None:
                continue
            frames.append({
                "step": step,
                "fileName": file_name,
                "truth": "observed",
                "kind": "latent-projection",
                "imageUrl": f"/api/traces/{run_id}/latent/frames/{file_name}",
            })
        return frames

    def _public_latent_telemetry(self, run_id: str, trace_path: Path, trace: dict[str, Any]) -> list[dict[str, Any]]:
        raw_samples = trace.get("latentTelemetry")
        if not isinstance(raw_samples, list):
            return []
        frame_dir = trace_path.parent / run_id
        samples: list[dict[str, Any]] = []
        for raw_sample in raw_samples:
            sample = self.job_runner._validated_latent_sample(raw_sample, frame_dir)
            if sample is None:
                continue
            sample["channels"] = [
                {
                    **channel,
                    "imageUrl": f"/api/traces/{run_id}/latent/frames/{channel['fileName']}",
                }
                for channel in sample["channels"]
            ]
            if "deltaFileName" in sample:
                sample["deltaImageUrl"] = f"/api/traces/{run_id}/latent/frames/{sample['deltaFileName']}"
            samples.append(sample)
        return sorted(samples, key=lambda item: item["step"])

    @staticmethod
    def _safe_attention_id(value: Any) -> str | None:
        if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value) is None:
            return None
        return value

    @classmethod
    def _attention_marker_is_observed(cls, value: dict[str, Any]) -> bool:
        return (
            value.get("contractVersion") == cls.H7_ATTENTION_CONTRACT_VERSION
            and value.get("kind") == "cross-attention"
            and value.get("truth") == "observed"
            and value.get("source") in ("debug-unet", "diffusers-unet")
        )

    def _attention_index_document(self, run_id: str) -> tuple[str, dict[str, Any] | None]:
        resolved_id, trace_path, trace = self._read_trace_document(run_id)
        if trace is None:
            return resolved_id, None
        index_path = trace_path.parent / resolved_id / "attention-index.json"
        if not self.config.path_under_dream(index_path) or not index_path.is_file():
            return resolved_id, None
        try:
            raw = read_bounded_json(index_path, INDEX_BYTES)
        except InvalidArtifact:
            return resolved_id, None
        if not isinstance(raw, dict) or not self._attention_marker_is_observed(raw):
            return resolved_id, None

        identity_research = raw['source'] == 'diffusers-unet'
        evidence = trace.get('evidence')
        backend = evidence.get('backend') if isinstance(evidence, dict) else None
        if (identity_research or backend == 'diffusers-unet') and (
                trace.get('runId') != resolved_id or backend != raw['source'] or not identity_research):
            return resolved_id, None
        try:
            provenance_fields = validate_research_provenance(raw)
        except InvalidArtifact:
            return resolved_id, None
        provenance = provenance_fields.get('provenance')
        visual_root = isinstance(evidence, dict) and (
            evidence.get('referenceKind') == 'visual' or is_visual_model_id(evidence.get('modelId')))
        if ('provenance' in trace or visual_root) and provenance is None:
            return resolved_id, None
        if visual_root and provenance['referenceKind'] != 'visual':
            return resolved_id, None
        if provenance is not None:
            try:
                root_provenance = validate_research_provenance(
                    {'source': backend, 'provenance': trace.get('provenance')})
            except InvalidArtifact:
                return resolved_id, None
            if (root_provenance != provenance_fields or not isinstance(evidence, dict)
                    or evidence.get('modelId') != provenance['modelId']
                    or evidence.get('referenceKind') != provenance['referenceKind']):
                return resolved_id, None

        raw_tokens = raw.get("tokens")
        raw_layers = raw.get("layers")
        raw_maps = raw.get("maps")
        if not isinstance(raw_tokens, list) or not 1 <= len(raw_tokens) <= self.MAX_ATTENTION_TOKENS:
            return resolved_id, None
        if not isinstance(raw_layers, list) or not 1 <= len(raw_layers) <= (32 if identity_research else self.MAX_ATTENTION_LAYERS):
            return resolved_id, None
        if not isinstance(raw_maps, list) or not 1 <= len(raw_maps) <= (30000 if identity_research else self.MAX_ATTENTION_MAPS):
            return resolved_id, None

        tokens: list[dict[str, Any]] = []
        token_slots: set[int] = set()
        for raw_token in raw_tokens:
            if not isinstance(raw_token, dict):
                return resolved_id, None
            slot = raw_token.get("slot")
            token_id = raw_token.get("tokenId")
            text = raw_token.get("text")
            chunk = raw_token.get("chunk")
            weight = raw_token.get("weight")
            if not isinstance(slot, int) or isinstance(slot, bool) or not 0 <= slot < self.MAX_ATTENTION_TOKENS or slot in token_slots:
                return resolved_id, None
            if not isinstance(token_id, int) or isinstance(token_id, bool) or not -(2 ** 31) <= token_id <= 2 ** 31 - 1:
                return resolved_id, None
            if not isinstance(text, str) or not text or len(text) > 128:
                return resolved_id, None
            if not isinstance(chunk, int) or isinstance(chunk, bool) or not 0 <= chunk <= 31:
                return resolved_id, None
            if not self._finite_number(weight) or not 0 <= float(weight) <= 100:
                return resolved_id, None
            token_slots.add(slot)
            tokens.append({"slot": slot, "tokenId": token_id, "text": text, "chunk": chunk, "weight": float(weight)})

        layers: list[dict[str, Any]] = []
        layer_ids: set[str] = set()
        layer_stages: set[str] = set()
        for raw_layer in raw_layers:
            if not isinstance(raw_layer, dict):
                return resolved_id, None
            layer_id = self._safe_attention_id(raw_layer.get("id"))
            stage = raw_layer.get("stage")
            label = raw_layer.get("label")
            if layer_id is None or layer_id in layer_ids or stage not in {"down", "mid", "up"} or (not identity_research and stage in layer_stages):
                return resolved_id, None
            if not isinstance(label, str) or not label or len(label) > 128:
                return resolved_id, None
            layer_ids.add(layer_id)
            layer_stages.add(stage)
            layers.append({"id": layer_id, "stage": stage, "label": label})

        maps: list[dict[str, Any]] = []
        map_ids: set[str] = set()
        map_files: set[str] = set()
        map_selections: set[tuple[int, str, int]] = set()
        for raw_map in raw_maps:
            if not isinstance(raw_map, dict):
                return resolved_id, None
            map_id = self._safe_attention_id(raw_map.get("id"))
            layer_id = self._safe_attention_id(raw_map.get("layerId"))
            file_name = raw_map.get("fileName")
            step = raw_map.get("step")
            token_slot = raw_map.get("tokenSlot")
            width = raw_map.get("width")
            height = raw_map.get("height")
            if map_id is None or map_id in map_ids or layer_id not in layer_ids:
                return resolved_id, None
            if not isinstance(file_name, str) or Path(file_name).name != file_name or re.fullmatch(r"attention-[A-Za-z0-9._-]+\.json", file_name) is None:
                return resolved_id, None
            if not isinstance(step, int) or isinstance(step, bool) or not 0 <= step <= self.MAX_ATTENTION_STEP:
                return resolved_id, None
            if not isinstance(token_slot, int) or isinstance(token_slot, bool) or token_slot not in token_slots:
                return resolved_id, None
            if not isinstance(width, int) or isinstance(width, bool) or not 1 <= width <= self.MAX_ATTENTION_DIMENSION:
                return resolved_id, None
            if not isinstance(height, int) or isinstance(height, bool) or not 1 <= height <= self.MAX_ATTENTION_DIMENSION:
                return resolved_id, None
            if width * height > self.MAX_ATTENTION_VALUES:
                return resolved_id, None
            selection = (step, layer_id, token_slot)
            if file_name in map_files or selection in map_selections:
                return resolved_id, None
            metrics: dict[str, float] = {}
            for metric in ("entropy", "peak", "coverage"):
                metric_value = raw_map.get(metric)
                if not self._finite_number(metric_value) or not 0 <= float(metric_value) <= 1:
                    return resolved_id, None
                metrics[metric] = float(metric_value)
            map_ids.add(map_id)
            map_files.add(file_name)
            map_selections.add(selection)
            maps.append({
                "id": map_id,
                "step": step,
                "layerId": layer_id,
                "tokenSlot": token_slot,
                "width": width,
                "height": height,
                **metrics,
                "fileName": file_name,
            })

        return resolved_id, {
            "contractVersion": self.H7_ATTENTION_CONTRACT_VERSION,
            "kind": "cross-attention",
            "truth": "observed",
            "source": raw['source'],
            **provenance_fields,
            "tokens": sorted(tokens, key=lambda item: item["slot"]),
            "layers": layers,
            "maps": sorted(maps, key=lambda item: (item["step"], item["layerId"], item["tokenSlot"])),
        }

    def attention_index(self, run_id: str) -> dict[str, Any]:
        resolved_id, index = self._attention_index_document(run_id)
        if index is None:
            return {
                "available": False,
                "runId": resolved_id,
                "message": "No validated native H7 attention trace is available",
                "truth": "unavailable",
            }
        public_maps = [
            {
                **{key: value for key, value in item.items() if key != "fileName"},
                "mapUrl": f"/api/traces/{resolved_id}/attention/maps/{item['id']}",
            }
            for item in index["maps"]
        ]
        return {"available": True, "runId": resolved_id, **{**index, "maps": public_maps}}

    def influence(self, run_id: str) -> dict[str, Any]:
        return self.research_traces.influence(run_id)

    def self_attention_index(self, run_id: str) -> dict[str, Any]:
        return self.research_traces.self_attention_index(run_id)

    def self_attention_map(self, run_id: str, map_id: str) -> dict[str, Any]:
        return self.research_traces.self_attention_map(run_id, map_id)

    def attention_map(self, run_id: str, map_id: str) -> dict[str, Any]:
        resolved_id, index = self._attention_index_document(run_id)
        safe_map_id = self._safe_attention_id(map_id)
        if index is None or safe_map_id is None:
            raise DreamApiError("ATTENTION_MAP_NOT_FOUND", "H7 attention map is not available", status_code=404)
        descriptor = next((item for item in index["maps"] if item["id"] == safe_map_id), None)
        if descriptor is None:
            raise DreamApiError("ATTENTION_MAP_NOT_FOUND", "H7 attention map is not available", status_code=404)
        map_path = self.config.dream_root / "traces" / resolved_id / descriptor["fileName"]
        if not self.config.path_under_dream(map_path) or not map_path.is_file():
            raise DreamApiError("ATTENTION_MAP_NOT_FOUND", "H7 attention map is not available", status_code=404)
        try:
            raw = read_bounded_json(map_path, MAP_BYTES)
            provenance_fields = validate_research_provenance(raw)
        except InvalidArtifact as exc:
            raise DreamApiError("ATTENTION_MAP_INVALID", "H7 attention map is invalid", status_code=422) from exc
        if not isinstance(raw, dict) or not self._attention_marker_is_observed(raw) or raw.get('source') != index['source']:
            raise DreamApiError("ATTENTION_MAP_INVALID", "H7 attention map is invalid", status_code=422)
        if provenance_fields.get('provenance') != index.get('provenance'):
            raise DreamApiError("ATTENTION_MAP_INVALID", "H7 attention map provenance does not match its index", status_code=422)
        for key in ("id", "step", "layerId", "tokenSlot", "width", "height", "entropy", "peak", "coverage"):
            if raw.get(key) != descriptor.get(key):
                raise DreamApiError("ATTENTION_MAP_INVALID", "H7 attention map does not match its index", status_code=422)
        values = raw.get("values")
        expected_values = descriptor["width"] * descriptor["height"]
        if not isinstance(values, list) or len(values) != expected_values:
            raise DreamApiError("ATTENTION_MAP_INVALID", "H7 attention map has an invalid value count", status_code=422)
        if any(not self._finite_number(value) or not 0 <= float(value) <= 1 for value in values):
            raise DreamApiError("ATTENTION_MAP_INVALID", "H7 attention map contains invalid values", status_code=422)
        return {
            "available": True,
            "runId": resolved_id,
            "contractVersion": self.H7_ATTENTION_CONTRACT_VERSION,
            "kind": "cross-attention",
            "truth": "observed",
            "source": index['source'],
            **provenance_fields,
            **{key: value for key, value in descriptor.items() if key != "fileName"},
            "values": [float(value) for value in values],
        }

    def _public_runtime_nodes(self, trace: dict[str, Any]) -> list[dict[str, Any]]:
        raw_nodes = trace.get("nodes")
        if not isinstance(raw_nodes, list):
            return []
        nodes: list[dict[str, Any]] = []
        valid_statuses = {"executed", "running", "skipped", "error"}
        for raw_node in raw_nodes:
            if not isinstance(raw_node, dict) or raw_node.get("truth") != "observed":
                continue
            node_id = raw_node.get("id")
            name = raw_node.get("name")
            backend = raw_node.get("backend")
            status = raw_node.get("status")
            if not all(isinstance(value, str) and value for value in (node_id, name, backend)) or status not in valid_statuses:
                continue
            node: dict[str, Any] = {
                "id": node_id,
                "name": name,
                "backend": backend,
                "status": status,
                "truth": "observed",
            }
            shape = raw_node.get("shape")
            if isinstance(shape, str) and shape:
                node["shape"] = shape
            duration = raw_node.get("durationMs")
            if self._finite_number(duration) and float(duration) >= 0:
                node["durationMs"] = int(duration) if float(duration).is_integer() else float(duration)
            expected_calls = raw_node.get("expectedCalls")
            if isinstance(expected_calls, int) and not isinstance(expected_calls, bool) and expected_calls >= 0:
                node["expectedCalls"] = expected_calls
                node["expectedCallsTruth"] = "derived"
            observed_calls = raw_node.get("observedCalls")
            if isinstance(observed_calls, int) and not isinstance(observed_calls, bool) and observed_calls >= 0:
                node["observedCalls"] = observed_calls
                node["observedCallsTruth"] = "observed"
            nodes.append(node)
        return nodes

    @staticmethod
    def _finite_number(value: Any) -> bool:
        try:
            return math.isfinite(float(value))
        except (OverflowError, TypeError, ValueError):
            return False

    def _public_runtime_events(self, trace: dict[str, Any]) -> list[dict[str, Any]]:
        raw_events = trace.get("events")
        if not isinstance(raw_events, list):
            return []
        events: list[dict[str, Any]] = []
        for raw_event in raw_events:
            if not isinstance(raw_event, dict) or raw_event.get("truth") != "observed":
                continue
            phase = raw_event.get("phase")
            label = raw_event.get("label")
            duration = raw_event.get("durationMs")
            if not isinstance(phase, str) or not phase or not isinstance(label, str) or not label:
                continue
            if not self._finite_number(duration) or float(duration) < 0:
                continue
            events.append({
                "phase": phase,
                "label": label,
                "durationMs": int(duration) if float(duration).is_integer() else float(duration),
                "truth": "observed",
            })
        return events

    def _public_trace_evidence(self, trace: dict[str, Any]) -> dict[str, Any]:
        raw_evidence = trace.get("evidence")
        if not isinstance(raw_evidence, dict):
            return {}
        evidence: dict[str, Any] = {}
        for key in ("modelId", "outputPath", "metadataPath", "samplingMethod", "scheduler", "wrapperLogPath"):
            value = raw_evidence.get(key)
            if isinstance(value, str) and value:
                evidence[key] = value
        backend = raw_evidence.get("backend")
        if isinstance(backend, str) and backend:
            evidence["backend"] = backend
            evidence["backendTruth"] = "observed"
        steps = raw_evidence.get("steps")
        if isinstance(steps, int) and not isinstance(steps, bool) and 1 <= steps <= 50:
            evidence["steps"] = steps
        cfg = raw_evidence.get("cfg")
        if isinstance(cfg, (int, float)) and not isinstance(cfg, bool) and self._finite_number(cfg) and 0 <= float(cfg) <= 30:
            evidence["cfg"] = cfg
        peak_vram = raw_evidence.get("peakVramMiB")
        if isinstance(peak_vram, (int, float)) and not isinstance(peak_vram, bool) and self._finite_number(peak_vram) and 0 <= float(peak_vram) <= 2 ** 53 - 1:
            evidence["peakVramMiB"] = peak_vram
        peak_ram = raw_evidence.get("peakRamBytes")
        if isinstance(peak_ram, int) and not isinstance(peak_ram, bool) and 0 <= peak_ram <= 2 ** 53 - 1:
            evidence["peakRamBytes"] = peak_ram
        if evidence:
            evidence["truth"] = "observed"
        return evidence

    def runtime_trace(self, run_id: str) -> dict[str, Any]:
        resolved_id, trace_path, value = self._read_trace_document(run_id)
        if value is None:
            return {"available": False, "runId": resolved_id, "message": "No native runtime trace is available", "truth": "unavailable"}
        total_time = value.get("totalTimeMs")
        result = {
            "available": True,
            "truth": "observed",
            "runId": resolved_id,
            "totalTimeMs": float(total_time) if self._finite_number(total_time) and float(total_time) >= 0 else 0,
            "nodes": self._public_runtime_nodes(value),
            "events": self._public_runtime_events(value),
            "evidence": self._public_trace_evidence(value),
        }
        result["latentPreviewFrames"] = self._public_latent_frames(resolved_id, trace_path, value)
        result["latentTelemetry"] = self._public_latent_telemetry(resolved_id, trace_path, value)
        return result

    def trace_runs(self) -> list[dict[str, Any]]:
        trace_root = self.config.dream_root / "traces"
        if not trace_root.exists():
            return []
        trace_files = sorted(
            (path for path in trace_root.glob("*.json") if path.is_file()),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        runs: list[dict[str, Any]] = []
        for trace_path in trace_files:
            run_id = trace_path.stem
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id) is None:
                continue
            try:
                trace = self.runtime_trace(run_id)
                if trace.get("available") is False:
                    continue
                _, attention = self._attention_index_document(run_id)
            except DreamApiError:
                continue
            evidence = trace.get("evidence") if isinstance(trace.get("evidence"), dict) else {}
            summary: dict[str, Any] = {
                "runId": run_id,
                "totalTimeMs": trace.get("totalTimeMs", 0),
                "hasAttention": attention is not None,
                "hasLatent": bool(trace.get("latentPreviewFrames") or trace.get("latentTelemetry")),
                "hasInfluence": self.influence(run_id)["available"],
                "hasSelfAttention": self.self_attention_index(run_id)["available"],
                "modifiedAt": datetime.fromtimestamp(trace_path.stat().st_mtime, tz=timezone.utc).isoformat(),
                "truth": "observed",
            }
            for key in ("modelId", "steps", "backend"):
                if key in evidence:
                    summary[key] = evidence[key]
            runs.append(summary)
            if len(runs) >= 100:
                break
        return runs

    def latent_trace(self, run_id: str) -> dict[str, Any]:
        resolved_id, trace_path, value = self._read_trace_document(run_id)
        if value is None:
            return {"available": False, "runId": resolved_id, "message": "No native runtime trace is available", "truth": "unavailable"}
        frames = self._public_latent_frames(resolved_id, trace_path, value)
        telemetry = self._public_latent_telemetry(resolved_id, trace_path, value)
        if not frames and not telemetry:
            return {"available": False, "runId": resolved_id, "message": "No native latent telemetry is available", "truth": "unavailable"}
        return {
            "available": True,
            "runId": resolved_id,
            "truth": "observed",
            "kind": "latent-state" if telemetry else "latent-projection",
            "frames": frames,
            "telemetry": telemetry,
        }

    def latent_trace_frame(self, run_id: str, file_name: str) -> Path:
        resolved_id, trace_path, value = self._read_trace_document(run_id)
        if value is None:
            raise DreamApiError("TRACE_FRAME_NOT_FOUND", "Latent frame is not available", status_code=404)
        frames = self._public_latent_frames(resolved_id, trace_path, value)
        telemetry = self._public_latent_telemetry(resolved_id, trace_path, value)
        declared_files = {frame["fileName"] for frame in frames}
        declared_files.update(channel["fileName"] for sample in telemetry for channel in sample["channels"])
        declared_files.update(sample["deltaFileName"] for sample in telemetry if "deltaFileName" in sample)
        if file_name not in declared_files:
            raise DreamApiError("TRACE_FRAME_NOT_FOUND", "Latent frame is not available", status_code=404)
        frame_path = trace_path.parent / resolved_id / file_name
        if not self.config.path_under_dream(frame_path) or not frame_path.is_file():
            raise DreamApiError("TRACE_FRAME_NOT_FOUND", "Latent frame is not available", status_code=404)
        return frame_path

    def settings(self) -> dict[str, Any]:
        path = self.config.dream_root / "data" / "settings.json"
        defaults: dict[str, Any] = {
            "dreamRoot": str(self.config.dream_root),
            "modelsPath": str(self.config.dream_root / "models"),
            "outputsPath": str(self.config.dream_root / "outputs"),
            "historyPath": str(self.config.dream_root / "history"),
            "cachePath": str(self.config.dream_root / "cache"),
            "logsPath": str(self.config.dream_root / "logs"),
            "autopilotEnabled": True,
            "precisionMode": "fp16",
            "fallbackToCpu": True,
            "tileMode": "automatic",
            "vaeMemoryMode": "sliced",
            "attentionSlicing": True,
            "vramThresholdGb": 4,
            "optimizationLevel": "balanced",
        }
        if path.exists():
            try:
                saved = json.loads(path.read_text(encoding="utf-8-sig"))
                if isinstance(saved, dict):
                    defaults.update(saved)
            except (OSError, json.JSONDecodeError):
                pass
        return defaults

    def update_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        current = self.settings()
        current.update(updates)
        path = self.config.dream_root / "data" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        return current

    def export_settings(self) -> dict[str, Any]:
        return self.settings()

    def open_workspace(self, entry: str) -> dict[str, Any]:
        paths = {
            "base": self.config.dream_root,
            "models": self.config.dream_root / "models",
            "outputs": self.config.dream_root / "outputs",
            "history": self.config.dream_root / "history",
            "cache": self.config.dream_root / "cache",
            "logs": self.config.dream_root / "logs",
        }
        path = paths.get(entry)
        if path is None:
            raise DreamApiError("WORKSPACE_ENTRY_INVALID", "Unknown Dream workspace entry", status_code=422, detail={"entry": entry})
        path.mkdir(parents=True, exist_ok=True)
        try:
            if self.workspace_launcher is not None:
                self.workspace_launcher(path)
            else:
                os.startfile(str(path))
        except OSError as exc:
            raise DreamApiError("WORKSPACE_OPEN_FAILED", str(exc), detail={"path": str(path)}) from exc
        return {"opened": True, "entry": entry, "path": str(path), "truth": "observed"}

    def generate(self, request):
        if request.trace_level in {"h6", "h7"} and max(request.width, request.height) > 1024:
            raise DreamApiError("RESEARCH_RESOLUTION_LIMIT", "H6/H7 研究采集的宽高各限 1024 像素；请缩小分辨率或改为仅阶段耗时。", status_code=422)
        model = self.get_model(request.model_id)
        if model["status"] != "ready":
            raise DreamApiError("MODEL_FILE_MISSING", "Selected model is not available on E:", detail={"modelId": request.model_id, "path": model["path"]})
        selected_engine = self.config.h7_engine_exe if request.trace_level in {"h6", "h7"} else self.config.engine_exe
        if request.trace_level == "h6" and not self.config.h6_conditioning_ready():
            raise DreamApiError("H6_ENGINE_MISSING", "H6 研究引擎未安装或构建清单无效")
        if request.trace_level == "h7" and not self.config.h7_research_ready():
            raise DreamApiError("H7_ENGINE_MISSING", "H7 研究引擎未安装或构建清单无效")
        if not self.config.core_exe.exists() or not selected_engine.exists() or not self.config.wrapper.exists():
            raise DreamApiError("DREAM_DEPENDENCY_MISSING", "Native CUDA generation dependencies are not ready", detail={"dreamCore": str(self.config.core_exe), "engine": str(selected_engine), "wrapper": str(self.config.wrapper)})
        if request.model_id != model["id"]:
            request = request.model_copy(update={"model_id": str(model["id"])})
        return self.job_runner.submit(request)

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self.job_runner.get(job_id)

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return self.job_runner.cancel(job_id)
