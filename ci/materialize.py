from __future__ import annotations
import base64, hashlib, io, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARTS = sorted((ROOT / 'ci' / 'overlay').glob('chunk*.b64'))
EXPECTED_SHA256 = '6a2e73091b27df0b711346df0b3abc39c78838a9764e03e1ec8c696cbfde3c6a'
if not PARTS:
    raise SystemExit('SAFE_CORE_OVERLAY_PARTS_MISSING')
encoded = ''.join(p.read_text(encoding='ascii').strip() for p in PARTS)
raw = base64.b64decode(encoded, validate=True)
actual = hashlib.sha256(raw).hexdigest()
if actual != EXPECTED_SHA256:
    raise SystemExit(f'SAFE_CORE_OVERLAY_SHA256_MISMATCH expected={EXPECTED_SHA256} actual={actual}')
with zipfile.ZipFile(io.BytesIO(raw)) as zf:
    bad = zf.testzip()
    if bad:
        raise SystemExit(f'SAFE_CORE_OVERLAY_CORRUPT member={bad}')
    root_resolved = ROOT.resolve()
    for info in zf.infolist():
        target = (ROOT / info.filename).resolve()
        if target != root_resolved and root_resolved not in target.parents:
            raise SystemExit(f'SAFE_CORE_OVERLAY_UNSAFE_PATH member={info.filename}')
    zf.extractall(ROOT)
print(f'SAFE_CORE_MATERIALIZE=PASS parts={len(PARTS)} sha256={actual}')
