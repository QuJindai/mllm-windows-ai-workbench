# S24U H4 Visual Microscope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and ship a tested S24U H4 APK whose microscope is visual-first, formula-driven, truthful about prompt truncation, and backed by real QNN/native telemetry.

**Architecture:** Apply H2 + H3 to the pinned Local Dream baseline, then add an H4 patch that extends native prompt-budget telemetry, fixes Android reducer semantics, raises fixed-shape chunk capacity to 8, and replaces the H3 text-heavy microscope body with an offline local WebView visualizer. The visualizer is newly authored SVG/HTML/CSS/JS inspired by Diffusion Explainer/Perfetto/Netron interaction patterns and consumes only serialized local runtime state.

**Tech Stack:** Kotlin/Jetpack Compose, Android WebView, C++20, Qualcomm QNN/QAIRT, httplib SSE, HTML/CSS/SVG/vanilla JavaScript, Python patch/test scripts, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-31-s24u-h4-visual-microscope-design.md`

## Global Constraints

- Upstream is pinned to `xororz/local-dream@a7666f6198412a58c6eb1eacc28828aa40c7d7ae`.
- Package remains `io.github.xororz.localdream.s24uharness`.
- H4 version is `7404 / 2.8.1-s24u-h4`.
- QNN CLIP invocation remains fixed at 77 slots; no model weight replacement.
- H4 chunk limit is 8 (`8 × 75` content-token capacity).
- Visualizer must be completely offline and block external navigation/requests.
- No fake attention heatmap; unavailable attention must be labeled `未采集`.
- H2 PURE RAW, H3 native SSE and fixed TEST-ONLY certificate remain regression gates.

---

### Task 1: H4 RED contracts and reference manifest

**Files:**
- Create: `s24u-image-harness/tests/test_h4_visual_microscope_contract.py`
- Create: `s24u-image-harness/OPEN_SOURCE_REFERENCES_H4.md`

**Interfaces:**
- Consumes: H2/H3 patched Local Dream tree.
- Produces: one Python contract that fails on H3 and passes only after all H4 requirements are present.

- [ ] **Step 1: Write the failing H4 contract**

Require exact markers for version 7404, 8 chunks, token budget fields, `schedulerSeen`, phase-gated `skipUncond`, `traceProgress`, local WebView asset URL, network blocking, formula/timeline/attention-unavailable markers and bundled visualizer files.

- [ ] **Step 2: Run RED against H3**

Run:

```bash
python3 s24u-image-harness/tests/test_h4_visual_microscope_contract.py local-dream
```

Expected: FAIL first on H4 version marker.

- [ ] **Step 3: Commit RED evidence contract**

Commit message:

```text
test(s24u): define H4 visual microscope contracts
```

### Task 2: Native token-budget truth and 8-chunk execution

**Files:**
- Create: `s24u-image-harness/patch_h4.py`
- Modify generated tree: `app/src/main/cpp/src/TextEncoder.hpp`
- Modify generated tree: `app/src/main/cpp/src/main.cpp`
- Modify generated tree: `app/src/main/cpp/src/Pipeline.hpp`

**Interfaces:**
- Consumes: `TextEncoder::splitPromptChunks`, H3 prompt SSE.
- Produces: H4 prompt trace fields `positive_input_tokens`, `positive_effective_tokens`, `positive_truncated_tokens`, negative equivalents, chunk-token arrays, `max_chunks=8`.

- [ ] **Step 1: Make chunk budget 8 while retaining 77-slot graph**

Patch `kS24uClipChunks` from 4 to 8. Keep `kS24uClipChunkLen=77` and `kS24uClipContentTokens=75` unchanged.

- [ ] **Step 2: Emit exact effective-token evidence**

For each emitted chunk, tokenize the exact rendered chunk string. Sum emitted chunk token counts as effective; compute truncated as `max(0, input-effective)`.

- [ ] **Step 3: Run H2/H3/H4 source contracts**

Expected: all GREEN after H4 patch.

- [ ] **Step 4: Commit native H4 changes**

Commit message:

```text
feat(s24u): expose truthful H4 prompt budget telemetry
```

### Task 3: Correct Android reducer semantics

**Files:**
- Modify generated tree: `app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt`

**Interfaces:**
- Consumes: H4 SSE trace JSON.
- Produces: `MicroscopeSnapshot` with `schedulerSeen`, `unetSeen`, `traceProgress`, token-budget fields and stable `skipUncond`.

- [ ] **Step 1: Add observed-state booleans and token budget fields**

Use explicit booleans so a measured `0ms` remains observed.

- [ ] **Step 2: Update skip-uncond only for `unet_step`**

Do not copy the default `false` from unrelated events.

- [ ] **Step 3: Make progress trace-derived and monotonic**

For `unet_step` / `scheduler_step`, set `traceProgress = diffusionStep / diffusionTotal`; for `vae_decode`, at least `0.98f`; for `complete`, `1.0f`.

- [ ] **Step 4: Run H4 reducer source contract**

Expected: PASS.

- [ ] **Step 5: Commit reducer fix**

Commit message:

```text
fix(s24u): make microscope runtime state truthful
```

### Task 4: Offline visual microscope assets

**Files:**
- Create: `s24u-image-harness/h4_assets/microscope/index.html`
- Create: `s24u-image-harness/h4_assets/microscope/microscope.css`
- Create: `s24u-image-harness/h4_assets/microscope/microscope.js`
- H4 patch copies them to `app/src/main/assets/s24u_microscope/`.

**Interfaces:**
- Consumes: JSON snapshot from Compose.
- Produces: `window.S24UMicroscope.update(snapshot)`.

- [ ] **Step 1: Build SVG architecture layer**

Render Prompt, Token/Chunk, CLIP, UNet, Fusion, Scheduler, Latent, VAE, Image as SVG nodes/edges. `phase` controls active/completed classes.

- [ ] **Step 2: Build token/chunk evidence layer**

Render up to eight 77-slot chunk strips and explicit `input / effective / truncated` counts. If truncated > 0, show a prominent truncation warning.

- [ ] **Step 3: Build live formula layer**

Render the five implementation-consistent equations and substitute `K`, hidden size, CFG, diffusion step/timestep and durations.

- [ ] **Step 4: Build Perfetto-style timeline**

Render CLIP, every UNet step, Scheduler step and VAE as scaled horizontal bars using native `elapsedMs` / `durationMs`.

- [ ] **Step 5: Build truthfulness/evidence layer**

Render `Cross-attention：未采集` until real tensors are provided. Put raw events and token IDs in a collapsed `<details>` section.

- [ ] **Step 6: Run static asset contract**

Expected: H4 formula, timeline, architecture and unavailable-attention markers all found.

- [ ] **Step 7: Commit visualizer**

Commit message:

```text
feat(s24u): add offline visual diffusion microscope
```

### Task 5: Compose/WebView bridge

**Files:**
- Modify generated tree: `app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt`

**Interfaces:**
- Consumes: `MicroscopeSnapshot` StateFlow.
- Produces: serialized state pushed to local visualizer using `evaluateJavascript`.

- [ ] **Step 1: Replace text-first H3 microscope body with WebView host**

Load `file:///android_asset/s24u_microscope/index.html` inside `AndroidView`.

