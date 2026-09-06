# Dream Windows GUI Alpha 验收记录

日期：2026-09-06  
分支：`feature/dream-windows-w2-gui-shell`  
范围：G0–G3 + History mock viewer continuity

## 当前状态

| Gate | 状态 | 说明 |
| --- | --- | --- |
| G0 Shell | PASS | Tauri 2 Rust shell、六项主导航、Hardware Status Bar、响应式布局 |
| G1 Domain / Mock | PASS | typed provider contract、MockDreamProvider、E:\\Dream fixtures |
| G2 Generate | PASS | queued → preparing → sampling → decoding → complete；失败、硬件不可用、禁用态可见 |
| G3 Models | PASS | registry grid、verified/unverified、SHA/path inspector、loading/empty/error |
| History viewer | PASS | grid、搜索/过滤、前后切换、键盘导航、删除后保持相邻项上下文 |
| G4–G8 production depth | PENDING | Semantic Lab、Microscope、H7、真实 CUDA/backend 仍按后续阶段接入 |

## 可重复验证

在 `apps/dream-windows` 目录执行：

```powershell
npm run test:run
npm run build
npm run verify:dpi
npm run verify:e-drive
npm run tauri:build
```

`tauri:build` 会自动将 npm cache、Cargo home 和 Cargo target 输出固定到 `E:\Dream`，release executable 目标为：

```text
E:\Dream\builds\dream-windows\release\dream-windows.exe
```

## 证据

- 自动化测试覆盖 mock generation lifecycle、hardware failure、CUDA unavailable、provider failure、history focus guard、Escape、delete continuity、empty/error states 和 E-drive build policy。
- live preview 已检查 Generate（宽/窄视口）、Models、History 及下一张结果切换；视觉目标按交接包中的深色工作站原型对照。
- 真实 Hardware Probe、CUDA 生成、Research Engine、MSI bundle/signing 未在本阶段伪造或接入。
