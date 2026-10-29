# S24U Image Harness H2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an S24 Ultra test APK that preserves already-downloaded models across future APK upgrades, provides a one-time no-redownload migration path from H1, and raises the effective SD/SDXL prompt budget beyond CLIP's single 77-token window without replacing the user's existing model files.

**Architecture:** Keep Local Dream v2.8.1 (`a7666f6198412a58c6eb1eacc28828aa40c7d7ae`) as the immutable upstream baseline and apply a small S24U patch set. H2 introduces a stable test signing identity for all future H2+ upgrades, a `run-as` backup/restore bridge for the one unavoidable H1 signature transition, and native multi-pass prompt chunking: each CLIP chunk remains the existing fixed 77-token QNN shape while denoising evaluates all chunks and blends their noise predictions, so no SDXL/QNN model re-download is required. The Android UI reports the expanded effective token budget and exposes pure-RAW prompt behavior.

**Tech Stack:** Android/Kotlin/Compose, C++17/NDK, Local Dream, Qualcomm QAIRT/QNN 2.39.0.250926, GitHub Actions, Python contract tests.

**Spec:** User request in the 2026-08-31 S24U local image-generation validation thread.

## Global Constraints

- Do not optimize or change image-generation speed as an H2 goal.
- Do not require re-downloading the existing multi-GB SDXL model for H2 token expansion.
- Preserve package id `io.github.xororz.localdream.s24uharness`.
- H1 used an ephemeral CI debug signing key; provide a one-time backup/uninstall/install/restore path before switching to the permanent H2 test signing identity.
- From H2 onward, use the same signing identity so normal Android upgrades preserve `filesDir/models`.
- Long-prompt mode must keep each QNN text/UNet context invocation at the existing 77-token shape; use multiple chunks rather than a new 154-token QNN model artifact.
- Positive and negative prompts are chunked independently and paired deterministically; missing chunks use the empty prompt.
- Default H2 effective CLIP prompt budget: 302 tokens = 4 chunks × 75 content tokens + BOS/EOS accounting per chunk; the UI must not grey text at token 77.
- Keep the Basic build without optional `safety_checker.mnn`.
- All patch source, build scripts, tests, signing-material warning, migration scripts and CI workflow are public GitHub content. Do not commit model weights.

---

### Task 1: H1 model-preserving migration and stable H2 signing

**Files:**
- Create: `s24u-image-harness/scripts/S24U_H1_MODEL_BACKUP.sh`
- Create: `s24u-image-harness/scripts/S24U_H2_MODEL_RESTORE.sh`
- Create: `s24u-image-harness/signing/README.md`
- Create: `s24u-image-harness/signing/s24u-test-signing-key.pem`
- Create: `s24u-image-harness/signing/s24u-test-signing-cert.pem`
- Create: `s24u-image-harness/tests/test_migration_contract.py`

**Interfaces:**
- Consumes: H1 package `io.github.xororz.localdream.s24uharness`, debuggable build, Android `run-as` through adb/rish.
- Produces: `/sdcard/Download/S24U_Image_Harness_model_backup.tar`, stable H2+ signing certificate.

- [ ] **Step 1: Write failing contract tests** checking that backup uses `run-as io.github.xororz.localdream.s24uharness`, archives `files/models`, restore writes the archive back under the same package, and signing documentation labels the key TEST-ONLY/PUBLIC.
- [ ] **Step 2: Run the tests and verify RED.**
- [ ] **Step 3: Implement backup/restore scripts with SHA-256 sidecar and free-space checks.**
- [ ] **Step 4: Generate one permanent test-only RSA signing identity and commit PEM material with explicit public-key security warning.**
- [ ] **Step 5: Run contract tests and verify GREEN.**

### Task 2: Pure RAW defaults and expanded UI token budget

**Files:**
- Create: `s24u-image-harness/patches/android-h2.patch`
- Create: `s24u-image-harness/tests/test_android_patch.py`

**Interfaces:**
- Consumes: Local Dream `ModelRunScreen.kt`, `PromptFieldController.kt`, `app/build.gradle.kts`.
- Produces: H2 app id/version, Pure RAW initialization, displayed long-prompt budget of 302, stable release/test signing configuration.

