# Task 3 latent correlation — 2026-09-28

Plan: `docs/superpowers/plans/2026-09-28-core-completion.md`, Task 3 plus the
requested spatial delta image and selected-channel comparison follow-up.

## Implementation and decisions

- Confirmed production source through `scripts/build_dream_cuda_engine.ps1`,
  `E:/Dream/builds/stable-diffusion-cuda-12.9.1-latent/CMakeCache.txt`, and
  `E:/Dream/app/native-engine.json`. Updated both native source trees in place.
- Extracted only the production inline writer to match H7's header layout.
  Preserved pre-existing native and shared application edits.
- Original floating latents, all batch/spatial observations, centered double
  accumulation, symmetric bounded Pearson matrix; zero variance/nonfinite
  channels emit null for every associated entry, including the diagonal.
- Backend accepts snake and camel matrix/method fields and existing channel
  file-name aliases. Rejects malformed dimensions, incomplete channel sets,
  nonnumeric/nonfinite/out-of-range values, asymmetry, inconsistent null rows,
  wrong methods and conflicting aliases. Existing records without correlation
  remain available without inventing correlation fields.
- Ruling: accept diagonal error up to `1e-12` while preserving the original
  number, because the real identity collector produces `0.9999999999999998`.
  Range and symmetry remain strict. A more-than-roundoff diagonal is rejected.
- Public root stays `truth: observed`; Pearson is labeled as derived from
  observed original latents. `trace.ts` edits add `channelCorrelation`,
  `correlationMethod`, `deltaFileName` and `deltaImageUrl`. Main agent owns its
  independent source/method unions.
- Accessible table follows the selected actual telemetry step. Sparse-step UI
  test checks displayed steps 3, 8 and 10, arrows/slider, null cells, and clearing
  the table for an older record. Malformed matrices are unavailable in the UI.
- Only latent component imports and insertions changed in `MicroscopePage.tsx`.
  `SelectedChannelComparison` independently displays min/max/mean/std/L2 for
  the selected channel in previous/current/final samples; global comparison is
  unchanged. Missing samples/channels remain explicitly unavailable.
  Identity collection, attention gating and history transactions remain owned
  by their assigned agents.
- Ruling: user instructions override the plan's installation/real-GPU steps.
  No GPU engine execution, installation, activation, profiles/photos, commits,
  or pushes were performed. GPU/browser deployment acceptance remains with main.

## Native builds and retained evidence

Both are successful incremental Release builds of the CUDA-linked `sd-cli`
target. Each first passed 14 CPU cases executing the actual writer. No CUDA
engine executable was run.

| Tree | Built executable | SHA256 |
| --- | --- | --- |
| Production | `E:/Dream/builds/stable-diffusion-cuda-12.9.1-latent/bin/sd-cli.exe` | `76830FB0D9C3EF65D6B849995914F343F4692A88D780C66FF6D32986FCA5DE18` |
| H7 | `E:/Dream/src/stable-diffusion.cpp-h7/build-h7-cuda-ninja/bin/sd-cli.exe` | `F8FE76A3F5684F2F0DEB5A09CCE9A411F572DFD89389094CA4BC0C6A40CD8729` |

- Production logs, CPU test executables and correlation/delta JSONL/PNG fixtures:
  `E:/Dream/test-runs/latent-correlation-20260928-182627-480`.
- H7 logs, CPU test executables and correlation/delta JSONL/PNG fixtures:
  `E:/Dream/test-runs/latent-correlation-20260928-182749-831`.
- Both fixture sets passed `scripts/verify_latent_correlation.py`: seven native
  samples and 14 saved-trace/latent HTTP roundtrips each (28 total), exact numeric
  and null preservation, real PNG decoding. This is CPU integration evidence,
  not a real model-generation acceptance run.
- Each build's seven-step delta fixture also passed saved-trace validation and
  three actual PNG responses through the existing frame route (six images total).
  Decoded pixels match hand-derived `[0,111,255]`, zero-change `[0,0,0]`, and
  uniform-change `[255,255,255]`. The intentional write-failure warning is expected.
- Installed production CLI remains SHA256
  `724A8C01B67926E5B87DA7D81C3F8D1B7B10F22FA293E3959EC5A2B56CD21494`;
  installed H7 CLI remains
  `971896EDDB0685DD9DC47D2028E1262749AA56F10479969B9775F1A72561BCA0`.

