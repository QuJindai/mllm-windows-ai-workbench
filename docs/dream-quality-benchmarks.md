# Dream pixel diagnostics and benchmark receipts

Status, 2026-10-29: diagnostic/receipt tools and independent refinement integration
are implemented. The separate CPU edge-lighting helper is connected to the worker
and returns actual mask diagnostics. See the [creative upgrade acceptance record](dream-windows/CREATIVE_UPGRADE_20261029.md)
for current GPU, GUI, integrity and release status.

The follow-up `immutable-scene-luma-ring-v3` guard checks each quantized proposal
against that pixel's original scene-luma residual. Non-improving proposals are
discarded without changing the target-derived mask. See the
[composition and local-lighting repair](dream-windows/COMPOSITION_REPAIR_20261029.md)
for the real-fixture regression and its limits; older measurements below remain
historical evidence for the v2 implementation.

These diagnostic tools do not themselves execute generation, initialize CUDA,
stop workers or select a better image. They produce no identity score, combined
quality score, automatic ranking or automatic correction. Real observations below
do not override the metric caveats or establish perfect likeness.

## Integration API

```python
from identity_quality import image_diagnostics, compare_images

image_diagnostics(image, *, edit_mask=None, protected_mask=None) -> dict
compare_images(baseline, candidate, *, edit_mask=None, protected_mask=None,
               baseline_label='baseline', candidate_label='candidate') -> dict
```

Inputs: PIL RGB images or NumPy `uint8[height,width,3]`. Masks: native-size PIL
L/1 or NumPy uint8/bool arrays. Images must have matching dimensions and already
share coordinates, orientation and colour encoding. Alpha, palette, grayscale
images, floating-point masks and automatic resizing are intentionally rejected;
preprocess explicitly and preserve that operation in source metadata. NumPy and
Pillow are required; no model/recognition package is imported.

All mask values greater than zero belong to the region, including feather pixels.
`protected_mask` is independently supplied; it is never inferred from an edit
mask's complement, which also includes background. Missing masks return `null`
for their regions. Empty regions report zero pixel count but `null` averages and
retention fractions. This avoids claiming perfect preservation without evidence.

Reports are JSON-safe and have `schemaVersion: 1`:

| Field | Meaning and unit |
| --- | --- |
| `regions.whole/protected/editSupport/outsideEdit` | Per-image statistics, or null when the relevant mask is absent |
| `pixelCount` | Number of selected pixels |
| `meanLuma`, `lumaStdDev` | Encoded RGB weighted by 0.2126/0.7152/0.0722, 0–255; not physical luminance |
| `channelEndpointFraction` | Fraction of channels exactly 0 or 255; descriptive, not proof of clipping |
| `meanAbsLumaNeighborDifference` | Mean absolute 4-connected difference, pairs entirely inside the region |
| `laplacianVariance` | Variance of a 4-neighbor luma Laplacian; only complete 3×3 neighborhoods inside the region |
| `retention.*.exactRetentionFraction` | Fraction of pixels whose three RGB channels are all unchanged |
| `changedPixels`, `meanAbsoluteRgbDelta`, `maxAbsoluteRgbDelta` | Changed pixel count and RGB-channel absolute differences, 0–255 |
| `seam.edgeCount` | Horizontal/vertical edges crossing edit support; includes both boundaries of a ring, excludes canvas border |
| `baselineMeanAbsRgbJump`, `candidateMeanAbsRgbJump` | Mean absolute RGB channel jump across the same edges |
| `meanAbsRgbJumpChange` | Candidate jump magnitude minus baseline jump magnitude; negative is not proof of improved appearance |
| `meanAbsResidualRgbJump` | Absolute change of the signed edge differences; distinguishes new discontinuities from unchanged scene edges |
| `lighting.meanLumaDelta/meanAbsoluteLumaDelta/meanRgbDelta` | Whole-image signed/absolute brightness and signed channel changes |

Pair reports include both complete per-image reports, named baselines, retention,
lighting and seam fields. Edge/neighborhood counts accompany statistics. A flat
image can have perfect continuity but no useful detail; noise can increase texture.
Natural edges, contrast, resolution, composition and mask shape all affect values.
Do not compare these as universal quality scores or identity similarity.

