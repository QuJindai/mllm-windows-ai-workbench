# Dream Creative Upgrade Implementation Plan — current ledger

**Status, 2026-10-29:** implementation and local acceptance are complete within the evidence boundaries below. Main-release push, remote SHA readback and CI remain pending. The original uncontended-benchmark step was adapted to an explicitly contended observation; it is not an uncontended pass.

**Goal:** deliver the approved creation workflows and publish verified source to main.
**Architecture:** existing serial worker ownership, immutable originals, independent versions, explicit scene recipes and provenance-bound research.
**Spec:** [current scope and contracts](../specs/2026-10-29-dream-creative-upgrade.md).
**User guide/evidence:** [creative upgrade acceptance](../../dream-windows/CREATIVE_UPGRADE_20261029.md).

## Constraints retained

- Shared Windows source and local artifacts; browser delivery. No private reference IDs or personal images in public docs.
- Preserve profiles, references and originals; never silently enable failed experimental models.
- Unit, CPU, GPU, GUI, quality and performance evidence are distinct. No fabricated likeness score or device parity.
- Release belongs to the parent task. This documentation update does not perform commit, push or service operations.

## Task 1: Immutable refinement service and worker

- [x] Red-to-green lifecycle/API coverage for creation, selection, cancellation, deletion, idempotency and recovery.
- [x] Serial execution, durable records, exact image dimensions and immutable sources.
- [x] Plain FaceID restore uses FacePolisher directly; visual/anime routes use compatible existing processors; errors propagate and unchanged output is rejected.
- [x] edge-lighting dispatch precedes generation/processor loading, forwards immutable scenePath and returns actual helper diagnostics.

## Task 2: Refinement UI

- [x] One-pass submission, progress, cancel, version selection, continue-edit and revert interactions.
- [x] Browser selection/revert accepted; overlap fixed; failed requests retain actionable state.
- [x] Component/type checks and complete frontend regression passed.

## Task 3: Scene and composition recipes

- [x] Portrait/half/full framing and photo/anime compatibility; prompt-only apply/undo preserved.
- [x] Explicit local-model recipes change only size, steps and CFG, preserving reference and identity settings.
- [x] Actual GUI selected full-body, applied sci-fi prompt, then 512×768 / 28 / 5.5 recommendation with reference fields retained.
- [x] Four anime scene generations succeeded. Acceptance records the head-and-shoulders outcome despite waist-up prompts; precise framing/pose is not claimed.

## Task 4: Fusion and microscope comparison

- [x] Inspected mobile chunk arithmetic; bounded CPU replay and provenance/missing-data tests.
- [x] Controlled Diffusers image engine, fusion CLI/raw-config dispatch, shared service, API and Lab UI fully connected.
- [x] GPU completed four valid images with the same seed/noise and positive [75, 38] / negative [9, 0] counts; two-chunk alpha 0.5 mean/anchor equality is expected.
- [x] Running fusion cancellation after sampling began reached cancelled in 343 ms, result null, no PNGs or remaining identity/persistent worker observed.
- [x] Lab restored the four completed images after restart.
- [x] Microscope GUI compared two compatible recorded runs: 28 matched steps, 84 statistical rows. Native/mobile device equivalence remains unverified.

## Task 5: Quality diagnostics and bounded correction

- [x] Fixed-image/mask tests and frozen diagnostic/receipt artifacts.
- [x] CPU edge-lighting integrated with actual edit/protected masks and immutable original scene provenance.
- [x] Real sample: protected/outside exact retention 100%, 3,839 changed pixels, maximum RGB-channel delta 2/255. This subtle edit is not a demonstrated quality winner.
- [x] Photo restore and four anime samples recorded separately; no perfect-likeness claim. Failed Illustrious Plus experimental gate remains disabled.

## Task 6: Performance, integration and release

- [x] **Adapted measurement:** contended cold/warm restore observations, 79.938 s→49.296 s; load 42.540 s→1.173 ms; sessionReused false→true; identical output hash. Three Unity processes and concurrent CPU tests were recorded.
- [ ] **Uncontended benchmark unavailable:** no clean-host speed acceptance or universal performance guarantee.
- [x] Bounded warm reuse through one existing transport/owner, content-hashed compatibility, 60-second idle TTL, no batch/refine cross-reuse; other modes release the warm child.
- [x] Hardware probe/request timeouts 3 s/6 s and failure backoff 3→6→12→30 s; coalescing, hidden pause and unknown/stale state preserved.
- [x] Full backend 1,686 passed / 2 skipped; full frontend 669 passed / 42 files; production build 94 modules.
- [x] Local GPU/GUI acceptance above; after restart no new GUI errors beyond four connection refusals during the planned restart.
- [x] 426 baseline reference/profile/original/output files verified, zero changed or missing.
- [ ] Record actual release commit and non-force push to main, confirm remote SHA, then record CI outcome. No completion claim before those operations succeed.

## Evidence boundary

Private receipts and screenshots stay local. This ledger records observed aggregates only. Pixel preservation does not prove aesthetic superiority; text framing does not constrain a skeleton; successful Diffusers fusion does not prove native/mobile parity. Prior intermediate red tests and concurrent-tree failures are superseded by the final integrated results, not hidden as outstanding implementation work.
