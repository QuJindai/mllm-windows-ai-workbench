"""Isolated authorization protocol tests. Never use real login or R2."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

import hq_authorization as auth
from errors import DreamApiError
from hq_service import atomic_json, read_json
from test_hq_routes import client
from test_hq_service import hq, sha


@pytest.fixture
def channel(hq, monkeypatch):
    cli = hq.root.parents[1] / 'tools/hq-depth-r2/node_modules/wrangler/wrangler-dist/cli.js'
    cli.parent.mkdir(parents=True)
    cli.write_text('// Fake CLI; never executed')
    monkeypatch.setattr(auth.shutil, 'which', lambda name: sys.executable)
    atomic_json(hq.session_path, {'token': '1' * 64, 'expiresAt': 1})
    published = []
    def publish(node, cli, payload, digest, temp):
        pending = read_json(temp / 'session.json')
        raw = read_json(payload)
        assert set(raw) == {'version', 'expiresAt'} and raw['version'] == 1
        assert raw['expiresAt'] == pending['expiresAt']
        assert sha(pending['token'].encode()) == digest
        assert 3500000 < raw['expiresAt'] - time.time() * 1000 <= auth.TTL_MS
        assert hq.session_path.read_bytes() == published_before
        hq.r2.session = pending['token']
        published.append((digest, raw))
    published_before = hq.session_path.read_bytes()
    monkeypatch.setattr(auth, '_publish', publish)
    return published


def test_expired_button_capability_is_read_only_and_profile_mode_needs_no_auth(hq, channel):
    status = hq.service.status()
    assert status['error']['code'] == 'HQ_AUTH_EXPIRED'
    assert '一键授权' in status['error']['message']
    assert status['authorization']['available'] is True
    assert not channel and not hq.r2.calls
    profile = hq.service.status('profile')
    assert profile['authorized'] is None and 'authorization' not in profile
    assert not channel and not hq.r2.calls


def test_post_rotates_verifies_and_invalidates_caches_without_generation(client, hq, channel):
    hq.service._person_cache = ('old', float('inf'), [], False)
    hq.service._auth_cache = ('old', float('inf'))
    response = client.post('/api/hq/authorization/renew', json={})
    assert response.status_code == 200
    assert response.json() == {'authorized': True, 'expiresAt': read_json(hq.session_path)['expiresAt'], 'reused': False}
    assert 'no-store' in response.headers['cache-control']
    assert hq.r2.session not in response.text and 'token' not in response.text
    assert len(channel) == 1 and len(hq.r2.calls) == 1
    assert hq.service._person_cache is None and hq.service._auth_cache is None
    assert client.get('/api/hq/status').json()['authorized'] is True
    assert client.get('/api/hq/catalog?kind=person').json()['items']
    assert not hq.boundary.calls and not hq.service.jobs()['jobs']
    assert not list(hq.session_path.parent.glob('.authorize-*'))
    # Retrying after a lost HTTP reply does not issue a second session.
    again = client.post('/api/hq/authorization/renew', json={})
    assert again.json()['reused'] is True and len(channel) == 1


def test_upstream_rejection_after_publish_keeps_old_session(client, hq, channel):
    before = hq.session_path.read_bytes()
    hq.r2.denied = True
    response = client.post('/api/hq/authorization/renew', json={})
    assert response.status_code == 401 and len(channel) == 1
    assert hq.session_path.read_bytes() == before
    assert not list(hq.session_path.parent.glob('.authorize-*'))
    assert hq.r2.session not in response.text


def test_unavailable_cloud_connection_keeps_old_session(client, hq, channel, monkeypatch):
    before = hq.session_path.read_bytes()
    def failed(*args):
        raise DreamApiError('HQ_AUTH_TIMEOUT', '授权连接超时', status_code=504)
    monkeypatch.setattr(auth, '_publish', failed)
    response = client.post('/api/hq/authorization/renew', json={})
    assert response.status_code == 504 and response.json()['code'] == 'HQ_AUTH_TIMEOUT'
    assert hq.session_path.read_bytes() == before
    assert not hq.r2.calls and not list(hq.session_path.parent.glob('.authorize-*'))


@pytest.mark.parametrize('headers', [{'origin': 'https://evil.invalid'}, {'origin': 'null'},
                                    {'sec-fetch-site': 'cross-site'}, {'x-forwarded-for': '127.0.0.1'}])
def test_renew_rejects_cross_site_and_forwarded_requests(client, hq, channel, headers):
    result = client.post('/api/hq/authorization/renew', json={}, headers=headers)
    assert result.status_code == 403 and not channel and not hq.r2.calls


@pytest.mark.parametrize('body', [{'token': 'secret'}, {'account': 'other'}, {'command': 'evil.exe'}, [], None])
def test_renew_does_not_accept_credentials_commands_or_account(client, channel, body):
    result = client.post('/api/hq/authorization/renew', content=json.dumps(body), headers={'content-type':'application/json'})
    assert result.status_code == 422 and not channel
    assert 'secret' not in result.text and 'evil.exe' not in result.text


def test_one_renewal_at_a_time(hq, channel, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    publish = auth._publish
    def held(*args):
        entered.set()
        assert release.wait(5)
        publish(*args)
    monkeypatch.setattr(auth, '_publish', held)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(hq.service.renew_authorization)
        try:
            assert entered.wait(5)
            with pytest.raises(DreamApiError) as error:
                hq.service.renew_authorization()
            assert error.value.code == 'HQ_AUTH_BUSY'
        finally:
            release.set()
        assert first.result(5)['authorized']
    assert len(channel) == 1


def test_session_path_cannot_escape_credentials(hq, channel, tmp_path):
    settings = hq.service._settings()
    settings['sessionFile'] = str(tmp_path / 'outside.json')
    assert auth.capability(hq.root, settings)['error']['code'] == 'HQ_AUTH_CONFIG_INVALID'
    with pytest.raises(DreamApiError):
        auth.renew(hq.root, settings, lambda _: pytest.fail('must not verify'))
    assert not channel


def test_missing_helper_explained_without_executing_it(hq, monkeypatch):
    monkeypatch.setattr(auth.shutil, 'which', lambda _: None)
    assert auth.capability(hq.root, hq.service._settings())['error']['code'] == 'HQ_AUTH_HELPER_MISSING'
    assert not hq.r2.calls


@pytest.mark.parametrize('output,code', [(b'run wrangler login TOP_SECRET', 'HQ_CLOUDFLARE_LOGIN_REQUIRED'),
                                       (b'connect error TOP_SECRET', 'HQ_AUTH_RENEW_FAILED')])
def test_cli_diagnostics_are_redacted_and_command_has_only_digest(tmp_path, monkeypatch, output, code):
    calls = []
    def command(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=1, stdout=output)
    monkeypatch.setattr(auth.subprocess, 'run', command)
    monkeypatch.setenv('CLOUDFLARE_API_TOKEN', 'TOP_SECRET')
    monkeypatch.setenv('NODE_OPTIONS', '--require arbitrary.js')
    monkeypatch.setenv('CLOUDFLARE_ACCOUNT_ID', 'wrong-account')
    with pytest.raises(DreamApiError) as error:
        auth._publish(Path('node'), Path('cli'), tmp_path / 'grant.json', 'a' * 64, tmp_path)
    assert error.value.code == code and 'TOP_SECRET' not in str(error.value)
    args, options = calls[0]
    assert args[5] == auth.BUCKET + '/sessions/v1/' + 'a' * 64 and '--remote' in args
    assert 'CLOUDFLARE_API_TOKEN' not in options['env'] and 'NODE_OPTIONS' not in options['env']
    assert options['env']['WRANGLER_LOG_SANITIZE'] == 'true'
    assert options['timeout'] == 45 and options['stdin'] == subprocess.DEVNULL


def test_private_file_has_owner_system_acl_after_atomic_replace(tmp_path):
    private = tmp_path / 'private'
    private.mkdir()
    auth._restrict(private)
    pending, final = private / 'pending.json', tmp_path / 'final.json'
    auth._private_json(pending, {'token': 'synthetic'})
    os.replace(pending, final)
    assert json.loads(final.read_text()) == {'token': 'synthetic'}
    if os.name != 'nt':
        assert final.stat().st_mode & 0o777 == 0o600
        return
    from ctypes import wintypes
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    get = advapi.GetFileSecurityW
    get.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    get.restype = wintypes.BOOL
    needed = wintypes.DWORD()
    get(str(final), 4, None, 0, ctypes.byref(needed))
    buffer = ctypes.create_string_buffer(needed.value)
    assert get(str(final), 4, buffer, len(buffer), ctypes.byref(needed))
    convert = advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW
    convert.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p]
    convert.restype = wintypes.BOOL
    result = wintypes.LPWSTR()
    assert convert(buffer, 1, 4, ctypes.byref(result), None)
    try:
        assert result.value == f'D:P(A;;FA;;;SY)(A;;FA;;;{auth._windows_user_sid()})'
    finally:
        free = ctypes.WinDLL('kernel32').LocalFree
        free.argtypes = [ctypes.c_void_p]
        free(ctypes.cast(result, ctypes.c_void_p))
