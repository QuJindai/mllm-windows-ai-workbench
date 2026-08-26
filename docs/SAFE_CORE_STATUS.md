# Safe Core status

## Checkpoint — 2026-08-26

Safe Core public Windows CI is active on the `safe-core` branch. The latest verified code checkpoint is commit `0b151e528538b0c9931b231f15a33ef9e43497a5`; GitHub Actions PR run `32928797822` completed successfully.

Verified at this checkpoint:

- raw checkout can bootstrap Safe Core without Python by validating and materializing the embedded overlay with SHA-256 `6a2e73091b27df0b711346df0b3abc39c78838a9764e03e1ec8c696cbfde3c6a`;
- the bootstrap is safe under PowerShell `Set-StrictMode` and no longer accidentally evaluates the WPF patch template's literal `$_` token;
- raw checkout CLI startup passes;
- raw checkout Doctor executes to completion, preserves diagnostic exit semantics, and creates evidence;
- raw checkout Core in an isolated empty offline environment fails closed as `BLOCKED` and does not create executable payloads;
- Windows PowerShell 5.1 parse/import/config/task-registry tests pass on Windows Server 2022 and Windows Server 2025;
- Safe Core offline-install smoke, Normal Doctor, Emergency Doctor, XAML load, WPF load, backend tests, static safety policy, and billing guard pass;
- WPF semantic binding gates verify `DoctorButton -> Doctor` and `InstallCoreButton -> Core -> Preset`, including the per-button `Tag` routing that prevents preset-loop capture errors;
- WPF code is gated against direct `winget install`, MSI, driver/DISM, Scheduled Task creation, and registry add/delete actions;
- `M_LLM_PHYSICAL_PREFLIGHT.ps1` passes a raw-checkout Windows Server 2022 contract test in `NON_INSTALLING` mode;
- physical preflight statically rejects direct installer/driver/registry/scheduled-task/download actions, records install/network action counts as zero, performs raw bootstrap + CLI + Doctor, and always reports `core_install_authorized=false` with `release_gate=BLOCKED_PENDING_EVIDENCE_REVIEW`;
- the preflight contract requires at least one Doctor evidence archive, a copied `doctor_evidence.zip`, and a real non-empty `M_LLM_PHYSICAL_PREFLIGHT_*.zip` evidence bundle. Bundle creation failure is a hard preflight failure rather than a warning.

## Physical-machine release gate

Physical-machine Core installation remains **blocked**. The previously reported physical Windows BSOD has not been reproduced or causally attributed in an isolated hardware environment. A green hosted CI run is therefore not evidence that the historical BSOD root cause is resolved.

The next permitted physical-machine action is **only** `M_LLM_PHYSICAL_PREFLIGHT.ps1`. It is designed as a non-installing evidence gate: raw bootstrap, CLI, Doctor, host/storage inventory, relevant System event inventory, signed-driver inventory, and evidence packaging. It does not authorize Core installation even when the preflight itself passes.

Do not use **Install Core** on the primary Windows machine until the real-machine preflight evidence bundle has been reviewed and a separate release decision is recorded.

PR #1 remains Draft and must not be merged solely on the basis of hosted CI.
