"""History transactions operate only on synthetic files under pytest's tmp_path."""
import importlib
import json
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from errors import DreamApiError
from runtime import DreamRuntime
from test_identity_history import IDENTITY_ID, history_case


@pytest.fixture
def transactions():
    assert importlib.util.find_spec('history_transactions') is not None, 'recoverable history transactions are missing'
    return importlib.import_module('history_transactions')


@pytest.fixture
def case(tmp_path):
    config, runtime, output, metadata, original = history_case(tmp_path)
    paths = [original, output, metadata]
    return config, runtime, paths, {path: path.read_bytes() for path in paths}


def records(root):
    return sorted((root / 'data' / 'history-trash').glob('*/committed.json'))


def assert_saved(saved):
    for path, content in saved.items():
        assert path.read_bytes() == content


def assert_recoverable(root, saved):
    receipts = records(root)
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding='utf-8'))
    assert receipt['item_id'] == IDENTITY_ID
    assert len(receipt['files']) == 3
    recovered = {root / entry['source']: (receipts[0].parent / entry['staged']).read_bytes()
                 for entry in receipt['files']}
    assert recovered == saved
    assert all(not path.exists() for path in saved)


def test_runtime_delete_retains_original_output_and_metadata_for_recovery(case):
    config, runtime, _, saved = case
    assert runtime.delete_history(IDENTITY_ID) == {'deleted': IDENTITY_ID, 'truth': 'observed'}
    assert runtime.history({})['total'] == 0
    assert_recoverable(config.dream_root, saved)


@pytest.mark.parametrize('failed_move', [1, 2, 3])
def test_move_failure_restores_every_file_and_allows_retry(transactions, case, monkeypatch, failed_move):
    config, _, paths, saved = case
    rename = Path.rename

    def fail_one(source, destination):
        if source == paths[failed_move - 1]:
            raise PermissionError('controlled stage failure')
        return rename(source, destination)

    with monkeypatch.context() as fault:
        fault.setattr(Path, 'rename', fail_one)
        with pytest.raises(DreamApiError) as error:
            transactions.delete_history_files(config.dream_root, IDENTITY_ID, paths)
    expected = 'HISTORY_ORIGINAL_DELETE_FAILED' if failed_move == 1 else 'HISTORY_DELETE_FAILED'
    assert error.value.code == expected
    assert error.value.retryable
    assert_saved(saved)
    transactions.delete_history_files(config.dream_root, IDENTITY_ID, paths)
    assert_recoverable(config.dream_root, saved)


class ProcessCrash(BaseException):
    pass


def crash_after_move(transactions, config, paths, monkeypatch, count):
    rename = Path.rename

    def crash(source, destination):
        result = rename(source, destination)
        if source == paths[count - 1]:
            raise ProcessCrash('simulated abrupt process exit after rename')
        return result

    with monkeypatch.context() as fault:
        fault.setattr(Path, 'rename', crash)
        with pytest.raises(ProcessCrash):
            transactions.delete_history_files(config.dream_root, IDENTITY_ID, paths)


@pytest.mark.parametrize('count', [1, 2, 3])
def test_restart_rolls_back_crash_after_move_without_progress_update(transactions, case, monkeypatch, count):
    config, _, paths, saved = case
    crash_after_move(transactions, config, paths, monkeypatch, count)
    assert all(not path.exists() for path in paths[:count])
    transactions.recover_history_transactions(config.dream_root)
    transactions.recover_history_transactions(config.dream_root)
    assert_saved(saved)
    assert records(config.dream_root) == []


def test_runtime_startup_recovers_before_history_is_read(transactions, case, monkeypatch):
    config, _, paths, saved = case
    crash_after_move(transactions, config, paths, monkeypatch, 2)
    restarted = DreamRuntime(config)
    assert restarted.history({})['items'][0]['id'] == IDENTITY_ID
    assert_saved(saved)


def test_commit_cleanup_failure_stays_committed_and_recoverable(transactions, case, monkeypatch):
    config, _, paths, saved = case
    unlink = Path.unlink

    def fail_cleanup(path, *args, **kwargs):
        if path.name == 'journal.json':
            raise PermissionError('controlled postcommit cleanup failure')
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(Path, 'unlink', fail_cleanup)
        transactions.delete_history_files(config.dream_root, IDENTITY_ID, paths)
        transactions.recover_history_transactions(config.dream_root)
    assert_recoverable(config.dream_root, saved)
    transactions.recover_history_transactions(config.dream_root)
    assert_recoverable(config.dream_root, saved)


