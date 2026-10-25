"""Recoverable history deletion, with no automatic eviction of committed trash.

The fsynced journal precedes *every* source move. A separate atomically published,
fsynced receipt is the commit point; its presence wins over a leftover journal.
Recovery infers move progress from the files themselves, including a process exit
between rename and bookkeeping. Only synthetic fixtures should exercise this API
in tests. POSIX also fsyncs directories; Windows does not expose directory fsync
through os, so the recovery guarantee there is process-crash, not power-loss.
"""
from __future__ import annotations

import json
import os
import re
import stat
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable

from errors import DreamApiError

MAX_TRASH_BYTES = 2 * 1024**3
MAX_TRANSACTIONS = 1024
MAX_JOURNAL_BYTES = 64 * 1024
MAX_FILES = 6  # output, metadata, original, and at most three visual stages
MAX_BATCH_ITEMS = 16
MAX_BATCH_FILES = MAX_FILES * MAX_BATCH_ITEMS
_LOCK = threading.RLock()
_TX_ID = re.compile(r'[a-f0-9]{32}')
_IDENTITY_ID = re.compile(r'identity-[a-f0-9]{24}')
_BATCH_ID = re.compile(r'batch-[a-f0-9]{24}')


def _path_error() -> DreamApiError:
    return DreamApiError('HISTORY_DELETE_PATH_INVALID', '历史图片存储路径无效，未删除文件', status_code=422)


def _recovery_error() -> DreamApiError:
    return DreamApiError('HISTORY_DELETE_RECOVERY_REQUIRED', '历史删除事务需要恢复，文件已保留，请检查占用或权限后重试', retryable=True)


def _full_error() -> DreamApiError:
    return DreamApiError('HISTORY_TRASH_FULL', '可恢复历史暂存区已达到上限，请先备份并整理暂存区', retryable=True)


def _plain(root: Path, path: Path) -> Path:
    """Reject traversal, ADS, symlinks and Windows reparse points, even dangling ones."""
    path = path if path.is_absolute() else root / path
    relative = path.relative_to(root)
    for part in relative.parts:
        if part in {'.', '..'} or ':' in part or '\\' in part or part.endswith((' ', '.')) or '\0' in part:
            raise ValueError('Unsafe path component')
    if path.resolve() != path.absolute():
        raise ValueError('Redirected path')
    for current in (path, *path.parents):
        try:
            info = current.lstat()
        except FileNotFoundError:
            info = None
        if info is not None and (stat.S_ISLNK(info.st_mode) or
                                 getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError('Redirected path')
        if current == root:
            break
    return path


def _root(value: Path) -> Path:
    root = Path(value).absolute()
    _plain(root, root)
    return root


def validate_history_path(root: Path, path: Path) -> Path:
    """Validate an owned record/artifact path without following redirects."""
    try:
        path = _plain(_root(root), path)
        if path.exists() and not path.is_file():
            raise ValueError('Not a regular file')
        return path
    except (OSError, RuntimeError, ValueError) as exc:
        raise _path_error() from exc


def _valid_id(item_id: Any) -> bool:
    return (isinstance(item_id, str) and 0 < len(item_id.encode('utf-8')) <= 512
            and item_id not in {'.', '..'} and not any(c in item_id for c in '/\\:\0')
            and not any(ord(c) < 32 for c in item_id))


def _source(root: Path, item_id: str, value: Path) -> Path:
    path = _plain(root, value)
    relative = path.relative_to(root)
    history_file = len(relative.parts) >= 2 and relative.parts[0] in {'outputs', 'history', 'exports'}
    original = bool(_IDENTITY_ID.fullmatch(item_id)) and relative == Path('data/identity/originals') / f'{item_id}.png'
    stage = bool(_IDENTITY_ID.fullmatch(item_id)) and relative in {
        Path('data/identity/stages') / item_id / f'{kind}.png' for kind in ('anchor', 'harmonize', 'detail')}
    if not history_file and not original and not stage:
        raise ValueError('Not a history file')
    if path.exists() and not path.is_file():
        raise ValueError('Not a regular file')
    return path


def _sync_directory(path: Path) -> None:
    if os.name != 'nt':
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


@contextmanager
def _locked(root: Path, store: Path):
    # Serialize threads AND separate service processes; recovery cannot race an
    # active deletion. The OS releases the file lock on abrupt process exit.
    with _LOCK:
        lock_path = _plain(root, store / '.lock')
        with lock_path.open('a+b') as handle:
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b'\0')
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise DreamApiError('HISTORY_DELETE_BUSY', '历史删除或恢复正在进行，请稍后重试', retryable=True) from exc
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _directories(root: Path, store: Path) -> list[Path]:
    result = []
    with os.scandir(store) as entries:
        for entry in entries:
            if entry.name == '.lock':
                continue
            path = _plain(root, Path(entry.path))
            if not _TX_ID.fullmatch(entry.name) or not path.is_dir():
                raise ValueError('Unknown trash entry; preserve for inspection')
            result.append(path)
            if len(result) > MAX_TRANSACTIONS:
                raise _full_error()
    return result


