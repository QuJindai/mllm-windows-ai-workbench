# Safe Core status

## Checkpoint — 2026-08-26

Safe Core public Windows CI is active on the `safe-core` branch. The latest verified checkpoint is commit `61722ecdd959a1a982df227af1917b96854cb3d2`; GitHub Actions run `32928257082` completed successfully.

Verified at this checkpoint:

- raw checkout can bootstrap Safe Core without Python by validating and materializing the embedded overlay with SHA-256 `6a2e73091b27df0b711346df0b3abc39c78838a9764e03e1ec8c696cbfde3c6a`;
- raw checkout CLI startup passes;
- raw checkout Doctor executes to completion, preserves diagnostic exit semantics, and creates evidence;
- raw checkout Core in an isolated empty offline environment fails closed as `BLOCKED` and does not create executable payloads;
- Windows PowerShell 5.1 parse/import/config/task-registry tests pass on Windows Server 2022 and Windows Server 2025;
- Safe Core offline-install smoke, Normal Doctor, Emergency Doctor, XAML load, WPF load, backend tests, static safety policy, and billing guard pass;
- WPF semantic binding gates verify `DoctorButton -> Doctor` and `InstallCoreButton -> Core -> Preset`, including the per-button `Tag` routing that prevents preset-loop capture errors;
- WPF code is gated against direct `winget install`, MSI, driver/DISM, Scheduled Task creation, and registry add/delete actions.

## Physical-machine release gate

Physical-machine Core installation remains **blocked**. CI coverage is now green, but the previously reported physical Windows BSOD has not been reproduced or causally attributed in an isolated hardware environment. A green hosted CI run is therefore not evidence that the historical BSOD root cause is resolved.

Do not use **Install Core** on the primary Windows machine yet. The next stage is a read-only/non-installing physical preflight that records OS/PowerShell/storage state, performs raw-checkout bootstrap and Doctor only, captures relevant Windows diagnostic evidence, and produces a reviewable evidence bundle before any Core installation is authorized.

PR #1 remains Draft and must not be merged solely on the basis of hosted CI.