def test_failed_commit_write_rolls_back_before_reporting_failure(transactions, case, monkeypatch):
    config, _, paths, saved = case
    replace = Path.replace

    def fail_commit(path, destination):
        if Path(destination).name == 'committed.json':
            raise OSError('controlled commit failure')
        return replace(path, destination)

    monkeypatch.setattr(Path, 'replace', fail_commit)
    with pytest.raises(DreamApiError):
        transactions.delete_history_files(config.dream_root, IDENTITY_ID, paths)
    assert_saved(saved)
    assert records(config.dream_root) == []


def test_rollback_failure_keeps_journal_for_restart(transactions, case, monkeypatch):
    config, _, paths, saved = case
    rename = Path.rename

    def fail_stage_and_rollback(source, destination):
        if source == paths[2] or Path(destination) == paths[0]:
            raise PermissionError('controlled rollback failure')
        return rename(source, destination)

    with monkeypatch.context() as fault:
        fault.setattr(Path, 'rename', fail_stage_and_rollback)
        with pytest.raises(DreamApiError) as error:
            transactions.delete_history_files(config.dream_root, IDENTITY_ID, paths)
    assert error.value.code == 'HISTORY_DELETE_RECOVERY_REQUIRED'
    assert list((config.dream_root / 'data' / 'history-trash').glob('*/journal.json'))
    transactions.recover_history_transactions(config.dream_root)
    assert_saved(saved)


@pytest.mark.parametrize('staged_count', [1, 2])
@pytest.mark.parametrize('crash', [False, True])
def test_rollback_preserves_changed_unmoved_metadata(transactions, case, monkeypatch, staged_count, crash):
    config, _, paths, saved = case
    move = transactions._move
    metadata = json.loads(paths[2].read_text(encoding='utf-8'))
    metadata['favorite'] = True
    updated = json.dumps(metadata).encode('utf-8')

    def change_after_staging(root, source, destination):
        if source == paths[staged_count]:
            raise PermissionError('controlled later stage failure')
        move(root, source, destination)
        if source == paths[staged_count - 1]:
            paths[2].write_bytes(updated)
            if crash:
                raise ProcessCrash('exit with already changed, unstaged metadata')

    with monkeypatch.context() as fault:
        fault.setattr(transactions, '_move', change_after_staging)
        with pytest.raises(ProcessCrash if crash else DreamApiError) as error:
            transactions.delete_history_files(config.dream_root, IDENTITY_ID, paths)
    if not crash:
        assert error.value.code == 'HISTORY_DELETE_FAILED'
    restarted = DreamRuntime(config)
    assert_saved({**saved, paths[2]: updated})
    assert restarted.history_item(IDENTITY_ID)['favorite'] is True
    assert not list((config.dream_root / 'data' / 'history-trash').glob('*/journal.json'))


@pytest.mark.parametrize('fail_delete', [False, True])
def test_favorite_waits_for_delete_before_reading_or_writing(transactions, case, monkeypatch, fail_delete):
    config, runtime, paths, saved = case
    move, locked = transactions._move, transactions._locked
    favorite_ready, favorite_done = threading.Event(), threading.Event()
    favorite_result, favorite_errors, during_stage = [], [], []

    def favorite():
        try:
            favorite_result.append(runtime.favorite_history(IDENTITY_ID, True))
        except Exception as exc:
            favorite_errors.append(exc)
        finally:
            favorite_done.set()
            favorite_ready.set()

    worker = threading.Thread(target=favorite, name='favorite-contender', daemon=True)

    @contextmanager
    def observe_lock(root, store):
        if threading.current_thread() is worker:
            favorite_ready.set()
        with locked(root, store):
            yield

    def pause_after_original(root, source, destination):
        if source == paths[1] and fail_delete:
            raise PermissionError('controlled later stage failure')
        move(root, source, destination)
        if source == paths[0]:
            worker.start()
            assert favorite_ready.wait(5), 'favorite never reached its lock or completed'
            during_stage.append((favorite_done.is_set(), paths[2].read_bytes()))

    monkeypatch.setattr(transactions, '_locked', observe_lock)
    monkeypatch.setattr(transactions, '_move', pause_after_original)
    try:
        if fail_delete:
            with pytest.raises(DreamApiError) as error:
                runtime.delete_history(IDENTITY_ID)
        else:
            runtime.delete_history(IDENTITY_ID)
    finally:
        if worker.ident is not None:
            worker.join(5)
    assert not worker.is_alive(), 'favorite remained blocked after deletion ended'
    assert during_stage == [(False, saved[paths[2]])]
    if fail_delete:
        assert error.value.code == 'HISTORY_DELETE_FAILED'
        assert not favorite_errors
        assert favorite_result[0]['favorite'] is True
        assert_saved({path: saved[path] for path in paths[:2]})
        assert DreamRuntime(config).history_item(IDENTITY_ID)['favorite'] is True
    else:
        assert not favorite_result
        assert len(favorite_errors) == 1
        assert isinstance(favorite_errors[0], DreamApiError)
        assert favorite_errors[0].code == 'HISTORY_NOT_FOUND'
        assert_recoverable(config.dream_root, saved)


