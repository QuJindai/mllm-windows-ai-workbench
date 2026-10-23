"""Read-only local preflight; never downloads models or allocates CUDA memory."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('E:/Dream/data/identity/runtime.json'))
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8-sig'))
    worker = Path(__file__).resolve().parents[1] / 'apps/dream-windows/server/identity_worker.py'
    temporary_root = args.config.parent / 'work'
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temporary_root, prefix='preflight-') as folder:
        folder = Path(folder)
        request, result = folder / 'request.json', folder / 'result.json'
        request.write_text(json.dumps({'configPath': str(args.config.resolve())}), encoding='utf-8')
        run = subprocess.run([config['python'], str(worker), '--operation', 'status', '--request', str(request), '--result', str(result)], timeout=30)
        if result.is_file():
            print(result.read_text(encoding='utf-8'))
        return run.returncode


if __name__ == '__main__':
    raise SystemExit(main())