def _transaction_files(root: Path, folder: Path) -> list[Path]:
    allowed = {'journal.json', 'journal.json.tmp', 'committed.json', 'committed.json.tmp',
               *(f'{index}.bin' for index in range(MAX_BATCH_FILES))}
    result = []
    with os.scandir(folder) as entries:
        for entry in entries:
            path = _plain(root, Path(entry.path))
            if entry.name not in allowed or not path.is_file():
                raise ValueError('Unknown transaction entry; preserve for inspection')
            result.append(path)
    return result


def _write_record(root: Path, destination: Path, record: dict[str, Any]) -> None:
    encoded = json.dumps(record, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(encoded) > MAX_JOURNAL_BYTES:
        raise ValueError('Journal is too large')
    temporary = _plain(root, destination.with_suffix(destination.suffix + '.tmp'))
    _plain(root, destination)
    # Exclusive temporary creation prevents accidental overwrites on retries.
    with temporary.open('xb') as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(destination)
    _sync_directory(destination.parent)


def _read_record(root: Path, folder: Path, name: str) -> dict[str, Any]:
    path = _plain(root, folder / name)
    with path.open('rb') as handle:
        raw = handle.read(MAX_JOURNAL_BYTES + 1)
    if len(raw) > MAX_JOURNAL_BYTES:
        raise ValueError('Journal is too large')
    value = json.loads(raw)
    if (not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] not in {1, 2, 3}
            or value.get('transaction_id') != folder.name or not _valid_id(value.get('item_id'))):
        raise ValueError('Invalid journal')
    files = value.get('files')
    if value['version'] == 2:
        if (set(value) != {'version', 'transaction_id', 'item_id', 'kind', 'files'}
                or value.get('kind') != 'identity-history-hidden'
                or not _IDENTITY_ID.fullmatch(value['item_id']) or files != []):
            raise ValueError('Invalid identity history tombstone')
        return value
    batch = value['version'] == 3
    if batch:
        members = value.get('member_ids')
        if (set(value) != {'version', 'transaction_id', 'item_id', 'kind', 'member_ids', 'files'}
                or value.get('kind') != 'identity-batch-deleted' or not _BATCH_ID.fullmatch(value['item_id'])
                or not isinstance(members, list) or not 1 <= len(members) <= MAX_BATCH_ITEMS
                or any(not isinstance(member, str) or not _IDENTITY_ID.fullmatch(member) for member in members)
                or len(set(members)) != len(members)):
            raise ValueError('Invalid batch tombstone')
    if not isinstance(files, list) or not (0 if batch else 1) <= len(files) <= (MAX_BATCH_FILES if batch else MAX_FILES):
        raise ValueError('Invalid journal files')
    sources = set()
    for index, entry in enumerate(files):
        if not isinstance(entry, dict) or not isinstance(entry.get('source'), str):
            raise ValueError('Invalid journal file')
        relative = Path(entry['source'])
        if relative.is_absolute() or relative.as_posix() != entry['source']:
            raise ValueError('Invalid source path')
        source = _record_source(root, value, entry)
        if source in sources or entry.get('staged') != f'{index}.bin':
            raise ValueError('Duplicate or redirected journal path')
        sources.add(source)
        for key in ('size', 'device', 'inode'):
            if type(entry.get(key)) is not int or entry[key] < 0:
                raise ValueError('Invalid file identity')
        _plain(root, folder / entry['staged'])
    return value