## Protected-face baseline findings and implemented integration

The earlier protected-face-v3 review identified two distinct baselines: original
scene→reference anchor and anchored image→later polish. Alpha composition preserves
zero-mask pixels against its immediate input; it does not prove that original
scene pixels survived an earlier reference replacement. A whole-face median LAB
offset may change feature colours before later polish preserves those anchored
features. It does not establish directional lighting or likeness.

Current independent `edge-lighting` is wired to `improve_edge_lighting(config,
item, image, strength, stage)`. The immutable original scene is supplied as
`item.scenePath`; the selected version remains the edit input. The helper returns
actual edit/protected mask diagnostics, which the refinement engine retains.
It avoids generation/FacePolisher loading and publishes no unchanged version.

The observed CPU candidate preserved protected and outside-edit pixels exactly
(100% in both regions), changed 3,839 pixels and had a maximum absolute RGB-channel
delta of 2/255. This is a subtle bounded correction, not evidence of an aesthetic
winner. Those mask-based claims come from the processor report; an older generic
comparison with null masks must not be retroactively treated as mask evidence.

Continue to compare original→anchor, anchor→polish and polish→next-pass separately.
Supply native-size edit and independently defined protected masks, keep their
baseline/provenance, and preserve the uncorrected version. Missing masks remain
null. A lower seam jump alone cannot select the better image; do not substitute
global smoothing, face restoration or an invented identity score. Private mask
files and image artifacts stay local.

## Freeze a reproducible image dataset

The manifest is local and can contain private paths/prompts. It preserves all
unknown metadata fields, seeds, complete settings and source objects; it does not
copy, upload or modify image files. Relative paths resolve against the input spec.
Freezing creates absolute paths plus SHA-256 for each baseline, variant and mask.
Evaluation rejects any file-byte change and decodes exactly the bytes verified.

Minimal input spec (replace the example with actual recorded generation settings):

```json
{
  "schemaVersion": 1,
  "datasetId": "protected-face-comparison-20261029",
  "cases": [{
    "id": "reference-a-anchor-to-pass1",
    "route": "anime-visual-reference",
    "baseline": {
      "label": "anchored-before-polish", "path": "anchor.png", "seed": 42,
      "settings": {"modelId": "actual-model-id", "note": "retain full original request here"},
      "source": {"jobId": "actual-job-id", "stage": "anchor", "referenceSha256": "record actual hash"}
    },
    "variants": [{
      "id": "pass1", "path": "pass1.png", "seed": 42,
      "settings": {"modelId": "actual-model-id", "note": "retain full actual refinement request here"},
      "source": {"jobId": "actual-job-id", "stage": "harmonize", "parent": "anchor"}
    }],
    "masks": {"edit": {"path": "ring.png"}, "protected": {"path": "protected.png"}}
  }]
}
```

Use separate cases for different comparison baselines and routes. Include actual
model/adapter hashes, reference hashes, pipeline version, prompt/negative prompt,
dimensions, steps, sampler, CFG, strengths, precision and seeds in source/settings.
These objects are retained without normalization; the tool cannot infer missing
generation parameters or guarantee bit-exact reruns across different runtimes.
Do not invent missing historical settings. Freeze only known complete cases.

```powershell
python E:/Dream/repo/scripts/benchmark_dream_quality.py freeze E:/Dream/test-runs/quality/spec.json --output E:/Dream/test-runs/quality/manifest.json
python E:/Dream/repo/scripts/benchmark_dream_quality.py evaluate E:/Dream/test-runs/quality/manifest.json --output E:/Dream/test-runs/quality/quality-report.json
```

Programmatic helpers in `benchmark_dream_quality`:

```python
freeze_manifest(spec: dict, *, base_dir: Path) -> dict
evaluate_manifest(manifest: dict) -> dict
canonical_hash(manifest: dict) -> str
```

Both commands write only to a new output file (`open(..., 'x')`); existing reports,
manifests and inputs cannot be overwritten. Output directories must exist. Reports
include the full frozen manifest and its canonical JSON SHA-256. Image diagnostics
are deterministic for the same inputs/runtime, with no timestamp added to reports.

## Cold/warm timing receipts

