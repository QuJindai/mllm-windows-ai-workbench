"""Windows ownership tests: real CPU processes, never models or a live service."""
import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from identity_service import WorkerLifetime
from identity_persistent_worker import PersistentWorkerClient


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Win32 Job Object")


def read_line(process):
    received = queue.Queue()
    thread = threading.Thread(target=lambda: received.put(process.stdout.readline()), daemon=True)
    thread.start()
    line = received.get(timeout=5)
    thread.join(1)
    return json.loads(line)


def kernel():
    from ctypes import wintypes
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    for name, arguments, result in (
        ("OpenProcess", [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        ("WaitForSingleObject", [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        ("TerminateProcess", [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        ("CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
    ):
        function = getattr(api, name)
        function.argtypes, function.restype = arguments, result
    return api


def open_owned(api, pid):
    handle = api.OpenProcess(0x100000 | 0x1000 | 1, False, pid)
    assert handle, ctypes.WinError(ctypes.get_last_error())
    return handle


def cleanup(process, lifetime, handles):
    # Only handles captured from this test's own child protocol are touched.
    api = kernel()
    for handle in handles:
        if api.WaitForSingleObject(handle, 0) == 258:
            api.TerminateProcess(handle, 1)
            assert api.WaitForSingleObject(handle, 5000) == 0
        api.CloseHandle(handle)
    lifetime.close()
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            stream.close()


@pytest.mark.parametrize("launcher_exits", [False, True])
def test_real_job_close_observes_zero_and_reaps_descendant_even_after_launcher_exit(monkeypatch, launcher_exits):
    script = """import sys,subprocess,json,time
sys.stdin.readline()
child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
print(json.dumps(child.pid),flush=True)
if not EXIT: time.sleep(30)
""".replace("EXIT", repr(launcher_exits))
    process = subprocess.Popen([sys.executable, "-u", "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    lifetime, handles = WorkerLifetime(process), []
    try:
        process.stdin.write(b"go\n")
        process.stdin.flush()
        handles.append(open_owned(kernel(), read_line(process)))
        if launcher_exits:
            process.wait(timeout=5)
        assert hasattr(lifetime, "active_processes"), "release must query the owned job, not just wait for its launcher"
        counts = []
        query = lifetime.active_processes
        def observed():
            count = query()
            counts.append(count)
            return count
        monkeypatch.setattr(lifetime, "active_processes", observed)
        lifetime.close(timeout=2)
        assert counts and counts[-1] == 0
        assert kernel().WaitForSingleObject(handles[0], 0) == 0
        assert lifetime.handle is None
    finally:
        cleanup(process, lifetime, handles)


@pytest.mark.parametrize("failure", ["terminate", "query", "timeout", "close"])
def test_job_release_failure_retains_handle_until_retry(monkeypatch, failure):
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    lifetime = WorkerLifetime(process)
    original = lifetime.handle
    try:
        with monkeypatch.context() as patch:
            if failure == "timeout":
                patch.setattr(lifetime, "active_processes", lambda: 1, raising=False)
            else:
                name = {"terminate": "TerminateJobObject", "query": "QueryInformationJobObject", "close": "CloseHandle"}[failure]
                def fail(*args):
                    ctypes.set_last_error(5)
                    return 0
                patch.setattr(lifetime.kernel, name, fail)
            with pytest.raises((OSError, RuntimeError)):
                lifetime.close(timeout=.05)
            assert lifetime.handle == original
        lifetime.close(timeout=2)
        process.wait(timeout=5)
        assert lifetime.handle is None
    finally:
        cleanup(process, lifetime, [])


CPU_TREE = '''import os,sys,subprocess
from identity_persistent_worker import serve
class Worker:
    def run_batch(self, request):
        assert 'torch' not in sys.modules and 'diffusers' not in sys.modules
        child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
        return {"ok":True,"items":[],"pid":os.getpid(),"child":child.pid}
    def close(self): pass
os._exit(serve(Worker(),sys.stdin.buffer,sys.stdout.buffer,ownership_handshake=True))
'''


@pytest.mark.parametrize("python", [sys.executable, os.environ.get("DREAM_IDENTITY_TEST_PYTHON")])
def test_handshake_binds_actual_worker_before_batch_and_release_reaps_real_tree(tmp_path, python):
    if not python:
        pytest.skip("opt-in installed identity Python; no downloads")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CUDA_VISIBLE_DEVICES": "-1"}
    # Deliberately let the venv launcher create its actual interpreter BEFORE
    # job assignment. The handshake must bind that already-existing child.
    ready, allow_binding = threading.Event(), threading.Event()
    lifetimes = []
    def factory(process):
        import time
        time.sleep(.25)
        owner = WorkerLifetime(process, awaiting_worker=True)
        lifetimes.append(owner)
        original = owner.confirm_worker
        def confirm(pid):
            ready.set()
            assert allow_binding.wait(3)
            return original(pid)
        owner.confirm_worker = confirm
        return owner
    client = PersistentWorkerClient([python, "-u", "-c", CPU_TREE], cwd=tmp_path, env=env,
                                    lifetime_factory=factory, ownership_handshake=True)
    results, errors, handles = [], [], []
    original_close = None
    def run():
        try:
            results.append(client.run_batch({"items": []}, timeout=5))
        except BaseException as exc:
            errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert ready.wait(3), errors
        assert not results, "batch was sent before ownership confirmation"
        allow_binding.set()
        thread.join(5)
        if errors:
            raise errors[0]
        assert not thread.is_alive() and not errors
        result = results[0]
        handles = [open_owned(kernel(), result[key]) for key in ("pid", "child")]
        if python != sys.executable:
            assert result["pid"] != client.process.pid, "must exercise the Windows venv launcher"
        assert lifetimes[0].active_processes() >= 2
        original_close = lifetimes[0].close
        def close_before_launcher():
            assert client.process.poll() is None, "launcher was killed before tree handles were pinned"
            return original_close()
        lifetimes[0].close = close_before_launcher
        client.close()
        assert all(kernel().WaitForSingleObject(handle, 0) == 0 for handle in handles)
        assert lifetimes[0].handle is None
    finally:
        allow_binding.set()
        if original_close is not None:
            lifetimes[0].close = original_close
        client.close()
        thread.join(5)
        for handle in handles:
            kernel().CloseHandle(handle)


def test_handshake_rejects_unowned_pid_without_binding_or_terminating_it():
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    lifetime = WorkerLifetime(process)
    try:
        assert hasattr(lifetime, "confirm_worker"), "actual worker ownership is not verified"
        with pytest.raises((ValueError, RuntimeError)):
            lifetime.confirm_worker(os.getpid())
    finally:
        cleanup(process, lifetime, [])


@pytest.mark.parametrize("action", ["cancel", "timeout", "invalid"])
def test_handshake_failure_never_sends_batch_and_releases_owned_process(tmp_path, action):
    marker = tmp_path / 'batch-received'
    script = '''import sys,json,pathlib,os,time
if INVALID: print(json.dumps({"type":"worker_ready","protocol":1,"pid":os.getppid()}),flush=True)
line=sys.stdin.readline()
if line: pathlib.Path(MARKER).write_text(line)
'''.replace('INVALID', repr(action == 'invalid')).replace('MARKER', repr(str(marker)))
    client = PersistentWorkerClient([sys.executable, '-u', '-c', script], cwd=tmp_path,
        env=os.environ.copy(), ownership_handshake=True,
        lifetime_factory=lambda process: WorkerLifetime(process, awaiting_worker=True))
    errors = []
    def run():
        try:
            client.run_batch({'items': []}, timeout=.25 if action == 'timeout' else 3)
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        if action == 'cancel':
            import time
            deadline = time.monotonic() + 2
            while client.process is None and time.monotonic() < deadline:
                time.sleep(.01)
            client.cancel()
        thread.join(7)
        assert not thread.is_alive() and errors
        assert not marker.exists()
        assert client.process is None
    finally:
        client.close()
        thread.join(7)


def test_cli_hello_is_before_any_inference_import_and_idle_exit(tmp_path):
    script = '''import sys,importlib.abc
class NoInference(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in ('torch','diffusers','transformers','onnxruntime'):
            raise AssertionError('inference imported before ownership')
sys.meta_path.insert(0,NoInference())
import identity_worker
sys.argv=['identity_worker','--persistent','--ownership-handshake','--idle-ttl','0.2']
identity_worker.main()
'''
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1]), 'CUDA_VISIBLE_DEVICES': '-1'}
    process = subprocess.Popen([sys.executable, '-u', '-c', script], env=env, cwd=tmp_path,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    lifetime = WorkerLifetime(process)
    try:
        hello = read_line(process)
        assert hello == {'type': 'worker_ready', 'protocol': 1, 'pid': process.pid}
        assert process.wait(timeout=3) == 0
        assert not process.stderr.read()
    finally:
        cleanup(process, lifetime, [])
