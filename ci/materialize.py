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

# The GUI adapter is itself a PowerShell module. Importing Core, State,
# Detection, Runtime, etc. as sibling nested modules leaves task scriptblocks
# (dot-sourced by Core.psm1) unable to resolve functions exported by those
# siblings. Keep Core local to GuiAdapter, but expose the shared engine
# dependencies in the process-global session state, matching the proven CLI
# launcher topology. This fixes Dashboard Detect and out-of-process GUI jobs.
gui_adapter = ROOT / 'gui' / 'GuiAdapter.psm1'
gui_text = gui_adapter.read_text(encoding='utf-8-sig')
gui_old = '''function Initialize-MLLMGuiEngine {
    param([string]$ProjectRoot)
    foreach($m in @('Core','State','Detection','Network','Download','Security','Evidence','Runtime')){
        Import-Module (Join-Path $ProjectRoot "engine\\$m.psm1") -Force
    }
    Import-MLLMTasks -ProjectRoot $ProjectRoot
}'''
gui_new = '''function Initialize-MLLMGuiEngine {
    param([string]$ProjectRoot)
    foreach($m in @('State','Detection','Network','Download','Security','Evidence','Runtime')){
        Import-Module (Join-Path $ProjectRoot "engine\\$m.psm1") -Force -Global
    }
    Import-Module (Join-Path $ProjectRoot 'engine\\Core.psm1') -Force
    Import-MLLMTasks -ProjectRoot $ProjectRoot
}'''
if gui_old in gui_text:
    gui_text = gui_text.replace(gui_old, gui_new, 1)
elif gui_new not in gui_text:
    raise SystemExit('SAFE_CORE_GUI_SCOPE_PATCH_TARGET_MISSING')
gui_adapter.write_text(gui_text, encoding='utf-8-sig')

# Windows PowerShell 5.1 compatibility and GUI startup-mode correctness.
wpf = ROOT / 'gui' / 'Workbench.Wpf.ps1'
text = wpf.read_text(encoding='utf-8-sig')
old = '{"http://$_`:$($st.runtime.web.port)"}'
new = "{ 'http://' + [string]$_ + ':' + [string]($st.runtime.web.port) }"
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit('SAFE_CORE_PS51_PATCH_TARGET_MISSING')

network_old = "if($SmokeTest){Write-Output 'WPF_SMOKE=PASS';return}"
network_new = '''$networkBootstrap=$window.FindName('NetworkModeCombo')
if(-not $networkBootstrap){throw 'Missing WPF control: NetworkModeCombo'}
$networkMatched=$false
foreach($item in @($networkBootstrap.Items)){
    if([string]$item.Content -eq [string]$NetworkMode){$networkBootstrap.SelectedItem=$item;$networkMatched=$true;break}
}
if(-not $networkMatched){throw "Unsupported initial network mode: $NetworkMode"}
if($SmokeTest){Write-Output ('WPF_SMOKE=PASS network_mode='+[string]$networkBootstrap.SelectedItem.Content);$window.Close();return}'''
if network_old in text:
    text = text.replace(network_old, network_new, 1)
elif network_new not in text:
    raise SystemExit('SAFE_CORE_WPF_NETWORK_MODE_PATCH_TARGET_MISSING')
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
print('SAFE_CORE_GUI_SCOPE_PATCH=PASS')
print('SAFE_CORE_PS51_WPF_PATCH=PASS')
print('SAFE_CORE_WPF_NETWORK_MODE_PATCH=PASS')
print('SAFE_CORE_PS51_UTF8_BOM=PASS')
print('SAFE_CORE_PS51_EMERGENCY_DOCTOR_PATCH=PASS')
print('SAFE_CORE_DOCTOR_ARRAY_SHAPE_PATCH=PASS')
