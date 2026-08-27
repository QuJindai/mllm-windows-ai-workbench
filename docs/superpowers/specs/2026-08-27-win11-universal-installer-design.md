# M-LLM Win11 Universal Installer Design

## Purpose

Build a Win11 installer that works across ordinary personal and enterprise-style Windows 11 PCs without relying on a single network source, a preinstalled Python/Git environment, or writable Downloads directories. The installer must be recoverable, diagnosable, versioned, and safe to rerun.

## Evidence driving the redesign

Two real-PC failures show the current R4 launcher is not a universal installation architecture:

1. On one Windows 11 PC, GitHub archive download and extraction succeeded but activating the extracted repository under `Downloads\M_LLM_WORKBENCH_FULL_TEST_R4\source` failed with Windows `Access denied`. This means Downloads cannot be treated as download area, staging area, runtime area, and install target simultaneously.
2. On another run, elevated Administrator mode still failed at `Invoke-WebRequest` because the machine could not connect to the GitHub source URL. Administrator rights do not solve network reachability; a single GitHub source is an unacceptable hard dependency.
3. Earlier real-PC testing also exposed Windows PowerShell 5.1 locale/encoding differences and GUI module-scope failures. Therefore entrypoints and diagnostics must be tested as user-facing flows, not only as internal module tests.

## Scope decomposition

The universal installer is split into three independently testable subprojects.

### Phase 1 — Universal Installer Foundation

Deliver a stable Win11 installer substrate:

- Administrator-first elevation and privilege reporting.
- Stable installation, staging, cache, state, and evidence directories outside Downloads.
- Versioned installs and rollback-safe activation.
- Multi-source acquisition with local/offline fallback.
- Resume/checkpoint state.
- Safe rerun behavior.
- User-facing diagnostics and evidence bundles.
- Minimal WPF installer shell showing stage, source used, status, and evidence path.

### Phase 2 — Component Engine

Attach existing M-LLM component tasks to the installer substrate:

- Core
- Git
- Git LFS
- Python
- llama.cpp
- ModelScope
- Local API/runtime
- Web Workbench
- Embedding/runtime packages
- Model assets

Each component exposes Detect → Plan → Install → Verify → Repair → Rollback and must be independently skippable and retryable.

### Phase 3 — Full GUI Install Center

Promote the installer shell into the full GUI install/repair/update center with recommended installation, advanced component selection, progress, logs, rollback, offline-package import, and machine capability display.

## Privilege model

The normal installer path is Administrator-first.

- The bootstrap checks elevation immediately.
- If not elevated, it relaunches itself with `Start-Process -Verb RunAs` while preserving arguments and run id.
- No installation work occurs before elevation is resolved.
- UAC denial is a clean blocked result with evidence, not a partial install.
- System-level operations remain explicitly categorized; driver/DISM/registry modifications are not silently introduced.

## Filesystem layout

Downloads is evidence/output only. It is never the primary install or staging directory.

### Program files

