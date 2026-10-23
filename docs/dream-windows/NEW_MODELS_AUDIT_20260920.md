# 新增模型与显微镜实测审计 — 2026-09-20

## 结论

- 新增模型共两个：Animagine XL 4.0 Opt、DreamShaper XL Lightning。两者当前 GGUF 文件 SHA-256 均重新计算，并与注册表一致；本地 API 均报告 ready。
- Animagine：本次检查的动漫人物样图符合蓝发、银色眼睛、白色外套、霓虹城市等主体要求，未见此前生成故障的大面积色块。基础生成和 H7 研究生成均可用。
- DreamShaper：**当前自动应用的默认配置未通过视觉验收**。4 步、CFG 2、DPM++ 2M、Discrete 在基础和 H7 模式下均出现明显彩色伪影与细节异常，不能将程序成功退出视为质量合格。
- DreamShaper 在同提示词、同种子、同分辨率下，逐项改为 Karras、8 步、DPM++ 2M SDE 后，人物、服装与场景细节明显改善。最终组合的基础与 H7 样图均正常；这只是单种子烟测，不代表多场景稳定性已验收。
- 两款模型均有真实 H6 条件影响、四通道潜空间、H7 Self/Cross-attention 数据，并完成浏览器显示检查。不能据此称所有显微镜功能齐全：通道相关矩阵仍未导出，注意力仅采集有限代表层、步骤、锚点与 Token。

## 范围和变更边界

本轮是检查，不修改产品代码、模型注册表或默认参数，不重启服务，不下载或替换模型。
新增六次本地测试生成及浏览器审计证据，保留历史记录。其他任务已有的未提交修改全部保留。
参考任务：Local Dream-PC-模型下载；其完成说明只是线索，本报告另行核对真实文件、输出图片、API 与 GUI。

## 生图对照

所有下表任务均为 768×768；种子 20260920。耗时为后端记录的 generation_time_ms，包含不同冷/暖状态及执行路径，不是统一冷启动基准。

| 模型/测试 | 参数 | 任务 | 记录耗时 | 人工视觉检查 |
| --- | --- | --- | --- | --- |
| Animagine 原有基础记录 | Euler a / Discrete，28 步，CFG 5 | job-a87b448b1568 | 38.953 秒 | 动漫人物正常 |
| Animagine 本轮 H7 | 同上 | job-0183f6e52ca3 | 52.783 秒 | 正常，构图接近，非像素级一致 |
| DreamShaper 原有基础记录 | DPM++ 2M / Discrete，4 步，CFG 2 | job-94e08e1bd794 | 11.375 秒 | 彩色伪影、细节异常 |
| DreamShaper 本轮 H7 | 同上 | job-8860e9f82490 | 18.038 秒 | 同类异常，排除仅由浏览器/显微镜显示造成 |
| DreamShaper 调度器对照 | DPM++ 2M / Karras，4 步，CFG 2 | job-46f310b9571c | 12.219 秒 | 仍有伪影、偏色，未通过 |
| DreamShaper 步数对照 | DPM++ 2M / Karras，8 步，CFG 2 | job-569293c59916 | 10.140 秒 | 结构改善，仍偏重描边风格 |
| DreamShaper 采样器对照 | DPM++ 2M SDE / Karras，8 步，CFG 2 | job-69997077fcae | 10.313 秒 | 明显改善；暖启动单次 |
| DreamShaper 最终 H7 | DPM++ 2M SDE / Karras，8 步，CFG 2 | job-b9007703e666 | 23.639 秒 | 正常，保持人物与场景 |

对照按一次一个请求参数改变执行；测试后未保存为默认配置。
已确认的问题是现有本地默认参数组合未通过视觉验收；尚不能断言模型权重本身有问题，也未完成不同引擎调度实现的数值等价性定位。

## 显微镜真实产物

| 运行 | H6 采样步骤 / 分块 | 潜空间帧 / 遥测 | Self-attention 图 | Cross-attention 图 |
| --- | --- | --- | --- | --- |
| Animagine job-0183f6e52ca3 | 5 / 1 | 28 / 28 | 135 | 480 |
| DreamShaper 默认参数 job-8860e9f82490 | 4 / 1 | 4 / 4 | 108 | 384 |
| DreamShaper 8 步 job-b9007703e666 | 5 / 1 | 8 / 8 | 135 | 480 |

检查内容：

- H6 JSON 通过服务端严格契约验证；API 返回 available=true、truth=observed、source=debug-unet。
- 全部 Self-attention 原始图通过严格验证，概率和约为 1，偏差小于 0.00000007。
- 全部 Cross-attention 图的空间维度、值数量、有限性与 [0,1] 值域通过检查。
- 对两个默认参数 H7 运行分别抽查三代表层的 Self/Cross API 图，与磁盘原始值一致；最终 8 步运行另核对四类产物 API 可用性。
- 本次提示词均为一个分块，H6 chunk-vs-full 差异为零是预期结果；不将其误报为未采集。本轮未新增多分块兼容性测试。
- 这些都是本次运行采集的数据；原来的 basic 记录不会自动补齐 H6/H7。

## GUI 检查

- 生成页切换 DreamShaper 后自动应用的值仍是 4 步、CFG 2、DPM++ 2M、Discrete，生成按钮可用。这正是待修正/重新验收的默认组合。
- 显微镜运行下拉列表能分别选中新模型任务，不需要硬编码原 CyberRealistic 模型。
- Animagine：H6 指标显示；Self-attention 切到 Up 1、第 28 步、中心锚点成功；Cross-attention 热力图显示。
- DreamShaper：Self-attention、astronaut Token 的 Cross-attention、潜空间步骤切换正常；四通道图片解码成功；最终 8 步 H7 记录也可选中并显示。
- 浏览器检查期间 console 为 0 errors / 0 warnings。
- 现有限制：潜空间明确显示“通道相关性不可用”；H7 为最多 3 个代表层、5 个采样步骤、每层 9 个锚点的受限采集，Cross 本次为前 32 个 Token，不是所有层/所有步骤的完整导出。

## 证据与后续

- [Animagine H7 样图](E:/Dream/outputs/2026-09-20/job-0183f6e52ca3.png)
- [DreamShaper 原默认坏图](E:/Dream/outputs/2026-09-20/job-94e08e1bd794.png)
- [DreamShaper 8 步基础样图](E:/Dream/outputs/2026-09-20/job-69997077fcae.png)
- [DreamShaper 8 步 H7 样图](E:/Dream/outputs/2026-09-20/job-b9007703e666.png)
- [Animagine 自注意力 GUI](E:/Dream/repo/output/playwright/model-audit-animagine-self.png)
- [DreamShaper 交叉注意力 GUI](E:/Dream/repo/output/playwright/model-audit-dreamshaper-cross.png)
- [DreamShaper 8 步 H7 GUI](E:/Dream/repo/output/playwright/model-audit-dreamshaper-8step-h7.png)

建议后续单独修正 DreamShaper 默认采样配置，并以多提示词、多种子、冷/暖启动分别回归；再补通道相关矩阵。不要把此次单样本改善升级为模型整体质量或手机端完全对齐结论。

参考作者资料：[Animagine 模型卡](https://huggingface.co/cagliostrolab/animagine-xl-4.0)建议 Euler a、28 步、CFG 5；[DreamShaper 模型卡](https://huggingface.co/Lykon/dreamshaper-xl-lightning)提供 Diffusers 4 步、CFG 2 示例。作者示例不等于本地 stable-diffusion.cpp 中同名/近似参数的画质已验证。
