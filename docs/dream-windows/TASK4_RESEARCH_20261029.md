# Task 4 research integration and acceptance

Status, 2026-10-29: CPU numerical replay, cross-run microscope comparison and controlled Diffusers image generation are implemented and connected to the application. The fusion worker dispatch is complete. Real GPU images, running-job cancellation and GUI result recovery have been accepted separately from CPU tests. See the [image contract](TASK4_IMAGE_CONTRACT.md) and [creative upgrade guide](CREATIVE_UPGRADE_20261029.md).

## Three distinct research paths

| Path | Implemented behavior | Evidence boundary |
| --- | --- | --- |
| CPU prediction replay | Four fusion operations over imported paired raw predictions | Imported provenance remains unverified; no images or device execution |
| Controlled image experiment | Four real Diffusers SD1.5 trajectories using matched seed/noise/settings | GPU completion observed; no mobile/native device parity or quality winner |
| Microscope comparison | Compatible recorded runs, exact coverage and source provenance | Descriptive recorded statistics, not an identity/quality score |

The earlier concurrent-tree failure ledger and pending worker-dispatch status are superseded by the integrated acceptance below. Historical red-to-green tests established missing-module/router/UI, provenance and dispatch boundaries; they are not current failures.

## Algorithm source and limits

The inspected Android harness uses four 77-slot chunks, each holding up to 75 content tokens. Positive and negative conditioning are paired at the same latent and timestep, with guided prediction:

`g[j] = u[j] + cfg * (p[j] - u[j])`

Effective token counts come from encoded conditioning, not re-tokenized decoded text. Use `max(1, positive_count)` only when unconditional inference can be skipped and CFG equals one; otherwise use `max(1, positive_count, negative_count)`.

- `first_only`: g[0], weights [1, 0, …].
- `equal_mean`: sum(g) / N.
- `token_weighted`: weighted sum with weights proportional to effective counts.
- `anchor_residual`: g[0] + alpha × sum(w[j] × (g[j] − g[0])) for j ≥ 1. Residual weights normalize over residual chunks only; a single chunk returns g[0].

Arithmetic uses explicit float32 rounding and float64 aggregate diagnostics. Compiler/device kernels are not claimed bitwise identical. The replay is a frozen-step counterfactual; generating a changed trajectory requires resampling every later step, as the separate controlled image engine does.

The inspected native H6 diagnostic path slices positive conditioning against a complete unconditional prediction and exports statistics/spatial differences. It does not supply the paired raw signed tensors or scheduler integration required by this contract. Native/mobile parity therefore remains unavailable; it must not be inferred from the successful Diffusers image route.

## HTTP and UI use

- GET `/api/research/fusion/capability`: CPU import replay limits of four chunks, 65,536 values per tensor and 12 MiB per request. `nativeGenerationAvailable=false` describes this native replay boundary, not the separate working Diffusers image route.
- POST `/api/research/fusion/replay`: bounded single-concurrent CPU execution, no image generation. Returns fused predictions, effective weights, mean absolute value, L2, delta-L2 and cosine relative to equal mean; zero-norm cosine is null. Duplicate JSON, nonfinite/missing predictions and invalid provenance are rejected.
- GET `/api/research/comparison?left={runId}&right={otherRunId}`: reads existing trace artifacts; rejects latest aliases, duplicate/mismatched IDs, missing data, incompatible model/engine/sampler/scheduler/CFG/steps/shapes or capture coverage. It neither interpolates nor fills missing values with zero.
- Lab **手机 chunk 预测融合** imports raw JSON and runs **执行 CPU 融合重放**. **受控融合图像实验** submits real images via the integrated identity queue. Prompt-rewrite experiments remain separate.
- Microscope **潜空间 → 对照运行 → 比较实测指标** shows comparison only after provenance/metric validation. A changed selection or refresh discards stale results.

## CPU import contract

Required fields: `contractVersion: mobile-chunk-predictions-v1`, `predictionType: epsilon`, `family: sd15|sdxl`, shape with 1..4 dimensions (each 1..128, product ≤65,536), CFG 0..30, alpha 0..1, canSkipUncond, provenance and chunks.

Chunks have sequential zero-based indices, positiveTokens/negativeTokens 0..75 excluding special/padding tokens, and flat positive/negative float arrays matching shape. Inputs must be pre-CFG epsilon predictions from the same latent/timestep and the corresponding negative chunk. Negative predictions may be absent only when canSkipUncond is true and CFG is one. Exhausted sides use empty conditioning; whole-prompt unconditional output is not a substitute.

Provenance requires runId, modelId, engine `android-qnn`, engineRevision, step, timestep, seed, timezone-qualified capturedAt, and lowercase SHA-256 values for model, latent and positive/negative prompts. These are imported declarations, not authenticated device evidence. Every result retains `inputVerification: imported-unverified` and `truth: derived`; a content digest proves content identity only. Anima and v-prediction are excluded.

## Current acceptance

- **1,686 backend tests passed, 2 skipped; 669 frontend tests passed; production build transformed 94 modules.**
- GPU fusion completed all four valid images with shared seed 42 and initial noise, positive counts [75, 38], negative counts [9, 0], CFG 5.5 and alpha 0.5. Equal-mean and anchor-residual hashes matched as expected for two chunks at alpha 0.5.
- Running fusion cancellation after sampling began at progress 6 completed in 343 ms, with null result, no PNGs and no remaining identity/persistent worker process observed.
- Lab restored the completed four-image result after service restart.
- Actual microscope GUI comparison succeeded for two compatible recorded runs: **28 matched steps, 84 statistical rows**.
- Existing immutable reference/profile/original/output files were checked after acceptance: **426 checked, zero changed or missing**.
- Final GUI checks reported no new errors except four connection refusals during the planned restart. Private recordings and snapshots remain local; public docs contain only generic counts and settings.

The observations do not establish perfect likeness, a preferred fusion mode, an uncontended benchmark or phone/native/device equality. Main-release push, remote SHA readback and CI are not yet recorded as complete.
