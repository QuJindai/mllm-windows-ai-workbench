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

# Avoid PS 5.1's ambiguous variable/colon parsing in the WPF LAN URL builder.
# Use plain concatenation rather than nested interpolation; remove this patch
# after the next source bundle refresh contains the corrected source directly.
wpf = ROOT / 'gui' / 'Workbench.Wpf.ps1'
text = wpf.read_text(encoding='utf-8-sig')
old = '{"http://$_`:$($st.runtime.web.port)"}'
new = "{ 'http://' + [string]$_ + ':' + [string]($st.runtime.web.port) }"
if old in text:
    wpf.write_text(text.replace(old, new, 1), encoding='utf-8')
elif new not in text:
    raise SystemExit('SAFE_CORE_PS51_PATCH_TARGET_MISSING')

print(f'SAFE_CORE_MATERIALIZE=PASS parts={len(PARTS)} sha256={actual}')
print('SAFE_CORE_PS51_WPF_PATCH=PASS')
