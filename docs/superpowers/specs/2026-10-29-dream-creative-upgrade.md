# Dream 创作升级范围与实现状态

2026-10-29：六项创作升级已实现并完成下述本机测试、GPU 与 GUI 验收；main 发布、远端 SHA 回读和 CI 仍待确认。当前使用方法与事实边界见 [创作升级验收](../../dream-windows/CREATIVE_UPGRADE_20261029.md)。

## 已实现范围与交付边界

1. 人物历史图可独立创建一轮精修版本，支持版本选择、继续修和回到原图。原图不被覆盖；失败/取消/无变化不发布成功版本，父图删除后版本不可访问。版本选择、回退及重叠修复已有 GUI 验证。
2. 像素质量对照与 CPU edge-lighting 已接入；保护率来自实际处理器掩膜与明确基线。实测保护区及编辑区外 100% 精确保留，3,839 像素变化、最大 RGB 变化 2/255。指标不等于人物相似度或质量胜出。
3. 四场景增加肖像/半身/全身文字构图和显式模型兼容参数。真实 GUI 已验证全身选项、科幻提示词、512×768 / 28 / 5.5 推荐参数及引用字段保留。四动漫场景成功，但腰部以上提示仍生成头肩图；不承诺骨架姿态或完整入镜。失败的 Illustrious Plus 实验门控保持禁用。
4. 独立 restore 直用处理器，并在既有持久传输中有界暖复用：一个暖子进程、60 秒空闲 TTL、内容哈希兼容键、每次独立计时和 sessionReused。观察耗时 79.938 s→49.296 s，load 42.540 s→1.173 ms，输出哈希相同；三个 Unity 进程和 CPU 测试同时运行，**未取得无争用基准，不作速度保证**。
5. CPU 手机预测重放、真实 Diffusers 受控融合及显微镜跨运行比较已分别实现。四融合图像真实 GPU 完成；两 chunk / alpha 0.5 的 mean 与 anchor 同哈希符合公式。实际显微镜 GUI 比较两个兼容运行、28 步、84 行统计；不声称设备等价。
6. 全后端 1,686 passed / 2 skipped、全前端 669 passed、构建 94 modules。真实 fusion 运行取消 343 ms 后无结果/PNG/残留 worker；Lab 重启恢复四图。426 个基线文件零变更、零缺失。代码与私人图像分离；Git 发布与 CI 不得在实际完成前标为通过。

## 版本接口约定

- GET `/api/identity/jobs/{sourceJobId}/refinements` → {sourceJobId, selectedVersionId, versions}。
- versions 包含 {id, state, message, error?, imageUrl?, createdAt, parentVersionId, settings, metrics?}；state=queued|running|complete|failed|cancelled。
- POST `/api/identity/refinements` 接受 sourceJobId、parentVersionId（result/original/服务生成的版本 ID）、mode（restore/redraw/reference-anchor/edge-lighting）、strength 0.15..0.65、prompt、negativePrompt、seed 和可选 requestId，返回版本记录；UI 重试复用 requestId。
- POST `/api/identity/refinements/{id}/cancel` 返回版本记录。
- POST `/api/identity/jobs/{sourceJobId}/refinements/select`，body {versionId}，返回 GET 同结构。
- GET `/api/identity/refinements/{id}/image` 返回 PNG；父图删除、产物缺失、未完成均不返回图片。
- result/original 为虚拟版本。选择仅改变编辑工作台选择，不覆盖历史主图；版本 ID 与路径仅由服务生成。
- edge-lighting 接收不可变原场景作为 scenePath，sourcePath 仍是当前所选版本；helper 提供实际掩膜诊断，无变化返回有意义的错误。

融合 worker/HTTP 契约见 [TASK4_IMAGE_CONTRACT.md](../../dream-windows/TASK4_IMAGE_CONTRACT.md)。无争用性能、完美 likeness、精确姿态和跨设备 parity 均不属于已验证结果。
