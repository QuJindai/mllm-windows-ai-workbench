# Dream Windows H7 Attention Research Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a real, debug-only cross-attention microscope for the Dream Windows browser application.

**Architecture:** Keep the verified production CUDA engine unchanged and build a separate H7 stable-diffusion.cpp worktree. Native code exports bounded observed attention artifacts; FastAPI validates and serves them; React fetches and renders one map at a time.

**Tech Stack:** C++17, stable-diffusion.cpp/ggml, CUDA 12.9.1, Python 3/FastAPI/Pydantic, React 19/TypeScript/Vitest.

**Spec:** `docs/superpowers/specs/2026-09-09-dream-windows-h7-attention-design.md`

## Global Constraints

- Do not modify or replace `E:\Dream\app\native-engine.json` while developing H7.
- Do not expose latent, influence, demo, or derived data as cross-attention.
- Accept only `contractVersion=h7-attention-v1`, `kind=cross-attention`, `truth=observed`, and `source=debug-unet`.
- Apply the documented token, layer, step, descriptor, dimension, and value bounds before returning data.
- Use test-first development and preserve all existing browser/API behavior.

---

### Task 1: Validated attention trace API

**Files:**
- Modify: `apps/dream-windows/server/runtime.py`
- Modify: `apps/dream-windows/server/app.py`
- Test: `apps/dream-windows/server/tests/test_api_contract.py`

**Interfaces:**
- Produces: `DreamRuntime.attention_index(run_id: str) -> dict[str, Any]`
- Produces: `DreamRuntime.attention_map(run_id: str, map_id: str) -> dict[str, Any]`
- Produces: `GET /api/traces/{run_id}/attention`
- Produces: `GET /api/traces/{run_id}/attention/maps/{map_id}`

- [ ] Add a failing API test with one valid observed index and map fixture; assert normalized public fields and canonical URLs.
- [ ] Run the focused test and confirm 404/failure because routes do not exist.
- [ ] Implement bounded index and map validators in `DreamRuntime`.
- [ ] Register the two FastAPI routes.
- [ ] Add failing rejection cases for demo truth, path traversal, non-finite values, wrong lengths, and excessive dimensions.
- [ ] Implement explicit unavailable/404 behavior and rerun focused backend tests.

### Task 2: Browser domain and provider contract

**Files:**
- Modify: `apps/dream-windows/src/domain/trace.ts`
- Modify: `apps/dream-windows/src/providers/DreamProvider.ts`
- Modify: `apps/dream-windows/src/providers/DreamHttpProvider.ts`
- Modify: `apps/dream-windows/src/providers/MockDreamProvider.ts`
- Test: `apps/dream-windows/src/providers/DreamHttpProvider.test.ts`

**Interfaces:**
- Produces: `RuntimeAttentionIndex`, `RuntimeAttentionMap`
- Produces: `DreamProvider.getAttentionIndex(runId)` and `getAttentionMap(runId, mapId)`

- [ ] Add failing HTTP-provider tests for index and selected-map endpoints.
- [ ] Run the focused Vitest file and confirm missing methods/types fail compilation.
- [ ] Add strict TypeScript domain types and provider methods.
- [ ] Rerun the focused provider tests and full TypeScript build.

### Task 3: H7 browser workbench

**Files:**
- Modify: `apps/dream-windows/src/app/pages/MicroscopePage.tsx`
- Modify: `apps/dream-windows/src/app/pages/MicroscopePage.test.tsx`
- Modify: `apps/dream-windows/src/app/shell.css`

**Interfaces:**
- Consumes: `getAttentionIndex(runId)` and `getAttentionMap(runId, mapId)` from Task 2.
- Produces: token, stage/layer, and step selection with a heatmap and measured statistics.

- [ ] Add a failing component test that supplies two tokens and two layers with distinct observed maps.
- [ ] Verify the test fails because no H7 workbench is rendered.
- [ ] Implement lazy index loading when the H7 tab opens.
- [ ] Implement token/layer/step controls and fetch only the selected map.
- [ ] Render the normalized values as an accessible CSS-grid heatmap with observed labels and metrics.
- [ ] Add and pass unavailable, loading, malformed, and selection-change tests.

