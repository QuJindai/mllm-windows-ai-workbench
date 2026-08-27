# Win11 Universal Installer Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an Administrator-first, resumable, multi-source, versioned Win11 installer foundation that no longer depends on Downloads being writable as an install root or GitHub being reachable.

**Architecture:** A small ASCII-safe CMD/PowerShell bootstrap resolves elevation and launches a modular PowerShell installer engine. The engine uses ProgramData for cache/state/staging, Program Files for immutable versioned application payloads, a provider-based acquisition layer with local/cache/HTTP/GitHub/custom-proxy fallbacks, and an atomic JSON active-version pointer. A minimal WPF shell renders engine state but never performs install logic directly.

**Tech Stack:** Windows PowerShell 5.1, .NET Framework APIs available on Windows 11, BITS, `System.Net.Http.HttpClient`, WPF/XAML, JSON state/config, pytest for repository contracts, GitHub Actions Windows 2022/2025.

**Spec:** `docs/superpowers/specs/2026-08-27-win11-universal-installer-design.md`

## Global Constraints

- Normal execution is Administrator-first and self-elevates before installation work.
- Program payloads install under `%ProgramFiles%\M-LLM\Workbench\versions\<version-id>`.
- Mutable installer state/cache/staging lives under `%ProgramData%\M-LLM`.
- Downloads is evidence/output only and must never be required for installation success.
- A previous active version is never overwritten, renamed, or deleted during new-version installation.
- GitHub is one acquisition provider, not a required dependency.
- Every package is SHA256-verified before extraction/install.
- Direct Windows PowerShell 5.1 entrypoints remain ASCII-only and are parser-gated.
- Phase 1 introduces no driver install, DISM, boot configuration, or registry policy changes.
- Component/Core installation remains separately gated; Phase 1 installs only the workbench payload used to prove the installer substrate.

---

### Task 1: Administrator Bootstrap and Stable Installer Paths

**Files:**
- Create: `M_LLM_UNIVERSAL_INSTALLER.cmd`
- Create: `installer/Start-UniversalInstaller.ps1`
- Create: `installer/InstallerPaths.psm1`
- Create: `tests/ci/Invoke-UniversalInstallerBootstrapSmoke.ps1`
- Modify: `tests/ci/test_repo_contract.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `Get-MLLMInstallerPaths -RunId <string> -VersionId <string> -> PSCustomObject`
- Produces: `Test-MLLMElevated -> bool`
- Produces: `Restart-MLLMInstallerElevated -OriginalArgs <string[]> -RunId <string> -> never returns on successful relaunch`
- Consumes: no installer-engine modules yet.

- [ ] **Step 1: Write failing repository/path bootstrap tests**

Add pytest contract assertions that `M_LLM_UNIVERSAL_INSTALLER.cmd`, `installer/Start-UniversalInstaller.ps1`, and `installer/InstallerPaths.psm1` exist and that the direct entrypoints contain only ASCII bytes.

Add `Invoke-UniversalInstallerBootstrapSmoke.ps1` assertions:

```powershell
Import-Module .\installer\InstallerPaths.psm1 -Force
$p=Get-MLLMInstallerPaths -RunId 'ci-run' -VersionId 'v1'
if($p.InstallVersionRoot -notlike "$env:ProgramFiles\M-LLM\Workbench\versions\v1*"){throw 'version root is not under Program Files'}
if($p.StagingRoot -notlike "$env:ProgramData\M-LLM\Installer\staging\ci-run*"){throw 'staging root is not under ProgramData'}
if($p.CacheRoot -notlike "$env:ProgramData\M-LLM\Installer\cache*"){throw 'cache root is not under ProgramData'}
if($p.EvidencePreferredRoot -like '*M_LLM_WORKBENCH_FULL_TEST*'){throw 'legacy Downloads work root leaked into universal installer'}
Write-Host 'UNIVERSAL_BOOTSTRAP_PATHS=PASS'
```

- [ ] **Step 2: Run tests and verify RED**

Run on Windows CI:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\ci\Invoke-UniversalInstallerBootstrapSmoke.ps1
```

Expected: FAIL because the new files/functions do not exist.

- [ ] **Step 3: Implement stable paths and elevation bootstrap**

`InstallerPaths.psm1` must return:

