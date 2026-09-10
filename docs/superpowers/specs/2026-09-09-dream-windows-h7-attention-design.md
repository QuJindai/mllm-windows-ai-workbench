# Dream Windows H7 Attention Research Engine Design

## Goal

Add a real, debug-only cross-attention microscope to the browser version of Dream on Windows without changing the verified production generation engine or presenting derived placeholders as measured attention.

## Architecture

Dream keeps two native engines:

- The existing production engine remains selected by `E:\Dream\app\native-engine.json` and continues to serve ordinary generation and H6 latent traces.
- A separate H7 research build lives under `E:\Dream\app\stable-diffusion-cuda-h7` and is invoked only for `traceLevel=h7` jobs.

The research build exports a bounded attention index plus one compact map file per selected step/layer/token. The Python server validates this material before exposing it. The React application fetches one selected map at a time instead of loading all attention values into the runtime trace.

## Truth boundary

- Only native tensors marked `truth=observed`, `kind=cross-attention`, and `contractVersion=h7-attention-v1` may activate the H7 visualizer.
- Production generation never claims H7 availability.
- Missing, malformed, non-finite, oversized, or path-escaping artifacts are rejected and shown as unavailable.
- Latent projections, prompt weights, and chunk influence must never be relabeled as attention.

## H7 trace contract

Each H7 run may contain `E:\Dream\traces\<run-id>\attention-index.json`:

```json
{
  "contractVersion": "h7-attention-v1",
  "kind": "cross-attention",
  "truth": "observed",
  "source": "debug-unet",
  "tokens": [
    {"slot": 0, "tokenId": 49406, "text": "<start>", "chunk": 0, "weight": 1.0}
  ],
  "layers": [
    {"id": "down-1", "stage": "down", "label": "Down 1"}
  ],
  "maps": [
    {
      "id": "s00-down-1-t00",
      "step": 0,
      "layerId": "down-1",
      "tokenSlot": 0,
      "width": 64,
      "height": 64,
      "fileName": "attention-s000-down-1-t000.json",
      "entropy": 0.71,
      "peak": 0.83,
      "coverage": 0.24
    }
  ]
}
```

Each map file contains the same identity fields plus `values`, a row-major normalized array whose length equals `width * height`. The server exposes the index at `/api/traces/{run_id}/attention` and one selected map at `/api/traces/{run_id}/attention/maps/{map_id}`.

## Bounds

- At most 77 tokens.
- Exactly three representative layers at most: one `down`, one `mid`, one `up`.
- At most 50 denoising steps and 512 map descriptors per run.
- Map dimensions are between 1 and 128; a map contains at most 16,384 finite values.
- Normalized values and metrics are within `[0, 1]`.
- The native exporter samples a bounded subset of token slots and steps rather than copying the full head-by-query-by-token tensor to CPU.

## Native capture strategy

The H7 stable-diffusion.cpp worktree is `E:\Dream\src\stable-diffusion.cpp-h7` on branch `feature/dream-h7-attention`. The debug path disables diffusion flash attention only for H7 so the cross-attention probability tensor exists. Three named UNet transformer locations reduce probabilities across heads on-device before copying the compact token-by-spatial map to the host. Ordinary production runs retain flash attention and do not build capture nodes.

The primary image output from the H7 build must match the production output within a frozen numeric/image tolerance for identical model, prompt, seed, sampler, dimensions, and steps. Failure blocks H7 activation.

## Browser experience

The H7 tab provides:

- Real token slots and token IDs from the native tokenizer.
- Down/Mid/Up layer selection and a denoising-step scrubber.
- A spatial heatmap for the selected token, step, and layer.
- Peak, entropy, and coverage metrics.
- Explicit `Debug only` and `observed` labels.
- An unavailable panel when no validated native attention artifact exists.

## Acceptance

1. A production/basic trace exposes no attention data.
2. A malformed or demo attention index cannot activate H7.
3. A valid observed fixture can be selected and rendered end-to-end through the real HTTP provider.
4. The research engine emits non-constant maps that change with token and layer.
5. H7 output passes parity against the production engine.
6. H7 remains opt-in and does not change normal generation latency or memory use.