def _record_source(root: Path, record: dict, entry: dict) -> Path:
    if record['version'] != 3:
        return _source(root, record['item_id'], Path(entry['source']))
    owner = entry.get('owner')
    if owner not in record['member_ids']:
        raise ValueError('Invalid batch file owner')
    path = _source(root, owner, Path(entry['source']))
    relative = path.relative_to(root)
    if relative.parts[0] in {'outputs', 'history', 'exports'} and path.name not in {f'{owner}.png', f'{owner}.json'}:
        raise ValueError('Batch file belongs to another job')
    return path


def _matches(path: Path, entry: dict[str, Any]) -> bool:
    info = path.stat()
    return (stat.S_ISREG(info.st_mode) and info.st_size == entry['size']
            and info.st_dev == entry['device'] and info.st_ino == entry['inode'])


def _move(root: Path, source: Path, destination: Path) -> None:
    _plain(root, source)
    _plain(root, destination)
    if destination.exists():
        raise FileExistsError('Refusing to overwrite a file during history recovery')
    source.rename(destination)
    _sync_directory(destination.parent)
    _sync_directory(source.parent)


def _cleanup_committed(root: Path, folder: Path) -> None:
    # Cleanup is optional: the receipt remains the authoritative commit record.
    for name in ('journal.json.tmp', 'committed.json.tmp', 'journal.json'):
        try:
            _plain(root, folder / name).unlink(missing_ok=True)
        except (OSError, ValueError):
            pass


def _rollback(root: Path, folder: Path, record: dict[str, Any]) -> None:
    pairs = []
    for entry in record['files']:
        source = _record_source(root, record, entry)
        staged = _plain(root, folder / entry['staged'])
        if staged.exists():
            if source.exists() or not _matches(staged, entry):
                raise ValueError('Recovery conflict; preserve both copies')
            pairs.append((staged, source))
        elif not source.exists():
            raise ValueError('Recovery file is missing')
        # With no staged copy, this safe regular file was never moved (or was
        # already restored). Preserve later edits; they must not strand other
        # files in trash. Staged copies still require their original identity
        # and an empty destination, so rollback never overwrites a newer file.
    for staged, source in reversed(pairs):
        _move(root, staged, source)
    # Remove the journal LAST, only after every original location is restored.
    for name in ('journal.json.tmp', 'committed.json.tmp', 'journal.json'):
        _plain(root, folder / name).unlink(missing_ok=True)
    folder.rmdir()
    _sync_directory(folder.parent)


def _recover_locked(root: Path, store: Path) -> None:
    for folder in _directories(root, store):
        files = _transaction_files(root, folder)
        if (folder / 'committed.json').exists():
            record = _read_record(root, folder, 'committed.json')
            if any(not _matches(folder / entry['staged'], entry) for entry in record['files']):
                raise ValueError('Committed trash is incomplete or changed')
            _cleanup_committed(root, folder)
        elif (folder / 'journal.json').exists():
            _rollback(root, folder, _read_record(root, folder, 'journal.json'))
        elif all(path.name == 'journal.json.tmp' for path in files):
            # Exit during initial journal publication: no move could have begun.
            for path in files:
                path.unlink()
            folder.rmdir()
            _sync_directory(store)
        else:
            raise ValueError('Unjournaled trash must be retained for inspection')


