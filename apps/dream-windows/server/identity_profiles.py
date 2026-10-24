"""Named local identity bindings; all operations share the service owner lease."""
from __future__ import annotations

import copy
from datetime import datetime
import logging
import re
import secrets
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from errors import DreamApiError
from identity_contract import IdentityGenerateRequest
from identity_models import VISUAL_MODEL_ID
from identity_service import JOB_PATTERN, REFERENCE_PATTERN, TERMINAL, WorkerCancelled, atomic_json, read_json, request_reference_kind


PROFILE_PATTERN = r"person-[0-9a-f]{24}"
VISUAL_DEFAULTS = {
    "modelId": VISUAL_MODEL_ID, "width": 768, "height": 768,
    "steps": 30, "cfg": 5.0, "identityStrength": .8, "structureStrength": 0,
    "faceLoraStrength": 0, "facePolish": False, "animeProfileId": None, "loraId": "",
    "visualPolishMode": "redraw", "visualAnchorStrength": .95, "visualPolishPasses": 1,
}


def timestamp() -> str:
    return datetime.now().astimezone().isoformat()


class ProfileName(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def meaningful_name(cls, value):
        if not value.strip():
            raise ValueError("请输入人物名称")
        return value.strip()


class ProfileCreate(ProfileName):
    referenceId: str = Field(pattern=f"^{REFERENCE_PATTERN}$")
    faceIndex: int = Field(ge=0, le=19)
    referenceKind: Literal["faceid", "visual"] = "faceid"


class ProfilePreset(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    jobId: str = Field(pattern=f"^{JOB_PATTERN}$")


class ProfileRecord(ProfileCreate):
    id: str = Field(pattern=f"^{PROFILE_PATTERN}$")
    state: Literal["preparing", "ready", "failed", "archived"]
    featureKey: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")
    featureVersion: int | None = Field(default=None, ge=1)
    defaults: dict
    error: str | None
    createdAt: str
    updatedAt: str


class IdentityProfiles:
    def __init__(self, service):
        self.service = service
        self.records = {}

    def path(self, profile_id):
        self.service._validate_id(profile_id, PROFILE_PATTERN)
        return self.service._safe(self.service.root / "profiles" / f"{profile_id}.json")

    def _save(self, record):
        record = {**record, "updatedAt": timestamp()}
        atomic_json(self.path(record["id"]), record)
        self.records[record["id"]] = record
        return copy.deepcopy(record)

    def recover(self):
        folder = self.service._safe(self.service.root / "profiles")
        for path in sorted(folder.glob("person-*.json")):
            if re.fullmatch(PROFILE_PATTERN, path.stem) is None:
                continue
            try:
                record = read_json(self.path(path.stem))
                ProfileRecord.model_validate(record)
                if record["id"] != path.stem:
                    raise ValueError("档案编号与文件不一致")
                if record["defaults"]:
                    # Visual defaults may have no prompt yet. Loading validates
                    # presets without writing their expanded values to disk.
                    values = {"prompt": "portrait", **record["defaults"], "referenceId": record["referenceId"], "faceIndex": record["faceIndex"]}
                    # The UI's unselected LoRA is '', the request wire value is null.
                    if values.get("loraId") == "":
                        values["loraId"] = None
                    defaults = IdentityGenerateRequest.model_validate(values)
                    if request_reference_kind(defaults) != record.get("referenceKind", "faceid"):
                        raise ValueError("档案预设与参考类型不一致")
                    if record.get("referenceKind", "faceid") == "faceid":
                        # Preserve the legacy public defaults (e.g. facePolish)
                        # while retaining old feature keys and on-disk records.
                        record["defaults"] = {key: value for key, value in defaults.model_dump().items() if key not in {"referenceId", "faceIndex"}}
                    else:
                        for key in ('visualPolishMode', 'visualAnchorStrength', 'visualPolishPasses'):
                            record['defaults'].setdefault(key, getattr(defaults, key))
                if record["state"] == "preparing":
                    record.update(state="failed", error="建档被服务重启中断，请重新创建档案")
                    self._save(record)
                else:
                    self.records[path.stem] = record
            except (OSError, ValueError):
                logging.getLogger(__name__).exception("人物档案 %s 恢复失败，原记录保留", path.stem)

    def get(self, profile_id):
        self.service._validate_id(profile_id, PROFILE_PATTERN)
        if profile_id not in self.records:
            raise DreamApiError("IDENTITY_PROFILE_NOT_FOUND", "人物档案不存在", status_code=404)
        return copy.deepcopy(self.records[profile_id])

    def list(self):
        return sorted((copy.deepcopy(p) for p in self.records.values() if p["state"] != "archived"), key=lambda p: (p["createdAt"], p["id"]), reverse=True)

    def create(self, request: ProfileCreate):
        self.service._validate_face(request.referenceId, request.faceIndex, request.referenceKind)
        profile_id = "person-" + secrets.token_hex(12)
        defaults = dict(VISUAL_DEFAULTS) if request.referenceKind == "visual" else {}
        record = self._save({"id": profile_id, **request.model_dump(), "state": "preparing", "defaults": defaults, "error": None, "createdAt": timestamp()})
        self.service._submit_background(profile_id, lambda event: self._prepare(profile_id, event), lambda: self._interrupted(profile_id))
        return record

    def _interrupted(self, profile_id):
        return self._failed(profile_id, "建档已随服务关闭而取消，请重新创建档案")

    def _failed(self, profile_id, message):
        record = {**self.records[profile_id], "state": "failed", "error": message}
        try:
            return self._save(record)
        except OSError:
            logging.getLogger(__name__).exception("人物档案 %s 失败状态保存失败，原记录保留供重启恢复", profile_id)
            record.update(error=f"{message}；状态未能保存，请检查磁盘，原记录将在重启后恢复", updatedAt=timestamp())
            self.records[profile_id] = record
            return copy.deepcopy(record)

    def _prepare(self, profile_id, cancelled):
        s = self.service
        try:
            if cancelled.is_set():
                raise WorkerCancelled()
            record = self.get(profile_id)
            kind = record.get("referenceKind", "faceid")
            s._validate_face(record["referenceId"], record["faceIndex"], kind)
            s.job_runner.release_native_for_identity()
            payload = {"imagePath": str(s.reference_image(record["referenceId"])), "faceIndex": record["faceIndex"], "dreamRoot": str(s.config.dream_root), "configPath": str(s.config_path)}
            if kind != "faceid":
                payload["referenceKind"] = kind
            result = s._worker("prepare", payload, cancelled)
            if result.get("ok") is not True or not isinstance(result.get("featureKey"), str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", result["featureKey"]) is None or type(result.get("cacheHit")) is not bool:
                raise ValueError("人物特征准备结果无效")
            if result.get("referenceKind", kind) != kind:
                raise ValueError("人物特征准备结果与档案参考类型不一致")
            with s._lock:
                if cancelled.is_set():
                    raise WorkerCancelled()
                prepared = {**self.records[profile_id], "state": "ready", "featureKey": result["featureKey"], "featureVersion": result.get("featureVersion"), "error": None}
                ProfileRecord.model_validate(prepared)
                self._save(prepared)
        except Exception as exc:
            with s._lock:
                if cancelled.is_set() or isinstance(exc, WorkerCancelled):
                    self._interrupted(profile_id)
                else:
                    self._failed(profile_id, f"人物建档失败：{exc}")

    def rename(self, profile_id, request: ProfileName):
        return self._save({**self.get(profile_id), "name": request.name})

    def archive(self, profile_id):
        record = self.get(profile_id)
        in_use = record["state"] == "preparing" or any(job["state"] not in TERMINAL and job["request"].get("referenceId") == record["referenceId"] and job["request"].get("faceIndex") == record["faceIndex"] for job in self.service._jobs.values())
        if in_use:
            raise DreamApiError("IDENTITY_PROFILE_BUSY", "人物档案正在建档或生成，请等待完成或先取消任务", status_code=409)
        return self._save({**record, "state": "archived"})

    def preset(self, profile_id, request: ProfilePreset):
        record = self.get(profile_id)
        job = self.service.get(request.jobId)
        if record["state"] != "ready" or job["state"] != "complete" or any(job["request"].get(key) != record[key] for key in ("referenceId", "faceIndex")):
            raise DreamApiError("IDENTITY_PRESET_CONFLICT", "仅可将本档案同一人脸的已完成人物任务存为预设", status_code=409)
        validated = IdentityGenerateRequest.model_validate(job["request"])
        if request_reference_kind(validated) != record.get("referenceKind", "faceid"):
            raise DreamApiError("IDENTITY_PRESET_CONFLICT", "任务模型与档案参考类型不一致，不能保存为此档案预设", status_code=409)
        return self._save({**record, "defaults": {k: v for k, v in validated.model_dump().items() if k not in {"referenceId", "faceIndex"}}})
