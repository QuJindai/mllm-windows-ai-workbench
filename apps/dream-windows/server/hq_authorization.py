"""Explicit local renewal of the existing private R2 session protocol.

Only a session digest reaches Wrangler. Credentials never pass through the
browser, command line, request payload, or diagnostic output. No login or
renewal runs on import, status reads, page loads, or background timers.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import time

from errors import DreamApiError

TTL_MS = 60 * 60 * 1000
CONFIG = Path(__file__).resolve().parents[3] / 'config/dream/hq-authorization.jsonc'
BUCKET = 'hq-tryon-private-people'


def _fail(code, message, status=503):
    raise DreamApiError(code, message, status_code=status) from None


def _paths(root: Path, settings: dict) -> tuple[Path, Path, Path]:
    # Paths come only from trusted local configuration, never the HTTP body.
    session = settings.get('sessionFile')
    directory = root / 'credentials'
    if (not isinstance(session, str) or not Path(session).is_absolute()
            or directory.is_symlink() or directory.resolve() != directory.absolute()
            or Path(session).is_symlink() or Path(session).resolve().parent != directory.resolve()):
        _fail('HQ_AUTH_CONFIG_INVALID', '人物会话必须保存在本机 HQ credentials 目录内')
    cli = root.parents[1] / 'tools/hq-depth-r2/node_modules/wrangler/wrangler-dist/cli.js'
    node = shutil.which('node')
    if not node or not cli.is_file() or not CONFIG.is_file():
        _fail('HQ_AUTH_HELPER_MISSING', '本机授权组件未就绪，请安装 Dream 配套的 Node.js 和 Wrangler')
    return Path(session), Path(node).resolve(), cli.resolve()


def capability(root: Path, settings: dict) -> dict:
    """Local file check only; does not consult or refresh Cloudflare login."""
    try:
        _paths(root, settings)
        return {'available': True, 'method': 'local-wrangler'}
    except DreamApiError as exc:
        return {'available': False, 'method': 'local-wrangler',
                'error': {'code': exc.code, 'message': exc.message}}


def _windows_user_sid() -> str:
    from ctypes import wintypes
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    open_token = advapi.OpenProcessToken
    open_token.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    open_token.restype = wintypes.BOOL
    get_info = advapi.GetTokenInformation
    get_info.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    get_info.restype = wintypes.BOOL
    convert = advapi.ConvertSidToStringSidW
    convert.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    convert.restype = wintypes.BOOL
    token, length = wintypes.HANDLE(), wintypes.DWORD()
    if not open_token(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise OSError('current user identity unavailable')
    try:
        get_info(token, 1, None, 0, ctypes.byref(length))
        buffer = ctypes.create_string_buffer(length.value)
        if not get_info(token, 1, buffer, len(buffer), ctypes.byref(length)):
            raise OSError('current user identity unavailable')
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        text = wintypes.LPWSTR()
        if not convert(sid, ctypes.byref(text)):
            raise OSError('current user identity unavailable')
        try:
            return text.value
        finally:
            kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))
    finally:
        kernel.CloseHandle(token)


def _restrict(path: Path) -> None:
    """Protect an EMPTY file/directory before writing anything sensitive."""
    if os.name != 'nt':
        path.chmod(0o700 if path.is_dir() else 0o600)
        return
    from ctypes import wintypes
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    convert.restype = wintypes.BOOL
    apply = advapi.SetFileSecurityW
    apply.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    apply.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    descriptor = ctypes.c_void_p()
    # Use the process user's SID, not an elevated file's Administrators owner.
    inherit = 'OICI' if path.is_dir() else ''
    sddl = f'D:P(A;{inherit};FA;;;SY)(A;{inherit};FA;;;{_windows_user_sid()})'
    if not convert(sddl, 1, ctypes.byref(descriptor), None):
        raise OSError('private ACL creation failed')
    try:
        if not apply(str(path), 0x80000004, descriptor):
            raise OSError('private ACL application failed')
    finally:
        kernel.LocalFree(descriptor)


def _private_json(path: Path, value: dict) -> None:
    # Exclusive creation rejects symlinks and existing files. Restrict before
    # writing; the eventual atomic rename preserves this private file's ACL.
    with path.open('xb') as stream:
        _restrict(path)
        stream.write(json.dumps(value, separators=(',', ':')).encode('utf-8'))
        stream.flush()
        os.fsync(stream.fileno())


def _publish(node: Path, cli: Path, payload: Path, digest: str, temp: Path) -> None:
    env = {**os.environ, 'CI': '1', 'WRANGLER_SEND_METRICS': 'false',
           'WRANGLER_LOG': 'error', 'WRANGLER_LOG_SANITIZE': 'true',
           'WRANGLER_LOG_PATH': str(temp / 'wrangler.log')}
    # Do not allow an inherited account selector or global-key login to change
    # the pinned owner or silently replace the user's existing OAuth login.
    for key in ('CLOUDFLARE_ACCOUNT_ID', 'CF_ACCOUNT_ID', 'CLOUDFLARE_API_KEY', 'CF_API_KEY',
                'CLOUDFLARE_EMAIL', 'CF_EMAIL', 'CLOUDFLARE_API_TOKEN', 'CF_API_TOKEN', 'NODE_OPTIONS',
                'CLOUDFLARE_API_BASE_URL', 'WRANGLER_API_ENVIRONMENT'):
        env.pop(key, None)
    args = [str(node), str(cli), 'r2', 'object', 'put', f'{BUCKET}/sessions/v1/{digest}',
            '--remote', '--file', str(payload), '--content-type', 'application/json',
            '--config', str(CONFIG)]
    try:
        result = subprocess.run(args, cwd=temp, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=45, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired:
        _fail('HQ_AUTH_TIMEOUT', '授权连接超时，原会话已保留；请检查网络后重试', 504)
    except OSError:
        _fail('HQ_AUTH_HELPER_MISSING', '本机授权组件无法启动，请检查 Node.js 和 Wrangler')
    if result.returncode:
        # Classify locally. Never include raw CLI output (including exceptions)
        # in HTTP responses or logs.
        diagnostic = (result.stdout or b'')[:65536].decode('utf-8', errors='replace').lower()
        if any(value in diagnostic for value in ('not logged in', 'authentication error', 'wrangler login',
                                                 'invalid_grant', 'code: 10000', 'code: 10001')):
            _fail('HQ_CLOUDFLARE_LOGIN_REQUIRED', '本机 Cloudflare 登录已失效，请完成本机 Cloudflare 登录后再次点击一键授权', 401)
        _fail('HQ_AUTH_RENEW_FAILED', '无法更新图库授权，请检查网络和本机 Cloudflare 账号的 R2 权限后重试；原会话已保留')


def renew(root: Path, settings: dict, verify) -> dict:
    """Called only by explicit POST. verify reads the existing private API."""
    session, node, cli = _paths(root, settings)
    try:
        # Lost-response retries and repeat clicks reuse a verified live session.
        if session.is_file() and session.stat().st_size <= 4096:
            try:
                old = json.loads(session.read_text(encoding='utf-8-sig'))
                expiry = old.get('expiresAt')
                if type(expiry) is int and expiry > int(time.time() * 1000) + 300000:
                    verify(settings)
                    return {'authorized': True, 'expiresAt': expiry, 'reused': True}
            except (ValueError, AttributeError):
                pass
            except DreamApiError as exc:
                if exc.code not in ('HQ_AUTH_REQUIRED', 'HQ_AUTH_EXPIRED'):
                    raise
        session.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=session.parent, prefix='.authorize-') as folder:
            temp = Path(folder)
            _restrict(temp)
            token = secrets.token_hex(32)
            expiry = int(time.time() * 1000) + TTL_MS
            digest = hashlib.sha256(token.encode()).hexdigest()
            pending, payload = temp / 'session.json', temp / 'grant.json'
            _private_json(pending, {'token': token, 'expiresAt': expiry})
            _private_json(payload, {'version': 1, 'expiresAt': expiry})
            _publish(node, cli, payload, digest, temp)
            # A successful R2 PUT alone is not authorization success. Verify the
            # new credential through the real private API before replacing old.
            verify({**settings, 'sessionFile': str(pending)})
            os.replace(pending, session)
            return {'authorized': True, 'expiresAt': expiry, 'reused': False}
    except (OSError, ValueError):
        _fail('HQ_AUTH_STORAGE_FAILED', '无法安全保存图库授权，原会话已保留；请检查本机凭据目录权限')
