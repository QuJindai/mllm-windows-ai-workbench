# S24U H6 Conditioning Influence Microscope Design

## Goal

Extend the current H5 process microscope with truthful, low-overhead observability of how each H2 prompt chunk contributes to every diffusion step, without adding inference passes, modifying model weights, changing the final generated image, or pretending contribution telemetry is cross-attention.

## Baseline

- Repository: `QuJindai/mllm-windows-ai-workbench`
- Base branch/commit: `feature/s24u-image-harness-h5-process-microscope@49d08e4c51059254203ad7f9906e49bffd293f80`
- Local Dream upstream remains pinned to v2.8.1 commit `a7666f6198412a58c6eb1eacc28828aa40c7d7ae`.
- H2 keeps at most four fixed 77-slot CLIP/QNN passes and averages per-chunk CFG noise predictions before one scheduler step.
- H5 already exposes real VAE process previews and real four-channel latent state previews.

## H6 User Contract

H6 adds an `Influence` microscope panel that shows, for each diffusion step and each active prompt chunk:

1. Exact chunk text and chunk index.
2. `mean_abs`: mean absolute value of that chunk's CFG noise prediction.
3. `l2`: L2 norm of that chunk prediction.
4. `fused_cosine`: cosine similarity between that chunk prediction and the final fused prediction used by the scheduler.
5. `delta_l2`: L2 norm of `chunk_pred - fused_pred`.
6. A real spatial contribution image computed from `abs(chunk_pred - fused_pred)`, channel-reduced into a single latent-space intensity plane and JPEG/base64 encoded for microscope display.

The UI must label this data as conditioning contribution/influence. It must continue to state `Cross-attention 未采集` and must never call the contribution map an attention heatmap.

## Native Architecture

The H2 denoising loop already computes each `chunk_pred` before averaging. H6 keeps these tensors only for the current diffusion step in a bounded vector of at most four entries. After the fused prediction is calculated, H6 computes scalar metrics and one reduced contribution map per chunk, emits them through the existing microscope trace callback, then releases the per-step chunk tensors before the scheduler advances.

No extra UNet invocation is permitted. The exact fused `noise_pred` passed to `scheduler->step(...)` remains unchanged.

### Trace event fields

Extend `MicroscopeTraceEvent` with contribution metadata:

- `int influence_chunk_index = -1`
- `int influence_chunk_count = 0`
- `float influence_mean_abs = 0.0f`
- `float influence_l2 = 0.0f`
- `float influence_fused_cosine = 0.0f`
- `float influence_delta_l2 = 0.0f`
- existing `image_base64` carries the reduced contribution image for `phase="conditioning_influence"`

One event is emitted per active chunk per diffusion step.

## Spatial Map

For tensor shape `[1, C, H, W]`, compute `abs(chunk_pred - fused_pred)`, average over `C`, normalize the resulting `H × W` plane by its min/max for visualization only, convert to grayscale RGB, JPEG encode, then base64 encode.

The normalization affects only the displayed map. Scalar metrics are computed from the original float tensors.

## Android Bridge

Extend the H5 microscope state with a bounded `InfluenceSample` history. Each sample contains diffusion step metadata, chunk index/count, four scalar metrics, and optional base64 image. History is bounded by both steps and chunk count; the implementation must never retain raw prediction tensors on the Android side.

The WebView bridge follows the H5 bootstrap+delta pattern:

- First attach: send bounded influence history once.
- Live updates: send only the newest influence sample(s).
- Existing process/latent media transport behavior remains unchanged.

## UI

Add a fifth top-level panel/tab: `Influence` / `条件影响`.

The panel contains:

- step scrubber;
- chunk selector/cards showing exact chunk text;
- metric cards for `mean_abs`, `L2`, `cosine`, and `delta L2`;
- contribution image viewer;
- per-step contribution bars/curves for active chunks;
- an explicit note: `这是 chunk prediction 相对 fused prediction 的差异，不是 cross-attention。`

The existing Expert attribution card continues to display `Cross-attention 未采集`.

## Performance Constraints

- No additional CLIP, UNet, VAE, or scheduler inference.
- Hold at most four chunk prediction tensors for the current step.
- Encode contribution previews at modest JPEG quality comparable to H5 latent maps.
- Keep Android/WebView histories bounded.
- Preserve H5 requestAnimationFrame coalescing, active-panel rendering, and incremental media updates.

## Versioning

- `versionCode = 7406`
- `versionName = "2.8.1-s24u-h6"`
- package id remains `io.github.xororz.localdream.s24uharness`
- signing identity remains the existing public TEST-ONLY H2+ identity so model-private storage survives in-place upgrades.

## Verification

H6 follows RED→GREEN.

The contract test must fail on the H5 baseline and then require:

- H6 version values;
- per-chunk tensor retention only within one diffusion step;
- metric computation and `conditioning_influence` trace events;
- spatial contribution renderer;
- serialization through native SSE and Android state;
- bounded history and bootstrap+delta WebView bridge;
- `Influence` panel controls and truthful non-attention wording;
- preserved `Cross-attention 未采集` wording;
- preserved H5 process/latent contracts.

GitHub Actions must rebuild the QNN native core, run contract/unit tests, build/sign the APK, verify package/version/native libraries/DEX H6 marker, and upload a phone-test artifact.

## Out of Scope

- Exporting QNN cross-attention tensors.
- Recompiling model graphs to expose attention outputs.
- Token-by-token ablation reruns.
- Any semantic prompt rewrite.
- Any modification of the final fused noise prediction used for generation.
