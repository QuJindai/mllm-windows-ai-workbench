# T8U SDXL MNN GPU 与显微镜实测

2026-11-17，Samsung SM-X900，SM8450，Adreno 730v2，Android 16，约 16 GB 内存。

已覆盖升级绘梦PLUS到 `2.8.1-t8u-h6r5r2-sdxlmnn`（7416）。原有 Absolute Reality 模型与历史保留；旧历史 PNG 与升级前文件哈希一致。SDXL GPU 选择已保存。原有 llama.cpp 8081 健康检查仍返回 ok，绘梦PLUS使用 18081。

## 代码来源与构建

- [实现提交 8ae5bad](https://github.com/QuJindai/mllm-windows-ai-workbench/commit/8ae5bad05f6db71dddba91405f2542118f543c8f)，专用分支 `feature/t8u-sdxl-mnn-gpu`，未合并 main。
- [GitHub Actions 44071981867](https://github.com/QuJindai/mllm-windows-ai-workbench/actions/runs/44071981867) 通过既有显微镜源码检查、原生编译、Android 单元测试、APK 构建及签名验证。
- APK SHA-256：`6f4ab872ff3119a061d0d5c9e26ca1b4f6d1ead69463e6ab0fc51aec220688b3`。
- 固定项目测试证书 SHA-256：`b60748d6461ef1f5e2681462f08eebca287b56b78bfafc801499cc2ba461e005`，与此前7415相同。
- SDXL MNN 阶段实现来自上游 `209ba95`；与 [原版3.0.0-alpha.7同名文件](https://github.com/xororz/local-dream/blob/2f1f3ba186eeca2a52268540108b3ee6e2296d17/app/src/main/cpp/src/PipelineSdxlMnn.hpp) 无后续差异。适配保留显微镜独立 fixed-77 chunk 管线，增加实际后端检查。
- MNN 固定为 `413b1c3c53d0d579e30848983b244aa82b2fbeee`，与原版 alpha.7 相同。

## 原版代码核对

| 路径 | 模型与执行方式 |
|---|---|
| S24U显微镜原始基线 / Local Dream 2.8.1 | `PipelineSdxl.hpp` 调用 QNN 的 `executeUnetGraphsSDXL`，属于 HTP/NPU；GPU开关出现在 `runOnCpu` 模型的设置分支。 |
| 新版原版 SDXL MNN | `PipelineSdxlMnn.hpp`：U-Net为 `MNN_FORWARD_OPENCL`、低精度、BUFFER、FAST调优；CLIP和VAE为CPU，VAE按模型声明640px分块。 |
| 本次7416 | 采用上述MNN阶段实现和相同MNN提交；保留显微镜采集，按阶段显示 OpenCL / CPU，校验MNN实际会话后端。 |

这次是 SDXL 的 GPU 去噪、CPU 文本编码与解码，不能称为所有阶段都由 GPU 完成。

## 相同模型、相同输入

模型：P-Master Lightning 8-step，SDXL MNN INT4，模型文件哈希见 `model-manifest.json`。

1024×1024，8步，CFG 1，Euler，Karras关，种子1632280009，负向空，单chunk。

正向：`a red sports car parked beside a lake, pine trees, snowy mountains, daylight, photograph`。

| 测试 | 整图计算耗时 | 结果 |
|---|---:|---|
| 显微镜7416首次GPU运行 | 288.029秒 | 成功，含首次调优与模型加载。 |
| 同后端第二次请求，缓存已建立 | 251.885秒 | 成功，与首张RGB/RGBA逐像素一致。 |
| 作者未修改alpha.7原生引擎，同机GPU对照 | 275.197秒 | 成功，与显微镜版RGB逐像素一致。 |

对照原版 APK 由作者 GitHub Release 下载，SHA-256 为 `704582052cb28e67eb6bfe1b943e48b18ac0f15e0804579d84447515d9a1b281`，作者签名。使用其未修改的 `libstable_diffusion_core.so`，以相同应用UID、模型目录、GPU库搜索路径、`sdxlmnn`、lowram和独立18082端口发起请求。对照仅测原生引擎，不是原版整个UI；确认进程加载了 `/vendor/lib64/libOpenCL.so`。一次缺少GPU库路径的预试因加载警告中止，未计入表格。

三次顺序运行，未控制GPU温度与频率，因此不能据此认定任一版本更快。结果没有显示出显微镜移植造成数量级的性能下降。S24U本机没有接入本次测试，不能用这组数据声称其实际速度。

两版RGB比较：1,048,576个像素全部一致，最大通道差0。RGB SHA-256：`f4d78a5dad214d2263095bda6975c2b4eab2df51dd8e0ff0e1682a860289be6d`。原图见 `result-first.png`、`result-second.png`、`result-original.png`。

画面包含红色跑车、湖面、松林和雪山，无此前CPU样图遗漏红车的问题。

## 显微镜验收

- 原生日志：U-Net `stage=0 backend=3`（OpenCL），VAE `stage=2 backend=13`（MNN CPU扩展后端）。推理进程打开OpenCL驱动及 `/dev/kgsl-3d0`，运行期GPU忙碌采样接近100%。
- 首次总耗时288029 ms：CLIP条件编码2221 ms，8次U-Net共177522 ms，8次Scheduler共8 ms，最终分块VAE解码38769 ms；其余69509 ms记录为未归属，主要包含会话初始化/调优，未把它伪计入U-Net算子时间。
- 8帧latent、8个过程变化样本；过程滑块切换到第1步与第8步，数值随步数变化；C0/C3通道可切换，统计与相关矩阵显示正常。
- 条件影响页8个样本；单chunk相对融合结果差异为0，符合单chunk条件。不是词语到区域的attention。
- 总览、过程图、条件影响、机制、专家页均实际打开并回读；结果与模型哈希对应。
- 结果页正确显示1024×1024及GPU；两次图像均写入历史。
- 逐步VAE彩色预览仍为 `NOT EXECUTED`，本次低内存后端未执行。词语到区域的cross-attention仍不支持。
- 沿用的界面在首次U-Net初始化时仍停留CLIP阶段，运行期总耗时尚未完成时显示0或空；最终完成值正确。提示词计数包含BOS/EOS，显微镜内容token计数不包含，两处相差2。

本次未验证多chunk融合A/B、img2img、UltraFix或所有SDXL模型。原版对照引擎已停止，临时原版App已移除，保留已升级的绘梦PLUS。
