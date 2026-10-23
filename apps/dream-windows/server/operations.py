"""Read-only, bounded operations diagnostics; never initialize an engine.

Identity submission routes can call ensure_generation_capacity(config) before
persisting or queueing work. Unknown capacity is explicit and does not reject
submission: only an observed value below the blocking threshold does.
"""
from __future__ import annotations

import json
import re
import shutil
import stat
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

from config import DreamServerConfig
from errors import DreamApiError

GIB = 1024 ** 3
WARNING_BYTES = 10 * GIB
BLOCKING_BYTES = 2 * GIB
MAX_RECORDS = 2000
ACTIVE_STATES = {"queued", "preparing", "sampling", "decoding"}
TERMINAL_STATES = {"complete", "failed", "cancelled"}


def _disk_status(config: DreamServerConfig) -> dict[str, Any]:
    free = None
    try:
        measured = shutil.disk_usage(config.dream_root).free
        if type(measured) is int and measured >= 0:
            free = measured
    except (OSError, ValueError):
        pass
    status = "unknown" if free is None else "blocked" if free < BLOCKING_BYTES else "warning" if free < WARNING_BYTES else "ok"
    messages = {
        "unknown": "无法读取数据盘可用空间，请检查磁盘连接与访问权限；容量尚未确认。",
        "blocked": "数据盘可用空间低于 2 GiB，已阻止新生成；请检查空间并手动处理不需要的文件。",
        "warning": "数据盘可用空间低于 10 GiB，请留意后续生成所需空间。",
        "ok": "数据盘可用空间充足。",
    }
    return {
        "status": status, "freeBytes": free,
        "warningBytes": WARNING_BYTES, "blockingBytes": BLOCKING_BYTES,
        "generationAllowed": None if free is None else status != "blocked",
        "message": messages[status],
    }


def ensure_generation_capacity(config: DreamServerConfig) -> dict[str, Any]:
    """Raise a sanitized HTTP 507 error before new work is persisted/queued."""
    result = _disk_status(config)
    if result["status"] == "blocked":
        raise DreamApiError(
            "DISK_SPACE_LOW", result["message"], status_code=507, retryable=True,
            detail={"freeBytes": result["freeBytes"], "minimumFreeBytes": BLOCKING_BYTES},
        )
    return result


def _read_object(path: Path, limit: int) -> dict[str, Any]:
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("record exceeds diagnostic limit")
    value = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("record must be an object")
    return value


def _identifier(value: Any) -> str | None:
    # Export only identifier-shaped values, never arbitrary manifest strings.
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", value):
        return None
    if re.search(r"(?i)(sk-|gh[pousr]_|github_pat_|token|secret|password|bearer)", value):
        return None
    return value


def _release(config: DreamServerConfig) -> dict[str, Any]:
    result = {"status": "unknown", "release": None, "buildId": None, "commit": None}
    try:
        raw = _read_object(config.frontend_dist / "release.json", 64 * 1024)
        result["release"] = _identifier(raw.get("release"))
        result["buildId"] = _identifier(raw.get("buildId"))
        commit = raw.get("commit")
        if isinstance(commit, str) and re.fullmatch(r"[0-9a-fA-F]{7,40}", commit):
            result["commit"] = commit
        if any(result[key] is not None for key in ("release", "buildId", "commit")):
            result["status"] = "known"
    except (OSError, ValueError, RecursionError):
        pass
    return result


def _pending(folder: Path, prefix: str) -> dict[str, Any]:
    """Count persisted states, not inferred running processes or GPU activity."""
    unknown = {"status": "unknown", "pendingCount": None}
    try:
        count = scanned = 0
        for path in folder.iterdir():
            if not path.name.startswith(prefix + "-") or path.suffix != ".json":
                continue
            scanned += 1
            if scanned > MAX_RECORDS:
                return unknown
            state = _read_object(path, 1024 * 1024).get("state")
            if not isinstance(state, str) or state not in ACTIVE_STATES | TERMINAL_STATES:
                return unknown
            count += state in ACTIVE_STATES
        return {"status": "known", "pendingCount": count}
    except (OSError, ValueError, RecursionError):
        return unknown


def _file_check(check_id: str, label: str, path: Path) -> dict[str, str]:
    try:
        status = "ok" if stat.S_ISREG(path.stat().st_mode) else "missing"
    except FileNotFoundError:
        status = "missing"
    except OSError:
        status = "unknown"
    message = {"ok": "文件存在；未执行生成验证。", "missing": "文件缺失，请核对本地安装或前端构建。", "unknown": "无法检查，请核对文件访问权限。"}[status]
    return {"id": check_id, "label": label, "status": status, "message": message}


def _dependencies() -> dict[str, str]:
    try:
        for package in ("fastapi", "uvicorn", "pydantic"):
            metadata.version(package)
        status = "ok"
    except metadata.PackageNotFoundError:
        status = "missing"
    except (OSError, ValueError):
        status = "unknown"
    return {
        "id": "dependencies", "label": "Web 服务依赖", "status": status,
        "message": {"ok": "Web 依赖元数据存在；未加载或验证 GPU 推理依赖。", "missing": "Web 依赖缺失，请核对服务使用的 Python 环境。", "unknown": "无法读取依赖元数据，请检查 Python 环境。"}[status],
    }


def _assets(config: DreamServerConfig) -> dict[str, str]:
    status = "missing"
    try:
        for index, path in enumerate((config.frontend_dist / "assets").iterdir()):
            if index >= MAX_RECORDS:
                status = "unknown"
                break
            if path.suffix == ".js" and stat.S_ISREG(path.stat().st_mode):
                status = "ok"
                break
    except FileNotFoundError:
        pass
    except OSError:
        status = "unknown"
    return {
        "id": "assets", "label": "前端脚本资源", "status": status,
        "message": {"ok": "发现前端脚本；未执行浏览器验证。", "missing": "前端脚本资源缺失，请核对本地构建。", "unknown": "无法确认前端资源，请检查构建与访问权限。"}[status],
    }


def get_operations(config: DreamServerConfig) -> dict[str, Any]:
    """Return only public status, identifiers, counts and static guidance."""
    return {
        "schemaVersion": 1, "service": "dream-web",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "release": _release(config), "disk": _disk_status(config),
        "checks": [
            _file_check("frontend", "前端入口", config.frontend_dist / "index.html"),
            _assets(config),
            _file_check("core", "生成核心", config.core_exe),
            _file_check("engine", "原生生成引擎", config.engine_exe),
            _file_check("wrapper", "生成包装器", config.wrapper),
            _file_check("registry", "模型注册表", config.registry_path),
            _dependencies(),
        ],
        "pendingWork": {
            "source": "persisted-records",
            "ordinary": _pending(config.dream_root / "data/jobs", "job"),
            "identity": _pending(config.dream_root / "data/identity/jobs", "identity"),
            "batches": _pending(config.dream_root / "data/identity/batches", "batch"),
            "message": "数量来自磁盘记录，可能包含中断任务；人物任务与批次分别统计，不相加。缺失、损坏或超出扫描上限时显示未知。",
        },
        "guidance": [
            "诊断只读取状态，不会删除文件、终止进程或自动恢复生成。",
            "服务不可用时，先检查端口是否被占用，再核对前端构建与 Web 依赖；确认进程归属后再手动处理。",
            "重启后请查看历史与批次记录，确认已完成结果，再手动继续未完成任务。",
        ],
    }
