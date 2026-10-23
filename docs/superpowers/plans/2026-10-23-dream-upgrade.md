# Dream P0–P2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Tasks with disjoint write sets may be delegated under dispatching-parallel-agents; the controller owns shared integration and Git.

**Goal:** Consolidate and publish main; deliver operational safeguards, visual reference control/research and resumable character creation with actual acceptance evidence.

**Architecture:** Extend the existing FastAPI/React workstation and existing isolated inference worker. Preserve production and research separation. No second app or node editor.

**Tech Stack:** Python/FastAPI/Pydantic, React/TypeScript/Vitest, existing PyTorch/Diffusers CUDA environment, PowerShell and GitHub CLI.

**Spec:** `docs/superpowers/specs/2026-10-23-dream-upgrade-design.md`.

## Global Constraints

- Browser only, localhost:8766, E-drive, 6 GB VRAM; preserve archives and original images.
- No automatic deletion/download/driver upgrade, LoRA training, ControlNet or remote GPU.
- Public GitHub push contains no user images, embeddings or credentials; no force push.
- Research artifacts bounded to512 MiB; SDXL representative capture only.
- Start/end control defaults0/1; historical requests remain valid.
- Disk below10 GiB warns; below2 GiB rejects new generation, unknown is not zero.

## Review Focus

1. A stale failed load or historical replay must not relabel another profile's draft.
2. Adapter scheduling/intervention/error must restore the prior scale; no cross-job leakage.
3. Duplicate retry clicks, process interruption and concurrent normal submit must not double-generate or alter completed records.
4. Low/unknown disk and unavailable GPU must not be presented as zero usage or trigger destructive cleanup.
5. Model route and reference kind must match actual loaded assets and artifact interpretation; no silent fallback or fabricated attention.

## Task 1 — main baseline and source release

Files: `.gitignore`, dependency manifests, `scripts/`, new release documentation; no user data.
Interfaces: existing Git history, source-only release receipt and reproducible environment inventory.
- [x] Record paths/hashes of protected archives and source baseline; review pending file list and secret patterns.
- [x] Run backend `python -m pytest -q` and frontend `npm.cmd run test:run -- --maxWorkers=2`; inspect failures before proceeding.
- [x] Commit reviewed current served source on main and merge origin/main's workflow update without force. Preserve feature worktree unchanged.
- [x] Push reviewed source on main; independently read remote SHA. Source commit `107b007db505f100d7dcb1c5391c4938eb81a8ec` matched both `ls-remote` and the GitHub commits API.

## Task 2 — operations diagnostics (independent sidecar)

Files: new `server/operations.py`, tests; `server/app.py` minimal routes/gates; new PowerShell diagnostic script; isolated React diagnostics component. Do not modify identity pipeline or batch files.
Interfaces: `GET /api/operations` JSON with release, disk status/free bytes, health checks and actionable messages. Integrate gate at ordinary and identity submission boundaries through a shared helper.
- [x] Tests prove low-disk rejection, warning threshold, unknown read error and no writes/deletion; RED before implementation.
- [x] Implement diagnostics and generation guard; preserve read/history/cancel access.
- [x] Expose concise Simplified Chinese status and safe troubleshooting without auto-killing listeners.
- [x] Run targeted tests; controller integrates and runs full suites. Source publication is tracked in Task 1.

## Task 3 — unfinished batch continuation (independent sidecar)

Files: `server/identity_batches.py`, `identity_routes.py`, dedicated retry tests; new frontend retry component/tests. Do not modify shared IdentityPage/domain/provider files; give controller an integration patch/contract.
Interfaces: `POST /api/identity/batches/{id}/retry` with `{mode: 'failed'|'unfinished', idempotencyKey: string}` returns the new existing batch shape with `parentBatchId` and selected original item indices. Use existing queue and publication journal.
- [x] RED tests: exact frozen seeds/steps, completed untouched, active rejected, no candidates, duplicate key, incompatible/missing inputs.
- [x] Implement safe child-batch creation and durable idempotency; no prior result mutation.
- [x] Add UI retry controls and parent provenance, disabled while pending; controller integrates provider/hook/types.
- [x] Verify API readback and independent completed-file hashes; run regression tests. Source publication is tracked in Task 1.

## Task 4 — visual route/control and research

Files: `identity_models.py`, `identity_contract.py`, `identity_pipeline.py`, `identity_research.py`, visual polish and validation readers; frontend identity domain/forms/research panels. Controller owns all shared integration files.
Interfaces: new `illustrious-xl-v2.0-plus-face` allowlisted visual model; `referenceStart`/`referenceEnd` floats0..1 with start<end, default0/1. Artifacts explicitly distinguish visual-reference ablation from FaceID ablation.
- [x] RED tests for route isolation, invalid intervals, batch incompatibility, restoration on errors, correct intervention label, historic reader compatibility.
- [x] Implement default-preserving sampling schedule and Illustrious visual bundle resolution using existing assets. The failed quality route is experimental/default disabled.
- [x] Implement representative visual H6/H7 observers and provenance, with truthful labels and bounds; keep extended SDXL rejected.
- [x] Wire draft/profile/history/UI and perform full suites/build. Run real local baseline/scheduled/Illustrious comparisons plus visual H7 capture; view actual images/maps.
- [ ] Illustrious Plus Face image-quality acceptance: FAILED, including strength/window comparisons. Keep disabled; tests/artifact validity do not close this item.

## Task 5 — performance and final acceptance

Files: performance probe/report, bounded worker/session implementation if supported by measured baseline; stage telemetry and result displays.
- [x] Record real cold/warm execution and observed idle worker release. Existing measurements are confounded by external GPU load; no speedup claim.
- [x] Test compatibility-key reuse and release/timeout/cancel, including actual Win32 process-tree ownership/exit and native-import regressions; implement a bounded route.
- [ ] Repeat uncontended performance and real GPU cancel/release/native hand-off under the final ownership repair. External GPU workload is preserved, not stopped.
- [x] Independently review entire delta, fix Important/Critical regressions, rerun full frontend/backend tests and build.
- [x] Deploy with scoped backup, preserve archives, perform real GUI retry/control/research/diagnostic checks, write itemized acceptance report.
- [x] Commit and push main, verify remote SHA and live release independently; no blanket completion claim for any open item. See the publication receipt in `docs/dream-windows/UPGRADE_20261023.md`.
