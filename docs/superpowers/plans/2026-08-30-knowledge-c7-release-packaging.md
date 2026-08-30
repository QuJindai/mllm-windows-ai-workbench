# Knowledge C7 Release Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and publish a verified Windows x64 offline install bundle and portable ZIP from the already-green C7 baseline.

**Architecture:** Reuse the existing self-contained desktop publisher as the payload producer and the existing Universal Installer as the only versioned installation engine. Add a thin C7 bundle wrapper, a release packager, an installation-level smoke test, and a GitHub Actions artifact workflow.

**Tech Stack:** .NET 8 WPF, Windows PowerShell 5.1, GitHub Actions, `actions/upload-artifact@v4`.

**Spec:** `docs/superpowers/specs/2026-08-30-knowledge-c7-release-packaging-design.md`

## Global Constraints

- Do not change the verified C7 application behavior.
- Windows target is `win-x64` and desktop publish remains `--self-contained true`.
- Reuse `installer/Start-UniversalInstaller.ps1 -Action ImportOffline`; do not introduce a second installer engine.
- Verify SHA-256 before installation.
- Acceptance must install into simulated Program Files/ProgramData, activate the version, and run the installed desktop with `--smoke`.
- Release files must be uploaded by GitHub Actions and downloadable after a successful run.

---

### Task 1: Add the failing release acceptance gate

**Files:**
- Create: `tests/ci/Invoke-C7ReleasePackageSmoke.ps1`
- Create: `.github/workflows/knowledge-c-release.yml`

**Interfaces:**
- Consumes: `ci/package_c7_release.ps1` (intentionally absent for RED)
- Produces: release CI gate and artifact contract.

- [ ] **Step 1: Write the failing package/install smoke**

The script must require `ci/package_c7_release.ps1`, build into `artifacts/c7-release`, verify both SHA files, extract the offline bundle, redirect `ProgramFiles`, `ProgramData`, and `USERPROFILE` to temporary directories, run `installer/Install-C7Bundle.ps1 -NoElevate -NoLaunch`, verify `current.json`, and execute the installed desktop with `--smoke`.

- [ ] **Step 2: Add the release workflow**

Run the smoke on Windows 2025 with .NET 8, then upload `artifacts/c7-release/*` using `actions/upload-artifact@v4` under artifact name `MLLM-Workbench-C7-win-x64`.

- [ ] **Step 3: Run the workflow and verify RED**

Expected failure: `C7 release package script missing` because `ci/package_c7_release.ps1` does not exist.

- [ ] **Step 4: Commit the RED gate**

Commit message: `test: require installable c7 release artifact`.

---

### Task 2: Implement the one-click C7 offline bundle

**Files:**
- Create: `installer/Install-C7Bundle.ps1`
- Create: `release/INSTALL_M_LLM_C7.cmd`

**Interfaces:**
- Consumes: bundled `payload/MLLM_WORKBENCH_C7_PORTABLE_win-x64.zip`, `config/source-manifest.json`, `installer/Start-UniversalInstaller.ps1`.
- Produces: one-click interactive installer and scriptable CI installer.

- [ ] **Step 1: Implement wrapper elevation**

`Install-C7Bundle.ps1` accepts `-NoElevate`, `-NoLaunch`, and a fixed default C7 version id. Without `-NoElevate`, non-admin execution relaunches itself with UAC and waits for the elevated child exit code.

- [ ] **Step 2: Invoke the existing transaction engine in a child process**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $universalEntry `
  -NoElevate -VersionId $VersionId -SourceManifestPath $manifest `
  -Action ImportOffline -OfflinePackagePath $payload
```

Treat any non-zero exit as installation failure.

- [ ] **Step 3: Verify activation and installed executable**

Read `%ProgramData%\M-LLM\Workbench\current.json`, require the requested version id, require `desktop\MLLM.Workbench.Desktop.exe`, and print `C7_INSTALL=PASS` with version/path.

- [ ] **Step 4: Create normal-user shortcuts and launch**

Interactive installs create Desktop and Start Menu shortcuts targeting the installed desktop executable and then launch it. `-NoLaunch` skips shortcuts and launch for CI.

- [ ] **Step 5: Add the CMD entrypoint**

`INSTALL_M_LLM_C7.cmd` resolves its adjacent `installer\Install-C7Bundle.ps1`, launches Windows PowerShell with execution-policy bypass, propagates the exit code, and displays an error only on failure.

---

### Task 3: Build deterministic release artifacts

**Files:**
- Create: `ci/package_c7_release.ps1`

**Interfaces:**
- Consumes: `ci/package_desktop_phase_a.ps1`, Task 2 wrapper files, existing `installer/` and `config/`.
- Produces: the four files defined in the release spec under the requested output root.

- [ ] **Step 1: Build the self-contained portable payload**

Call `ci/package_desktop_phase_a.ps1`, copy/rename its ZIP to `MLLM_WORKBENCH_C7_PORTABLE_win-x64.zip`, and recompute a matching SHA-256 sidecar.

- [ ] **Step 2: Stage the offline installer bundle**

Stage `INSTALL_M_LLM_C7.cmd`, the full existing `installer` directory plus `Install-C7Bundle.ps1`, `config/source-manifest.json`, portable payload + SHA, and a `RELEASE_INFO.txt` containing source commit, version id, build UTC time, payload SHA, and verification scope.

- [ ] **Step 3: Compress and hash the installer bundle**

Create `MLLM_WORKBENCH_C7_OFFLINE_INSTALLER_win-x64.zip` and its `.sha256`. Emit `C7_RELEASE_PACKAGE=PASS` with paths, sizes, hashes, and source SHA.

- [ ] **Step 4: Run the release acceptance gate**

Expected: package hashes match, simulated offline install/activation succeeds, installed desktop `--smoke` exits 0.

- [ ] **Step 5: Commit GREEN**

Commit message: `feat: package verified c7 offline installer`.

---

### Task 4: Verify release and hand off the binaries

**Files:**
- No source changes expected.

**Interfaces:**
- Consumes: successful `knowledge-c-release` run artifact.
- Produces: exact user-downloadable files.

- [ ] **Step 1: Verify workflow conclusion**

Require workflow `knowledge-c-release` to finish with `conclusion=success` on the final source SHA.

- [ ] **Step 2: Read install evidence from logs**

Require explicit PASS markers for package SHA, offline install, version activation, and installed desktop smoke.

- [ ] **Step 3: Download the GitHub Actions artifact**

Download artifact `MLLM-Workbench-C7-win-x64`, materialize it into the active runtime, and extract the four release files.

- [ ] **Step 4: Recompute final hashes locally**

Confirm each ZIP matches its `.sha256` after materialization.

- [ ] **Step 5: Deliver individual links**

Provide separate clickable links for the offline installer ZIP, installer SHA-256, portable ZIP, and portable SHA-256, plus the final source SHA and CI run evidence.

## Self-review

- Spec coverage: offline installer, portable build, hashes, actual install/activation, installed smoke, artifact publishing, and final links are all covered.
- Placeholder scan: no deferred implementation placeholders.
- Type/interface consistency: wrapper calls the existing Universal Installer through its published CLI contract; release smoke consumes the same filenames the packager produces.
