# Task 4 controlled image-generation contract

Status, 2026-10-29: the engine, worker, shared service, API and Lab UI are fully wired. Real GPU generation, running-job cancellation and restoration of completed results after service restart have been observed. This is a controlled Diffusers SD1.5 implementation; native/mobile device parity is not claimed. See the [creative upgrade guide and acceptance record](CREATIVE_UPGRADE_20261029.md).

## Integrated execution

1. The identity router mounts `create_research_image_router(service)` at `/api/identity/research/images`, reusing the existing IdentityService, lease, serial queue and background registry. Mutation routes apply the shared local-origin and bounded-body guards.
2. `identity_worker.py` accepts `fusion`, returns the raw local runtime config for that operation and dispatches `research_image_engine.generate_fusion_images(config, request)` without importing `identity_pipeline`. Only the configured RV checkpoint and SD1.5 pipeline configuration are resolved; FaceID assets are not required.
3. The service uses the existing native/identity ownership barriers, releases a warm identity child before fusion and applies a 900-second timeout. Cancellation and shutdown own worker exit; the engine creates no additional process, executor or GPU pool.

Worker signature: `generate_fusion_images(config: dict, payload: dict) -> dict`.

Payload fields are `jobId`, `dreamRoot`, `configPath`, `settings`, `assetBinding`, `outputPaths` (four service-owned pending PNG paths) and `eventPath`. The result contains `contractVersion='diffusers-chunk-fusion-images-v1'`, `jobId`, provenance and variants with mode, image SHA-256, effective weights and duration. Progress uses bounded JSONL events with type `fusion-progress`, jobId, mode, step and totalSteps. Identifiers in this contract are field names/placeholders, not published private records.

## Sampling contract

- Model: `realistic-vision-v5.1-fusion`; settings include prompt, negativePrompt, seed, steps 1..30, CFG 1..15, alpha 0..1, width/height 256..512 aligned to 64, and requestId.
- Variants: `first_only`, `equal_mean`, `token_weighted`, `anchor_residual`.
- Offline `StableDiffusionPipeline.from_single_file` uses configured local assets with no downloads.
- CLIP chunks contain up to 75 content tokens plus BOS/EOS; packed IDs are padded directly, without re-tokenizing decoded text. Maximum four chunks; overlong inputs are rejected, never silently truncated. Prompt-weight syntax is literal text.
- At each step, paired positive/negative chunks use the same scaled latent and timestep. Empty conditioning fills an exhausted side. Guided predictions are fused before exactly one scheduler update.
- Each variant resets EulerDiscreteScheduler with epsilon prediction, linspace timesteps and no alternate sigma schedules. All trajectories start from identical CPU-generated noise; no random scheduler updates are used.
- CFG=1 skips negative encoding/inference and uses positive-only effective counts. Prepared negative token IDs remain recorded, with `negativeEncodingPerformed=false` when skipped.
- Provenance includes settings, asset/config/code/noise hashes, actual encoded token IDs/counts, versions, effective weights and timings. It is not a likeness score or proof of phone/native parity.

## API and UI

| Endpoint | Behavior |
| --- | --- |
| GET `/api/identity/research/images/capability` | Local asset readiness; readiness alone does not prove GPU execution |
| POST `/api/identity/research/images` | Strict settings and idempotency requestId; returns queued record; no caller-selected output paths |
| GET `/api/identity/research/images/{jobId}` | Persisted bounded status/result and validated provenance |
| POST `/api/identity/research/images/{jobId}/cancel` | Cancels queued/running work; terminal cancellation waits for owned worker exit |
| GET `/api/identity/research/images/{jobId}/{mode}/image` | Completed, hash-bound PNG for an allowlisted mode only |

Only one fusion experiment is active at a time; storage is bounded to 128 immutable records. The worker writes exclusive pending PNGs. The service verifies all four PNGs, dimensions, hashes, weights and metadata before exposing results. Failure/cancellation removes pending outputs. Missing or altered completed artifacts are rejected.

In Lab, open **受控融合图像实验**, enter settings and submit. The panel displays progress, cancellation and four published images with provenance. It restores the last experiment from local storage; uncertain submission retries retain their requestId. No preview is claimed before publication. CPU imported-prediction replay is a separate panel and does not generate images.

## Verification, 2026-10-29

- Full backend: **1,686 passed, 2 skipped**. Full frontend: **669 passed across 42 files**. Production build: **94 modules**.
- The worker CLI dispatch regression passes; the earlier missing-fusion/RED integration snapshot is superseded.
- Real GPU experiment completed with four valid 512×512 PNGs, seed 42, 12 steps, CFG 5.5 and alpha 0.5. Encoded content counts were positive **[75, 38]**, negative **[9, 0]**.
- Effective weights were [1, 0], [0.5, 0.5], [75/113, 38/113] and [0.5, 0.5], respectively. Equal-mean and anchor-residual output hashes matched: with exactly two chunks and alpha 0.5 these formulas are equivalent. This is expected, not a quality-ranking result.
- Real cancellation after sampling started at progress 6 reached terminal cancelled in **343 ms**; result was null, no PNG files remained, and process inspection found no identity worker or persistent Python worker afterward.
- After service restart, the Lab GUI restored the completed experiment and all four images. Final GUI checks reported no new errors beyond four connection refusals during the planned restart.
- Local evidence includes the fusion completion/cancellation records and browser snapshots. Private IDs, prompts, paths to personal images and image files are intentionally excluded from public documentation.

CPU tests separately cover paired arithmetic, encoding, one scheduler update, exclusive publication, cancellation/shutdown, request/origin guards, immutable metadata and single-service ownership. Neither those tests nor one GPU experiment establish aesthetic superiority, likeness, repeatable performance on other hosts or device parity. Main-release push/remote SHA/CI remain pending confirmation.
