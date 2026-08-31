# S24U H4 Visual Microscope Design

## Goal

Turn the H3 text-heavy runtime trace page into a visual-first, mathematically grounded, offline microscope for Stable Diffusion/SDXL execution on S24U while preserving PURE RAW, QNN/NPU execution, stable signing, and real native telemetry.

## Baseline

- Upstream Local Dream: `xororz/local-dream@a7666f6198412a58c6eb1eacc28828aa40c7d7ae` (2.8.1).
- H2 behavior retained: PURE RAW, fixed TEST-ONLY signing, fixed 77-slot QNN CLIP graph, multi-chunk prompt conditioning.
- H3 behavior retained: native SSE phases `prompt`, `clip`, `unet_step`, `scheduler_step`, `vae_decode`, `complete`.
- H4 package stays `io.github.xororz.localdream.s24uharness` so H3→H4 is an in-place upgrade.
- H4 version: `versionCode=7404`, `versionName=2.8.1-s24u-h4`.

## Open-source references

H4 uses external projects as interaction/design references, not as runtime network dependencies:

- `poloclub/diffusion-explainer` (MIT): architecture-first explanation, progressive text/denoise drill-down.
- Perfetto: timeline vocabulary for stage/step duration bars.
- DAAM / ComfyUI-DAAM: prompt-to-image attribution vocabulary. H4 MUST NOT display an attention heatmap unless real cross-attention data is collected.
- Netron: hierarchical model/tensor inspection vocabulary.

The bundled H4 visualizer is newly authored offline HTML/CSS/JS. No network access is required or permitted by the visualizer.

## Architecture

### Native telemetry

`Pipeline.hpp` and `main.cpp` remain the authoritative execution source. H4 extends prompt trace metadata with:

- input positive/negative token counts;
- effective positive/negative token counts actually sent through chunk conditioning;
- truncated positive/negative token counts;
- positive/negative chunk token counts;
- configured maximum chunk count.

H4 raises the fixed-shape long-prompt budget from 4 chunks to 8 chunks. Every CLIP/QNN invocation remains exactly 77 slots (`BOS + <=75 content + EOS/PAD`), so existing SDXL QNN model files remain compatible. Maximum effective content budget becomes about 600 content tokens.

### Android state reducer

`BackgroundGenerationService` keeps a single `MicroscopeSnapshot` but fixes H3 reducer semantics:

- `schedulerSeen` and `unetSeen` distinguish a real 0–3 ms event from “not observed”.
- `skipUncond` is only updated from `unet_step` events.
- trace-derived progress is monotonic and `complete` forces 100%.
- timing uses native event elapsed/duration values; UI never invents a second clock.
- token-budget fields are retained from the `prompt` event.

### Visual layer

The fourth pager tab remains `显微镜`, but the body becomes a local WebView that loads:

`file:///android_asset/s24u_microscope/index.html`

Compose serializes the current `MicroscopeSnapshot` plus generation metadata to JSON and calls:

`window.S24UMicroscope.update(snapshotJson)`

The WebView:

- enables JavaScript only for local visualizer logic;
- blocks external navigation and remote requests;
- has no JavaScript interface exposing Android objects;
- renders an SVG pipeline diagram, token/chunk grid, formulas, timeline and evidence panel.

### Visual hierarchy

1. **Teaching layer (default)**
   - animated pipeline: Prompt → Token/Chunk → CLIP → UNet → Fusion → Scheduler → Latent → VAE → Image;
   - active stage and completed stages from real events;
   - human-readable explanation of the current stage;
   - formulas with actual runtime substitutions.

2. **Diagnostics layer**
   - Perfetto-style horizontal timing lane;
   - per-step UNet/Scheduler bars;
   - chunk count and token budget;
   - explicit `input / effective / truncated` warning;
   - latent shape and backend.

3. **Expert evidence layer (collapsed by default)**
   - raw event list;
   - token IDs/chunk texts;
   - exact native fields.

### Formula contract

The visualizer always presents the implementation-consistent equations:

`K = min(Kmax, ceil(Ncontent / 75))`

`C_k = CLIP(T_k),  C_k ∈ R^(77×hidden)`

`ε_t^(k) = ε_u,t^(k) + s(ε_c,t^(k) - ε_u,t^(k))`

`ε̄_t = (1/K) Σ_k ε_t^(k)`

`z_(t-1) = Scheduler(z_t, ε̄_t, t)`

Runtime values (`K`, `hidden`, `step`, `t`, durations) are substituted beside the symbolic formula.

## Truthfulness rules

- Never render a fake cross-attention heatmap. Until real tensors are available, the attribution card must display `Cross-attention：未采集` and explain that QNN intermediate attention tensors are not exported in this build.
- Never label truncated prompt content as participating. Show input/effective/truncated counts separately.
- A 0 ms scheduler measurement is a valid observed event, not `WAIT`.
- Completion state always renders 100% even if the older generation-progress callback resets.
- Raw evidence remains available for audit.

## H4 acceptance criteria

1. H2 PURE RAW behavior passes regression contracts.
2. H3 native trace phases pass regression contracts.
3. Long prompt supports 8 fixed-77 chunks without changing QNN graph shapes or model weights.
4. Input/effective/truncated token counts are emitted by native code and visible in the visualizer.
5. Scheduler and skip-uncond reducer bugs are fixed by explicit seen/phase semantics.
6. Offline visualizer assets are bundled inside APK; no network dependency.
7. Visualizer contains live SVG architecture, formulas, timeline, token/chunk view and collapsed expert evidence.
8. DAAM-style attribution is truthfully marked unavailable unless real attention data exists.
9. Native arm64/QNN build passes.
10. Android unit tests and `assembleBasicDebug` pass.
11. APK package/version/native markers/offline assets/fixed certificate are independently verified.
