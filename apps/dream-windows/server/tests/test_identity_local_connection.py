import urllib.error

from persistent_engine import PersistentEngineClient, PersistentEngineUnavailable
from test_persistent_engine import make_config


def test_release_probe_allows_windows_delayed_connection_refusal(tmp_path):
    def transport(method, path, body, timeout):
        # Observed Windows loopback refusal is about 2.05s. A 2s deadline
        # reports timeout instead, which correctly fails ownership closed.
        reason = ConnectionRefusedError(10061, 'refused') if timeout >= 3 else TimeoutError('timed out')
        raise PersistentEngineUnavailable('unavailable') from urllib.error.URLError(reason)
    client = PersistentEngineClient(make_config(tmp_path), transport=transport)
    assert client._release_endpoint() is None