def test_reentrant_favorite_cannot_mutate_an_active_delete(transactions, case, monkeypatch):
    config, runtime, paths, saved = case
    move = transactions._move
    favorite_errors = []

    def favorite_after_original(root, source, destination):
        if source == paths[1]:
            raise PermissionError('controlled later stage failure')
        move(root, source, destination)
        if source == paths[0]:
            try:
                runtime.favorite_history(IDENTITY_ID, True)
            except DreamApiError as exc:
                favorite_errors.append(exc.code)

    monkeypatch.setattr(transactions, '_move', favorite_after_original)
    with pytest.raises(DreamApiError) as error:
        runtime.delete_history(IDENTITY_ID)
    assert favorite_errors == ['HISTORY_DELETE_BUSY']
    assert error.value.code == 'HISTORY_DELETE_FAILED'
    assert_saved(saved)
    assert DreamRuntime(config).history_item(IDENTITY_ID)['favorite'] is False


def test_favorite_recovers_an_interrupted_delete_before_lookup(transactions, case, monkeypatch):
    config, runtime, paths, saved = case
    crash_after_move(transactions, config, paths, monkeypatch, 2)
    assert runtime.favorite_history(IDENTITY_ID, True)['favorite'] is True
    assert_saved({path: saved[path] for path in paths[:2]})
    assert DreamRuntime(config).history_item(IDENTITY_ID)['favorite'] is True


@pytest.mark.parametrize('unsafe', ['outside', 'traversal', 'profile', 'directory', 'trash', 'duplicate'])
def test_preflight_rejects_unsafe_paths_without_moving_files(transactions, case, tmp_path, unsafe):
    config, _, paths, saved = case
    targets = {
        'outside': tmp_path / 'secret.png',
        'traversal': config.dream_root / 'outputs' / '..' / 'outputs' / paths[1].name,
        'profile': config.dream_root / 'data' / 'identity' / 'profiles' / 'person.json',
        'directory': paths[1].parent,
        'trash': config.dream_root / 'data' / 'history-trash' / 'keep.png',
        'duplicate': paths[0],
    }
    with pytest.raises(DreamApiError) as error:
        transactions.delete_history_files(config.dream_root, IDENTITY_ID, [*paths[:2], targets[unsafe]])
    assert error.value.code == 'HISTORY_DELETE_PATH_INVALID'
    assert_saved(saved)


@pytest.mark.parametrize('target', ['output', 'metadata', 'original', 'trash', 'data'])
def test_symlink_escape_is_rejected_before_staging(transactions, case, tmp_path, target):
    config, _, paths, saved = case
    link = {'output': paths[1], 'metadata': paths[2], 'original': paths[0],
            'trash': config.dream_root / 'data' / 'history-trash',
            'data': config.dream_root / 'data'}[target]
    outside = tmp_path / ('redirect-' + target)
    directory = target in {'data', 'trash'}
    if link.exists():
        link.rename(outside)
    elif directory:
        outside.mkdir()
    try:
        link.symlink_to(outside, target_is_directory=directory)
    except OSError as exc:
        pytest.skip(f'Symlinks unavailable: {exc}')
    with pytest.raises(DreamApiError) as error:
        transactions.delete_history_files(config.dream_root, IDENTITY_ID, paths)
    assert error.value.code == 'HISTORY_DELETE_PATH_INVALID'
    assert_saved(saved)


def test_recovery_never_overwrites_a_recreated_source(transactions, case, monkeypatch):
    config, _, paths, saved = case
    crash_after_move(transactions, config, paths, monkeypatch, 2)
    paths[0].write_bytes(b'new occupant')
    with pytest.raises(DreamApiError) as error:
        transactions.recover_history_transactions(config.dream_root)
    assert error.value.code == 'HISTORY_DELETE_RECOVERY_REQUIRED'
    assert paths[0].read_bytes() == b'new occupant'
    staged_bytes = [p.read_bytes() for p in (config.dream_root / 'data' / 'history-trash').glob('*/*.bin')]
    assert saved[paths[0]] in staged_bytes