def recover_history_transactions(root: Path) -> None:
    """Roll back uncommitted transactions; keep committed trash indefinitely."""
    try:
        root = _root(root)
        store = _plain(root, root / 'data' / 'history-trash')
    except (OSError, RuntimeError, ValueError) as exc:
        raise _path_error() from exc
    if not store.exists():
        return
    try:
        with _locked(root, store):
            _recover_locked(root, store)
    except (OSError, RuntimeError, ValueError) as exc:
        raise _recovery_error() from exc


def _committed_flags_locked(root: Path, store: Path) -> dict[str, dict[str, bool]]:
    flags = {}
    for folder in _directories(root, store):
        if (folder / 'committed.json').exists():
            record = _read_record(root, folder, 'committed.json')
            entry = flags.setdefault(record['item_id'], {'historyDeleted': True})
            if record['version'] == 1:
                entry['resultDeleted'] = True
            elif record['version'] == 3:
                result_owners = {file['owner'] for file in record['files']}
                for member in record['member_ids']:
                    child = flags.setdefault(member, {'historyDeleted': True})
                    if member in result_owners:
                        child['resultDeleted'] = True
    return flags


def history_deletion_flags(root: Path) -> dict[str, dict[str, bool]]:
    """Read authoritative receipts, serialized with staging/commit/rollback.

    File absence (or an I/O failure) alone never means deletion succeeded.
    Read once per public job/batch response, not once per image.
    """
    try:
        root = _root(root)
        store = _plain(root, root / 'data' / 'history-trash')
        if not store.exists():
            return {}
        with _locked(root, store):
            return _committed_flags_locked(root, store)
    except (OSError, RuntimeError, ValueError) as exc:
        raise _recovery_error() from exc


def committed_history_deletions(root: Path) -> set[str]:
    return set(history_deletion_flags(root))


@contextmanager
def history_mutation_lock(root: Path):
    """Serialize metadata mutations with deletion, recovering before lookup.

    Hold this across the entire read/modify/write operation. Other threads wait;
    another process or a same-thread nested mutation receives a retryable busy
    error from the same OS lock used by deletion and startup recovery.
    """
    try:
        root = _root(root)
        store = _plain(root, root / 'data' / 'history-trash')
    except (OSError, RuntimeError, ValueError) as exc:
        raise _path_error() from exc
    try:
        store.mkdir(parents=True, exist_ok=True)
        _sync_directory(store.parent)
        with _locked(root, store):
            _recover_locked(root, store)
            yield set(_committed_flags_locked(root, store))
    except (OSError, RuntimeError, ValueError) as exc:
        raise _recovery_error() from exc


