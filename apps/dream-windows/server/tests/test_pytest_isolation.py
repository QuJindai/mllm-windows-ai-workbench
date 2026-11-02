"""Exercise the actual pytest collection path in a fresh interpreter."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize('home', ['unset', 'live-default', 'explicit-test'])
def test_collection_initializes_recovery_only_under_test_root(tmp_path, home):
    server = Path(__file__).resolve().parents[1]
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    configured = tmp_path / 'explicit-home'
    configured.mkdir()
    explicit_config = tmp_path / 'worker-settings.json'
    env = os.environ.copy()
    for name in ('DREAM_HOME', 'DREAM_IDENTITY_CONFIG', 'PYTEST_ADDOPTS'):
        env.pop(name, None)
    env.update(TEMP=str(scratch), TMP=str(scratch), TMPDIR=str(scratch), PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    if home == 'live-default':
        env.update(DREAM_HOME='E:/Dream', DREAM_IDENTITY_CONFIG='E:/Dream/data/identity/runtime.json')
    elif home == 'explicit-test':
        env.update(DREAM_HOME=str(configured), DREAM_IDENTITY_CONFIG=str(explicit_config))
    # Install the guard before importing app or collecting its tests. Even an
    # unfixed conftest must fail before recovery gets access to a live root.
    script = '''
import os, sys
from pathlib import Path
import pytest
server, scratch, explicit, worker_config = map(Path, sys.argv[1:5])
custom = sys.argv[5] == 'explicit-test'
sys.path.insert(0, str(server))
import history_transactions
recover = history_transactions.recover_history_transactions
seen = []
def guarded(root):
    root = Path(root).resolve()
    assert (root == explicit if custom else root.is_relative_to(scratch)), f'unsafe recovery root: {root}'
    assert Path(os.environ['DREAM_IDENTITY_CONFIG']) == (worker_config if custom else root / 'data/identity/runtime.json')
    from config import DreamServerConfig
    defaults = DreamServerConfig.for_testing()
    assert defaults.dream_root == root and defaults.core_exe.is_relative_to(root) and defaults.engine_exe.is_relative_to(root)
    seen.append(root)
    return recover(root)
history_transactions.recover_history_transactions = guarded
before = (os.getenv('DREAM_HOME'), os.getenv('DREAM_IDENTITY_CONFIG'))
code = pytest.main(['--collect-only', '-q', '-p', 'no:cacheprovider', str(server / 'tests/test_identity_api.py') + '::test_status_uses_configured_python_and_returns_loras'])
assert code == 0 and len(seen) == 1
assert (os.getenv('DREAM_HOME'), os.getenv('DREAM_IDENTITY_CONFIG')) == before
assert seen[0].exists() == custom
'''
    result = subprocess.run([sys.executable, '-c', script, str(server), str(scratch), str(configured),
                             str(explicit_config), home], cwd=tmp_path, env=env, capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