```powershell
[pscustomobject]@{
  ProgramRoot = (Join-Path $env:ProgramFiles 'M-LLM\Workbench')
  VersionsRoot = (Join-Path $env:ProgramFiles 'M-LLM\Workbench\versions')
  InstallVersionRoot = (Join-Path $env:ProgramFiles ("M-LLM\Workbench\versions\"+$VersionId))
  ProgramDataRoot = (Join-Path $env:ProgramData 'M-LLM')
  CacheRoot = (Join-Path $env:ProgramData 'M-LLM\Installer\cache')
  StagingRoot = (Join-Path $env:ProgramData ("M-LLM\Installer\staging\"+$RunId))
  RunRoot = (Join-Path $env:ProgramData ("M-LLM\Installer\runs\"+$RunId))
  StatePath = (Join-Path $env:ProgramData 'M-LLM\Installer\state\installer_state.json')
  CurrentPointer = (Join-Path $env:ProgramData 'M-LLM\Workbench\current.json')
  SharedDataRoot = (Join-Path $env:ProgramData 'M-LLM\Data')
  EvidencePreferredRoot = (Join-Path $env:USERPROFILE ("Downloads\M_LLM_EVIDENCE\"+$RunId))
}
```

`Start-UniversalInstaller.ps1` must check elevation before creating installer directories. If not elevated and `-NoElevate` is not set, relaunch:

```powershell
Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $forwardedArgs
exit 0
```

`M_LLM_UNIVERSAL_INSTALLER.cmd` only launches `installer\Start-UniversalInstaller.ps1` and remains ASCII-only.

- [ ] **Step 4: Run bootstrap tests and verify GREEN**

Expected markers:

```text
UNIVERSAL_BOOTSTRAP_PATHS=PASS
UNIVERSAL_ENTRYPOINT_ASCII=PASS
```

- [ ] **Step 5: Commit**

Commit message:

```text
feat: add universal installer elevation and paths
```

---

### Task 2: Resumable Installer State Machine

**Files:**
- Create: `installer/InstallerState.psm1`
- Create: `tests/ci/Invoke-InstallerStateSmoke.ps1`
- Modify: `installer/Start-UniversalInstaller.ps1`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `New-MLLMInstallerState -RunId -VersionId -Paths -> ordered dictionary`
- Produces: `Save-MLLMInstallerState -State -Path`
- Produces: `Read-MLLMInstallerState -Path -> PSCustomObject|null`
- Produces: `Set-MLLMInstallerStage -State -Stage -StatePath`
- Produces: `Test-MLLMStageComplete -State -Stage -> bool`

- [ ] **Step 1: Write failing state/resume tests**

Test exact stage sequence:

```powershell
$expected=@('INIT','ELEVATED','PREFLIGHT','ACQUIRE','VERIFY_PACKAGE','EXTRACT','VALIDATE_STAGE','INSTALL_VERSION','VERIFY_INSTALL','ACTIVATE','COMPLETE')
```

Create a state, mark `PREFLIGHT` complete, persist it, reload it, and verify `Test-MLLMStageComplete` returns true. Verify an incomplete run preserves `RunId`, `VersionId`, `selected_source`, and completed stages.

- [ ] **Step 2: Run and verify RED**

Expected: missing `InstallerState.psm1` or functions.

- [ ] **Step 3: Implement atomic state writes**

`Save-MLLMInstallerState` writes `<path>.tmp`, flushes, then uses `[IO.File]::Replace` when the target exists or `Move-Item` only for the temporary state file in the same state directory. No application/version directory is moved.

State schema:

```json
{
  "schema": "mllm.universal-installer.state.v1",
  "run_id": "...",
  "version_id": "...",
  "stage": "PREFLIGHT",
  "completed_stages": ["INIT", "ELEVATED", "PREFLIGHT"],
  "source_attempts": [],
  "selected_source": null,
  "package_sha256": null,
  "staging_path": "...",
  "installed_version_path": null,
  "previous_active_version": null,
  "new_active_version": null,
  "errors": [],
  "updated_at": "..."
}
```

- [ ] **Step 4: Run and verify GREEN**

Expected marker:

```text
INSTALLER_STATE_SMOKE=PASS resume_stage=PREFLIGHT
```

- [ ] **Step 5: Commit**

```text
feat: add resumable installer state machine
```

---

### Task 3: Provider-Based Multi-Source Acquisition

**Files:**
- Create: `installer/Acquisition.psm1`
- Create: `config/source-manifest.json`
- Create: `tests/ci/Invoke-AcquisitionFailoverSmoke.ps1`
- Modify: `installer/Start-UniversalInstaller.ps1`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `Get-MLLMSourceManifest -Path -> PSCustomObject`
- Produces: `Invoke-MLLMAcquirePackage -Package -CacheRoot -State -StatePath -> PSCustomObject { path, source_id, sha256 }`
- Produces: `Invoke-MLLMHttpDownload -Uri -DestinationPartial -TimeoutSeconds -> result`
- Consumes: `Save-MLLMInstallerState` from Task 2.

