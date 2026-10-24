"""Serial multi-image jobs, durable partial results, and validated observations."""
from __future__ import annotations

import copy
from datetime import date
import hashlib
import logging
from pathlib import Path
import re
import secrets
from time import monotonic
from typing import Annotated, Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from errors import DreamApiError
import operations
from identity_contract import IdentityGenerateRequest
from identity_profiles import PROFILE_PATTERN, timestamp
from identity_service import AnimeBinding, JOB_PATTERN, TERMINAL, WorkerCancelled, atomic_json, read_json, request_reference_kind


BATCH_PATTERN = r"batch-[0-9a-f]{24}"
PREVIEW_PATTERN = rf"({JOB_PATTERN})-step-([0-9]{{3}})\.png"
StepNumber = Annotated[int, Field(ge=1, le=50)]


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    profileId: str | None = Field(default=None, pattern=f"^{PROFILE_PATTERN}$")
    request: IdentityGenerateRequest
    count: int = Field(ge=1, le=8)
    stepValues: list[StepNumber] | None = Field(default=None, min_length=1)
    previewEvery: Literal[0, 5, 10] = 0

    @field_validator("previewEvery", mode="before")
    @classmethod
    def integer_interval(cls, value):
        if type(value) is not int:
            raise ValueError("预览间隔必须是整数")
        return value

    @model_validator(mode="after")
    def bounded_matrix(self):
        if self.stepValues is not None:
            self.stepValues = list(dict.fromkeys(self.stepValues))
            if len(self.stepValues) > 4:
                raise ValueError("最多比较四种采样步数")
        if self.count * len(self.stepValues or [self.request.steps]) > 16:
            raise ValueError("一个批次最多十六张图片")
        # Step overrides must satisfy the complete request contract before any
        # child records are persisted, including research limits and budgets.
        base = self.request.model_dump()
        for steps in self.stepValues or []:
            IdentityGenerateRequest.model_validate({**base, "steps": steps})
        return self


class BatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    id: str = Field(pattern=f"^{JOB_PATTERN}$")
    state: Literal["queued", "preparing", "sampling", "complete", "failed", "cancelled"]
    progress: float = Field(ge=0, le=100)
    message: str
    request: IdentityGenerateRequest
    result: dict | None
    error: str | None
    animeBinding: AnimeBinding | None = None


class BatchRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["failed", "unfinished"]
    idempotencyKey: str = Field(min_length=1, max_length=128)

    @field_validator("idempotencyKey")
    @classmethod
    def nonblank_key(cls, value):
        if not value.strip():
            raise ValueError("重试请求编号不能为空")
        return value


class BatchRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    id: str = Field(pattern=f"^{BATCH_PATTERN}$")
    state: Literal["queued", "preparing", "sampling", "complete", "failed", "cancelled"]
    request: BatchRequest
    items: list[BatchItem] = Field(min_length=1, max_length=16)
    currentItem: int = Field(ge=0, le=16)
    totalItems: int = Field(ge=1, le=16)
    completedItems: int = Field(ge=0, le=16)
    step: int = Field(ge=0, le=50)
    totalSteps: int = Field(ge=0, le=50)
    progress: float = Field(ge=0, le=100)
    stage: str = Field(max_length=120)
    elapsedMs: int = Field(ge=0)
    etaMs: int | None = Field(ge=0)
    previewUrl: str | None
    error: str | None
    createdAt: str
    updatedAt: str
    parentBatchId: str | None = Field(default=None, pattern=f"^{BATCH_PATTERN}$")
    originalItemIndices: list[Annotated[int, Field(ge=0, le=15)]] | None = Field(default=None, min_length=1, max_length=16)
    retryMode: Literal["failed", "unfinished"] | None = None
    retryKeyHash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    type: str
    elapsedMs: int = Field(ge=0, le=86_400_000)


class StageEvent(Event):
    type: Literal["stage"]
    stage: str = Field(min_length=1, max_length=120)
    itemIndex: int | None = Field(default=None, ge=0, le=15)


class StepEvent(Event):
    type: Literal["step"]
    itemIndex: int = Field(ge=0, le=15)
    step: int = Field(ge=1, le=50)
    totalSteps: int = Field(ge=1, le=50)
    previewFile: str | None = Field(default=None, max_length=80)
    previewSource: str | None = Field(default=None, max_length=120)


class CompleteEvent(Event):
    type: Literal["item_complete"]
    itemIndex: int = Field(ge=0, le=15)
    jobId: str = Field(pattern=f"^{JOB_PATTERN}$")


