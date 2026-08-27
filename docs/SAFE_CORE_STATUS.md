# Safe Core status

## Checkpoint — 2026-08-27

Safe Core public Windows CI is active on the `safe-core` branch. R3 is retired for physical-machine GUI testing after a real Chinese Windows PowerShell 5.1 locale/encoding failure. The current safe test launcher is `M_LLM_WORKBENCH_FULL_TEST_R4.cmd`.

### Real-machine R3 finding

A physical Windows 11 host running Windows PowerShell `5.1.26100.9168` passed Safe Core bootstrap and the non-installing physical preflight, then failed while parsing `M_LLM_GUI_PREFLIGHT.ps1`. The failure was caused by a literal Chinese diagnostic regex in a raw GitHub UTF-8 file without BOM. Windows PowerShell 5.1 can decode such files using the active Windows ANSI code page, so the hosted English Windows CI did not reproduce the same tokenizer failure.

This was a CI coverage gap rather than a return of the earlier Dashboard module-scope bug.

### R4 locale-safe remediation

The R4 source checkpoint is commit `b576c87b541ad95474e2ce89a4dc12af29e66325`. The R4 launcher itself was added at commit `2027edb7faea8c1ed7e695f31bb8b96936feea26`.

Changes and hard gates:

- `M_LLM_GUI_PREFLIGHT.ps1` is ASCII-only; its Chinese CommandNotFound diagnostic match is represented with Unicode regex escapes rather than literal non-ASCII source text;
- `tests/ci/Invoke-GuiPreflightEntrypointSmoke.ps1` constructs the Chinese diagnostic form from Unicode character codes and requires the ASCII regex to match it (`unicode_regex=PASS`);
- repository contract now requires all raw Windows PowerShell 5.1 direct entrypoints to be ASCII-only: `Bootstrap_SafeCore.ps1`, `M_LLM_PHYSICAL_PREFLIGHT.ps1`, `M_LLM_GUI_PREFLIGHT.ps1`, and `Start_M_LLM_Workbench.ps1`;
- `M_LLM_WORKBENCH_FULL_TEST_R4.cmd` adds a pre-bootstrap locale/encoding gate. It prints current culture and ANSI code page, rejects non-ASCII bytes in all four direct entrypoints, and invokes the Windows PowerShell parser on each file before any preflight or GUI execution;
- if this locale/encoding gate fails, R4 stops safely and does not authorize Core installation.

Fresh R4 verification:

- final R4 user-entry run `33032782989`: PASS on Windows Server 2022 / Windows PowerShell 5.1;
- its log shows all four `locale-safe parse` checks PASS, Safe Core bootstrap PASS, physical preflight PASS, and `GUI_PREFLIGHT=PASS tasks=8 snapshot_errors=0 network_mode=OFFLINE_CACHE core_install_authorized=false`;
- main `safe-core-ci` run `33032782994`: all jobs PASS, including Windows PowerShell 5.1 on Windows Server 2022 and 2025, repository contract, static/safety policy, Doctor, Core, raw checkout bootstrap, WPF load/binding, Dashboard snapshot, initial NetworkMode, physical preflight, backend tests, and billing guard;
- standalone GUI-preflight run `33032782955`: PASS with `tasks=8`, `snapshot_errors=0`, and `unicode_regex=PASS`.

### Existing verified behavior

- raw checkout can bootstrap Safe Core without Python by validating and materializing the embedded overlay with SHA-256 `6a2e73091b27df0b711346df0b3abc39c78838a9764e03e1ec8c696cbfde3c6a`;
- raw checkout Doctor executes to completion, preserves diagnostic exit semantics, and creates evidence;
- raw checkout Core in an isolated empty offline environment fails closed as `BLOCKED` and does not create executable payloads;
- real GUI Dashboard snapshot regression executes task detection and requires zero internal snapshot exceptions;
- the GUI module-scope fix keeps `Resolve-MLLMLlamaRuntime`, `Get-MLLMState`, and `Find-MLLMPython` visible to task handlers;
- WPF startup honors requested `NetworkMode`; `OFFLINE_CACHE` no longer silently displays `AUTO_CN_FIRST`;
- `M_LLM_GUI_PREFLIGHT.ps1` and `M_LLM_PHYSICAL_PREFLIGHT.ps1` remain non-installing gates with `core_install_authorized=false`;
- WPF code remains gated against direct system installer/driver/DISM/Scheduled Task/registry mutation routes.

## Physical-machine release gate

Physical-machine Core installation remains **blocked**. The previously reported physical Windows BSOD has not been reproduced or causally attributed in an isolated hardware environment. Hosted CI and successful non-installing preflights do not prove that historical BSOD root cause is resolved.

The current permitted physical-machine path is **R4 safe testing only**. `M_LLM_WORKBENCH_FULL_TEST_R4.cmd` performs the locale/encoding gate, raw bootstrap, non-installing physical preflight, and non-installing GUI Dashboard preflight before opening the isolated GUI in `OFFLINE_CACHE` mode. It does not authorize Core installation.

Do not use **Install Core** on the primary Windows machine until the real-machine physical-preflight evidence bundle has been reviewed and a separate release decision is recorded.

PR #1 remains Draft and must not be merged solely on the basis of hosted CI.