## TDD and application verification

- Observed RED: missing native field; backend dropped valid matrices and
  accepted malformed matrices; UI had no matrix. Implemented and observed GREEN.
- Observed RED for nine UI malformed cases, then GREEN after defensive checking.
- Observed RED for diagonal roundoff and the actual identity CPU collector,
  then GREEN after bounded diagonal tolerance. Collector file was not modified.
- Focused backend correlation suite: 26 passed, including actual CPU Torch
  identity collector interoperability and raw/public persistence.
- Follow-up RED→GREEN: missing native delta field, backend filename/route handling,
  sparse-step delta display and selected-channel comparisons. Focused correlation
  plus delta backend suite: 36 passed.
- Full frontend: 265 passed, 25 test files;
  `E:/Dream/test-runs/latent-delta-ui-full.log`.
- TypeScript app/node checks and Vite production build passed. Build output is
  isolated at `E:/Dream/test-runs/latent-delta-frontend-build`; serving assets were
  not replaced. Build-info files are in `E:/Dream/test-runs/latent-delta-*.tsbuildinfo`.
- Full backend final rerun: 625 passed in 111.33 seconds;
  `E:/Dream/test-runs/latent-delta-backend-full.log`. CUDA visibility was
  disabled; the Python runtime reports Torch `2.13.0+cpu`.
- Final review: self-review (no subagent tool), against the plan/spec and scoped
  diff. Reviewed original-float math, null semantics, alias validation, shared
  file boundaries, patch application, artifact paths and untouched installation.
  Independent whole-change review remains with the main integrator.
- `git diff --check` passed. Both native patches also passed reverse-apply
  checks against the current source trees; all three helper copies have SHA256
  `8AF5F08AE25D3112C3405F2947BB6767A390C39CFDB71D7844F04AA91324C3F3`.

## Reproducibility assets

`native/latent-correlation/{production.patch,h7.patch,latent_correlation.h,README.md}`,
`scripts/build_latent_correlation.ps1`, and
`scripts/verify_latent_correlation.py`. Both patches were applied to saved
pre-task fixtures and matched the edited native files. These are Task 3 deltas
on the pre-existing Dream-instrumented baseline; see the README prerequisite.

Application code/tests: `server/job_runner.py`,
`server/tests/test_latent_correlation.py`,
`server/tests/test_native_latent_telemetry_contract.py`,
`src/domain/trace.ts`, `src/app/components/CorrelationMatrix.tsx` and its tests,
`src/app/pages/MicroscopeCorrelation.test.tsx`, and the latent placeholder in
`src/app/pages/MicroscopePage.tsx` (paths under `apps/dream-windows`).

Follow-up files: `server/tests/test_latent_delta.py`, the two latent-only methods
in `server/runtime.py`, `src/app/components/LatentDeltaImage.tsx`,
`src/app/components/SelectedChannelComparison.tsx` and its tests; native
`tests/test_latent_delta.cpp` is included in both patches.

## Exact identity-producer delta contract

For zero-based `step: 7`, export the optional raw field:

```json
{"delta_file_name": "latent-step-007-delta.png"}
```

Place that PNG in the same trace directory as channel PNGs. Preserve the existing
`shape: [W,H,C,B]` and `truth: observed`. Compute a W×H field from original floats:
`mean(abs(current - previous), axis=(0,1))` for B×C×H×W tensors. Encode grayscale
uint8 by flooring `255 * field / max(field)`, using all black for max=0. This is
derived data; color normalization is per step and cannot compare absolute
strength across steps. No extra raw delta metadata is required.

Omit the field entirely (do not send null) without a compatible previous latent,
on nonfinite differences, or if the PNG could not be written. Backend accepts
`delta_file_name` and persisted `deltaFileName`, checks the basename, sample step,
alias agreement and in-root file existence. It exposes `deltaFileName` and creates
`deltaImageUrl: /api/traces/{runId}/latent/frames/{fileName}`. Incoming URLs are
discarded; undeclared files return 404. Older samples without this field retain
their statistics and show an unavailable delta image. Identity writer remains
owned by main and was not modified by this follow-up.
