# S24U Image Harness H2

Public experimental Android image-generation harness for Samsung Galaxy S24 Ultra / Snapdragon 8 Gen 3, built from the immutable Local Dream v2.8.1 baseline (`a7666f6198412a58c6eb1eacc28828aa40c7d7ae`).

## H2 goals

- Preserve already-downloaded multi-GB model data across H2+ APK upgrades.
- Provide a one-time H1→H2 model backup/restore bridge because H1 used an ephemeral CI debug signing key.
- PURE RAW first-run prompt behavior: no model-default positive/negative prompt is injected by the H2 UI.
- Raise SD/SDXL effective prompt capacity from one 77-token CLIP window to four fixed-shape passes (302-token harness budget) without replacing or re-downloading the user's QNN model files.
- Keep every actual CLIP/QNN context invocation at the original fixed 77-token model shape.
- Keep the Basic build without the optional `safety_checker.mnn` asset.
- Reproducible public GitHub Actions build using Android API 37, NDK r28c and QAIRT Community SDK 2.39.0.250926.

## Long-prompt architecture

H2 does not pretend that the existing QNN graph suddenly accepts a 302-token tensor. Instead it performs true multi-pass conditioning:

1. Token-aware split positive and negative prompts into up to four chunks, each with at most 75 content tokens.
2. Each chunk is encoded through the unchanged 77-slot CLIP/QNN graph (`BOS + 75 content + EOS/PAD`).
3. Positive/negative chunks are paired deterministically; a missing side is represented by an empty chunk.
4. At each denoising step the existing fixed-shape UNet runs for each conditioning chunk.
5. Per-chunk CFG noise predictions are averaged, then the scheduler executes one image step.

No new SDXL model package is needed for this feature. The trade-off is additional compute for prompts that need more than one chunk; H2 deliberately does not treat speed tuning as a release goal.

## Model-preserving upgrade policy

`io.github.xororz.localdream.s24uharness` remains the package id. H2+ builds use one fixed **public TEST-ONLY** signing identity so Android in-place upgrades preserve package-private `files/models`.

H1 was signed with an ephemeral GitHub-hosted runner debug key, so Android cannot accept H2 as an in-place update over H1. Use the supplied scripts once:

- `scripts/S24U_H1_MODEL_BACKUP.sh`
- `scripts/S24U_H2_MODEL_RESTORE.sh`

The backup script must report `[S24U-H2][100%] H1 model backup PASS` before H1 is uninstalled. It creates `/sdcard/Download/S24U_Image_Harness_model_backup.tar` and a SHA-256 sidecar. After H2 is installed, the restore script writes the same model tree back into H2 private storage. H3/H4/etc. then update H2 normally without model migration.

## Public test signing warning

The H2 signing private key is intentionally public for reproducible lab builds. It provides update continuity, **not authenticity**. Never use it for production or trust an APK merely because Android accepts its signature. See `signing/README.md`.

## Build / verification

Workflow: `.github/workflows/s24u-image-harness-h2.yml`

The CI gate verifies:

- migration contract and RED→GREEN H2 source contracts;
- QAIRT/NDK native rebuild of modified `libstable_diffusion_core.so`;
- Android unit tests and APK compile;
- package id `io.github.xororz.localdream.s24uharness`;
- version `2.8.1-s24u-h2` / versionCode `7402`;
- arm64 native core and QNN runtime present;
- `safety_checker.mnn` absent from Basic APK;
- fixed H2 certificate fingerprint;
- APK SHA-256 and evidence artifact generation.

Latest verified H2 CI run during development: GitHub Actions run `33344873224` (PASS).