### Task 4: Isolated native H7 callback contract

**Files:**
- Modify in H7 engine worktree: `include/stable-diffusion.h`
- Modify in H7 engine worktree: `src/core/util.h`
- Modify in H7 engine worktree: `src/core/util.cpp`
- Modify in H7 engine worktree: `src/core/ggml_extend.hpp`
- Test/Create in H7 engine worktree: `tests/test_h7_attention_contract.py`

**Interfaces:**
- Produces: `sd_attention_trace_cb_t`
- Produces: an opt-in runner context that receives compact F32 attention snapshots.

- [ ] Add a failing source/compile contract requiring the callback signature and no activation by default.
- [ ] Confirm the contract fails against clean H7 source.
- [ ] Add callback registration and an optional runner capture sink.
- [ ] Ensure normal runner execution contains no extra capture output.
- [ ] Build the narrow native targets and pass the contract.

### Task 5: SDXL representative cross-attention capture

**Files:**
- Modify in H7 engine worktree: `src/model/common/block.hpp`
- Modify in H7 engine worktree: `src/model/diffusion/unet.hpp`
- Modify in H7 engine worktree: `src/stable-diffusion.cpp`
- Test: `tests/test_h7_attention_contract.py`

**Interfaces:**
- Consumes: opt-in attention capture sink from Task 4.
- Produces: head-mean token-by-spatial probability maps for one Down, Mid, and Up layer.

- [ ] Add failing graph-contract assertions for selected Down/Mid/Up layer IDs and debug-only manual attention.
- [ ] Extend the runner context with the active logical denoising step and selected layer identity.
- [ ] In debug mode only, expose manual softmax probabilities from cross-attention and reduce across heads before host copy.
- [ ] Capture only the three selected layer locations and bounded token/step subsets.
- [ ] Build and run a one-step 256×256 native probe; assert three finite, non-constant maps.

### Task 6: Native artifact writer and Dream H7 launcher

**Files:**
- Modify in H7 engine worktree: `examples/cli/main.cpp`
- Create: `scripts/build_dream_h7_engine.ps1`
- Modify: `apps/dream-windows/server/job_runner.py`
- Test: `apps/dream-windows/server/tests/test_generation_jobs.py`

**Interfaces:**
- Produces: `--attention-trace-path <directory>` CLI option.
- Produces: `E:\Dream\app\stable-diffusion-cuda-h7\sd-cli.exe`.
- Produces: H7-only job routing that never changes the production engine selection.

- [ ] Add failing CLI help and job-routing tests.
- [ ] Write index/map artifacts atomically under the run trace directory.
- [ ] Build/package the H7 executable separately and record source revision plus SHA256.
- [ ] Route only `traceLevel=h7` to the research executable; keep off/basic/h6 behavior unchanged.
- [ ] Pass CLI, backend, cancellation, and production-route regression tests.

### Task 7: Parity, performance, and GUI acceptance

**Files:**
- Create: `scripts/verify_dream_h7_parity.py`
- Create: `docs/dream-windows/H7_ATTENTION_ACCEPTANCE.md`
- Modify: `docs/dream-windows/W3_BROWSER_ACCEPTANCE.md`

**Interfaces:**
- Consumes: production and H7 executable paths plus a frozen generation request.
- Produces: a JSON parity/performance report and browser screenshots.

- [ ] Generate a frozen production image and H7 image with identical model, prompt, negative prompt, seed, sampler, scheduler, steps, and dimensions.
- [ ] Compare dimensions, finite pixels, perceptual difference, wall time, peak VRAM, and peak RAM against frozen limits.
- [ ] Verify token and layer changes select distinct non-constant maps.
- [ ] Run backend tests, frontend tests, TypeScript build, service health, and browser GUI walkthrough.
- [ ] Record exact limitations and leave H7 disabled if parity or bounded-memory gates fail.