@pytest.mark.parametrize('corruption', ['source-traversal', 'staged-traversal', 'oversized', 'malformed'])
def test_recovery_rejects_untrusted_journal_without_touching_files(transactions, case, monkeypatch, corruption):
    config, _, paths, _ = case
    crash_after_move(transactions, config, paths, monkeypatch, 2)
    journal = next((config.dream_root / 'data' / 'history-trash').glob('*/journal.json'))
    before = {p: p.read_bytes() for p in journal.parent.glob('*.bin')}
    value = json.loads(journal.read_text(encoding='utf-8'))
    if corruption == 'source-traversal':
        value['files'][0]['source'] = '../outside.png'
    if corruption == 'staged-traversal':
        value['files'][0]['staged'] = '../../../outside.png'
    journal.write_text('x' * 65537 if corruption == 'oversized' else '{' if corruption == 'malformed'
                       else json.dumps(value), encoding='utf-8')
    with pytest.raises(DreamApiError):
        transactions.recover_history_transactions(config.dream_root)
    assert_saved(before)
    assert not paths[0].exists() and not paths[1].exists()


def test_trash_budget_refuses_new_deletion_and_preserves_prior_commits(transactions, case, monkeypatch):
    config, _, paths, saved = case
    transactions.delete_history_files(config.dream_root, IDENTITY_ID, paths)
    for path, content in saved.items():
        path.write_bytes(content)
    with monkeypatch.context() as limit:
        limit.setattr(transactions, 'MAX_TRASH_BYTES', 1)
        with pytest.raises(DreamApiError) as error:
            transactions.delete_history_files(config.dream_root, IDENTITY_ID, paths)
    assert error.value.code == 'HISTORY_TRASH_FULL'
    assert_saved(saved)
    assert len(records(config.dream_root)) == 1


def test_transaction_count_is_bounded_without_eviction(transactions, case, monkeypatch):
    config, _, paths, saved = case
    transactions.delete_history_files(config.dream_root, IDENTITY_ID, paths)
    for path, content in saved.items():
        path.write_bytes(content)
    monkeypatch.setattr(transactions, 'MAX_TRANSACTIONS', 1)
    with pytest.raises(DreamApiError) as error:
        transactions.delete_history_files(config.dream_root, IDENTITY_ID, paths)
    assert error.value.code == 'HISTORY_TRASH_FULL'
    assert_saved(saved)
    assert len(records(config.dream_root)) == 1


@pytest.mark.parametrize('point', ['staged', 'committed'])
def test_abrupt_subprocess_exit_releases_lock_and_recovers(transactions, case, point):
    config, _, paths, saved = case
    script = '''
import os, sys
from pathlib import Path
from history_transactions import delete_history_files
root, item_id, point, *names = sys.argv[1:]
rename, replace = Path.rename, Path.replace
def stage(source, destination):
    result = rename(source, destination)
    if point == 'staged' and source == Path(names[1]):
        os._exit(73)
    return result
def commit(source, destination):
    result = replace(source, destination)
    if point == 'committed' and Path(destination).name == 'committed.json':
        os._exit(73)
    return result
Path.rename, Path.replace = stage, commit
delete_history_files(Path(root), item_id, map(Path, names))
'''
    result = subprocess.run([sys.executable, '-c', script, str(config.dream_root), IDENTITY_ID,
                             point, *map(str, paths)], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, timeout=15)
    assert result.returncode == 73, result.stderr.decode(errors='replace')
    transactions.recover_history_transactions(config.dream_root)
    if point == 'staged':
        assert_saved(saved)
    else:
        assert_recoverable(config.dream_root, saved)


@pytest.mark.parametrize('operation', ['recovery', 'favorite'])
def test_recovery_cannot_rollback_another_process_active_transaction(transactions, case, tmp_path, operation):
    config, runtime, paths, saved = case
    ready = tmp_path / 'writer-ready'
    script = '''
import sys, time
from pathlib import Path
from history_transactions import delete_history_files
root, item_id, ready, operation, *names = sys.argv[1:]
rename = Path.rename
def stage(source, destination):
    result = rename(source, destination)
    if source == Path(names[1 if operation == 'recovery' else 0]):
        Path(ready).touch()
        time.sleep(15)
    return result
Path.rename = stage
delete_history_files(Path(root), item_id, map(Path, names))
'''
    process = subprocess.Popen([sys.executable, '-c', script, str(config.dream_root), IDENTITY_ID,
                                str(ready), operation, *map(str, paths)], cwd=Path(__file__).resolve().parents[1],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert ready.exists(), 'child did not reach the staged transaction'
        with pytest.raises(DreamApiError) as error:
            if operation == 'recovery':
                transactions.recover_history_transactions(config.dream_root)
            else:
                runtime.favorite_history(IDENTITY_ID, True)
        assert error.value.code == 'HISTORY_DELETE_BUSY'
        assert not paths[0].exists()
        if operation == 'recovery':
            assert not paths[1].exists()
        assert paths[2].read_bytes() == saved[paths[2]]
    finally:
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=10)
    transactions.recover_history_transactions(config.dream_root)
    assert_saved(saved)