def delete_history_files(root: Path, item_id: str, paths: Iterable[Path] | Callable[[], Iterable[Path]],
                         *, idempotent: bool = False, allow_empty: bool = False,
                         batch_members: dict[str, Callable[[], Iterable[Path]]] | None = None) -> None:
    """Commit files, or an explicit owned identity tombstone, under one lock.

    Lazy path resolution runs after recovery and idempotency lookup. Only the
    identity service, after validating a durable terminal owner, uses allow_empty.
    """
    try:
        root = _root(root)
        batch = batch_members is not None
        if batch and (not _BATCH_ID.fullmatch(item_id) or not 1 <= len(batch_members) <= MAX_BATCH_ITEMS
                      or any(not _IDENTITY_ID.fullmatch(member) for member in batch_members)):
            raise ValueError('Invalid batch members')
        if not _valid_id(item_id) or (allow_empty and not batch and not _IDENTITY_ID.fullmatch(item_id)):
            raise ValueError('Invalid history ID')
        store = _plain(root, root / 'data' / 'history-trash')
    except (OSError, RuntimeError, ValueError) as exc:
        raise _path_error() from exc
    try:
        store.mkdir(parents=True, exist_ok=True)
        _sync_directory(store.parent)
        with _locked(root, store):
            try:
                _recover_locked(root, store)
            except (OSError, RuntimeError, ValueError) as exc:
                raise _recovery_error() from exc
            flags = _committed_flags_locked(root, store)
            if idempotent and item_id in flags:
                return
            try:
                sources = []
                owners = batch_members if batch else {item_id: paths}
                for owner, resolver in owners.items():
                    if batch and owner in flags:
                        continue
                    owned = []
                    for path in resolver() if callable(resolver) else resolver:
                        source = _source(root, owner, Path(path))
                        if source in owned or len(owned) >= MAX_FILES:
                            raise ValueError('Duplicate or excessive history files')
                        owned.append(source)
                    if owned and _IDENTITY_ID.fullmatch(owner):
                        for kind in ('anchor', 'harmonize', 'detail'):
                            stage = _source(root, owner, root / 'data/identity/stages' / owner / f'{kind}.png')
                            if stage not in owned:
                                owned.append(stage)
                    if len(owned) > MAX_FILES:
                        raise ValueError('Excessive history files')
                    sources.extend((owner, path) for path in owned)
                if not sources and not allow_empty:
                    raise ValueError('No history files')
                if len({path for _, path in sources}) != len(sources):
                    raise ValueError('Duplicate batch files')
            except (OSError, RuntimeError, ValueError) as exc:
                raise _path_error() from exc
            files = []
            for owner, path in sources:
                _source(root, owner, path)
                if path.exists():
                    info = path.stat()
                    files.append({'source': path.relative_to(root).as_posix(), 'staged': f'{len(files)}.bin',
                                  'size': info.st_size, 'device': info.st_dev, 'inode': info.st_ino})
                    if batch:
                        files[-1]['owner'] = owner
            if not files and not allow_empty:
                return
            folders = _directories(root, store)
            used = sum(path.stat().st_size for folder in folders for path in _transaction_files(root, folder))
            if len(folders) >= MAX_TRANSACTIONS or used + sum(f['size'] for f in files) + 3 * MAX_JOURNAL_BYTES > MAX_TRASH_BYTES:
                raise _full_error()
            folder = store / uuid.uuid4().hex
            folder.mkdir()
            _sync_directory(store)
            record = {'version': 1, 'transaction_id': folder.name, 'item_id': item_id, 'files': files}
            if batch:
                record.update(version=3, kind='identity-batch-deleted', member_ids=list(batch_members))
                # Validate owner-bound paths before any file is moved.
                for entry in files:
                    _record_source(root, record, entry)
            elif not files:
                record.update(version=2, kind='identity-history-hidden')
            moving = None
            try:
                _write_record(root, folder / 'journal.json', record)
                for entry in files:
                    moving = root / entry['source']
                    if not _matches(moving, entry):
                        raise ValueError('Source changed before staging')
                    _move(root, moving, folder / entry['staged'])
                moving = None
                _write_record(root, folder / 'committed.json', record)
            except Exception as exc:
                # A receipt may already be published when directory fsync fails.
                # Never roll back a transaction that recovery will see committed.
                if not (folder / 'committed.json').exists():
                    try:
                        _rollback(root, folder, record)
                    except (OSError, RuntimeError, ValueError) as recovery_exc:
                        raise _recovery_error() from recovery_exc
                    original = root / 'data' / 'identity' / 'originals' / f'{item_id}.png'
                    if moving == original:
                        raise DreamApiError('HISTORY_ORIGINAL_DELETE_FAILED', '人物原图暂存失败，历史图片和元数据已保留，请检查文件占用或权限后重试', retryable=True) from exc
                    raise DreamApiError('HISTORY_DELETE_FAILED', '历史删除失败，文件已恢复，请检查占用或权限后重试', retryable=True) from exc
            _cleanup_committed(root, folder)
    except (OSError, RuntimeError, ValueError) as exc:
        raise DreamApiError('HISTORY_DELETE_FAILED', '历史删除失败，文件已保留，请检查占用或权限后重试', retryable=True) from exc
