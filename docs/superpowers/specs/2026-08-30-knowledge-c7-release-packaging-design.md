# C7 Release Packaging Design

**Date:** 2026-08-30

## Goal

Deliver the verified Knowledge Phase C/C7 build as a Windows x64 offline install bundle that a user can unzip and install with one click, while also preserving a portable self-contained ZIP for inspection or direct execution.

## Baseline

- Source branch: `feature/knowledge-phase-c`
- Verified functional baseline: `b25c65e9b9c273d97722fbd43f736e42422bcdc5`
- Existing desktop publisher: `ci/package_desktop_phase_a.ps1`
- Existing versioned installer engine: `installer/Start-UniversalInstaller.ps1`
- Installer stage validation, SHA-256 verification, version activation, rollback, and evidence modules must be reused rather than duplicated.

## Deliverables

1. `MLLM_WORKBENCH_C7_OFFLINE_INSTALLER_win-x64.zip`
   - `INSTALL_M_LLM_C7.cmd`
   - `installer/Install-C7Bundle.ps1`
   - existing `installer/*.ps1|psm1|xaml`
   - `config/source-manifest.json`
   - `payload/MLLM_WORKBENCH_C7_PORTABLE_win-x64.zip`
   - `payload/MLLM_WORKBENCH_C7_PORTABLE_win-x64.zip.sha256`
   - `RELEASE_INFO.txt`
2. `MLLM_WORKBENCH_C7_OFFLINE_INSTALLER_win-x64.zip.sha256`
3. `MLLM_WORKBENCH_C7_PORTABLE_win-x64.zip`
4. `MLLM_WORKBENCH_C7_PORTABLE_win-x64.zip.sha256`

## Installation behavior

`INSTALL_M_LLM_C7.cmd` starts `installer/Install-C7Bundle.ps1`. The helper requests UAC only when needed, then launches the existing Universal Installer transaction in a child PowerShell process with `-Action ImportOffline`. The existing transaction engine performs payload hash validation, safe extraction, stage-contract validation, versioned copy to `%ProgramFiles%\M-LLM\Workbench\versions\<version>`, activation through `%ProgramData%\M-LLM\Workbench\current.json`, and rollback bookkeeping.

After activation, the helper verifies the current pointer and installed `desktop\MLLM.Workbench.Desktop.exe`, creates user shortcuts in normal interactive installs, and starts the installed desktop application. CI uses `-NoElevate -NoLaunch` with temporary `ProgramFiles`, `ProgramData`, and `USERPROFILE`, so the exact same installation path is exercised without mutating the hosted runner.

## Acceptance gates

- Release bundle and portable payload each have independently verified SHA-256 files.
- Bundle contains all installer, payload, config, and release metadata files.
- Offline installation succeeds with networking unnecessary.
- Installed version is activated through the current pointer.
- Installed desktop executable is launched from the installed version directory with `--smoke` and exits 0.
- Existing Knowledge Phase C regression remains green.
- GitHub Actions uploads the four release files as one downloadable artifact.

## Non-goals

- No MSI/Inno/WiX dependency is introduced in this release.
- No code-signing certificate is fabricated or assumed.
- No changes are made to C7 retrieval, RAG, evidence microscope, or locator behavior during packaging.
