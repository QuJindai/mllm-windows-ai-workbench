# Dream Core Completion Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans; independent disjoint tasks may use superpowers:dispatching-parallel-agents.

**Goal:** Complete the audited browser backlog except identity likeness/face-polish tuning.
**Architecture:** Preserve React/FastAPI/native CUDA plus isolated Diffusers identity worker. Extend measured trace sidecars and recoverable file operations, not model generation semantics.
**Tech Stack:** Python/pytest/PyTorch/Diffusers, React/TypeScript/Vitest, C++/CUDA, PowerShell.
**Spec:** `docs/superpowers/specs/2026-09-28-core-completion-design.md`

## Global Constraints
- All new runtime artifacts on E:/Dream; preserve source images, profiles, history and user edits.
- Do not tune identity or face-polish behavior. Research OFF remains backward-compatible.
- Serial GPU work, observed/derived/unavailable provenance, bounded memory/disk, no remote push.
- No tests may delete real user outputs. Rollback/build evidence must be retained.

## Review Focus
- Failure between the second and third filesystem moves must restore history consistently.
- Constant/nonfinite latent channels must not produce forged correlation values.
- Instrumenting IP-Adapter attention must not remove its image condition or change generated output.
- Extended capture must reject unsafe requests before GPU work and validate source/shape/index coherence.
- Old drafts, profiles and records must load without requiring new research fields or implying collected data.

### Task 1: Model defaults and regression
**Files:** config/dream/model-registry.json; tests/dream-windows/test_model_registry_contract.py; apps/dream-windows/server/tests/test_api_contract.py as needed.
**Interfaces:** generation_defaults consumed by model API/UI: steps=8,cfg=2,sampling_method=dpm++2m_sde,scheduler=karras (verify exact native sampler spelling from existing API).
- [x] Add failing consumer-visible default payload test; run focused pytest and observe wrong current values.
- [x] Correct the registered default and labels without overriding explicit requests; rerun focused tests.
- [x] Main agent: serial real-GPU prompt/seed matrix, inspect every image, retain metadata and report limits.

### Task 2: Recoverable history deletion
**Files:** new server/history_transactions.py; runtime.py deletion entry point only; server/tests/test_history_transactions.py.
**Interfaces:** delete_history_files(root,item_id,paths) validates paths, stages to root/data/history-trash, journals and rolls back precommit failures; recover_history_transactions(root) on service startup/read.
- [x] Write tests for move failure, restart mid-stage, commit cleanup failure, symlink escape and success; observe failure without implementation.
- [x] Implement recoverable scoped transaction and integrate deletion without touching research methods.
- [x] Run focused tests and full backend suite before marking complete.

### Task 3: Latent correlation
**Files:** native examples/cli/latent_trace_writer.h and reusable correlation helper in both local native trees; export reproducible patch in repo; server/job_runner.py latent validation; src/domain/trace.ts correlation fields only; new CorrelationMatrix component and MicroscopePage integration; tests.
**Interfaces:** raw `channel_correlation`: square channels×channels float|null, Pearson from actual latent. Public `channelCorrelation`, `correlationMethod: pearson`, null for zero variance. Existing fields unchanged. Identity writer produces same raw field.
- [x] Test hand-derived +/-1, zero variance, invalid/asymmetric matrix and real UI step selection; observe RED.
- [x] Compute native raw correlations before per-channel quantization; validate in backend and render accessible table.
- [x] Build native executables, verify measured trace and retain original binaries before local installation; run unit/frontend regressions.

### Task 4: Identity research observer and UI
**Files:** new server/identity_research.py and tests; identity_contract.py; identity_pipeline.py; identity_service.py; identity_batches.py only if required; existing research validators/runtime provenance; src/domain/identity.ts; IdentityPage/components; trace domain source/method unions.
**Interfaces:** traceLevel off/basic/h6/h7 default off, researchCoverage representative/extended default representative; stable serialized request. Opt-in collector writes traces/<job>.json and sidecars with source diffusers-unet and actual conditioning method. Public API exposes measured data to existing microscope.
- [x] Tests strict fields/limits, actual small Torch attention blocks preserving base forward output, identity ablation/CFG math, serialized trace contract and disabled no-op; observe RED.
- [x] Hook real UNet Q/K for text cross/self maps; batch/head reduce with bounded queries; H6 separate intervention forward excluded from sampling state; record raw latent stats, channel maps, correlation.
- [x] Integrate worker/session lifetime, API validation, UI research selector and result-to-microscope link; add tests before each behavior change.
- [x] CUDA same-seed OFF/ON output comparison plus captured nonconstant tensors and coverage evidence; browser browse H6/Self/Cross/latent.

### Task 5: Integration, acceptance and recoverable release
**Files:** docs/dream-windows/CORE_COMPLETION_20260928.md; IDENTITY_GUIDE.md; current acceptance index; scripts only if launch bugs confirmed.
**Interfaces:** current app frontend/API on127.0.0.1:8766, desktop CMD continues official launcher. Version manifest and recoverable local Git snapshot.
- [x] Full backend/frontend tests, production build, diff check and independent whole-change review.
- [x] Serial browser core workflow and model output quality checks; compare Android source feature inventory to actual browser capabilities without claiming device benchmark.
- [x] Back up serving assets/source, synchronize verified changes, launch official service, verify live version and controls.
- [x] Commit scoped local source, write accurate acceptance and remaining excluded likeness task. Do not push.