- [ ] **Step 1: Write failing failover tests**

The test creates a valid local ZIP and a package manifest whose first source is deliberately unreachable and second source is `local_file`:

```json
{
  "packages": [{
    "id": "safe-core-payload",
    "version": "ci-v1",
    "sha256": "<test hash>",
    "sources": [
      {"id":"dead-http","kind":"http","uri":"http://127.0.0.1:9/never.zip","timeout_seconds":2},
      {"id":"offline-local","kind":"local_file","path":"<fixture path>"}
    ]
  }]
}
```

Assertions:

```powershell
if($r.source_id -ne 'offline-local'){throw 'failover did not select local source'}
if(@($state.source_attempts | Where-Object {$_.source_id -eq 'dead-http' -and $_.status -eq 'FAILED'}).Count -ne 1){throw 'failed source not recorded'}
```

Add a second case with HTTP source 1 returning failure and HTTP source 2 served by a local test web server returning the payload.

- [ ] **Step 2: Run and verify RED**

Expected: acquisition module/functions missing.

- [ ] **Step 3: Implement source providers**

Support exactly Phase 1 kinds:

```text
local_file
local_cache
http
github
custom_proxy
```

Provider behavior:

- `local_file`: copy to cache partial, verify hash, promote.
- `local_cache`: use only when existing file hash matches manifest.
- `http`/`github`/`custom_proxy`: attempt BITS first when available; use `HttpClient` fallback with bounded timeout.
- Every failure appends `{source_id, kind, status, error, started_at, finished_at}` to state and proceeds to the next source.
- No provider loops indefinitely.

Default `source-manifest.json` may contain GitHub plus local/cache slots but must not invent an unverified China mirror URL.

- [ ] **Step 4: Run and verify GREEN**

Expected:

```text
ACQUISITION_FAILOVER_SMOKE=PASS selected=offline-local
ACQUISITION_HTTP_FAILOVER_SMOKE=PASS selected=http-good
```

- [ ] **Step 5: Commit**

```text
feat: add multi-source installer acquisition
```

---

### Task 4: Package Verification and Safe Extraction

**Files:**
- Create: `installer/PackageValidation.psm1`
- Create: `tests/ci/Invoke-PackageValidationSmoke.ps1`
- Modify: `installer/Start-UniversalInstaller.ps1`

**Interfaces:**
- Produces: `Test-MLLMPackageHash -Path -ExpectedSha256 -> bool`
- Produces: `Expand-MLLMSafeArchive -ArchivePath -Destination -> PSCustomObject`
- Produces: `Test-MLLMStageContract -StageRoot -> PSCustomObject`

- [ ] **Step 1: Write failing validation tests**

Cases:

1. Valid ZIP + correct hash passes.
2. Same ZIP + wrong hash fails before extraction.
3. ZIP containing `..\escape.txt` is rejected.
4. Stage missing `Start_M_LLM_Workbench.ps1` is rejected.
5. Valid Safe Core payload passes locale/parser/bootstrap contract.

- [ ] **Step 2: Run and verify RED**

Expected: validation functions missing.

- [ ] **Step 3: Implement validation/extraction**

Use `System.IO.Compression.ZipArchive` and calculate each entry destination with `GetFullPath`; reject any path whose normalized destination does not start with the normalized staging root plus directory separator.

The stage contract must require at least:

```text
Start_M_LLM_Workbench.ps1
Bootstrap_SafeCore.ps1
M_LLM_PHYSICAL_PREFLIGHT.ps1
M_LLM_GUI_PREFLIGHT.ps1
```

Direct PS5.1 entrypoints are checked for ASCII-only bytes and parsed with `Management.Automation.Language.Parser` before any stage is installable.

- [ ] **Step 4: Run and verify GREEN**

Expected:

```text
PACKAGE_VALIDATION_SMOKE=PASS
ZIP_TRAVERSAL_REJECTION=PASS
STAGE_CONTRACT_SMOKE=PASS
```

- [ ] **Step 5: Commit**

```text
feat: validate and safely extract installer packages
```

---

### Task 5: Versioned Install, Atomic Activation, and Rollback

**Files:**
- Create: `installer/Activation.psm1`
- Create: `tests/ci/Invoke-VersionActivationSmoke.ps1`
- Modify: `installer/Start-UniversalInstaller.ps1`