`%ProgramFiles%\M-LLM\Workbench\versions\<version-id>\`

Contains immutable versioned application files.

### Shared mutable state

`%ProgramData%\M-LLM\`

Subdirectories:

- `Installer\cache\` — verified reusable archives/packages.
- `Installer\staging\<run-id>\` — temporary extraction and validation area.
- `Installer\runs\<run-id>\` — logs and machine-readable run state.
- `Installer\state\installer_state.json` — resumable installer checkpoint.
- `Workbench\current.json` — active version pointer.
- `Data\` — shared mutable runtime data and component state.

### User-visible evidence

`%USERPROFILE%\Downloads\M_LLM_EVIDENCE\<run-id>\`

Contains summary JSON/Markdown plus a final ZIP. Failure to write Downloads evidence falls back to `%ProgramData%\M-LLM\Installer\runs\<run-id>\evidence` without invalidating the install itself.

## No destructive activation

The installer never overwrites or renames an active installation directory.

Activation sequence:

1. Acquire package into cache.
2. Verify hash/size/package contract.
3. Extract into a unique staging directory.
4. Run locale, parser, repository, and installer preflight gates.
5. Copy into a new immutable version directory.
6. Verify the installed version in place.
7. Atomically replace `current.json` with a pointer to the new version.
8. Keep the previous version available for rollback.

If an old version is locked by antivirus, a running GUI, or another process, the new version can still be installed because the old tree is not modified.

## Acquisition architecture

Network acquisition is provider-based rather than hard-coded to GitHub.

`source-manifest.json` defines ordered sources for each package. Supported source kinds in Phase 1:

1. `local_file` — user-provided or previously cached ZIP/package; highest reliability and usable fully offline.
2. `local_cache` — verified installer cache from earlier runs.
3. `http` — ordinary HTTPS source, including a future China-hosted mirror.
4. `github` — GitHub archive/release source when reachable.
5. `custom_proxy` — explicit user/enterprise proxy URL supplied in config.

The engine probes a source with bounded timeouts, records the exact failure, then moves to the next source automatically. A single unreachable source never terminates the whole installation if another source is available.

Phase 1 does not fabricate a domestic mirror URL. It provides the source interface and manifest so a real ModelScope/Gitee/GitCode/object-storage mirror can be added and tested as a separate publishing task.

## Download behavior

- Use BITS when available for HTTP(S) payloads because it supports resumable transfer and survives transient network interruption.
- Fall back to `HttpClient` when BITS is unavailable or unsuitable.
- Downloads go to `*.partial` and are promoted only after checksum verification.
- Retries are bounded per source; failures switch source instead of looping indefinitely.
- Existing verified cache is reused.
- The final chosen source and every failed source attempt are recorded in run state.

## Installer state machine

Machine-readable states:

`INIT → ELEVATED → PREFLIGHT → ACQUIRE → VERIFY_PACKAGE → EXTRACT → VALIDATE_STAGE → INSTALL_VERSION → VERIFY_INSTALL → ACTIVATE → COMPLETE`

Failure states:

- `BLOCKED_PRIVILEGE`
- `BLOCKED_POLICY`
- `ACQUIRE_FAILED`
- `PACKAGE_INVALID`
- `STAGE_INVALID`
- `INSTALL_FAILED`
- `VERIFY_FAILED`
- `ACTIVATE_FAILED`

`installer_state.json` records:

- schema version
- run id
- target version
- current stage
- completed stages
- source attempts
- selected source
- package SHA256
- staging path
- installed version path
- previous active version
- new active version
- errors
- timestamps

A rerun detects an incomplete compatible run and resumes from the last verified stage. It never trusts an unverified partial artifact.

## Locale and PowerShell compatibility

All PowerShell 5.1 scripts invoked directly before the managed installer engine starts must be ASCII-only or UTF-8 with an explicit safe loading path. Phase 1 keeps direct bootstrap entrypoints ASCII-only and runs the PowerShell parser before execution.

User-visible localized strings are stored as data/resources rather than embedded into raw PowerShell 5.1 entrypoint source.

## Minimal GUI shell in Phase 1

The first GUI is intentionally small and testable. It shows:

- Administrator status
- OS/build/architecture
- target install root
- current stage
- current acquisition source
- per-source failures
- progress/status text
- selected/active version
- evidence location

Actions:

- Install / Resume
- Retry Acquisition
- Import Offline Package
- Open Evidence Folder
- Roll Back to Previous Version

The GUI does not directly perform install logic. It invokes the installer engine and renders state.

## Failure handling

Every failure must produce a deterministic result:

- no infinite retries
- no hidden partial success
- no destructive cleanup of the previous working version
- failed staging trees are preserved until evidence packaging completes
- failed partial packages are marked invalid and not reused
- evidence records command, exit code, exception type, stage, source, and relevant paths

## Security and safety boundaries

- Package hash verification is mandatory before install.
- ZIP extraction rejects path traversal.
- No arbitrary script execution from downloaded packages before contract verification.
- No driver install, DISM operation, boot configuration change, or registry policy change is part of Phase 1.
- Core/component installation remains separately gated until the component engine phase.
- Hosted CI passing is not treated as proof that previously reported physical BSOD causes are resolved.

## Phase 1 acceptance tests

Phase 1 is accepted only when all of the following are automated:

1. Fresh install on Windows Server 2022 and 2025 CI under Windows PowerShell 5.1.
2. Bootstrap self-elevation argument preservation test.
3. Installation root is outside Downloads.
4. Existing/locked previous version does not block installing a new version.
5. GitHub source unreachable + local package available → install succeeds via fallback.
6. First HTTP source fails + second HTTP source succeeds → source failover works and is recorded.
7. Partial download is not activated before SHA256 verification.
8. Corrupt ZIP/path traversal package is rejected.
9. Interrupted run resumes from checkpoint without repeating verified work.
10. Active pointer changes only after installed-version verification passes.
11. Failed new version leaves previous active version unchanged.
12. Rollback repoints to previous verified version.
13. Direct PowerShell 5.1 entrypoints pass ASCII/parse gates.
14. Minimal WPF shell loads and binds to installer state without executing installation code directly.
15. Evidence ZIP exists for both success and failure runs.

## Release rule

R4 remains a diagnostic artifact and is not the universal installer. The universal installer becomes the new mainline only after Phase 1 acceptance gates pass. Real component installation and any operation related to the historical BSOD remain separately gated until Phase 2 verification.