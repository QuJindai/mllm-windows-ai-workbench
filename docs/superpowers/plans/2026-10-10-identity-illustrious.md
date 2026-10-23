# Illustrious XL Identity Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Select Illustrious XL v2.0 + FaceID Plus V2 SDXL in the existing browser identity workflow.

**Architecture:** Add an allowlisted identity model resolver, preserving the legacy RV SD1.5 runtime as default. Select the matching Diffusers pipeline, adapter, companion LoRA and local pipeline config per request; retain model identity in batches, history and saved presets. SDXL uses memory-bounded offload on the 6GB GPU. Existing raw identity/CLIP features remain reusable.

**Tech Stack:** FastAPI/Pydantic, Diffusers 0.36, PyTorch CUDA, React/TypeScript, Vitest, pytest.

**Spec:** User request “Illustrious XL接入” in the context of selectable person-creation base models; scope below is the concrete implementation specification.

## Global Constraints

- Default `modelId`: `realistic-vision-v5.1-faceid`; additional allowlisted ID `illustrious-xl-v2.0-faceid`.
- Runtime `models` map supplies SDXL checkpoint/adapter/faceLora/pipelineConfig overrides; shared extraction assets stay unchanged. No client-supplied model paths.
- Frontend status `models` entries: id, name, architecture, ready, message, loras; no filesystem paths exposed.
- Existing profiles, jobs and batches without modelId keep SD1.5 behavior.
- Downloads/caches/backups remain on E:. Never alter reference photos or old outputs.
- SDXL initially shares existing 256–768 resolution limits. Default on selection: 768×768, 30 steps, CFG5; editable. No automatic polish opt-in.
- H6/H7 representative capture supported through actual UNet observations; SDXL extended capture rejected until its larger layer-budget is specifically validated. Show this limitation rather than falsely promise full capture.
- FaceID remains research/non-commercial; Illustrious is an illustration model, not a guaranteed likeness fix.
- Real CUDA, preview, batch, history/replay, and GUI evidence required. Do not claim likeness improvement from structural tests.

## Review Focus

- Missing SDXL assets must not disable the default model or silently fall back to SD1.5.
- Historical requests and presets without modelId must preserve the original model.
- Mixed-model batches or incompatible style LoRAs must fail clearly before unsafe GPU loading.
- Offload and optional face polish must work across repeated batch renders without forcing the whole SDXL model onto CUDA.
- Research metadata, history replay, and saved presets must identify the selected model truthfully.

### Task 1: Model routing and safe SDXL pipeline

**Files:** Add server/identity_models.py and tests/test_identity_models.py; modify identity_contract.py, identity_worker.py, identity_pipeline.py, identity_service.py, identity_batches.py, identity_research.py and their tests (all under apps/dream-windows).

**Interfaces:** `resolve_identity_model(config, model_id=DEFAULT_MODEL_ID)` returns a new config with modelId/modelName/architecture plus validated asset paths. `identity_model_catalog(config)` returns public per-model capability rows. Request.modelId travels unchanged to metadata and batching.

- [x] Write failing tests: omitted model→RV; SDXL→separate assets without mutating default config; unavailable SDXL isolated; wrong/unknown model rejected; style LoRAs filtered; mixed batch rejected; service/history IDs retained; SDXL extended capture rejected.
- [x] Run `python -m pytest apps/dream-windows/server/tests/test_identity_models.py -q`; expect failures for missing model routing.
- [x] Implement resolver, pipeline choice and sequential CPU offload (CUDA compute remains mandatory), metadata and status propagation, architecture-labelled research.
- [x] Run all server tests and inspect failures; preserve legacy behavior.
- [x] Download pinned official SDXL FaceID and small SDXL config files into E:, verify checksums; run isolated real worker inference with authorized existing reference, safe prompt, preview and H7 representative capture.

### Task 2: Browser model selection and replay

**Files:** src/domain/identity.ts, src/app/pages/IdentityPage.tsx and IdentityPage.test.tsx, relevant result component and tests.

**Interfaces:** Consume status.models and request.modelId from Task 1. Old status responses without models still expose RV only. Profile/default/history serialization retains modelId.

- [x] Write failing UI tests selecting Illustrious and verifying submitted request, per-model readiness/LoRA filtering, legacy default, replay preservation, and SDXL extended-capture validation.
- [x] Run targeted Vitest; expect failures for absent selector.
- [x] Implement labelled select, unavailable-state explanation, model-specific defaults, architecture hints and correct result model display.
- [x] Run full frontend tests and production build.

### Task 3: Verification and release

**Files:** docs/dream-windows/IDENTITY_ILLUSTRIOUS_20261010.md; runtime config example.

- [x] Independent whole-change code review; fix important issues with regression tests.
- [x] Back up exact affected serving sources/config/build; compare source baseline against feature HEAD before syncing only this feature.
- [x] Verify no active jobs, restart through existing hidden launcher, verify health and release asset hash.
- [x] GUI select model, run safe image batch, observe preview/progress, inspect final image and H7 data, navigate away/back, verify history replay; default RV regression.
- [x] Record tests, job IDs, measured memory/time, known restrictions and rollback paths. Commit feature branch; do not push or merge unrelated serving work.
