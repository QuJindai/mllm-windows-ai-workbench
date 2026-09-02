# S24U H6 Conditioning Influence Microscope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add truthful per-prompt-chunk conditioning influence telemetry and visualization to the S24U Local Dream microscope without changing generation results or adding inference passes.

**Architecture:** Apply one H6 patch after the verified H2→H5 patch chain. The native loop temporarily retains each current-step `chunk_pred`, computes metrics and a reduced spatial difference map against the already-computed fused prediction, emits bounded trace events, and releases those tensors before the scheduler step. Android/WebView transport uses the existing H5 bootstrap+delta pattern and adds a dedicated Influence panel.

**Tech Stack:** C++17/xtensor, Local Dream native QNN pipeline, Kotlin/Compose/WebView, HTML/CSS/vanilla JS, Python patch/contract tests, GitHub Actions, Android Gradle, QAIRT Community SDK 2.39.0.250926.

**Spec:** `docs/superpowers/specs/2026-09-01-s24u-h6-conditioning-influence-design.md`

## Global Constraints

- Base: `feature/s24u-image-harness-h5-process-microscope@49d08e4c51059254203ad7f9906e49bffd293f80`.
- Version must be `versionCode = 7406` and `versionName = "2.8.1-s24u-h6"`.
- Package/signature continuity must remain unchanged from H5.
- No additional CLIP, UNet, VAE, or scheduler inference.
- Final `noise_pred` passed to the scheduler must remain the same H2 arithmetic mean of chunk predictions.
- Contribution maps must be labeled as chunk/fused prediction differences, never as cross-attention.
- Existing `Cross-attention 未采集` text remains visible.
- Histories and image transfer remain bounded/incremental.

---

### Task 1: Establish H6 RED contract

**Files:**
- Create: `s24u-image-harness/tests/test_h6_conditioning_influence_contract.py`

**Interfaces:**
- Consumes: H5-patched Local Dream tree.
- Produces: one source contract that fails on H5 and checks all H6 native/Android/UI invariants.

- [ ] **Step 1: Write the failing contract**

Require the following exact source markers after H6 is applied:

```python
require(gradle, "versionCode = 7406", "H6 versionCode")
require(gradle, 'versionName = "2.8.1-s24u-h6"', "H6 versionName")
require(pipeline, "conditioning_influence", "influence trace phase")
require(pipeline, "influence_chunk_index", "influence chunk index")
require(pipeline, "influence_mean_abs", "influence mean abs")
require(pipeline, "influence_l2", "influence L2")
require(pipeline, "influence_fused_cosine", "influence cosine")
require(pipeline, "influence_delta_l2", "influence delta L2")
require(pipeline, "renderConditioningInfluencePreview", "real spatial influence renderer")
require(pipeline, "chunk_predictions", "current-step chunk prediction retention")
require(main_cpp, '"influence_chunk_index"', "native SSE influence serialization")
require(service, "data class InfluenceSample", "Android influence model")
require(service, "influenceSamples: List<InfluenceSample>", "bounded influence history")
require(screen, "S24U_H6_CONDITIONING_INFLUENCE", "compiled H6 marker")
require(html, 'data-panel="influence"', "Influence panel")
require(html, 'id="influence-main-image"', "Influence image")
require(html, "不是 cross-attention", "truthful influence wording")
require(html, "Cross-attention 未采集", "preserved honest attribution state")
require(js, "influence_samples", "Influence local history")
require(js, "renderInfluence", "Influence renderer")
```

Also require that the H2 fusion line still exists:

```python
require(pipeline, "noise_pred = xt::eval(noise_pred / (float)conds.size())", "unchanged H2 fusion")
```

- [ ] **Step 2: Run on the H5 baseline and verify RED**

Run in CI before applying H6:

```bash
python3 s24u-image-harness/tests/test_h6_conditioning_influence_contract.py local-dream
```

Expected: non-zero exit, first missing requirement is `H6 versionCode`.

- [ ] **Step 3: Commit RED contract**

Commit message:

```text
test(s24u): add RED contract for H6 conditioning influence
```

---

### Task 2: Implement native conditioning influence telemetry

