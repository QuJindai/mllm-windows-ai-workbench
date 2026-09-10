# Dream Windows 手机版能力对齐与显微镜增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 Windows 浏览器版与 Android H6R5R1 的主要可操作能力对齐，并把显微镜增强为真实数据驱动的 H6 工作台。

**Architecture:** 保留 React/FastAPI/stable-diffusion.cpp 分层，新增稳定的前端 provider/domain 契约和串行实验编排。UI 仅展示后端实际返回的 observed 数据，推导值和不可用值使用独立真值状态。

**Tech Stack:** React 19, TypeScript, Vitest, Testing Library, FastAPI, Pydantic, pytest, PowerShell, stable-diffusion.cpp CUDA。

**Spec:** `docs/superpowers/specs/2026-09-07-dream-mobile-parity-design.md`

## Global Constraints

- Dream 自有模型、缓存、历史、trace、实验和构建资产只位于 `E:\\Dream`。
- Production Engine 继续使用 stable-diffusion.cpp + CUDA；不把 Android QNN binary 当 Windows 模型。
- 6GB VRAM 默认串行生成，实验不并发启动多个 native job。
- `observed`、`derived`、`unavailable` 必须在 UI 中可见。
- 不能用 latent 图冒充 decoded preview，不能用 influence 冒充 cross-attention。

---

### Task 1: 扩展数据契约和 Provider 能力

**Files:**
- Modify: `apps/dream-windows/src/domain/generation.ts`
- Modify: `apps/dream-windows/src/domain/experiment.ts`
- Modify: `apps/dream-windows/src/domain/trace.ts`
- Modify: `apps/dream-windows/src/providers/DreamProvider.ts`
- Modify: `apps/dream-windows/src/providers/DreamHttpProvider.ts`
- Modify: `apps/dream-windows/src/providers/MockDreamProvider.ts`
- Test: `apps/dream-windows/src/providers/DreamHttpProvider.test.ts`

**Interfaces:**
- Produces `GenerationBatch`, `ExperimentRequest`, `RuntimeCapability`, and provider methods `cancelJob`, `runExperiment`, `getExperiment`.
- Existing `generate`, history, settings and trace methods remain source compatible.

- [x] Write failing contract tests for cancel, experiment payload, and H6/H7 capability response.
- [x] Run the focused Vitest file and confirm it fails because the methods/types are absent.
- [x] Add the minimum types and HTTP calls, with JSON error propagation unchanged.
- [x] Add deterministic mock behavior for tests, including four same-seed experiment variants.
- [x] Run the focused file and then all provider/domain tests.

### Task 2: Generate 预设与批量队列

**Files:**
- Modify: `apps/dream-windows/src/app/pages/GeneratePage.tsx`
- Modify: `apps/dream-windows/src/app/pages/GeneratePage.test.tsx`
- Modify: `apps/dream-windows/src/app/shell.css`

**Interfaces:**
- Consumes `GenerationRequest` and provider `generate/getJob/cancelJob`.
- Produces a visible Prompt/预设/高级 tab set, saved presets in local storage, sequential batch queue, per-item progress, cancel button, and completed result strip.

- [x] Add failing tests for saving/selecting a preset, submitting a two-image serial batch, and cancelling the active item.
- [x] Run the focused tests and verify the expected failures.
- [x] Implement queue state as an explicit reducer; submit only the next item after the previous terminal state.
- [x] Add quality-preserving default preset and prevent unsafe dimension/step combinations before queue submission.
- [x] Run focused tests and existing Generate tests.

### Task 3: History Carousel、实时刷新、缩放比较和重新生成

**Files:**
- Modify: `apps/dream-windows/src/app/pages/HistoryPage.tsx`
- Modify: `apps/dream-windows/src/app/pages/HistoryPage.test.tsx`
- Modify: `apps/dream-windows/src/app/App.tsx`
- Modify: `apps/dream-windows/src/app/shell.css`

