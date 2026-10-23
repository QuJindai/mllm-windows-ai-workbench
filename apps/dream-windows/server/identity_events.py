"""Bounded local worker events; no tensor/image data belongs in this channel."""
from __future__ import annotations

import json
import math
from pathlib import Path

MAX_LINE = 16 * 1024
MAX_READ = 64 * 1024


def emit_event(path, event: dict) -> None:
    if path is None:
        return
    if not isinstance(event, dict):
        raise ValueError('人物事件必须为对象')
    encoded = (json.dumps(event, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')
    if len(encoded) > MAX_LINE:
        raise ValueError('人物事件超过大小限制')
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('ab') as stream:
        stream.write(encoded)
        stream.flush()


def _reject_constant(value):
    raise ValueError('人物事件数值无效')


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('人物事件数值无效')
    return number


def read_events(path, offset: int = 0) -> tuple[list[dict], int]:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError('人物事件偏移无效')
    target = Path(path)
    if not target.exists():
        return [], offset
    with target.open('rb') as stream:
        if stream.seek(0, 2) < offset:
            raise ValueError('人物事件文件被截断')
        stream.seek(offset)
        data = stream.read(MAX_READ)
    events, consumed = [], 0
    for line in data.splitlines(keepends=True):
        try:
            if len(line) > MAX_LINE:
                raise ValueError('人物事件超过大小限制')
            if not line.endswith(b'\n'):
                break
            value = json.loads(line.decode('utf-8'), parse_constant=_reject_constant, parse_float=_finite_float)
            if not isinstance(value, dict):
                raise ValueError('人物事件必须为对象')
        except (ValueError, UnicodeDecodeError) as exc:
            # Commit complete valid events before failing on a later bad line.
            # The next read begins at that bad line and raises; it is never skipped.
            if events:
                return events, offset + consumed
            raise ValueError('人物事件内容无效') from exc
        events.append(value)
        consumed += len(line)
    return events, offset + consumed
