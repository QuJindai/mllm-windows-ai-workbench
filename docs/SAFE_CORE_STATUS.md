# Safe Core status

## Checkpoint — 2026-08-26

Safe Core public Windows CI is active on the `safe-core` branch. The latest verified R3 code checkpoint is commit `dfd0b54e8a2a7738fe4496d2caf85cf668e9168b`.

Fresh verification at this checkpoint:

- main `safe-core-ci` run `32956060797`: all jobs and all relevant steps PASS;
- exact user R3 entrypoint run `32956060836`: `M_LLM_WORKBENCH_FULL_TEST_R3.cmd --gui-preflight-only --refresh --no-pause` PASS;
- standalone GUI preflight run `32956060773`: PASS;
- R3 downloaded exact pinned source commit `229ab18a01e2c13afe4eb3169222e48f843db9b9`, bootstrapped it, ran physical preflight, then ran real GUI Dashboard preflight with `tasks=8`, `snapshot_errors=0`, `network_mode=OFFLINE_CACHE`, and `core_install_authorized=false`.

Verified behavior and regression coverage:

- raw checkout can bootstrap Safe Core without Python by validating and materializing the embedded overlay with SHA-256 `6a2e73091b27df0b711346df0b3abc39c78838a9764e03e1ec8c696cbfde3c6a`;
- direct `Bootstrap_SafeCore.ps1` invocation now resolves its project root correctly on Windows PowerShell 5.1; the original empty `Path` parameter-binding regression has a dedicated Windows test;
- raw checkout CLI startup passes;
- raw checkout Doctor executes to completion, preserves diagnostic exit semantics, and creates evidence;
- raw checkout Core in an isolated empty offline environment fails closed as `BLOCKED` and does not create executable payloads;
- Windows PowerShell 5.1 parse/import/config/task-registry tests pass on Windows Server 2022 and Windows Server 2025;
- Safe Core offline-install smoke, Normal Doctor, Emergency Doctor, XAML load, WPF load, backend tests, static safety policy, and billing guard pass;
- WPF semantic binding gates verify `DoctorButton -> Doctor` and `InstallCoreButton -> Core -> Preset`, including the per-button `Tag` routing that prevents preset-loop capture errors;
- real GUI Dashboard snapshot regression executes task detection instead of only loading XAML. It requires zero internal snapshot exceptions and rejects `CommandNotFoundException`/command-visibility errors;
- the GUI module-scope bug that caused `Resolve-MLLMLlamaRuntime`, `Get-MLLMState`, and `Find-MLLMPython` to become invisible to task handlers is fixed by exposing shared engine dependencies to the global session while keeping Core local to the GUI adapter;
- WPF startup now honors the requested `NetworkMode`; an `OFFLINE_CACHE` launch is tested to select and report `OFFLINE_CACHE` rather than silently displaying `AUTO_CN_FIRST`;
- both real Dashboard snapshot and initial NetworkMode tests run on materialized Windows 2022/2025 paths and raw-checkout bootstrap paths;
- `M_LLM_GUI_PREFLIGHT.ps1` is a non-installing user-entry gate. It performs raw bootstrap plus a real Dashboard snapshot, writes `gui_preflight.json`, requires `snapshot_errors=0`, records `install_actions_executed=0` and `network_actions_executed=0`, and always records `core_install_authorized=false`;
- `M_LLM_WORKBENCH_FULL_TEST_R3.cmd` performs exact-source download/reuse -> raw bootstrap -> non-installing physical preflight -> non-installing GUI Dashboard preflight -> GUI. CI exercises the exact CMD itself before it is delivered to a user;
- WPF code is gated against direct `winget install`, MSI, driver/DISM, Scheduled Task creation, and registry add/delete actions;
- `M_LLM_PHYSICAL_PREFLIGHT.ps1` passes a raw-checkout Windows Server 2022 contract test in `NON_INSTALLING` mode;
- physical preflight statically rejects direct installer/driver/registry/scheduled-task/download actions, records install/network action counts as zero, performs raw bootstrap + CLI + Doctor, and always reports `core_install_authorized=false` with `release_gate=BLOCKED_PENDING_EVIDENCE_REVIEW`;
- the preflight contract requires at least one Doctor evidence archive, a copied `doctor_evidence.zip`, and a real non-empty `M_LLM_PHYSICAL_PREFLIGHT_*.zip` evidence bundle. Bundle creation failure is a hard preflight failure rather than a warning.

## Physical-machine release gate

Physical-machine Core installation remains **blocked**. The previously reported physical Windows BSOD has not been reproduced or causally attributed in an isolated hardware environment. A green hosted CI run is therefore not evidence that the historical BSOD root cause is resolved.

The current permitted physical-machine path is R3 safe testing only: `M_LLM_WORKBENCH_FULL_TEST_R3.cmd` performs the non-installing physical and GUI preflights before opening the isolated GUI. It does not authorize Core installation.

Do not use **Install Core** on the primary Windows machine until the real-machine physical-preflight evidence bundle has been reviewed and a separate release decision is recorded.

PR #1 remains Draft and must not be merged solely on the basis of hosted CI.