**Interfaces:**
- Produces: `Install-MLLMVersion -StageRoot -VersionRoot -> PSCustomObject`
- Produces: `Test-MLLMInstalledVersion -VersionRoot -> PSCustomObject`
- Produces: `Get-MLLMActiveVersion -PointerPath -> PSCustomObject|null`
- Produces: `Set-MLLMActiveVersion -PointerPath -VersionId -VersionPath -Previous -> PSCustomObject`
- Produces: `Invoke-MLLMRollback -PointerPath -> PSCustomObject`

- [ ] **Step 1: Write failing locked-old-version test**

Create version `v1`, hold an open read handle to a file in `v1`, set `current.json` to v1, then install v2. Assert v2 installation and activation succeed without touching v1.

Also create a deliberately invalid v3 and verify activation does not change from v2.

- [ ] **Step 2: Run and verify RED**

Expected: activation module missing.

- [ ] **Step 3: Implement copy-verify-activate**

Rules:

- Never `Move-Item` the old active version.
- Never delete the old active version during a new install.
- Install into a new version directory using file copy.
- If the exact target version exists, verify it and reuse only if valid; otherwise create a unique repair suffix rather than overwriting it.
- `current.json` is updated only after `Test-MLLMInstalledVersion` passes.
- Pointer update uses same-directory temporary file + atomic replacement.

Pointer schema:

```json
{
  "schema": "mllm.workbench.current.v1",
  "version_id": "v2",
  "version_path": "C:\\Program Files\\M-LLM\\Workbench\\versions\\v2",
  "previous_version_id": "v1",
  "previous_version_path": "C:\\Program Files\\M-LLM\\Workbench\\versions\\v1",
  "activated_at": "..."
}
```

- [ ] **Step 4: Run and verify GREEN**

Expected:

```text
VERSION_ACTIVATION_SMOKE=PASS old_version_locked=true active=v2
FAILED_VERSION_PRESERVES_ACTIVE=PASS active=v2
ROLLBACK_SMOKE=PASS active=v1
```

- [ ] **Step 5: Commit**

```text
feat: add versioned install activation and rollback
```

---

### Task 6: Evidence and Deterministic Failure Results

**Files:**
- Create: `installer/InstallerEvidence.psm1`
- Create: `tests/ci/Invoke-InstallerEvidenceSmoke.ps1`
- Modify: `installer/Start-UniversalInstaller.ps1`

**Interfaces:**
- Produces: `Write-MLLMInstallerSummary -State -RunRoot -> {json,md}`
- Produces: `Export-MLLMInstallerEvidence -State -RunRoot -PreferredEvidenceRoot -> zip path`
- Produces: `Add-MLLMInstallerError -State -Stage -Exception -Context -StatePath`

- [ ] **Step 1: Write failing evidence tests**

Simulate `ACQUIRE_FAILED` and verify summary JSON contains stage, source attempts, error type/message, run id, paths, and `core_install_authorized=false`.

Simulate unwritable/missing preferred Downloads output by pointing the evidence preference to an invalid path; verify evidence ZIP falls back under ProgramData run storage.

- [ ] **Step 2: Run and verify RED**

Expected: evidence module missing.

- [ ] **Step 3: Implement evidence packaging**

Evidence bundle must include:

```text
installer_state.json
installer_summary.json
installer_summary.md
source_attempts.json
system_profile.json
installer.log
```

Success and failure both produce a ZIP. Evidence-path failure itself is recorded but does not corrupt the installer state.

- [ ] **Step 4: Run and verify GREEN**

Expected:

```text
INSTALLER_EVIDENCE_SMOKE=PASS
INSTALLER_EVIDENCE_FALLBACK=PASS
```

- [ ] **Step 5: Commit**

```text
feat: add universal installer evidence bundles
```

---

### Task 7: Minimal WPF Universal Installer Shell

**Files:**
- Create: `installer/UniversalInstaller.xaml`
- Create: `installer/UniversalInstaller.Wpf.ps1`
- Create: `tests/ci/Invoke-UniversalInstallerWpfSmoke.ps1`
- Modify: `installer/Start-UniversalInstaller.ps1`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: installer state JSON and top-level installer-engine operations.
- Produces UI actions: `Install / Resume`, `Retry Acquisition`, `Import Offline Package`, `Open Evidence Folder`, `Rollback`.
- The WPF layer must not call BITS, `Invoke-WebRequest`, `HttpClient`, file-copy install logic, or pointer-write logic directly.

- [ ] **Step 1: Write failing WPF contract tests**