**Interfaces:**
- Consumes history provider methods and an app-level rerun callback.
- Produces auto-refresh for newest tasks, current index/total, arrow and pointer-swipe navigation, zoom/pan without accidental navigation, compare mode, export/open-folder actions, and rerun-to-Generate.

- [x] Add failing tests for auto-refresh, index/total, touch swipe, zoom state, compare selection and rerun callback.
- [x] Run focused tests and confirm failures describe missing behavior.
- [x] Implement bounded polling that stops on unmount and does not reset the selected item when the same list remains.
- [x] Implement pointer gesture threshold and zoom-aware navigation guard.
- [x] Add compare panel and rerun route state without duplicating provider logic.
- [x] Run focused and full frontend tests.

### Task 4: 真实同种子 Semantic Lab

**Files:**
- Modify: `apps/dream-windows/server/models.py`
- Modify: `apps/dream-windows/server/app.py`
- Modify: `apps/dream-windows/server/runtime.py`
- Modify: `apps/dream-windows/server/job_runner.py`
- Modify: `apps/dream-windows/src/app/pages/LabPage.tsx`
- Modify: `apps/dream-windows/src/app/pages/LabPage.test.tsx`
- Modify: `apps/dream-windows/server/tests/test_api_contract.py`
- Modify: `apps/dream-windows/server/tests/test_generation_jobs.py`

**Interfaces:**
- `POST /api/experiments` accepts prompt, negative prompt, model, seed, steps, CFG, and variant kind.
- Returns experiment id plus four variant job identities; a later GET returns current states and completed image URLs.

- [x] Add failing API tests for required same-seed fields and serialized variant identity.
- [x] Run focused pytest and confirm failure.
- [x] Implement serial orchestration on the existing one-worker job runner; each variant receives the same seed and common parameters.
- [x] Implement Lab controls, progress cards, comparison metrics only from returned results, and a clear unavailable state when native dependencies are missing.
- [x] Run backend and Lab tests.

### Task 5: Microscope H6 工作台增强

**Files:**
- Modify: `apps/dream-windows/src/domain/trace.ts`
- Modify: `apps/dream-windows/src/app/pages/MicroscopePage.tsx`
- Modify: `apps/dream-windows/src/app/pages/MicroscopePage.test.tsx`
- Modify: `apps/dream-windows/src/app/shell.css`
- Modify: `apps/dream-windows/server/runtime.py`
- Modify: `apps/dream-windows/server/tests/test_api_contract.py`

**Interfaces:**
- Consumes runtime trace, latent telemetry, evidence, hardware and research capability responses.
- Produces views for Prompt/Chunk/CFG truth, Process Dynamics, Latent State Inspector, Runtime Compute Graph, Influence, Mechanism and Expert raw trace; H7 is capability-gated.

- [x] Add failing UI tests for the new tabs, observed/derived/unavailable labels, and the no-fake-attention boundary.
- [x] Run focused tests and verify missing tab/content failures.
- [x] Implement the tabs using existing trace data; show exact formulas only as derived explanations and raw token/attention as unavailable unless returned by backend.
- [x] Add hardware evidence cards for VRAM, RAM, temperature and backend when present.
- [x] Add accessible selectors, step/chunk controls and bounded rendering for traces.
- [x] Run Microscope tests and all frontend tests.

### Task 6: Browser acceptance and artifact verification

**Files:**
- Modify: `docs/dream-windows/W3_BROWSER_ACCEPTANCE.md`
- Modify: `docs/dream-windows/W2_GUI_ACCEPTANCE.md`
- Modify: `apps/dream-windows/README.md`

- [x] Build the frontend and restart the local browser service on port 8766.
- [x] Use browser UI to navigate every page, exercise Generate presets/batch, History carousel/compare, Lab entry, and every Microscope tab.
- [x] Run frontend tests, backend tests, production build, PowerShell parser, and `git diff --check`.
- [x] Re-read the spec and plan, record any capability that remains genuinely unavailable, and do not claim H7 native attention without research-engine evidence.