- [ ] **Step 2: Harden WebView**

Enable JavaScript/local assets, disable file URL cross-access, block non-`file:///android_asset/s24u_microscope/` navigation and all remote requests. Do not install a JavaScript Android interface.

- [ ] **Step 3: Serialize live snapshot**

Use `JSONObject` / `JSONArray` to create a JSON object containing generation metadata and every trace event required by the visualizer, then call `window.S24UMicroscope.update(<json>)` after page load and on state changes.

- [ ] **Step 4: Preserve expert fallback**

If WebView fails, show a compact Compose error card; raw state remains in snapshot and is not lost.

- [ ] **Step 5: Run H4 Compose/WebView contract**

Expected: PASS.

- [ ] **Step 6: Commit bridge**

Commit message:

```text
feat(s24u): bridge live QNN trace into visual microscope
```

### Task 6: Full CI build and APK verification

**Files:**
- Create: `.github/workflows/s24u-image-harness-h4.yml`

**Interfaces:**
- Consumes: pinned Local Dream + H2 + H3 + H3 capture fix + H4.
- Produces: verified `S24U_Image_Harness_H4_20260831.apk` artifact and evidence.

- [ ] **Step 1: Add RED→GREEN source gates**

Run H4 contract before patch and require failure; apply H4; run H2/H3/H4 contracts and require PASS.

- [ ] **Step 2: Build modified arm64 QNN native core**

Use Android 17/API 37.0, NDK `28.2.13676358`, Rust Android target and QAIRT `2.39.0.250926`.

- [ ] **Step 3: Run Gradle unit tests and assemble APK**

Run:

```bash
./gradlew --no-daemon --stacktrace \
  -PRELEASE_STORE_FILE=/tmp/s24u-test.jks \
  -PRELEASE_STORE_PASSWORD="$SIGN_PASS" \
  -PRELEASE_KEY_ALIAS="$SIGN_ALIAS" \
  -PRELEASE_KEY_PASSWORD="$SIGN_PASS" \
  testBasicDebugUnitTest assembleBasicDebug
```

Expected: exit 0.

- [ ] **Step 4: Verify APK content and signing**

Check package/version, native QNN core, offline microscope HTML/CSS/JS, H4 DEX marker, absence of `safety_checker.mnn`, and certificate SHA-256 `B60748D6461EF1F5E2681462F08EEBCA287B56B78BFAFC801499CC2BA461E005`.

- [ ] **Step 5: Upload APK and complete evidence**

Artifact must contain APK, SHA-256, native build log, Gradle log, source gates and APK verification evidence.

### Task 7: Independent artifact verification and handoff

**Files:**
- Download artifact to `/mnt/data`.
- Produce: `/mnt/data/S24U_Image_Harness_H4_20260831.apk`
- Produce: `/mnt/data/S24U_Image_Harness_H4_20260831.sha256`

**Interfaces:**
- Consumes: final GitHub Actions artifact.
- Produces: user-downloadable APK proven independently from CI.

- [ ] **Step 1: Extract final artifact locally**

- [ ] **Step 2: Recompute SHA-256 and inspect APK ZIP**

Verify native core, QNN libs, H4 offline assets, and absence of safety checker.

- [ ] **Step 3: Compare against CI SHA**

Expected: exact match.

- [ ] **Step 4: Deliver APK and SHA file**

Provide direct sandbox links and a compact phone test checklist focused on visual architecture, formulas, 8-chunk prompt evidence, timeline and truthful attention-unavailable state.