Require named controls:

```text
AdminStatusText
MachineStatusText
InstallRootText
StageText
SourceText
ProgressBar
StatusText
InstallResumeButton
RetryAcquisitionButton
ImportOfflineButton
EvidenceButton
RollbackButton
LogTextBox
```

Static test rejects direct install/network primitives inside `UniversalInstaller.Wpf.ps1`.

- [ ] **Step 2: Run and verify RED**

Expected: XAML/WPF files missing.

- [ ] **Step 3: Implement state-rendering WPF shell**

The GUI reads state and invokes engine operations through exported functions. Initial window must show the real Program Files install root and ProgramData state root. Import Offline Package uses a file picker and feeds the selected package into the acquisition layer as a local source override.

- [ ] **Step 4: Run and verify GREEN**

Expected:

```text
UNIVERSAL_INSTALLER_WPF_LOAD=PASS
UNIVERSAL_INSTALLER_WPF_BINDINGS=PASS
UNIVERSAL_INSTALLER_WPF_NO_DIRECT_INSTALL=PASS
```

- [ ] **Step 5: Commit**

```text
feat: add universal installer WPF shell
```

---

### Task 8: End-to-End Universal Installer CI Gates

**Files:**
- Create: `tests/ci/Invoke-UniversalInstallerE2E.ps1`
- Create: `.github/workflows/universal-installer.yml`
- Modify: `docs/SAFE_CORE_STATUS.md`
- Modify: `README.md`

**Interfaces:**
- Consumes all Phase 1 modules and entrypoints.
- Produces final Phase 1 acceptance marker and evidence bundle.

- [ ] **Step 1: Write E2E test scenarios before enabling release claim**

The E2E harness runs isolated roots and must cover:

```text
fresh install
unreachable GitHub + local fallback
failed first HTTP + successful second HTTP
existing locked previous version
corrupt hash
ZIP traversal rejection
interrupted state resume
failed candidate preserves current pointer
rollback
success evidence ZIP
failure evidence ZIP
```

Use a test-only path override parameter so hosted CI never writes real `C:\Program Files\M-LLM` or `C:\ProgramData\M-LLM`; production defaults remain unchanged.

- [ ] **Step 2: Run E2E and verify RED until every scenario is implemented**

Workflow matrix:

```yaml
strategy:
  matrix:
    os: [windows-2022, windows-2025]
```

Run Windows PowerShell 5.1 explicitly.

- [ ] **Step 3: Fix only failures exposed by the E2E matrix**

Do not weaken assertions to obtain green CI. Any mismatch between installer state and filesystem/pointer state is a product failure.

- [ ] **Step 4: Run complete Phase 1 verification**

Required final markers:

```text
UNIVERSAL_INSTALLER_E2E=PASS
NETWORK_FAILOVER=PASS
LOCKED_PREVIOUS_VERSION=PASS
RESUME=PASS
ATOMIC_ACTIVATION=PASS
ROLLBACK=PASS
EVIDENCE_SUCCESS=PASS
EVIDENCE_FAILURE=PASS
```

All existing `safe-core-ci` jobs must remain green on Windows 2022 and Windows 2025.

- [ ] **Step 5: Update durable checkpoint**

`docs/SAFE_CORE_STATUS.md` must record:

- exact Phase 1 verified commit
- workflow run ids
- exact supported OS/powershell matrix
- which network/permission failures are now covered
- that Phase 2 component/Core installation remains separately gated

- [ ] **Step 6: Commit**

```text
test: gate universal installer phase 1
```

---

## Self-review

### Spec coverage

- Administrator-first elevation: Task 1.
- Program Files/ProgramData layout and removal of Downloads as install root: Task 1.
- Resumable checkpoint state: Task 2.
- GitHub-independent multi-source acquisition: Task 3.
- SHA256 and safe ZIP extraction: Task 4.
- Locked old version / versioned install / atomic pointer / rollback: Task 5.
- Deterministic success/failure evidence: Task 6.
- Minimal GUI shell without direct install logic: Task 7.
- Windows 2022/2025 and failure-mode acceptance matrix: Task 8.

### Placeholder scan

No TBD/TODO/"implement later" requirements are used. The future domestic mirror is explicitly outside Phase 1 publishing scope; Phase 1 implements and tests the provider interface without inventing a URL.

### Interface consistency

Task 2 state APIs are consumed by Tasks 3 and 6. Task 1 paths are consumed by all subsequent tasks. Task 5 owns activation/pointer writes. Task 7 is UI-only and consumes engine operations rather than duplicating them.