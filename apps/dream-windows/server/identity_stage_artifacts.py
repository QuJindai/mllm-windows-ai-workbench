"""Immutable, job-scoped visual stages. No inference or service dependencies."""
from __future__ import annotations

import errno
import os
from pathlib import Path
import re
import stat
import tempfile

from PIL import Image


STAGE_KINDS = ('anchor', 'harmonize', 'detail')
MAX_STAGE_BYTES = 16 * 1024 * 1024
JOB_PATTERN = re.compile(r'identity-[a-f0-9]{24}')
TEMP_PATTERN = re.compile(r'\.(?:anchor|harmonize|detail)-[A-Za-z0-9_-]+\.tmp')


def visual_stage_url(job_id, kind):
    if not isinstance(job_id, str) or not JOB_PATTERN.fullmatch(job_id) or kind not in STAGE_KINDS:
        raise ValueError('无效人物阶段编号')
    return f'/api/identity/jobs/{job_id}/stages/{kind}'


def visual_stage_path(item, kind):
    visual_stage_url(item['jobId'], kind)
    root = Path(item['dreamRoot']).absolute()
    path = root / 'data' / 'identity' / 'stages' / item['jobId'] / f'{kind}.png'
    return _safe_stage_path(root, path)


def _safe_stage_path(root, path):
    path.relative_to(root)
    if path.resolve() != path:
        raise ValueError('人物阶段路径被重定向')
    for current in (path, *path.parents):
        try:
            info = current.lstat()
        except FileNotFoundError:
            info = None
        if info is not None and (stat.S_ISLNK(info.st_mode) or
                getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError('人物阶段路径被重定向')
        if current == root:
            break
    return path


def validate_visual_stage(item, kind):
    path = visual_stage_path(item, kind)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_STAGE_BYTES:
        raise ValueError('人物阶段图片不存在或超过大小限制')
    with Image.open(path) as image:
        if image.format != 'PNG' or image.size != (item['width'], item['height']):
            raise ValueError('人物阶段图片格式或尺寸无效')
        image.verify()
    return path


def save_visual_stage(image, item, kind):
    """Publish a full-size PNG atomically; even a competing writer cannot be overwritten."""
    path = visual_stage_path(item, kind)
    if image.size != (item['width'], item['height']):
        raise ValueError('人物阶段图片尺寸与请求不一致')
    if path.exists():
        raise FileExistsError('人物阶段图片已存在，未覆盖')
    path.parent.mkdir(parents=True, exist_ok=True)
    visual_stage_path(item, kind)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w+b', prefix=f'.{kind}-', suffix='.tmp',
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            image.save(stream, format='PNG')
            if stream.tell() > MAX_STAGE_BYTES:
                raise ValueError('人物阶段图片超过大小限制')
            stream.flush()
            os.fsync(stream.fileno())
        visual_stage_path(item, kind)
        # A hard link publishes the already-complete file, failing if the final
        # name exists. replace/rename-with-overwrite would violate immutability.
        os.link(temporary, path)
    finally:
        if temporary is not None:
            # Do not follow a directory redirected while the image was encoded.
            visual_stage_path(item, kind)
            temporary.unlink(missing_ok=True)
    return visual_stage_url(item['jobId'], kind)


def cleanup_visual_stages(item):
    """Remove this job's PNGs and publication temps; preserve originals.

    Call only after the publisher has exited or unwound its save call. Worker
    termination can skip finally, leaving an owned temporary in this directory.
    Never recurse or follow links, including links masquerading as temp files.
    """
    root = Path(item['dreamRoot']).absolute()
    paths = [visual_stage_path(item, kind) for kind in STAGE_KINDS]
    folder = paths[0].parent
    try:
        entries = list(folder.iterdir())
    except FileNotFoundError:
        entries = []
    for entry in entries:
        if TEMP_PATTERN.fullmatch(entry.name):
            safe = _safe_stage_path(root, entry)
            if safe.is_file():
                paths.append(safe)
    for path in paths:
        _safe_stage_path(root, path).unlink(missing_ok=True)
    try:
        folder.rmdir()
    except OSError as exc:
        if exc.errno not in (errno.ENOENT, errno.ENOTEMPTY, errno.EEXIST):
            raise
