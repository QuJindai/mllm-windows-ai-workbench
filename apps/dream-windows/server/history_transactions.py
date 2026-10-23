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
from typing import Any, Iterable

from errors import DreamApiError

MAX_TRASH_BYTES = 2 * 1024**3
MAX_TRANSACTIONS = 1024
MAX_JOURNAL_BYTES = 16 * 1024
MAX_FILES = 3
_LOCK = threading.RLock()
_TX_ID = re.compile(r'[a-f0-9]{32}')
_IDENTITY_ID = re.compile(r'identity-[a-f0-9]{24}')


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


def _valid_id(item_id: Any) -> bool:
    return (isinstance(item_id, str) and 0 < len(item_id.encode('utf-8')) <= 512
            and item_id not in {'.', '..'} and not any(c in item_id for c in '/\\:\0')
            and not any(ord(c) < 32 for c in item_id))


def _source(root: Path, item_id: str, value: Path) -> Path:
    path = _plain(root, value)
    relative = path.relative_to(root)
    history_file = len(relative.parts) >= 2 and relative.parts[0] in {'outputs', 'history', 'exports'}
    original = bool(_IDENTITY_ID.fullmatch(item_id)) and relative == Path('data/identity/originals') / f'{item_id}.png'
    if not history_file and not original:
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
               '0.bin', '1.bin', '2.bin'}
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
    if (not isinstance(value, dict) or value.get('version') != 1
            or value.get('transaction_id') != folder.name or not _valid_id(value.get('item_id'))):
        raise ValueError('Invalid journal')
    files = value.get('files')
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError('Invalid journal files')
    sources = set()
    for index, entry in enumerate(files):
        if not isinstance(entry, dict) or not isinstance(entry.get('source'), str):
            raise ValueError('Invalid journal file')
        relative = Path(entry['source'])
        if relative.is_absolute() or relative.as_posix() != entry['source']:
            raise ValueError('Invalid source path')
        source = _source(root, value['item_id'], relative)
        if source in sources or entry.get('staged') != f'{index}.bin':
            raise ValueError('Duplicate or redirected journal path')
        sources.add(source)
        for key in ('size', 'device', 'inode'):
            if type(entry.get(key)) is not int or entry[key] < 0:
                raise ValueError('Invalid file identity')
        _plain(root, folder / entry['staged'])
    return value


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
        source = _source(root, record['item_id'], Path(entry['source']))
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


def committed_history_deletions(root: Path) -> set[str]:
    """Read authoritative receipts, serialized with staging/commit/rollback.

    File absence (or an I/O failure) alone never means deletion succeeded.
    Read once per public job/batch response, not once per image.
    """
    try:
        root = _root(root)
        store = _plain(root, root / 'data' / 'history-trash')
        if not store.exists():
            return set()
        with _locked(root, store):
            return {_read_record(root, folder, 'committed.json')['item_id']
                    for folder in _directories(root, store)
                    if (folder / 'committed.json').exists()}
    except (OSError, RuntimeError, ValueError) as exc:
        raise _recovery_error() from exc


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
            yield
    except (OSError, RuntimeError, ValueError) as exc:
        raise _recovery_error() from exc


def delete_history_files(root: Path, item_id: str, paths: Iterable[Path]) -> None:
    """Stage up to three associated files, then publish a recoverable receipt."""
    try:
        root = _root(root)
        if not _valid_id(item_id):
            raise ValueError('Invalid history ID')
        sources = []
        for path in paths:
            source = _source(root, item_id, Path(path))
            if source in sources or len(sources) >= MAX_FILES:
                raise ValueError('Duplicate or excessive history files')
            sources.append(source)
        if not sources:
            raise ValueError('No history files')
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
            files = []
            for path in sources:
                _source(root, item_id, path)
                if path.exists():
                    info = path.stat()
                    files.append({'source': path.relative_to(root).as_posix(), 'staged': f'{len(files)}.bin',
                                  'size': info.st_size, 'device': info.st_dev, 'inode': info.st_ino})
            if not files:
                return
            folders = _directories(root, store)
            used = sum(path.stat().st_size for folder in folders for path in _transaction_files(root, folder))
            if len(folders) >= MAX_TRANSACTIONS or used + sum(f['size'] for f in files) + 3 * MAX_JOURNAL_BYTES > MAX_TRASH_BYTES:
                raise _full_error()
            folder = store / uuid.uuid4().hex
            folder.mkdir()
            _sync_directory(store)
            record = {'version': 1, 'transaction_id': folder.name, 'item_id': item_id, 'files': files}
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
