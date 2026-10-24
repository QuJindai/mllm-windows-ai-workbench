"""Record-only deletion publication and recovery, on synthetic temporary stores."""
import json
from pathlib import Path

import pytest

from errors import DreamApiError
import history_transactions as transactions


JOB_ID = 'identity-' + 'a' * 24


class ProcessCrash(BaseException):
    pass


@pytest.mark.parametrize('point', ['journal-temp', 'journal', 'commit-temp', 'committed'])
def test_empty_receipt_crash_is_atomic_and_recoverable(tmp_path, monkeypatch, point):
    write = transactions._write_record
    replace = Path.replace

    def crash_write(root, destination, record):
        write(root, destination, record)
        if (point == 'journal' and destination.name == 'journal.json'
                or point == 'committed' and destination.name == 'committed.json'):
            raise ProcessCrash()

    def crash_replace(source, destination):
        if (point == 'journal-temp' and source.name == 'journal.json.tmp'
                or point == 'commit-temp' and source.name == 'committed.json.tmp'):
            raise ProcessCrash()
        return replace(source, destination)

    with monkeypatch.context() as fault:
        fault.setattr(transactions, '_write_record', crash_write)
        fault.setattr(Path, 'replace', crash_replace)
        with pytest.raises(ProcessCrash):
            transactions.delete_history_files(tmp_path, JOB_ID, [], idempotent=True, allow_empty=True)
    assert (JOB_ID in transactions.history_deletion_flags(tmp_path)) is (point == 'committed')
    transactions.recover_history_transactions(tmp_path)
    transactions.recover_history_transactions(tmp_path)
    assert (JOB_ID in transactions.history_deletion_flags(tmp_path)) is (point == 'committed')
    transactions.delete_history_files(tmp_path, JOB_ID, [], idempotent=True, allow_empty=True)
    assert transactions.history_deletion_flags(tmp_path) == {JOB_ID: {'historyDeleted': True}}
    records = list((tmp_path / 'data/history-trash').glob('*/committed.json'))
    assert len(records) == 1
    assert not list(records[0].parent.glob('*.tmp'))


@pytest.mark.parametrize('damage', ['version-bool', 'wrong-kind', 'unknown-field', 'files', 'nonidentity', 'traversal'])
def test_invalid_tombstone_never_becomes_a_deletion_flag(tmp_path, damage):
    transactions.delete_history_files(tmp_path, JOB_ID, [], allow_empty=True)
    path = next((tmp_path / 'data/history-trash').glob('*/committed.json'))
    record = json.loads(path.read_text())
    if damage == 'version-bool':
        record['version'] = True
    elif damage == 'wrong-kind':
        record['kind'] = 'arbitrary-delete'
    elif damage == 'unknown-field':
        record['source'] = '../outside.png'
    elif damage == 'files':
        record['files'] = [{'source': '../outside.png'}]
    elif damage == 'nonidentity':
        record['item_id'] = 'ordinary-image'
    else:
        record['item_id'] = '../' + JOB_ID
    path.write_text(json.dumps(record), encoding='utf-8')
    before = path.read_bytes()
    for read in (transactions.history_deletion_flags, transactions.recover_history_transactions):
        with pytest.raises(DreamApiError) as error:
            read(tmp_path)
        assert error.value.code == 'HISTORY_DELETE_RECOVERY_REQUIRED'
    assert path.read_bytes() == before


def test_empty_record_requires_explicit_identity_scope(tmp_path):
    for item_id, allow_empty in [('ordinary-image', True), (JOB_ID, False)]:
        with pytest.raises(DreamApiError) as error:
            transactions.delete_history_files(tmp_path, item_id, [], allow_empty=allow_empty)
        assert error.value.code == 'HISTORY_DELETE_PATH_INVALID'
    assert transactions.history_deletion_flags(tmp_path) == {}


def test_tombstone_publication_cannot_bypass_trash_limits(tmp_path, monkeypatch):
    transactions.delete_history_files(tmp_path, JOB_ID, [], idempotent=True, allow_empty=True)
    monkeypatch.setattr(transactions, 'MAX_TRANSACTIONS', 1)
    # A replay does not consume capacity, but a new deletion must not be hidden.
    transactions.delete_history_files(tmp_path, JOB_ID, [], idempotent=True, allow_empty=True)
    with pytest.raises(DreamApiError) as error:
        transactions.delete_history_files(tmp_path, 'identity-' + 'b' * 24, [], allow_empty=True)
    assert error.value.code == 'HISTORY_TRASH_FULL'
    assert transactions.history_deletion_flags(tmp_path) == {JOB_ID: {'historyDeleted': True}}
