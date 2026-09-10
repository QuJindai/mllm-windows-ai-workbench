# Dream Windows 手机版能力对齐与显微镜增强设计

## 目标

把 Windows 浏览器工作站补齐到 Android H6R5R1 已验证的可操作能力：生成参数与队列、模型身份、历史连续浏览与比较、同种子实验，以及 H6 显微镜的过程、Latent、运行图、条件影响和真值边界。所有生产后端尚未导出的数据必须显示为“不可用”，不能用演示数据冒充 native 实测。

## 方案

采用现有 React + FastAPI + stable-diffusion.cpp 分层，不重写引擎：

1. 扩展 domain/provider 契约，让生成、实验、历史和 trace 的数据可以被页面共享。
2. Generate 页面增加预设、批量队列、取消、结果变体和质量保护；批量任务逐个进入现有单 worker，避免 6GB GPU 并发争抢。
3. History 页面实现实时刷新、Carousel 键盘/触摸导航、缩放平移、收藏、删除、重新生成和双图比较。
4. Lab 页面提交真实同种子实验；每个变体都由后端实际生成，结果只在完成后呈现。
5. Microscope 页面增加 Prompt/Chunk/CFG/Influence/Mechanism/Expert 视图，复用已有 runtime trace、latent telemetry 和 native hardware evidence；H7 只有检测到研究引擎和 attention 输出时才显示可信数据。
6. 统一使用 `observed`、`derived`、`unavailable` 真值徽标，并保留 E:\\Dream 路径约束。

## 错误与稳定性

- 生成失败、取消、缺少输出、trace 缺失都返回结构化错误并可重试。
- 前端不预加载全部历史原图；图片 lazy/async 加载。
- 批量任务串行运行，单个任务失败不污染其他任务。
- 实验和历史数据均保留 job/experiment identity，避免页面刷新后丢失上下文。

## 验收

- 前端行为测试覆盖批量队列、预设、Carousel、触摸/缩放、比较和显微镜 tab。
- 后端测试覆盖实验请求、串行 job identity、history refresh、trace capability boundary。
- 前端测试、后端测试、生产构建、PowerShell 解析全部通过。
- 浏览器实际操作每个导航项、提交一次低负载生成、打开历史、运行实验入口和显微镜各视图；无法运行 native 的能力必须明确显示原因。
