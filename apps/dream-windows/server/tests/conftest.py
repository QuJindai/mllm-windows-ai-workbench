from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import sys
import tempfile

import pytest

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))


def pytest_configure(config):
    # Test modules import app during collection, before session fixtures run.
    from config import DreamServerConfig

    live = Path('E:/Dream').resolve()
    configured = os.environ.get('DREAM_HOME')
    home = Path(configured).resolve() if configured else None
    patch = pytest.MonkeyPatch()
    if home is None or home == live or home.is_relative_to(live / 'data'):
        if Path(tempfile.gettempdir()).resolve().is_relative_to(live / 'data'):
            raise pytest.UsageError('Choose a pytest temporary directory outside Dream/data')
        temporary = tempfile.TemporaryDirectory(prefix='dream-pytest-home-')
        config.add_cleanup(temporary.cleanup)
        home = Path(temporary.name).resolve()
        patch.setenv('DREAM_HOME', str(home))
    config.add_cleanup(patch.undo)

    worker_config = os.environ.get('DREAM_IDENTITY_CONFIG')
    if not worker_config or Path(worker_config).resolve().is_relative_to(live / 'data'):
        patch.setenv('DREAM_IDENTITY_CONFIG', str(home / 'data/identity/runtime.json'))

    # for_testing() has its own hardcoded default. Rebase only the three paths
    # anchored to that root; keep the factory's other test settings intact.
    factory = DreamServerConfig.for_testing.__func__
    def test_config(cls):
        settings = factory(cls)
        return replace(settings, dream_root=home,
                       core_exe=home / settings.core_exe.relative_to(settings.dream_root),
                       engine_exe=home / settings.engine_exe.relative_to(settings.dream_root))

    patch.setattr(DreamServerConfig, 'for_testing', classmethod(test_config))
