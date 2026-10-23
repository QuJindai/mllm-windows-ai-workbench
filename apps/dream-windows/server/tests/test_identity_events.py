import json

import pytest


@pytest.mark.parametrize('suffix', [b'broken-json\n', b'[]\n', b'x' * (16 * 1024 + 1) + b'\n'], ids=['malformed', 'array', 'oversized'])
def test_valid_prefix_survives_later_bad_event(tmp_path, suffix):
    from identity_events import read_events
    path = tmp_path / 'events.ndjson'
    valid = b'{"type":"item_complete"}\n'
    path.write_bytes(valid + suffix)
    assert read_events(path) == ([{'type': 'item_complete'}], len(valid))
    with pytest.raises(ValueError):
        read_events(path, len(valid))


def test_partial_event_is_not_consumed(tmp_path):
    from identity_events import read_events
    path = tmp_path / 'events.ndjson'
    path.write_bytes(b'{"type":"step"')
    assert read_events(path, 0) == ([], 0)
    path.write_bytes(b'{"type":"step"}\n')
    assert read_events(path, 0) == ([{'type': 'step'}], 16)


def test_event_roundtrip_and_incremental_offset(tmp_path):
    from identity_events import emit_event, read_events
    path = tmp_path / 'events.ndjson'
    emit_event(path, {'type': 'step', 'step': 1, 'stage': '采样'})
    first, offset = read_events(path)
    emit_event(path, {'type': 'step', 'step': 2})
    second, end = read_events(path, offset)
    assert first == [{'type': 'step', 'step': 1, 'stage': '采样'}]
    assert second == [{'type': 'step', 'step': 2}]
    assert end > offset
    assert read_events(path, end) == ([], end)


@pytest.mark.parametrize('content', [b'bad\n', b'[]\n', b'{"step":NaN}\n', b'{"step":1e999}\n', b'x' * 17000], ids=['invalid-json','array','nonfinite','overflow','oversized'])
def test_bad_events_fail_closed(tmp_path, content):
    from identity_events import read_events
    path = tmp_path / 'events.ndjson'
    path.write_bytes(content)
    with pytest.raises(ValueError):
        read_events(path)


def test_emitter_rejects_nonfinite_and_oversized_event(tmp_path):
    from identity_events import emit_event
    path = tmp_path / 'events.ndjson'
    for event in ({'step': float('nan')}, {'value': 'x' * 18000}):
        with pytest.raises(ValueError):
            emit_event(path, event)
    assert not path.exists()


def test_read_is_bounded_and_can_continue(tmp_path):
    from identity_events import read_events
    path = tmp_path / 'events.ndjson'
    line = json.dumps({'type': 'step', 'value': 'x' * 900}).encode() + b'\n'
    path.write_bytes(line * 100)
    events, offset = read_events(path)
    assert 0 < len(events) < 100
    assert 0 < offset <= 65536
    remaining, end = read_events(path, offset)
    assert len(events) + len(remaining) == 100
    assert end == len(line) * 100
