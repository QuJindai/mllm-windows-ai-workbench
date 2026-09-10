# Dream Windows GUI Alpha 验收记录

日期：2026-09-06
分支：`feature/dream-windows-w0-hardware`
范围：浏览器工作站壳层、真实 HTTP provider、原生 CUDA job、模型/历史/设置页及研究页诚实状态

## 当前状态

| Gate | 状态 | 说明 |
| --- | --- | --- |
| G0 Shell | PASS | 浏览器 localhost 工作站壳层、六项主导航、Hardware Status Bar、响应式布局 |
| G1 Provider | PASS | typed provider contract、生产入口使用 DreamHttpProvider；Mock 仅测试 |
| G2 Generate | PASS | 浏览器提交真实 job，经本地 stable-diffusion.cpp + CUDA 完成并生成 PNG/JSON |
| G3 Models | PASS | E:\\Dream registry、verified、SHA/path inspector、搜索/分类、verify/reindex |
| G4 History | PASS | 真实 E:\\Dream 文件扫描、grid、搜索/过滤、viewer、favorite/delete、图片服务 |
| G5 Settings | PASS | E:\\Dream 路径、硬件事实、诊断、内存设置持久化 |
| G6 Research truth | PASS | Semantic Lab 运行真实串行同种子任务；Microscope 读取真实 runtime/latent trace；H7 Debug UNet 提供实测 token/layer/step cross-attention；未导出的 H6 chunk influence 仍显式不可用 |

## 可重复验证

在 `apps/dream-windows` 目录执行：

```powershell
npm run test:run
npm run build
npm run verify:dpi
npm run verify:e-drive
python -m pytest ..\\..\\apps\\dream-windows\\server\\tests -q

# repository root
.\scripts\run_dream_web.ps1 -Port 8866 -OpenBrowser
```

浏览器服务默认绑定 `127.0.0.1:8866`，不会改变 E:\\Dream 数据路径。桌面 EXE/Tauri 不属于支持的交付入口。当前 Windows 动态端口保留范围包含 8766，因此不再使用该端口。

## 证据

- 自动化测试覆盖真实 HTTP API contract、原生 job artifact、静态服务、mock lifecycle、hardware failure、CUDA unavailable、history focus guard、Escape、delete continuity、empty/error states 和 E-drive build policy。
- Playwright 已验证浏览器读取真实 GPU/RAM/模型，点击 Generate 后 job 进入 Sampling/Complete，并显示 `/api/history/{id}/image` 的 live PNG。
- H7 研究引擎已验证历史运行选择、token/layer/step 切换与 180 张实测 cross-attention 映射；热力图显示归一化色阶，同时保留原始统计值和证据边界。
- 本机当前验证结果：NVIDIA RTX 1000 Ada 6141 MiB VRAM、Intel i7-14700HX、约 64 GB RAM、Micron DDR5；原生模型 CyberRealistic XL v10 标准版可用。