**Files:**
- Create: `s24u-image-harness/patch_h6.py`
- Modify generated Local Dream files through patch:
  - `app/build.gradle.kts`
  - `app/src/main/cpp/src/Pipeline.hpp`
  - `app/src/main/cpp/src/main.cpp`

**Interfaces:**
- Consumes: H5 `MicroscopeTraceEvent`, H2 `conds`, per-chunk `chunk_pred`, fused `noise_pred`.
- Produces: `phase="conditioning_influence"` trace events with scalar metrics and `image_base64`.

- [ ] **Step 1: Add H6 version and trace fields**

Patch H5 version to H6 and extend `MicroscopeTraceEvent` with:

```cpp
int influence_chunk_index = -1;
int influence_chunk_count = 0;
float influence_mean_abs = 0.0f;
float influence_l2 = 0.0f;
float influence_fused_cosine = 0.0f;
float influence_delta_l2 = 0.0f;
```

- [ ] **Step 2: Preserve per-chunk predictions only for the current step**

Replace the H2/H5 fusion loop with the same computation plus a bounded vector:

```cpp
std::vector<xt::xarray<float>> chunk_predictions;
chunk_predictions.reserve(conds.size());
for (auto &chunk_cond : conds) {
  // existing runUnetTiled/runUnetStep and CFG calculation stays unchanged
  chunk_predictions.push_back(chunk_pred);
  noise_pred = xt::eval(noise_pred + chunk_pred);
}
noise_pred = xt::eval(noise_pred / (float)conds.size());
```

Do not add any new inference call.

- [ ] **Step 3: Add metric helpers and real spatial renderer**

Implement helpers that iterate original tensors to compute mean absolute value, L2, cosine to fused, delta L2, and a grayscale JPEG/base64 image from channel-mean `abs(chunk_pred - fused_pred)`.

Renderer signature:

```cpp
inline std::string renderConditioningInfluencePreview(
    const xt::xarray<float> &chunk_pred,
    const xt::xarray<float> &fused_pred);
```

- [ ] **Step 4: Emit one influence event per chunk before scheduler step**

For each retained prediction:

```cpp
MicroscopeTraceEvent influence_trace;
influence_trace.phase = "conditioning_influence";
influence_trace.diffusion_step = i - start_step + 1;
influence_trace.diffusion_total = static_cast<int>(timesteps.size()) - start_step;
influence_trace.influence_chunk_index = static_cast<int>(chunk_index);
influence_trace.influence_chunk_count = static_cast<int>(chunk_predictions.size());
// populate metrics and image_base64
emit_trace(influence_trace);
```

Then let `chunk_predictions` leave scope before the next diffusion iteration.

- [ ] **Step 5: Serialize new fields in `main.cpp`**

Add the six influence fields to the existing native trace JSON. Do not change existing H3/H5 fields.

- [ ] **Step 6: Run source contract to confirm native portions turn GREEN**

Run the H6 contract after patching. It may still fail on missing Android/UI markers, but all native marker assertions must pass.

- [ ] **Step 7: Commit native implementation**

Commit message:

```text
feat(s24u): capture real H6 conditioning influence telemetry
```

---

### Task 3: Add Android bridge and Influence microscope panel

**Files:**
- Create: `s24u-image-harness/h6_assets/microscope/index.html`
- Create: `s24u-image-harness/h6_assets/microscope/microscope.css`
- Create: `s24u-image-harness/h6_assets/microscope/microscope.js`
- Extend: `s24u-image-harness/patch_h6.py`
- Modify generated Local Dream files through patch:
  - `app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt`
  - `app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt`
  - `app/src/main/assets/s24u_microscope/*`

**Interfaces:**
- Consumes: native `conditioning_influence` trace JSON.
- Produces: bounded `InfluenceSample` history and incremental WebView JSON, rendered by `renderInfluence()`.

- [ ] **Step 1: Add Android data model and parser**

Add:

```kotlin
data class InfluenceSample(
    val diffusionStep: Int,
    val diffusionTotal: Int,
    val chunkIndex: Int,
    val chunkCount: Int,
    val meanAbs: Float,
    val l2: Float,
    val fusedCosine: Float,
    val deltaL2: Float,
    val imageBase64: String,
)
```

Parse `phase == "conditioning_influence"`, append to a bounded history, and never store raw tensors.

- [ ] **Step 2: Bridge bootstrap+delta state**

