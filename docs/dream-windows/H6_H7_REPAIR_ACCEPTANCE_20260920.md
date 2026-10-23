# H6 / H7 真实采集修复验收

日期：2026-09-20。范围：浏览器版的 H6 条件影响、H7 Self/Cross-attention、研究引擎潜变量数据。不是全部手机版功能逐项对齐的声明。

## 已完成

- 原生研究引擎：增加真实分块条件预测对照、现有 CFG 影响指标、有限空间锚点 Self-attention；保留既有 Cross-attention。
- 接回普通引擎已有的原始 sampler latent 回调、每通道统计/直方图/空间图，避免研究模式仅剩 RGB 投影。
- 接口：严格校验 JSON、标记、数值、尺寸、索引一致性、文件大小和目录边界；缺失旧记录不伪造热图。能力来自升级构建清单，数据来自所选运行产物。
- 页面：H6 步骤/分块/指标/空间图；H7 Self 的层/步骤/锚点切换；Cross 聚合、原图叠加、区域 Top5；兼容记录快捷选择和设置能力状态。
- 普通生成保留 Flash Attention 和原有任务状态持久化。H6/H7 的研究计算均为主动选择。

## 真实验收证据

最终安装二进制的完整运行：`job-53a948ac3474`。

| 项目 | 实际结果 |
| --- | --- |
| 模型 | CyberRealistic XL v10 标准版 Q8 GGUF，SDXL |
| 参数 | 512×512，20 步，CFG 4，seed 4202026，DPM++2M SDE/Karras |
| H6 | 2 个分块，5 个采样步骤，分块差异非零 |
| Self | 3 个代表层、9 个锚点、5 步，共 135 张图 |
| Cross | 32 个采集 Token、3 层、5 步，共 480 张图 |
| Self 概率和 | 0.9999999666—1.0000000666 |
| 潜变量 | 20 步；每步 4 通道；原始统计与通道图 |
| 数值不干扰 | 对同种子、同参数、同非 FA 引擎的无采集基线：RGB 平均绝对误差 0，最大误差 0 |
| 最终研究运行耗时 | wrapper 测得 25.420 秒；不是手机/PC 公平性能对比 |
| 显存采样峰值 | 全 GPU 3750 MiB / 6141 MiB，含其他进程 |

额外边界运行 `job-86c9c112686f`：单分块、CFG=1，4 步的 CFG 差异和分块差异均精确为 0。此运行仅用于数学边界测试，不是图像质量示例。

普通 GUI 生图 `job-7da0a89374f0`：512×512、20 步成功，Flash Attention=true，wrapper 17.583 秒。生成时切换历史再返回，提示词、队列及结果均保留。

基线图片：`E:\Dream\outputs\research-baseline-20260920.png`。
最终图片：`E:\Dream\outputs\2026-09-20\job-53a948ac3474.png`。
最终产物：`E:\Dream\traces\job-53a948ac3474\`。

可复核命令：

```powershell
python scripts/verify_research_generation.py E:\Dream\traces\job-53a948ac3474 E:\Dream\outputs\2026-09-20\job-53a948ac3474.png --baseline E:\Dream\outputs\research-baseline-20260920.png
```

## 验证与发布

- 后端及 wrapper 测试：204 项通过。
- 前端：18 个测试文件、155 项通过；TypeScript 与 Vite 生产构建通过。
- 原生：CUDA Release 构建；2 项 callback/采样契约测试；独立 C++ 指标、锚点、尺寸边界断言通过。
- 浏览器：H6 分块/步骤，Self 层/锚点/步骤，Cross 区域选择，旧基础记录的不可用提示及兼容记录按钮均实际操作；控制台 0 errors / 0 warnings。
- 原生入口 1536×512 研究请求在模型加载/生图前拒绝；在线 API 同样返回 `RESEARCH_RESOLUTION_LIMIT`。未对用户普通大图请求施加这一研究限制。
- 前端发布目录：`E:\Dream\builds\dream-windows\frontend`。页面与 API 正常响应于 `http://127.0.0.1:8766/`。
- 研究二进制：`E:\Dream\app\stable-diffusion-cuda-h7`；源码：`E:\Dream\src\stable-diffusion.cpp-h7`。普通 CUDA 安装未替换。
- 更新前的研究 EXE、DLL、清单保存在 `E:\Dream\backups\h7-before-research-20260920`。没有删除用户模型、输出或历史，没有提交或推送 Git。

GUI 截图：`output/playwright/research-h6-20260920.png`、`research-self-20260920.png`、`research-cross-region-20260920.png`。

## 明确边界

H6 比较“同一 latent/timestep 下的单块引导预测与完整上下文引导预测”，不是声称 Windows 采用手机版的分块预测算术平均生产算法。至多采集 3 块/5 步；H7 至多 3 个代表层/5 步/9 个固定 Self 锚点，Cross 当前采集前 32 个有效 Token。没有全层、全头或全 Token 数据就不显示为全量能力。

浏览器研究宽高各限 1024；额外研究成本已在页面说明。H7 统一非 FA 路径用于可解释采集；普通模式不受影响。当前真实 GPU 验收仅覆盖上述 SDXL 标准模型和参数，不据此保证全部模型、ControlNet、APG、视频或直接调用底层库的组合。

独立原生审查未发现浏览器约束内的 P0/P1 问题。审查提出的直接 CLI 超尺寸和混合 FA 边界已增加入口保护并验证；基础库 API 的其他组合未声称验收。
