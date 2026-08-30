# Workbench Full C8 Component Engine Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the originally planned Windows local AI installation chain into the native Workbench while preserving the repaired C7 knowledge workbench and Safe Core safety gates.

**Architecture:** Keep normal desktop runtime in `OFFLINE_CACHE`, but expose an explicit, allowlisted component-installation network mode only for user-triggered installs. Reuse the existing Safe Core task engine (`Invoke-MLLMPreset` / `Invoke-MLLMTask`) through fixed named-pipe RPC methods; never expose arbitrary shell/command execution. The native Installation Center becomes the control surface for presets and component state.

**Tech Stack:** .NET 8 WPF, Windows PowerShell 5.1 Safe Core, named-pipe RPC, existing Universal Installer/version activation, GitHub Actions Windows 2022/2025.

**Spec:** `docs/superpowers/specs/2026-08-27-win11-universal-installer-design.md`

## Global Constraints

- Preserve the corrected C7 knowledge-navigation runtime smoke and complete runtime package list.
- No generic exec/shell/script RPC method.
- Component task allowlist: `git`, `git-lfs`, `python`, `modelscope`, `llama-cpp`, `qwen35-4b`, `local-api`, `web-workbench`.
- Preset allowlist: `Core`, `Local AI Fast`, `Web Workbench`, `Developer Tools`, `Full Setup`.
- Install network-mode allowlist: `AUTO_CN_FIRST`, `CHINA_ONLY`, `GLOBAL_FIRST`, `OFFLINE_CACHE`.
- Normal desktop/backend runtime remains `OFFLINE_CACHE` unless a specific component install request supplies an install mode.
- CI must never download the multi-GB model; online acquisition remains user-triggered. CI proves correct safe blocking in `OFFLINE_CACHE` and fixed routing to the existing task engine.
- Do not reintroduce low-level automatic system mutation or the historical unsafe “Install Core” behavior.

---

### Task 1: Fixed component-install RPC contract

**Files:**
- Create: `src/MLLM.Workbench.Contracts/Components/ComponentInstallContracts.cs`
- Modify: `src/MLLM.Workbench.Infrastructure/Backend/IWorkbenchBackendClient.cs`
- Modify: `runtime/WorkbenchBackend.ps1`
- Modify: `tests/backend/Invoke-WorkbenchBackendPhaseBContractSmoke.ps1`
- Create: `tests/infrastructure/MLLM.Workbench.Infrastructure.Tests/ComponentInstallBackendTests.cs`

**Interfaces:**
- Produces `ComponentPresetInstallRequest`, `ComponentTaskInstallRequest`, `ComponentInstallResult`, `ComponentInstallItemResult`.
- Produces client methods `InstallComponentPresetAsync` and `InstallComponentTaskAsync`.
- Backend methods: `components.installPreset`, `components.installTask`.

- [ ] Write real-backend RED tests requiring the two fixed methods and safe `OFFLINE_CACHE` blocking.
- [ ] Run the C8 workflow and confirm RED is only missing component-install capability.
- [ ] Implement exact allowlists and Safe Core engine initialization in `WorkbenchBackend.ps1`.
- [ ] Return typed result objects and reject unknown preset/task/network mode.
- [ ] Re-run tests; require no model/llama executable to appear in an empty offline cache.

### Task 2: Native Installation Center component controls

**Files:**
- Modify: `src/MLLM.Workbench.Desktop/Pages/Installation/InstallationPageViewModel.cs`
- Modify: `tests/desktop/MLLM.Workbench.Desktop.Tests/InstallationViewModelTests.cs`

**Interfaces:**
- Produces `InstallNetworkModes`, `SelectedInstallNetworkMode` defaulting to `AUTO_CN_FIRST`.
- Produces commands for `Core`, `Local AI Fast`, `Web Workbench`, `Developer Tools`, `Full Setup`.

- [ ] Add RED ViewModel tests verifying exact preset/network requests.
- [ ] Implement minimal commands using `IWorkbenchBackendClient` rather than privileged shell execution.
- [ ] Refresh typed Doctor/Installer state after every component operation.
- [ ] Preserve existing Universal Installer foundation actions and rollback.

### Task 3: Native Installation Center UI

**Files:**
- Modify: `src/MLLM.Workbench.Desktop/Pages/Installation/InstallationPage.xaml`
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/ComponentInstallShellTests.cs`

**Interfaces:**
- Adds `ComponentInstallNetworkMode` ComboBox.
- Adds AutomationIds for five preset buttons.

- [ ] Add RED shell contract tests.
- [ ] Add install-mode selector and explicit preset controls.
- [ ] Clearly distinguish “Workbench foundation/version management” from “Local AI components”.
- [ ] Keep component status table visible and retain safe-gate explanation.

### Task 4: C8 full regression and installed safety smoke

**Files:**
- Create: `.github/workflows/workbench-full-c8.yml`
- Modify/create C8 installed smoke as needed.

- [ ] Run Knowledge Core, full Desktop, real backend component tests, backend allowlist, runtime adapter/service lifecycle on Windows 2022 and 2025.
- [ ] In an isolated installed tree, run `--smoke`, `--smoke-knowledge`, then invoke `Full Setup` with `OFFLINE_CACHE` and require deterministic BLOCKED/READY behavior without unintended installs.
- [ ] Verify no generic command RPC is exposed.

### Task 5: C8 release package

**Files:**
- Create: `ci/package_c8_release.ps1`
- Create: `tests/ci/Invoke-C8ReleasePackageSmoke.ps1`
- Create: `.github/workflows/workbench-c8-release.yml`

- [ ] Package the self-contained desktop plus complete runtime/Safe Core/component configuration.
- [ ] Verify SHA-256, offline foundation installation, active-version pointer, Dashboard/Doctor runtime, Knowledge navigation, and component-engine offline safety.
- [ ] Upload installer + portable ZIP + SHA sidecars as the C8 artifact.
- [ ] Deliver only after both the C8 dual-Windows matrix and installed release smoke are GREEN.
