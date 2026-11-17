# S24U Image Harness H2

Public experimental Android image-generation harness for Samsung Galaxy S24 Ultra / Snapdragon 8 Gen 3, built from the immutable Local Dream v2.8.1 baseline (`a7666f6198412a58c6eb1eacc28828aa40c7d7ae`).

## C206 横屏显微镜

[H6R5R1 构建](../.github/workflows/s24u-image-harness-h6r5-build.yml)先生成 S24 Ultra 手机版，再用同一份 ARM64 推理库生成 `c206-image-harness-h6r5r1-landscape` 附件。车机显微镜版名为 **绘梦PLUS**，版本号为 `2.8.1-s24u-h6r5r1-c206.3`（7415），与手机版共用包名。模型目录采用网格排列，显微镜横向并排显示计算链、Token 和耗时，历史图预览避开系统栏。

在「生成结果」页，宽屏左侧按可用高度等比显示完整图片，右侧显示操作、最近出图和生成参数。点主图可进入缩放预览。回归时用历史里的同一张图，先核对首屏是否同时显示图像四边和参数，再切换缩略图、打开大图并返回。7413 的结果页曾按整屏宽度生成正方形容器，导致 256×256 样图只有一部分能在首屏看到。

2026-11-17 用下文种子 `1632280009` 的同一张历史 PNG 实测。7413 的预览宽 2448 像素，当时屏幕只露出 1101 像素高。7414 在模型标题展开时完整显示为 910×910，点开大图后为 1214×1214。已用原图四角核对首屏，并验证 3 张历史缩略图、生成参数弹窗和大图返回。对比两个版本的大图截图，图像区域从 `(673, 94)` 到 `(1887, 1308)`（右、下边界不计），1,473,796 个像素全部一致。

GitHub 附件使用项目测试证书。C206 实机安装包需要使用该车已配置的平台签名；用同一证书覆盖安装可以保留模型。

C206 实测分辨率为 2560×1440，应用可用区域为 2560×1308，底部空调栏保持可操作。手机包在同一车机上只有 736 像素宽。

验证桌面品牌时，覆盖安装后打开中控「全部应用」。普通版入口为「HQ 绘梦」，显微镜版入口为「绘梦PLUS」，启动图标下半部也应写有「绘梦PLUS」。点后者应打开同名的横屏模型目录。7414 在这个页面出现过两个「HQ 绘梦」，显微镜版显示为白底紫色星形。自 7415 起，应用和启动 Activity 的常规与圆形图标都直接引用同一张 512 像素透明圆角 PNG。构建会检查各语言名称和 APK 里的图标引用。[绘梦PLUS 品牌源文件](https://github.com/QuJindai/hq-branding/blob/e71db324acbf87f812f8c170ced86c6138c96cc5/assets/icons/hq-huimeng-plus.svg)

2026-11-17 从 7414 覆盖升级时，「全部应用」立即更新了名称，却继续显示缓存的紫色星形。退出再进入列表仍可复现。先点「绘梦PLUS」使列表退到后台，在已选 C206 执行 `adb -s <C206序列号> shell am kill --user 10 ltd.qisi.appmanager`，再打开「全部应用」，第三排的 141×141 图标即显示品牌标识和 PLUS 短名。该命令仅回收后台应用列表进程。复测时对照第二排普通版图标，确认其像素与升级前完全一致。

与普通版共存时，显微镜版的本机生成、健康检查和放大统一使用 `localhost:18081`。普通版占用 `8081` 时，同一张图仍然可能生成成功，但借用它的后端会丢失显微镜的原生事件。回归时同时保留两个应用，进入 **CPU Models → Absolute Reality** 生成一张图，在 **显微镜 → 总览** 核对实际 U-Net 调用和模型文件哈希，再到 **过程图** 查看采样帧。远程受控模式沿用协议的 `8808/8081`。

2026-11-16 在 C206 上使用 Absolute Reality、CPU/MNN、256×256、20 步、DPM++ 2M、CFG 7 和种子 `1632280009` 复测。正向提示词为 `a red sedan beside an alpine lake and pine trees`，负向留空。实机验证包耗时 54,484 ms，[GitHub 最终构建](https://github.com/QuJindai/mllm-windows-ai-workbench/actions/runs/43851540161)重签覆盖安装后耗时 52,862 ms，冷启动 1,342 ms。两次出图的 65,536 个像素完全一致，RGBA 像素 SHA-256 为 `f94a100beff0fe4ff0b408a63ad4c18226636e04520bf25f66fdbd93a96eb217`。

显微镜记录到 U-Net 和调度器各 20 次、最终 VAE 解码 1 次，过程页保留 8 帧内部 latent。该模型的逐步 VAE 彩色预览显示 `NOT EXECUTED`。从模型页历史打开第一张，向左滑到第二张，再向右滑回第一张，点图像两侧留白返回列表。

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