Initial WebView attach sends `influence_samples` bounded history. Live updates send only the latest sample(s) under `influence_sample` while preserving H5 process/latent delta behavior.

- [ ] **Step 3: Create H6 microscope assets from H5 structure**

Keep H5 Overview/Process/Mechanism/Expert panels and add a fifth tab/panel:

```html
<button class="tab" data-tab="influence">条件影响</button>
<section class="panel" data-panel="influence">
  ...
  <img id="influence-main-image" alt="真实 conditioning influence 图">
  ...
  <p>这是 chunk prediction 相对 fused prediction 的差异，不是 cross-attention。</p>
</section>
```

Keep the Expert text `Cross-attention 未采集` unchanged.

- [ ] **Step 4: Implement `renderInfluence()`**

The JS stores bounded `influence_samples`, supports a diffusion-step scrubber and chunk selection, renders the contribution image and scalar metrics, and only re-renders while the Influence panel is active.

- [ ] **Step 5: Compile H6 marker into DEX-visible Kotlin**

Add `S24U_H6_CONDITIONING_INFLUENCE` to `ModelRunScreen.kt` and include it in the WebView snapshot JSON.

- [ ] **Step 6: Run full H6 source contract**

Expected:

```text
H6_CONDITIONING_INFLUENCE_CONTRACT_PASS
```

- [ ] **Step 7: Commit Android/UI implementation**

Commit message:

```text
feat(s24u): add H6 conditioning influence microscope panel
```

---

### Task 4: Add deterministic H6 GitHub Actions build and APK verification

**Files:**
- Create: `.github/workflows/s24u-image-harness-h6-build.yml`

**Interfaces:**
- Consumes: H2→H5 verified patch chain plus H6 patch/assets/test.
- Produces: signed H6 phone-test APK and evidence artifact.

- [ ] **Step 1: Copy the H5 workflow structure and retarget H6 branch/job names**

Use branch:

```yaml
branches: [feature/s24u-image-harness-h6-conditioning-influence]
```

Apply H2→H5 first, then execute H6 RED and GREEN.

- [ ] **Step 2: Verify native H6 markers**

After native rebuild, require strings:

```bash
grep -F -m1 'conditioning_influence' /tmp/h6-native-strings.txt
grep -F -m1 'influence_delta_l2' /tmp/h6-native-strings.txt
grep -F -m1 'image_base64' /tmp/h6-native-strings.txt
```

- [ ] **Step 3: Build and preserve APK**

Output:

```text
S24U_Image_Harness_H6_20260901.apk
```

- [ ] **Step 4: Deterministically verify APK**

Require package id, `7406`, `2.8.1-s24u-h6`, native core/QNN libs, H6 microscope assets, Influence panel, truthful non-attention wording, `Cross-attention 未采集`, native strings, DEX marker `S24U_H6_CONDITIONING_INFLUENCE`, expected signing certificate, and SHA-256 integrity.

- [ ] **Step 5: Upload phone-test evidence package**

Artifact name:

```text
s24u-image-harness-h6
```

Include APK, SHA-256/size, H2-H6 source logs, native build logs, Gradle logs, package/signing verification, and final verification PASS marker.

- [ ] **Step 6: Commit workflow**

Commit message:

```text
ci(s24u): build and verify H6 conditioning influence APK
```

---

### Task 5: Fresh verification and handoff

**Files:**
- No production changes unless verification exposes a defect.

**Interfaces:**
- Consumes: latest H6 branch head and workflow run.
- Produces: evidence-backed readiness verdict and phone-test artifact metadata.

- [ ] **Step 1: Inspect the H6 workflow run associated with the latest branch head**

Every required build/test/verification step must conclude `success`; skipped failure-evidence steps are acceptable.

- [ ] **Step 2: Inspect uploaded artifact metadata**

Record artifact id/name/size/digest and confirm it is not expired.

- [ ] **Step 3: Re-fetch the H6 branch head and confirm all intended commits are present**

- [ ] **Step 4: Report remaining gate honestly**

CI success makes H6 ready for S24U phone acceptance, not automatically phone-validated. The handset gate must check in-place installation/model retention, normal generation result equivalence, Influence live updates, scrubber/chunk selection, memory/thermal behavior, and UI smoothness.
