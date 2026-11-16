# S24U Image Harness H2

Public experimental Android image-generation harness for Samsung Galaxy S24 Ultra / Snapdragon 8 Gen 3, built from the immutable Local Dream v2.8.1 baseline (`a7666f6198412a58c6eb1eacc28828aa40c7d7ae`).

## C206 横屏显微镜

[H6R5R1 构建](../.github/workflows/s24u-image-harness-h6r5-build.yml)先生成 S24 Ultra 手机版，再用同一份 ARM64 推理库生成 `c206-image-harness-h6r5r1-landscape` 附件。车机版版本号为 `2.8.1-s24u-h6r5r1-c206.1`（7413），与手机版共用包名。模型目录采用网格排列，显微镜横向并排显示计算链、Token 和耗时，历史图预览避开系统栏。

GitHub 附件使用项目测试证书。C206 实机安装包需要使用该车已配置的平台签名；用同一证书覆盖安装可以保留模型。

C206 实测分辨率为 2560×1440，应用可用区域为 2560×1308，底部空调栏保持可操作。手机包在同一车机上只有 736 像素宽。车机版沿用 [HQ 绘梦的无白边图标](https://github.com/QuJindai/hq-branding/tree/main/assets/android/huimeng)。

与普通版共存时，显微镜版的本机生成、健康检查和放大统一使用 `localhost:18081`。普通版占用 `8081` 时，同一张图仍然可能生成成功，但借用它的后端会丢失显微镜的原生事件。回归时同时保留两个应用，进入 **CPU Models → Absolute Reality** 生成一张图，在 **显微镜 → 总览** 核对实际 U-Net 调用和模型文件哈希，再到 **过程图** 查看采样帧。远程受控模式沿用协议的 `8808/8081`。

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
