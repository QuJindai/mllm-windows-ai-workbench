# Dream/Codex GPU Stability Implementation Plan

> **For agentic workers:** Execute this plan task-by-task with a failing test before each production change. Preserve unrelated dirty-worktree changes and do not commit them implicitly.

**Goal:** Keep Windows Dream CUDA generation below a safe shared-GPU budget and reduce Chromium renderer pressure when viewing Dream history.

**Architecture:** A small, pure Python VRAM policy computes a conservative native budget from total VRAM and non-Dream usage. The PowerShell wrapper consumes that budget, records total and Dream-process observations, and retains CPU offload. The React history grid marks thumbnails as lazy/async so only visible images are decoded eagerly.

**Tech Stack:** Python 3.12, pytest, PowerShell, React 19, TypeScript, Vitest, Testing Library.

**Spec:** The observed failure evidence in the current task: six recent Codex renderer crashes, Dream peak usage of 5841/6141 MiB, a hard-coded `--max-vram 5.2`, total-card rather than per-process sampling, and eager loading of all history PNGs.

## Global Constraints

- Never change BIOS or GPU driver settings as part of this application fix.
- Keep at least 1 GiB of GPU headroom for Codex/desktop rendering on a 6 GiB card.
- Preserve `--offload-to-cpu` and truthful resource metadata.
- Do not run another high-resolution generation during verification.
- Do not overwrite unrelated existing worktree changes.

### Task 1: Add the safe VRAM policy

**Files:**
- Create: `apps/dream-windows/server/vram_policy.py`
- Test: `apps/dream-windows/server/tests/test_vram_policy.py`

**Interfaces:**
- Produces `safe_cuda_budget_gb(total_vram_mib: int, other_vram_mib: int = 0, reserve_mib: int = 1024, overhead_mib: int = 512) -> float`.

- [ ] Write a failing test for a 6141 MiB GPU with no other usage, expecting a 4.5 GiB native target.
- [ ] Write a failing test proving other GPU usage reduces the target and the result never drops below 3.0 GiB.
- [ ] Run `pytest -q apps/dream-windows/server/tests/test_vram_policy.py` and confirm the expected import/behavior failure.
- [ ] Implement only the pure policy calculation with 0.1 GiB flooring and a 3.0 GiB lower bound.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Remove the unsafe wrapper hard-code

**Files:**
- Modify: `scripts/run_stable_diffusion_wrapper.ps1:70-125`
- Test: `apps/dream-windows/server/tests/test_generation_jobs.py`

**Interfaces:**
- The wrapper reads optional `DREAM_CUDA_MAX_VRAM_GB`; if unset, it computes a conservative target from `nvidia-smi` total memory and current non-Dream usage.
- The native command contains the computed value in the `--max-vram` argument and preserves `--offload-to-cpu`.

- [ ] Add a failing contract test that rejects the literal `"--max-vram", "5.2"` and requires a computed `$maxVramGb` argument.
- [ ] Add a failing contract test that requires the wrapper to record both `total_vram_mib` and `peak_vram_mib` plus the selected budget in metadata.
- [ ] Run the focused tests and confirm they fail against the hard-coded wrapper.
- [ ] Add wrapper helpers to parse `nvidia-smi`, reserve 1 GiB for the desktop/browser, subtract 512 MiB runtime overhead, clamp the budget, and honor an explicitly provided safe environment override.
- [ ] Keep process cleanup in `finally`, and ensure diagnostic sampling cannot turn a successful generation into a failure.
- [ ] Run the focused backend tests and confirm they pass.

### Task 3: Reduce browser renderer image pressure

**Files:**
- Modify: `apps/dream-windows/src/app/pages/HistoryPage.tsx:68-75`
- Test: `apps/dream-windows/src/app/pages/HistoryPage.test.tsx`

**Interfaces:**
- History thumbnails render with `loading="lazy"` and `decoding="async"`.
- The selected viewer image decodes asynchronously without changing viewer behavior.

- [ ] Add a failing test that checks history thumbnail images are lazy and asynchronous.
- [ ] Run the focused Vitest test and confirm it fails against eager `<img>` tags.
- [ ] Add the two attributes to thumbnails and the async decode hint to the viewer image.
- [ ] Run the focused Vitest test and confirm it passes.

### Task 4: Verify without high-load reproduction

**Files:**
- Modify: `docs/dream-windows/W3_BROWSER_ACCEPTANCE.md` only if the observed stability evidence needs recording.

- [ ] Run the full frontend test suite: `npm run test:run` from `apps/dream-windows`.
- [ ] Run the frontend production build: `npm run build` from `apps/dream-windows`.
- [ ] Run the full backend suite: `pytest -q apps/dream-windows/server/tests`.
- [ ] Run `git diff --check`.
- [ ] Check `http://127.0.0.1:8766/api/health` and `nvidia-smi` while idle; do not launch a high-resolution generation.
- [ ] Report remaining uncertainty: renderer crash dumps are unavailable, so the fix reduces the confirmed GPU-pressure path but cannot prove every Codex crash is caused by Dream.
