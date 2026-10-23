"""Real loopback/proxy HTTP checks; never launch Dream, a browser, or inference."""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


LAUNCHER = Path(__file__).resolve().parents[2] / "scripts/start_dream_web_background.ps1"
PWSH = shutil.which("pwsh.exe")
DREAM_PAGE = b"<!doctype html><html><head><title>Dream Windows</title></head></html>"
pytestmark = pytest.mark.skipif(os.name != "nt" or not PWSH, reason="Windows PowerShell 7 launcher")


@contextmanager
def http_listener(status: int, content: bytes):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            pass

    # Binding port 0 reserves an OS-selected port without a free-port race.
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server.server_port, requests
        finally:
            server.shutdown()
            thread.join(timeout=5)


def run_launcher(port: int, proxy_port: int):
    # Configure only the child process, not the user's proxy or environment.
    env = {key: value for key, value in os.environ.items()
           if key.lower() not in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}}
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env[key] = f"http://127.0.0.1:{proxy_port}"
    env["DREAM_LAUNCHER_UNDER_TEST"] = str(LAUNCHER)
    # Real port discovery, HTTP readiness and exit behavior remain intact.
    # An erroneous start must fail the test before it can launch anything.
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "function Start-Process { throw 'UNEXPECTED_PROCESS_START' }; "
        f"& $env:DREAM_LAUNCHER_UNDER_TEST -Port {port} -NoBrowser"
    )
    return subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", command],
        env=env, text=True, encoding="utf-8", errors="replace",
        capture_output=True, timeout=20,
    )


def test_existing_dream_listener_is_reused_even_when_proxy_returns_502():
    with http_listener(200, DREAM_PAGE) as (port, requests), http_listener(502, b"proxy failure") as (proxy_port, proxy_requests):
        for _ in range(2):
            result = run_launcher(port, proxy_port)
            output = result.stdout + result.stderr
            assert result.returncode == 0, output
            assert f"DREAM_WEB_ALREADY_RUNNING PID={os.getpid()}" in output
            assert "UNEXPECTED_PROCESS_START" not in output
            assert "DREAM_WEB_READY" not in output
        assert requests == ["/", "/"]
        assert proxy_requests == []


@pytest.mark.parametrize("status,content", [
    (200, b"<title>Other Application</title>"),
    (503, DREAM_PAGE),
])
def test_occupied_unready_listener_is_rejected_even_when_proxy_impersonates_dream(status, content):
    with http_listener(status, content) as (port, requests), http_listener(200, DREAM_PAGE) as (proxy_port, proxy_requests):
        result = run_launcher(port, proxy_port)
        output = result.stdout + result.stderr
        assert result.returncode != 0, output
        assert f"Port {port} is occupied by another application (PID {os.getpid()})" in output
        assert "UNEXPECTED_PROCESS_START" not in output
        assert "DREAM_WEB_ALREADY_RUNNING" not in output
        assert requests == ["/"]
        assert proxy_requests == []
