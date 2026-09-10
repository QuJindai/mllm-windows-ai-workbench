# Dream Windows 生图引擎速度与质量升级 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修正错误模型身份和生成参数，移除可避免的固定耗时，默认启用 CUDA Flash Attention，并用真实生图验证速度和质量。

**Architecture:** 保留 React + FastAPI + dream-core + stable-diffusion.cpp 分层。模型 canonical identity 在 registry 定义，HTTP runtime 负责旧 id 兼容与规范化；PowerShell 支持模块负责纯参数构造与哈希缓存；包装脚本只编排引擎和元数据。

**Tech Stack:** React 19, TypeScript, Vitest, FastAPI, Pydantic, pytest, PowerShell 7/Windows PowerShell, C++17, stable-diffusion.cpp CUDA。

**Spec:** `docs/superpowers/specs/2026-09-08-dream-engine-speed-quality-design.md`

## Global Constraints

- 不覆盖或清理工作树中已有的 GUI、显微镜和后端改动。
- Dream 资产只写入 `E:\\Dream`；测试临时目录除外。
- 所有修复先写失败测试，再写最小实现，再运行回归。
- 当前模型不得继续声称为 DMD2。
- 不提高 RTX 1000 Ada 的功耗上限。

---

### Task 1: 修正模型身份并保留旧 id 兼容

**Files:**
- Modify: `tests/dream-windows/test_model_registry_contract.py`
- Modify: `config/dream/model-registry.json`
- Modify: `apps/dream-windows/server/runtime.py`
- Modify: `apps/dream-windows/server/tests/test_api_contract.py`
- Modify: `apps/dream-windows/server/tests/test_generation_jobs.py`
- Modify: `apps/dream-windows/src/app/pages/GeneratePage.tsx`
- Modify: `apps/dream-windows/src/app/pages/GeneratePage.test.tsx`

- [x] Replace the existing DMD2 registry assertions with tests for canonical standard-v10 identity, `dmd2.enabled == false`, and the legacy alias.
- [x] Add backend tests showing `get_model` resolves both ids and a legacy-id generation request is normalized before submission.
- [x] Run focused pytest and confirm failures are specifically caused by the old registry/runtime behavior.
- [x] Update the registry and add one runtime resolver used by model lookup and generation submission.
- [x] Change the browser default model id and visible model name without deleting old-history compatibility.
- [x] Run focused registry, backend and Generate page tests.

### Task 2: Add behavior-tested model hash caching

**Files:**
- Create: `scripts/DreamEngineSupport.psm1`
- Create: `tests/dream-windows/test_engine_support_module.py`
- Modify: `scripts/run_stable_diffusion_wrapper.ps1`

- [x] Add a pytest that creates a temporary model file, calls `Get-DreamCachedFileHash` twice, and requires miss then hit with the same digest.
- [x] Extend the test to mutate the file and require cache invalidation.
- [x] Run the focused test and confirm the module/function is missing.
- [x] Implement resilient JSON loading and atomic cache replacement in the PowerShell module.
- [x] Replace unconditional `Get-FileHash` in the wrapper and write cache-hit status to metadata.
- [x] Run the focused test and PowerShell parser checks.

### Task 3: Enable Flash Attention through a testable argument builder

**Files:**
- Modify: `scripts/DreamEngineSupport.psm1`
- Modify: `tests/dream-windows/test_engine_support_module.py`
- Modify: `scripts/run_stable_diffusion_wrapper.ps1`
- Modify: `apps/dream-windows/server/models.py`
- Modify: `apps/dream-windows/src/domain/generation.ts`

- [x] Add tests requiring `New-DreamStableDiffusionArguments` to include `--diffusion-fa` by default and omit it only when explicitly disabled.
- [x] Add tests for basic versus H6 trace arguments and `dpm++2m_sde` sampler acceptance.
- [x] Run focused tests and confirm the new expectations fail.
- [x] Implement the pure argument builder and make the wrapper use its returned array.
- [x] Extend backend/frontend sampler contracts to `dpm++2m_sde`.
- [x] Add `flash_attention`, engine wall time and postprocess time to metadata.
- [x] Run focused Python, TypeScript and PowerShell checks.

### Task 4: Set truthful, stable browser defaults

**Files:**
- Modify: `apps/dream-windows/src/app/pages/GeneratePage.tsx`
- Modify: `apps/dream-windows/src/app/pages/GeneratePage.test.tsx`
- Modify: `apps/dream-windows/src/domain/generation-quality.ts`
- Modify: `apps/dream-windows/src/domain/generation-quality.test.ts`
- Modify: `apps/dream-windows/server/models.py`

- [x] Add frontend tests for 512 x 512, 20 steps, CFG 4, DPM++ 2M SDE/Karras and basic trace defaults.
- [x] Add a UI assertion that H6/H7 are opt-in analysis modes rather than the normal default.
- [x] Run focused Vitest and confirm it fails against current defaults.
- [x] Update frontend and backend defaults while retaining user-selected high-resolution and trace options.
- [x] Adjust quality guard copy/rules so the safe balanced profile is accepted and very low-step standard-model misuse is warned.
- [x] Run focused and full frontend/backend tests.

### Task 5: Full regression and real-engine acceptance

**Files:**
- Verify only, except for narrowly scoped defects exposed by verification.

- [x] Run all frontend Vitest tests and the production frontend build.
- [x] Run all backend pytest tests and core/project pytest tests.
- [x] Parse every changed PowerShell script/module.
- [x] Generate two real 512 x 512 images with identical settings; use the second run to verify a hash-cache hit.
- [x] Record end-to-end, engine, sampling, decode and postprocess times from generated metadata.
- [x] Visually inspect the generated image for recognizable subject, coherent composition, normal contrast and absence of the prior 8-step standard-model failure pattern.
- [x] Start the browser service on 127.0.0.1:8866, verify health, generation submission, history display and model identity through real browser interaction.
- [x] Summarize measured improvement and list persistent-engine/service-guardian work as the next separately testable phase.

## Execution Evidence

- Browser-triggered balanced generation: 512 x 512, 20 steps, CFG 4, DPM++ 2M SDE/Karras, Basic trace.
- End-to-end native job: 13.7 s; sampling: 9.55 s; decode: 1.10 s; cached postprocess: 0.081 s.
- Flash Attention: enabled; model hash cache: hit; observed total GPU memory peak: 3,145 MiB.
- Image inspection: coherent mountain, lake, reflection and lighting; near-black channel ratio 0.056%, near-white channel ratio 0.053%.
- Browser checks: Generate, Models, History, Lab, seven Microscope tabs and Settings loaded from the live backend with no browser console warnings/errors.