- [ ] **Step 1: Write a failing source contract** requiring `versionName = "2.8.1-s24u-h2"`, no automatic model default prompt/negative prompt in PURE RAW initialization, and an expanded max-length value returned from backend rather than a hard stop at 77.
- [ ] **Step 2: Verify RED against the pinned upstream tree.**
- [ ] **Step 3: Implement minimal Android patch.** Keep saved user prompts intact; only first-run PURE RAW starts empty.
- [ ] **Step 4: Verify GREEN.**

### Task 3: Native 4-chunk CLIP prompt path without model replacement

**Files:**
- Create: `s24u-image-harness/patches/native-long-prompt-h2.patch`
- Create: `s24u-image-harness/tests/test_long_prompt_patch.py`

**Interfaces:**
- Consumes: `TextEncoder.hpp`, `Pipeline.hpp`, `main.cpp` from pinned Local Dream.
- Produces: up to four 75-content-token CLIP chunks per positive/negative prompt, per-chunk fixed-shape conditioning, averaged conditional/unconditional noise prediction, `/tokenize max_length=302`.

- [ ] **Step 1: Write RED contracts** requiring `kS24uClipChunks = 4`, `kClipChunkLen = 77`, a chunk-splitting path that never passes `max_len > 77` into one CLIP/QNN invocation, and tokenizer response max 302.
- [ ] **Step 2: Implement token-aware prompt chunking** while preserving prompt weights and textual-inversion boundaries.
- [ ] **Step 3: Pair positive/negative chunk lists to `max(posChunks, negChunks)` and synthesize an empty chunk when one side is shorter.**
- [ ] **Step 4: Encode each chunk separately through the existing 77-token text encoder graph.**
- [ ] **Step 5: During every denoising step, run the unchanged fixed-shape UNet once per chunk pair, convert each output to CFG noise prediction, average predictions across chunks, then execute one scheduler step.** This intentionally trades speed for prompt capacity and avoids new QNN model weights.
- [ ] **Step 6: Verify source contracts GREEN and add deterministic unit-level tests for 1, 2 and 4 chunk pairing.**

### Task 4: Reproducible QAIRT native build and APK CI

**Files:**
- Create: `s24u-image-harness/build_h2.py`
- Create: `.github/workflows/s24u-image-harness-h2.yml`
- Create: `s24u-image-harness/README.md`

**Interfaces:**
- Consumes: public QAIRT Community SDK 2.39.0.250926, Android NDK, pinned Local Dream source, both patch files, committed test signing identity.
- Produces: `S24U_Image_Harness_H2_20260831.apk` and evidence bundle.

- [ ] **Step 1: CI clones the pinned upstream commit and verifies the SHA.**
- [ ] **Step 2: Download QAIRT 2.39.0.250926 from Qualcomm's public Community SDK endpoint and install Android NDK required by Local Dream.**
- [ ] **Step 3: Run all RED/GREEN patch contracts.**
- [ ] **Step 4: Build the modified native `libstable_diffusion_core.so`, package official-compatible QNN runtime libraries, and compile Basic APK.**
- [ ] **Step 5: Sign with the permanent H2 test key.**
- [ ] **Step 6: Verify package id/version, arm64 core, QNN libs, absence of `safety_checker.mnn`, long-prompt markers and certificate fingerprint.**
- [ ] **Step 7: Upload APK, SHA-256, certificate fingerprint, test logs and package inventory as GitHub Actions artifacts.**

### Task 5: Phone migration acceptance gate

**Files:**
- Create: `s24u-image-harness/PHONE_TEST_H2.md`

**Interfaces:**
- Consumes: H1 device with existing model, backup script, H2 APK, restore script.
- Produces: evidence that no model download occurred and a >77-token prompt is accepted and generated.

- [ ] **Step 1: Back up H1 `files/models` and verify archive SHA-256.**
- [ ] **Step 2: Uninstall H1 only after backup verification, install H2, restore model archive, and verify the model appears without network download.**
- [ ] **Step 3: Enter a 100–150 token prompt; verify the UI does not grey token 78+, trace reports chunk count ≥2, and NPU generation completes using the existing model.**
- [ ] **Step 4: Install a second H2+ build over H2 without uninstalling; verify Android accepts the update and model storage remains present.**