`benchmark_dream_performance.py` is an offline summarizer, not a measurement runner.
The operator owns scheduling, cancellation, worker reuse/release boundaries and
device synchronization appropriate to a measurement. This tool never restarts a
worker or kills a process to force a cold run.

Current observed restore receipts were contended: three Unity processes and
concurrent backend tests were present. Cold/warm wall time was 79.938 s / 49.296 s,
load 42.540 s / 1.173 ms, with identical output hashes and sessionReused false / true.
No uncontended benchmark was obtained; these receipts remain excluded from clean
performance aggregates and do not imply a speed guarantee.

`summarize_runs(manifest: dict, runs: list[dict]) -> dict` requires each run to bind
to the manifest's canonical SHA-256 and an existing case/variant. The variant's full
provenance is attached to the output; this is caller-declared binding, not automatic
verification that a generator actually used those settings. Supply an observed
receipt or artifact path/hash under `source` to make that binding auditable.

Example shape (numbers are illustrative, not measured performance):

```json
[{
  "runId": "run-01", "caseId": "reference-a-anchor-to-pass1", "variantId": "pass1",
  "manifestSha256": "canonical_hash(manifest) value",
  "sessionId": "observed-worker-session-id", "temperature": "cold",
  "temperatureEvidence": "New worker/pipeline observed; OS cache state unknown",
  "outcome": "complete", "uncontended": true,
  "wallMs": 10000,
  "phasesMs": {"load": 3000, "samplingDecode": 5000, "facePolish": 1500, "save": null},
  "environment": {"device": "actual device", "runtime": "actual versions", "codeRevision": "actual SHA"},
  "source": {"receiptPath": "path to original observation", "receiptSha256": "actual hash"}
}]
```

Cold means fresh worker/pipeline initialization; OS/file caches may still be warm.
Warm means an observed compatible loaded processor or pipeline was reused in that session.
Neither a first batch index nor a feature-cache hit proves either state. Record
temperature evidence and hardware/software/code configuration for every receipt.

Phase durations are **disjoint wall-clock intervals inside the same wallMs**:

| Phase | Existing evidence / limitation |
| --- | --- |
| `load` | May sum reference/features and model/conditioning initial stages, only when actually incurred in this measured run |
| `samplingDecode` | Existing `采样与 VAE 解码` includes sampling and VAE decode; do not relabel it sampling-only |
| `facePolish` | Existing `可选修脸` duration, including its setup; nested pass timings must not be added again |
| `save` | Explicit measurement if instrumented; absent current metadata must stay null |

The current initial-stage metadata can outlive a warm session; never blindly copy
old load times into a new warm receipt. Explicit observed no-load/no-polish can be
zero. Missing/uninstrumented is null or omitted. Sum exceeding wallMs is rejected
to expose overlap/stale timing or inconsistent boundaries; use original precision
when independent rounding would make totals exceed the wall measurement.

Output groups are separated by case, variant, cold/warm and complete environment
object. Each phase has its own sample count, median, min and max; there is no
cross-case speed ranking. Failed/cancelled/contended runs remain in `runs` and
`excludedRuns`. `unattributedMs` is only computed when all three principal phases
are known, and may include save/queue/other overhead; it is not an inferred phase.

```powershell
python E:/Dream/repo/scripts/benchmark_dream_performance.py E:/Dream/test-runs/quality/manifest.json E:/Dream/test-runs/quality/receipts.json --output E:/Dream/test-runs/quality/performance-report.json
```

## Verification boundary

Synthetic tests exercise known pixel changes, a hard seam, an unchanged natural
edge, uniform exposure change, a blurred checkerboard, texture-region isolation,
empty/missing/tiny masks, real PNG hashes and drift, JSON CLI output, receipt
binding, cold/warm separation, missing phases and exclusion of failed/busy runs.
They do not establish real-face likeness, aesthetic quality, a clean GPU speed
benchmark or anime quality. Current local acceptance separately includes real
restore/fusion outputs, four successful anime scenes, refinement selection/revert,
28-step/84-row microscope GUI comparison and 426 unchanged baseline files. Anime
waist-up prompts still yielded head-and-shoulders framing; the failed Illustrious
Plus experimental route stays disabled. Private originals, variants, masks,
manifests and receipts remain local. Main-release push/remote SHA/CI are pending.