class PreviewErrorEvent(Event):
    type: Literal["preview_error"]
    itemIndex: int = Field(ge=0, le=15)
    message: str = Field(default="中间预览不可用，继续生成", max_length=500)


EVENT_TYPES = {"stage": StageEvent, "step": StepEvent, "item_complete": CompleteEvent, "preview_error": PreviewErrorEvent}


class CompletionPersistenceError(OSError):
    """The output is valid; only its completion commit failed."""


class IdentityBatches:
    def __init__(self, service):
        self.service = service
        self.records = {}
        self.item_owners = {}
        self.samples = {}
        self._pending_completions = {}
        self._execution_started = {}

    def path(self, batch_id):
        self.service._validate_id(batch_id, BATCH_PATTERN)
        return self.service._safe(self.service.root / "batches" / f"{batch_id}.json")

    def work(self, batch_id):
        self.path(batch_id)
        return self.service._safe(self.service.root / "batches" / batch_id)

    def _save(self, record):
        record = {**record, "updatedAt": timestamp()}
        if record["state"] in TERMINAL:
            record["elapsedMs"] = self._execution_elapsed(record)
        atomic_json(self.path(record["id"]), record)
        self.records[record["id"]] = record
        return copy.deepcopy(record)

    def _execution_elapsed(self, record):
        started = self._execution_started.get(record["id"])
        # A monotonic origin exists only for execution owned by this process.
        # Never include queue wait or extrapolate a historical/recovered record.
        return record["elapsedMs"] if started is None else max(record["elapsedMs"], round((monotonic() - started) * 1000))

    def get(self, batch_id, *, live_elapsed=True):
        with self.service._lock:
            self.path(batch_id)
            if batch_id not in self.records:
                raise DreamApiError("IDENTITY_BATCH_NOT_FOUND", "人物批次不存在", status_code=404)
            record = copy.deepcopy(self.records[batch_id])
            if live_elapsed and record["state"] not in TERMINAL:
                record["elapsedMs"] = self._execution_elapsed(record)
            return record

    def list(self):
        with self.service._lock:
            return sorted((self.get(batch_id) for batch_id in self.records), key=lambda b: (b["createdAt"], b["id"]), reverse=True)

    @staticmethod
    def item_requests(request):
        base = request["request"]
        return [{**base, "seed": (base["seed"] + index) % 2147483648, "steps": steps} for index in range(request["count"]) for steps in (request.get("stepValues") or [base["steps"]])]

    def submit(self, request: BatchRequest):
        s = self.service
        with s._lock:
            s._require_open()
            kind = request_reference_kind(request.request)
            s._validate_face(request.request.referenceId, request.request.faceIndex, kind)
            s.anime_profiles.resolve_request(request.request.model_dump())
            if request.profileId:
                profile = s.profiles.get(request.profileId)
                if profile["state"] != "ready" or profile.get("referenceKind", "faceid") != kind or any(profile[k] != getattr(request.request, k) for k in ("referenceId", "faceIndex")):
                    raise DreamApiError("IDENTITY_PROFILE_CONFLICT", "请选用已准备完成且参考图、人脸选择一致的人物档案", status_code=409)
            frozen = request.model_dump()
            if frozen["request"]["seed"] == "random":
                frozen["request"]["seed"] = secrets.randbelow(2147483648)
            return self._submit_frozen(frozen, self.item_requests(frozen))

    @staticmethod
    def _validate_lineage(record, records):
        """Validate the entire chain; indices always refer to the root matrix."""
        seen = set()
        while True:
            record = BatchRecord.model_validate(record).model_dump()
            if record["id"] in seen:
                raise ValueError("批次来源存在循环")
            seen.add(record["id"])
            items = record["items"]
            if record["totalItems"] != len(items) or len({item["id"] for item in items}) != len(items):
                raise ValueError("批次记录编号或数量无效")
            if record["request"]["request"]["seed"] == "random":
                raise ValueError("原批次种子尚未固定")
            parent_id = record.get("parentBatchId")
            indices = record.get("originalItemIndices")
            if parent_id is None:
                if any(record.get(key) is not None for key in ("originalItemIndices", "retryMode", "retryKeyHash")):
                    raise ValueError("批次来源信息不完整")
                if IdentityBatches.item_requests(record["request"]) != [item["request"] for item in items]:
                    raise ValueError("批次记录参数不一致")
                return
            if (not indices or len(indices) != len(items) or indices != sorted(set(indices))
                    or record.get("retryMode") is None or record.get("retryKeyHash") is None):
                raise ValueError("批次重试来源无效")
            parent = records.get(parent_id)
            if parent is None or parent["state"] not in TERMINAL or record["request"] != parent["request"]:
                raise ValueError("原批次不存在、仍在运行或参数不一致")
            parent_indices = parent.get("originalItemIndices") or list(range(len(parent["items"])))
            originals = dict(zip(parent_indices, parent["items"]))
            for index, item in zip(indices, items):
                original = originals.get(index)
                if (original is None or original["state"] == "complete" or original["request"] != item["request"]
                        or (record["retryMode"] == "failed" and original["state"] != "failed")):
                    raise ValueError("重试图片与原批次不一致")
            record = parent

    def retry(self, batch_id, request: BatchRetryRequest):
        s = self.service
        with s._lock:
            s._require_open()
            self.path(batch_id)
            # Include the parent in the digest so a damaged parentBatchId cannot
            # hide an already committed request during restart recovery.
            key_hash = hashlib.sha256(f"{batch_id}\0{request.idempotencyKey}".encode("utf-8")).hexdigest()
            matches = []
            for path in s._safe(s.root / "batches").glob("batch-*.json"):
                if re.fullmatch(BATCH_PATTERN, path.stem) is None:
                    continue
                try:
                    value = read_json(self.path(path.stem))
                except (OSError, ValueError) as exc:
                    # An unreadable commit marker may reserve this key. Fail
                    # closed rather than accidentally submitting it again.
                    raise DreamApiError("IDENTITY_BATCH_RETRY_CONFLICT", "批次记录无法读取，请检查存储后重试", status_code=409) from exc
                if isinstance(value, dict) and value.get("retryKeyHash") == key_hash:
                    matches.append((path.stem, value))
            if matches:
                saved_id, saved = matches[0]
                if (len(matches) != 1 or saved_id not in self.records or saved.get("parentBatchId") != batch_id
                        or saved.get("retryMode") != request.mode):
                    raise DreamApiError("IDENTITY_BATCH_RETRY_CONFLICT", "重试请求编号已使用或来源记录无效，请检查原批次", status_code=409)
                try:
                    self._validate_lineage(saved, self.records)
                except (ValueError, TypeError, KeyError) as exc:
                    raise DreamApiError("IDENTITY_BATCH_RETRY_CONFLICT", "重试来源记录无效，请检查原批次", status_code=409) from exc
                return self.get(saved_id)
            parent = self.get(batch_id)
            if parent["state"] not in TERMINAL:
                raise DreamApiError("IDENTITY_BATCH_ACTIVE", "原批次仍在运行，请等待结束或先取消", status_code=409)
            try:
                durable = BatchRecord.model_validate(read_json(self.path(batch_id))).model_dump()
                snapshot = BatchRecord.model_validate(parent).model_dump()
                frozen_keys = ("id", "state", "request", "parentBatchId", "originalItemIndices", "retryMode", "retryKeyHash")
                members = lambda record: [(item["id"], item["state"], item["request"]) for item in record["items"]]
                if any(durable[key] != snapshot[key] for key in frozen_keys) or members(durable) != members(snapshot):
                    raise ValueError("原批次终态尚未持久化或记录已变化")
                self._validate_lineage(parent, self.records)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                raise DreamApiError("IDENTITY_BATCH_RETRY_INVALID", "原批次参数、终态或来源记录未完整保存，请检查存储并重启恢复后重试", status_code=409) from exc
            selected = [(index, item) for index, item in enumerate(parent["items"])
                        if item["state"] == "failed" or (request.mode == "unfinished" and item["state"] != "complete")]
            if not selected:
                raise DreamApiError("IDENTITY_BATCH_RETRY_EMPTY", "没有符合条件的待重试图片", status_code=409)
            frozen = copy.deepcopy(parent["request"])
            for _, item in selected:
                params = IdentityGenerateRequest.model_validate(item["request"])
                kind = request_reference_kind(params)
                s._validate_face(params.referenceId, params.faceIndex, kind)
                s.reference_image(params.referenceId)
                resolved = s.anime_profiles.resolve_request(item["request"])
                binding = item.get("animeBinding") or s._jobs.get(item["id"], {}).get("animeBinding")
                if binding and binding != {key: resolved.get("animeProfile", {}).get(key) for key in AnimeBinding.model_fields}:
                    raise DreamApiError("IDENTITY_PROFILE_CONFLICT", "原动漫档案已变化，不能复用此批次", status_code=409)
                if frozen.get("profileId"):
                    profile = s.profiles.get(frozen["profileId"])
                    if (profile["state"] != "ready" or profile.get("referenceKind", "faceid") != kind
                            or any(profile[key] != getattr(params, key) for key in ("referenceId", "faceIndex"))):
                        raise DreamApiError("IDENTITY_PROFILE_CONFLICT", "原人物档案不可用或与批次不一致", status_code=409)
            original_indices = parent.get("originalItemIndices") or list(range(len(parent["items"])))
            # Replayed keys above only read their accepted child. Check runtime
            # readiness and capacity only for new work, under the same lock as
            # key lookup and publication so concurrent retries cannot duplicate it.
            s._require_visual_polish_ready(frozen['request'])
            operations.ensure_generation_capacity(s.config)
            return self._submit_frozen(frozen, [item["request"] for _, item in selected],
                                       parentBatchId=batch_id, originalItemIndices=[original_indices[index] for index, _ in selected],
                                       retryMode=request.mode, retryKeyHash=key_hash)

    def _submit_frozen(self, frozen, requests, **provenance):
        s = self.service
        with s._lock:
            batch_id = "batch-" + secrets.token_hex(12)
            items = [{"id": "identity-" + secrets.token_hex(12), "state": "queued", "progress": 0, "message": "等待批次生成", "request": copy.deepcopy(params), "result": None, "error": None} for params in requests]
            record = {"id": batch_id, "state": "queued", "request": frozen, "items": items, "currentItem": 0, "totalItems": len(items), "completedItems": 0, "step": 0, "totalSteps": 0, "progress": 0, "stage": "等待本地生成队列", "elapsedMs": 0, "etaMs": None, "previewUrl": None, "error": None, "createdAt": timestamp(), **provenance}
            child_paths = [s._job_path(item["id"]) for item in items]
            batch_path = self.path(batch_id)
            if len(set(child_paths)) != len(items) or any(path.exists() for path in [*child_paths, batch_path]) or any(item["id"] in s._jobs for item in items):
                raise DreamApiError("IDENTITY_BATCH_SAVE_FAILED", "批次编号冲突，未保存任务，请重试", status_code=503)
            index_path = s._safe(s.root / "jobs" / "index.json")
            attempted, index_attempted, prior_index = [], False, None
            try:
                if index_path.exists():
                    prior_index = read_json(index_path)
                for path, item in zip(child_paths, items):
                    attempted.append(path)
                    atomic_json(path, item)
                index_attempted = True
                atomic_json(index_path, {"ids": [*s._jobs, *(item["id"] for item in items)]})
                attempted.append(batch_path)
                # The batch record is the commit marker. Publish memory and
                # enqueue only after all durable records have been saved.
                initial = self._save(record)
                for item in items:
                    s._jobs[item["id"]] = item
                    self.item_owners[item["id"]] = batch_id
                s._submit_background(batch_id, lambda event: self._execute(batch_id, event), lambda: self._finish(batch_id, "cancelled", None))
                return initial
            except (OSError, ValueError, RuntimeError) as exc:
                if provenance and batch_id in self.records:
                    # Keep the durable idempotency reservation after acceptance,
                    # even if the executor cannot enqueue the committed child.
                    logging.getLogger(__name__).exception("人物重试批次 %s 入队失败，保留请求编号", batch_id)
                    return self._finish(batch_id, "failed", "重试批次已保存但未能入队，请检查队列后从该子批次重试")
                logging.getLogger(__name__).exception("人物批次 %s 提交保存失败，正在回滚未接受的任务", batch_id)
                cleanup_failed = False
                self.records.pop(batch_id, None)
                for item in items:
                    s._jobs.pop(item["id"], None)
                    self.item_owners.pop(item["id"], None)
                for path in reversed(attempted):
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        cleanup_failed = True
                        logging.getLogger(__name__).exception("人物批次 %s 提交回滚文件失败：%s", batch_id, path)
                if index_attempted:
                    try:
                        if prior_index is None:
                            index_path.unlink(missing_ok=True)
                        else:
                            atomic_json(index_path, prior_index)
                    except OSError:
                        cleanup_failed = True
                        logging.getLogger(__name__).exception("人物批次 %s 提交回滚索引失败，重启时将校验遗留记录", batch_id)
                message = "人物批次未能保存，未启动生成，请检查磁盘后重试"
                if cleanup_failed:
                    message += "；部分未接受的记录未能清理，详情请查看日志"
                raise DreamApiError("IDENTITY_BATCH_SAVE_FAILED", message, status_code=503) from exc

    def output_paths(self, record, item):
        day = date.fromisoformat(record["createdAt"][:10]).isoformat()
        self.service._validate_id(item["id"], JOB_PATTERN)
        folder = self.service._safe(self.service.config.dream_root / "outputs" / day)
        return tuple(self.service._safe(folder / f"{item['id']}{suffix}") for suffix in (".png", ".json"))

    def _complete_item(self, record, index):
        s = self.service
        item = record["items"][index]
        prior = self._pending_completions.get(item["id"], s._jobs.get(item["id"], item))
        if prior["state"] == "complete":
            if item["id"] in self._pending_completions:
                s._jobs[item["id"]] = copy.deepcopy(prior)
            record["items"][index] = copy.deepcopy(prior)
            record["completedItems"] = sum(j["state"] == "complete" for j in record["items"])
            return
        if any(s._jobs.get(previous["id"], previous)["state"] != "complete" for previous in record["items"][:index]):
            raise ValueError("批次完成事件顺序无效")
        output, metadata = self.output_paths(record, item)
        params = item["request"]
        if output.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("批次输出图片超过大小限制")
        with Image.open(output) as image:
            if image.format != "PNG" or image.size != (params["width"], params["height"]):
                raise ValueError("批次输出图片格式或尺寸无效")
            image.verify()
        value = read_json(metadata)
        s._validate_face_polish(item["id"], params, value)
        value.update({"id": item["id"], "model_id": params.get('modelId', 'realistic-vision-v5.1-faceid'), "identity": params, "output": str(output), "prompt": params["prompt"], "negative_prompt": params["negativePrompt"], "seed": params["seed"], "width": params["width"], "height": params["height"], "steps": params["steps"], "cfg": params["cfg"], "generated_at": timestamp()})
        changes = dict(state="complete", progress=100, message="生成完成", error=None, result={"imageUrl": f"/api/history/{item['id']}/image", "metadata": value})
        persistence_error = None
        try:
            atomic_json(metadata, value)
            completed = s._update(item["id"], **changes)
        except OSError as exc:
            # Validation above is authoritative about the output, independently
            # of a failed metadata/job commit. Keep the old durable job and the
            # worker's completion journal for retry; never terminalize that job
            # on disk or let _finish delete these already validated artifacts.
            persistence_error = exc
            warning = "图片已完整生成，但完成状态保存失败；原图和事件记录已保留，请检查磁盘后重启恢复"
            completed = {**prior, **changes, "progress": 99, "message": "图片已保留，完成状态待保存", "error": warning}
            s._jobs[item["id"]] = copy.deepcopy(completed)
            self._pending_completions[item["id"]] = copy.deepcopy(completed)
            logging.getLogger(__name__).exception("人物批次 %s 子任务 %s 完成状态保存失败，保留已验证图片和恢复记录", record["id"], item["id"])
        record["items"][index] = completed
        record["completedItems"] = sum(j["state"] == "complete" for j in record["items"])
        record.update(currentItem=index + 1, step=params["steps"], totalSteps=params["steps"])
        if persistence_error is not None:
            raise CompletionPersistenceError(completed["error"]) from persistence_error

    def _preview_path(self, record, filename):
        match = re.fullmatch(PREVIEW_PATTERN, filename)
        if match is None:
            raise DreamApiError("IDENTITY_PREVIEW_INVALID", "中间预览文件名无效", status_code=422)
        item = next((item for item in record["items"] if item["id"] == match[1]), None)
        if item is None or not 1 <= int(match[2]) <= item["request"]["steps"]:
            raise DreamApiError("IDENTITY_PREVIEW_INVALID", "中间预览不属于该批次或步数无效", status_code=422)
        folder = self.work(record["id"]) / "previews"
        path = self.service._safe(folder / filename)
        if path.resolve().parent != folder.resolve():
            raise DreamApiError("IDENTITY_PREVIEW_INVALID", "中间预览路径无效", status_code=422)
        if not path.is_file():
            raise DreamApiError("IDENTITY_PREVIEW_NOT_FOUND", "中间预览尚未完成或不存在", status_code=404)
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("中间预览超过大小限制")
        with Image.open(path) as image:
            if image.format != "PNG" or max(image.size) > 256:
                raise ValueError("中间预览图片格式或尺寸无效")
            image.verify()
        return path

    def preview(self, batch_id, filename):
        try:
            return self._preview_path(self.get(batch_id), filename)
        except (OSError, ValueError) as exc:
            raise DreamApiError("IDENTITY_PREVIEW_INVALID", "中间预览尚未完成或图片无效，请稍后重试", status_code=422) from exc

    @staticmethod
    def _validated_event(record, value):
        model = EVENT_TYPES.get(value.get("type"))
        if model is None:
            raise ValueError("未知人物工作进程事件")
        event = model.model_validate(value)
        if event.elapsedMs < record["elapsedMs"]:
            raise ValueError("批次事件时间不能倒退")
        index = getattr(event, "itemIndex", None)
        if index is not None and (index >= record["totalItems"] or index > record["completedItems"]):
            raise ValueError("批次事件图片序号无效")
        if isinstance(event, CompleteEvent) and event.jobId != record["items"][index]["id"]:
            raise ValueError("批次完成事件任务编号不一致")
        if isinstance(event, StepEvent):
            item = record["items"][index]
            if index != record["completedItems"] or event.totalSteps != item["request"]["steps"] or event.step > event.totalSteps or (record["currentItem"] == index + 1 and event.step < record["step"]):
                raise ValueError("批次采样步数与请求或顺序不一致")
            if event.previewFile and (not record["request"]["previewEvery"] or event.previewFile != f"{item['id']}-step-{event.step:03d}.png"):
                raise ValueError("中间预览与当前任务或步数不一致")
        return event

    def consume(self, batch_id, value):
        s = self.service
        with s._lock:
            # Worker timestamps start after process/import preparation and can
            # lag a live GET. Validate against the saved worker cursor, not the
            # service execution clock; reads must not alter journal ordering.
            record = self.get(batch_id, live_elapsed=False)
            event = self._validated_event(record, value)
            record["elapsedMs"] = event.elapsedMs
            index = getattr(event, "itemIndex", None)
            if isinstance(event, CompleteEvent):
                self._complete_item(record, index)
            elif isinstance(event, StageEvent):
                record["stage"] = event.stage
                record["etaMs"] = None
                if index is not None and index == record["completedItems"]:
                    if record["currentItem"] != index + 1:
                        record.update(step=0, previewUrl=None)
                    record.update(currentItem=index + 1, totalSteps=record["items"][index]["request"]["steps"])
                    item = record["items"][index]
                    record["items"][index] = s._update(item["id"], message=event.stage)
            elif isinstance(event, PreviewErrorEvent):
                record.update(previewUrl=None, error=f"中间预览不可用：{event.message}")
            elif isinstance(event, StepEvent):
                item = record["items"][index]
                if record["currentItem"] != index + 1:
                    record["previewUrl"] = None
                record.update(state="sampling", currentItem=index + 1, step=event.step, totalSteps=event.totalSteps, stage="采样")
                if event.previewFile:
                    self._preview_path(record, event.previewFile)
                    record["previewUrl"] = f"/api/identity/batches/{batch_id}/previews/{event.previewFile}"
                prior = self.samples.get((batch_id, index))
                if prior and event.step > prior[0] and event.elapsedMs > prior[1]:
                    remaining = sum(j["request"]["steps"] for j in record["items"][index:]) - event.step
                    record["etaMs"] = round((event.elapsedMs - prior[1]) / (event.step - prior[0]) * remaining)
                self.samples[(batch_id, index)] = (event.step, event.elapsedMs)
                if event.step == event.totalSteps:
                    record["etaMs"] = None
                record["items"][index] = s._update(item["id"], state="sampling", progress=min(99, 100 * event.step / event.totalSteps), message=f"正在采样 {event.step}/{event.totalSteps}")
            total = sum(j["request"]["steps"] for j in record["items"])
            observed = sum(j["request"]["steps"] for j in record["items"] if j["state"] == "complete")
            if record["currentItem"] and record["items"][record["currentItem"] - 1]["state"] != "complete":
                observed += record["step"]
            record["progress"] = min(100 if record["completedItems"] == record["totalItems"] else 99, 100 * observed / total)
            self._save(record)

    def _execute(self, batch_id, cancelled):
        s = self.service
        event_path = str(self.work(batch_id) / "events.ndjson")
        try:
            with s._lock:
                if cancelled.is_set():
                    raise WorkerCancelled()
                self._execution_started[batch_id] = monotonic()
                record = self._save({**self.records[batch_id], "state": "preparing", "stage": "准备批次"})
            s.job_runner.release_native_for_identity()
            if cancelled.is_set():
                raise WorkerCancelled()
            items = []
            for item in record["items"]:
                output, metadata = self.output_paths(record, item)
                output.parent.mkdir(parents=True, exist_ok=True)
                items.append({**item["request"], "jobId": item["id"], "imagePath": str(s.reference_image(item["request"]["referenceId"])), "outputPath": str(output), "metadataPath": str(metadata), "dreamRoot": str(s.config.dream_root), "configPath": str(s.config_path)})
                items[-1].update(s.anime_profiles.resolve_request(item['request']))
                s.bind_anime_dispatch(item['id'],items[-1])
            with s._lock:
                s._event_callbacks[event_path] = lambda event: self.consume(batch_id, event)
            result = s._worker("batch", {"items": items, "dreamRoot": str(s.config.dream_root), "configPath": str(s.config_path), "eventPath": event_path, "previewDir": str(self.work(batch_id) / "previews"), "previewEvery": record["request"]["previewEvery"]}, cancelled)
            with s._lock:
                if cancelled.is_set():
                    raise WorkerCancelled()
                record = self.get(batch_id)
                reported = result.get("items")
                if result.get("ok") is not True or not isinstance(reported, list) or [r.get("jobId") for r in reported if isinstance(r, dict)] != [j["id"] for j in record["items"]] or len(reported) != len(items):
                    raise ValueError("人物批次工作进程返回了无效结果")
                for index in range(len(items)):
                    self._complete_item(record, index)
                self._save({**record, "state": "complete", "stage": "生成完成", "progress": 100, "etaMs": 0, "error": None})
        except Exception as exc:
            with s._lock:
                was_cancelled = cancelled.is_set() or isinstance(exc, WorkerCancelled)
                self._finish(batch_id, "cancelled" if was_cancelled else "failed", None if was_cancelled else f"人物批次失败：{exc}")
        finally:
            with s._lock:
                s._event_callbacks.pop(event_path, None)
                self._execution_started.pop(batch_id, None)

    def _finish(self, batch_id, state, error):
        record = self.get(batch_id)
        persistence_errors = [item["id"] for item in record["items"] if item["id"] in self._pending_completions]
        cleanup_errors = []
        for index, item in enumerate(record["items"]):
            prior = self._pending_completions.get(item["id"], self.service._jobs.get(item["id"], item))
            if prior["state"] == "complete":
                record["items"][index] = copy.deepcopy(prior)
                if item["id"] in self._pending_completions:
                    self.service._jobs[item["id"]] = copy.deepcopy(prior)
                continue
            changes = {"state": state, "message": "已取消生成" if state == "cancelled" else "人物批次中断", "result": None, "error": error}
            cleanup_error = self.service._cleanup_incomplete(item["id"], *self.output_paths(record, item))
            if cleanup_error:
                cleanup_errors.append(cleanup_error)
                changes["error"] = "；".join(filter(None, (error, cleanup_error)))
            try:
                record["items"][index] = self.service._update(item["id"], **changes)
            except OSError as exc:
                # Child exit has already completed. Do not keep serving a false
                # running state merely because its durable update failed.
                persistence_errors.append(exc)
                record["items"][index] = {**prior, **changes}
                self.service._jobs[item["id"]] = copy.deepcopy(record["items"][index])
                logging.getLogger(__name__).exception("人物批次 %s 子任务 %s 停止后保存失败，原记录保留供重启恢复", batch_id, item["id"])
        record["completedItems"] = sum(j["state"] == "complete" for j in record["items"])
        record.update(state=state, stage="已取消" if state == "cancelled" else "批次失败", etaMs=None, error=error)
        if cleanup_errors:
            record["error"] = "；".join(filter(None, (error, "部分文件清理失败，请检查文件占用或权限及子任务错误")))
        if any(item["id"] in self._pending_completions for item in record["items"]):
            record["progress"] = min(99, record["progress"])
        elif record["completedItems"] == record["totalItems"]:
            record["progress"] = 100
        persistence_message = "批次已停止，但状态或未完成输出未能完整保存，请检查磁盘；原记录将在重启后恢复"
        if persistence_errors:
            record["error"] = f"{record['error'] or ''} {persistence_message}".strip()
        try:
            return self._save(record)
        except OSError:
            logging.getLogger(__name__).exception("人物批次 %s 停止后保存失败，原记录保留供重启恢复", batch_id)
            record.update(error=f"{record['error'] or ''} {persistence_message}".strip(), updatedAt=timestamp())
            record["elapsedMs"] = self._execution_elapsed(record)
            self.records[batch_id] = record
            return copy.deepcopy(record)

    def cancel(self, batch_id):
        s = self.service
        with s._lock:
            record = self.get(batch_id)
            if record["state"] in TERMINAL:
                return record
            future, event, cancel_queued = s._background[batch_id]
            event.set()
            if future.cancel():
                return cancel_queued()
        future.result()
        return self.get(batch_id)

    def load_for_recovery(self):
        """Validate membership without mutating jobs or outputs under the lease."""
        s = self.service
        folder = s._safe(s.root / "batches")
        candidates, seen, conflicts = {}, set(), set()
        for path in sorted(folder.glob("batch-*.json")):
            if re.fullmatch(BATCH_PATTERN, path.stem) is None:
                continue
            try:
                record = BatchRecord.model_validate(read_json(self.path(path.stem))).model_dump()
                for key in ("parentBatchId", "originalItemIndices", "retryMode", "retryKeyHash"):
                    if record[key] is None:
                        record.pop(key)
                if record["id"] != path.stem or record["totalItems"] != len(record["items"]) or len({item["id"] for item in record["items"]}) != len(record["items"]):
                    raise ValueError("批次记录编号或数量无效")
                for item in record["items"]:
                    self.output_paths(record, item)
                    child_path = s._job_path(item["id"])
                    if child_path.exists():
                        child = BatchItem.model_validate(read_json(child_path)).model_dump()
                        if child["id"] != item["id"] or child["request"] != item["request"]:
                            raise ValueError("批次子任务记录参数不一致")
                ids = {item["id"] for item in record["items"]}
                conflicts.update(seen & ids)
                seen.update(ids)
                candidates[record["id"]] = record
            except (OSError, ValueError, TypeError):
                logging.getLogger(__name__).exception("人物批次 %s 恢复失败，原记录保留", path.stem)
        for batch_id, record in candidates.items():
            try:
                self._validate_lineage(record, candidates)
            except (ValueError, TypeError, KeyError):
                logging.getLogger(__name__).exception("人物批次 %s 来源或参数无效，原记录保留", batch_id)
                continue
            if any(item["id"] in conflicts for item in record["items"]):
                logging.getLogger(__name__).error("人物批次 %s 子任务归属冲突，不能保护未完成输出", batch_id)
                continue
            self.records[batch_id] = record
            self.item_owners.update({item["id"]: batch_id for item in record["items"]})
        return set(self.item_owners)

    def _replay_completions(self, record):
        from identity_events import read_events

        path = self.service._safe(self.work(record["id"]) / "events.ndjson")
        if not path.exists():
            return
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("人物事件文件超过大小限制")
        # Replay has its own observation cursor; saved UI progress may already
        # be ahead of the event being replayed. Never downgrade committed jobs.
        cursor = {**record, "elapsedMs": 0, "completedItems": 0, "currentItem": 0, "step": 0}
        offset = 0
        for _ in range(65):
            events, next_offset = read_events(path, offset)
            for value in events:
                event = self._validated_event(cursor, value)
                index = getattr(event, "itemIndex", None)
                cursor["elapsedMs"] = event.elapsedMs
                if isinstance(event, CompleteEvent):
                    # Valid event plus validated PNG AND metadata are required.
                    # Persist each child before reading a potentially bad tail.
                    try:
                        self._complete_item(record, index)
                    except CompletionPersistenceError:
                        # A storage error must not discard other valid durable
                        # completions later in this same event prefix.
                        pass
                    cursor["completedItems"] = max(cursor["completedItems"], index + 1)
                elif isinstance(event, StepEvent):
                    cursor.update(currentItem=index + 1, step=event.step)
                elif isinstance(event, StageEvent) and index is not None and index == cursor["completedItems"]:
                    if cursor["currentItem"] != index + 1:
                        cursor.update(currentItem=index + 1, step=0)
                record["elapsedMs"] = max(record["elapsedMs"], event.elapsedMs)
            if next_offset == offset:
                return  # An incomplete crash tail is not a completion event.
            offset = next_offset
        raise ValueError("人物事件文件超过读取限制")

    def recover(self):
        s = self.service
        for batch_id, record in list(self.records.items()):
            try:
                for index, item in enumerate(record["items"]):
                    if item["id"] not in s._jobs:
                        s._jobs[item["id"]] = copy.deepcopy(item)
                    record["items"][index] = copy.deepcopy(s._jobs[item["id"]])
                record["completedItems"] = sum(item["state"] == "complete" for item in record["items"])
                if record["state"] not in TERMINAL or any(item["state"] not in TERMINAL for item in record["items"]):
                    try:
                        self._replay_completions(record)
                    except (OSError, ValueError, TypeError, DreamApiError):
                        logging.getLogger(__name__).exception("人物批次 %s 事件恢复中断，保留此前已验证的完成图片", batch_id)
                    finally:
                        self._finish(batch_id, "failed", "批次被服务重启中断，已完成图片已保留，请重新提交剩余任务")
            except (OSError, ValueError, TypeError):
                logging.getLogger(__name__).exception("人物批次 %s 恢复失败，原记录保留", batch_id)
