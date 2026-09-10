# Dream Windows Browser Workstation 验收记录

日期：2026-09-10
分支：`feature/dream-windows-w0-hardware`
入口：`http://127.0.0.1:8866`（避开本机 Windows 动态保留的 8766 端口）

## 已验证闭环

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| 同源静态页面 | PASS | FastAPI `/` 返回 Vite 构建产物，favicon 200 |
| 真实硬件 | PASS | `/api/hardware` 返回 RTX 1000 Ada、6141 MiB VRAM、i7-14700HX、约 64 GB RAM |
| 真实模型 | PASS | `/api/models` 返回 E:\\Dream GGUF，registry identity verified |
| Generate job | PASS | 浏览器提交 → queued/preparing/sampling/decoding → complete |
| 真实文件 | PASS | PNG 与 sidecar JSON 写入 `E:\\Dream\\outputs\\2026-09-06` |
| History | PASS | 真实输出出现在 `/api/history`，图片由 `/api/history/{id}/image` 提供 |
| Models/Settings | PASS | registry、verify/reindex、路径和设置读写均走 HTTP API |
| Semantic Lab | PASS | 四个变体沿单 worker 串行执行，显式保持共同 seed；页面只显示后端返回的真实状态和指标 |
| H6 Microscope | PASS | 七个可访问视图读取 runtime trace、真实 latent 步骤和硬件证据；当前硬件与单次运行峰值分离显示 |
| Research truth | PASS | H7 Debug UNet 的 token/layer/step cross-attention 由独立研究引擎实测导出；未导出的 H6 chunk influence 继续显式不可用，不使用 latent/influence 伪装 attention |

## 最终实机回归

- 浏览器提交 `job-f144dcff4f9f`：512 × 512、20 步、DPM++ 2M / Karras、H6，16.167 秒完成。
- 输出：`E:\\Dream\\outputs\\2026-09-08\\job-f144dcff4f9f.png`；人工检查主体清晰、结构完整，无模糊色块。
- 轨迹：后端 `CUDA · observed`，20 个真实 Latent 步骤，每步均含 C0–C3 四通道，峰值 VRAM 3159 MiB。
- 最终自动化：前端 116/116、服务端 67/67、core/CUDA 契约 21/21；TypeScript/Vite 生产构建和 `git diff --check` 通过。
- H7 历史运行 `job-9e8f5b8ec81f`：契约 `h7-attention-v1`，180 张实测映射；浏览器已验证 `lake / Mid 1 / 第 20 步` 切换和原始统计显示。
- 最新基础生成 `job-a2a306b0661a`：768 × 768、20 步、DPM++ 2M SDE / Karras，22.281 秒；人工检查主体、山体、水面和光照结构完整。

## 自动化命令

```powershell
cd E:\Dream\worktrees\dream-windows-w0-hardware\apps\dream-windows
npm run test:run
npm run build
cd E:\Dream\worktrees\dream-windows-w0-hardware
python -m pytest apps/dream-windows/server/tests -q
.\scripts\run_dream_web.ps1 -Port 8866 -OpenBrowser
```

## 说明

- 生产浏览器入口是 `DreamHttpProvider`，`MockDreamProvider` 只在 Vitest/domain 测试注入。
- `127.0.0.1:8866` 是支持的浏览器入口；未终止或复用占用 8765 的无关进程。
- Semantic Lab 使用真实生成任务，latent microscope 仅展示 trace 实际导出的步骤证据；H7 attention 仅对具有 `h7-attention-v1` 实测索引的研究运行启用；H6 chunk influence 仍等待对应原生张量导出。
- 桌面 EXE/Tauri 不属于本验收和后续运行路径。
