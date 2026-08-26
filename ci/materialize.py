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

# Windows PowerShell 5.1 ParseFile/script loading treats UTF-8 without BOM as
# the active ANSI code page. Workbench.Wpf.ps1 contains a non-ASCII em dash,
# so a no-BOM file can be tokenized incorrectly even when ParseInput(UTF8)
# reports zero errors. Also avoid the variable/colon interpolation ambiguity in
# the LAN URL builder. Remove this compatibility rewrite after the next source
# bundle contains both fixes directly.
wpf = ROOT / 'gui' / 'Workbench.Wpf.ps1'
text = wpf.read_text(encoding='utf-8-sig')
old = '{"http://$_`:$($st.runtime.web.port)"}'
new = "{ 'http://' + [string]$_ + ':' + [string]($st.runtime.web.port) }"
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit('SAFE_CORE_PS51_PATCH_TARGET_MISSING')
wpf.write_text(text, encoding='utf-8-sig')

# Windows PowerShell 5.1 can throw System.ArgumentException ('Argument types do
# not match') when @() forces enumeration of Generic.List[object] inside a
# PSCustomObject literal. Convert both object-literal uses explicitly to arrays.
doctor = ROOT / 'engine' / 'EmergencyDoctor.ps1'
doctor_text = doctor.read_text(encoding='utf-8-sig')
doctor_patches = [
    ('        checks=@($checks)', '        checks=$checks.ToArray()'),
    ('    [pscustomobject]@{checks=@($checks);evidence_dir=$evidenceDir;json=$jsonPath;text=$txtPath}',
     '    [pscustomobject]@{checks=$checks.ToArray();evidence_dir=$evidenceDir;json=$jsonPath;text=$txtPath}'),
]
for old_text, new_text in doctor_patches:
    if old_text in doctor_text:
        doctor_text = doctor_text.replace(old_text, new_text, 1)
    elif new_text not in doctor_text:
        raise SystemExit('SAFE_CORE_PS51_EMERGENCY_DOCTOR_PATCH_TARGET_MISSING')
doctor.write_text(doctor_text, encoding='utf-8-sig')

# Invoke-MLLMDoctor must emit each result object to the PowerShell pipeline.
# The bundled source used unary comma before ToArray(), which wraps all checks
# as one nested array object; callers using @(Invoke-MLLMDoctor ...) therefore
# observe Count == 1. Remove only that wrapper so callers receive a normal
# object[] when they collect the pipeline.
core = ROOT / 'engine' / 'Core.psm1'
core_text = core.read_text(encoding='utf-8-sig')
core_old = '    ,$results.ToArray()\n}\nfunction Get-MLLMTaskStatus'
core_new = '    $results.ToArray()\n}\nfunction Get-MLLMTaskStatus'
if core_old in core_text:
    core_text = core_text.replace(core_old, core_new, 1)
elif core_new not in core_text:
    raise SystemExit('SAFE_CORE_DOCTOR_ARRAY_SHAPE_PATCH_TARGET_MISSING')
core.write_text(core_text, encoding='utf-8-sig')

print(f'SAFE_CORE_MATERIALIZE=PASS parts={len(PARTS)} sha256={actual}')
print('SAFE_CORE_PS51_WPF_PATCH=PASS')
print('SAFE_CORE_PS51_UTF8_BOM=PASS')
print('SAFE_CORE_PS51_EMERGENCY_DOCTOR_PATCH=PASS')
print('SAFE_CORE_DOCTOR_ARRAY_SHAPE_PATCH=PASS')
