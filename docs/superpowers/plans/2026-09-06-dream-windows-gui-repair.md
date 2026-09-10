# Dream Windows GUI Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the browser workstation behaviours found during GUI inspection while keeping unsupported research features truthful.

**Architecture:** The FastAPI runtime remains the single owner of E-drive files, native jobs, trace artifacts, workspace actions, and exported configuration. React pages consume those operations through the typed provider; unsupported latent/attention/semantic capabilities remain explicitly unavailable instead of receiving fabricated data.

**Tech Stack:** React 19, TypeScript, Vitest, Testing Library, FastAPI, Pydantic, pytest, PowerShell, existing native generation boundary.

**Spec:** `docs/superpowers/specs/2026-09-06-dream-windows-browser-design.md`

## Global Constraints

- Keep all Dream state, outputs, traces, logs, and exports below `E:\Dream`.
- Never invent latent, attention, or semantic experiment evidence that the native Windows runtime does not export.
- Keep the browser client on the typed `DreamHttpProvider`; `MockDreamProvider` is test-only.
- Preserve all existing user working-tree changes and do not stage or reset unrelated files.
- Every production behaviour change gets a failing regression test before implementation.

---

### Task 1: Persist real process traces and remove expected trace-console errors

**Files:**
- Modify: `apps/dream-windows/server/job_runner.py`
- Modify: `apps/dream-windows/server/runtime.py`
- Modify: `apps/dream-windows/server/tests/test_generation_jobs.py`
- Modify: `apps/dream-windows/server/tests/test_api_contract.py`
- Modify: `apps/dream-windows/src/domain/trace.ts`
- Modify: `apps/dream-windows/src/providers/DreamHttpProvider.ts`
- Modify: `apps/dream-windows/src/app/pages/MicroscopePage.tsx`
- Create or modify: `apps/dream-windows/src/app/pages/MicroscopePage.test.tsx`

**Interfaces:**
- A completed native job with `traceLevel !== "off"` writes `E:\Dream\traces\<job-id>.json` containing the actual native generation duration and output metadata.
- `GET /api/traces/latest` returns an unavailable response with HTTP 200 when no trace exists and a real `RuntimeTrace` once a job has completed.

- [ ] **Step 1: Add failing backend tests** for trace persistence after a successful injected native runner, latest-trace selection by file modification time, and a structured unavailable response when no trace exists.
- [ ] **Step 2: Run the focused backend tests** and verify they fail because jobs do not create traces and the endpoint returns 404.
- [ ] **Step 3: Implement the smallest trace writer** using measured job/native metadata; expose only observed process-level nodes and resource fields, not fabricated latent or attention tensors.
- [ ] **Step 4: Update the trace endpoint/provider/UI types** so unavailable state is data, not a browser network error; keep Latent and H7 unavailable copy intact.
- [ ] **Step 5: Run the focused backend and frontend tests** and verify the trace regression passes without changing unsupported capability claims.

### Task 2: Make Settings tabs and workspace actions real

**Files:**
- Modify: `apps/dream-windows/server/app.py`
- Modify: `apps/dream-windows/server/runtime.py`
- Modify: `apps/dream-windows/server/tests/test_api_contract.py`
- Modify: `apps/dream-windows/src/providers/DreamProvider.ts`
- Modify: `apps/dream-windows/src/providers/DreamHttpProvider.ts`
- Modify: `apps/dream-windows/src/providers/MockDreamProvider.ts`
- Modify: `apps/dream-windows/src/app/pages/SettingsPage.tsx`
- Create or modify: `apps/dream-windows/src/app/pages/SettingsPage.test.tsx`

**Interfaces:**
- `POST /api/workspace/open` accepts a fixed workspace entry key and opens only the corresponding validated E-drive directory.
- `GET /api/settings/export` downloads the persisted settings JSON with an attachment filename.
- Settings Rebuild Index calls the existing model reindex provider operation and reports its result.
- Every Settings tab has `aria-selected` state and a distinct tab panel.

- [ ] **Step 1: Add failing API/provider/UI tests** for fixed-key workspace opening, settings download, Rebuild Index invocation, and distinct Hardware/Model & Inference/User Interface/Advanced/About panels.
- [ ] **Step 2: Run focused tests** and verify the new assertions fail against the inert tab buttons and notice-only actions.
- [ ] **Step 3: Implement validated server actions** and provider methods without accepting arbitrary browser-supplied filesystem paths.
- [ ] **Step 4: Refactor Settings into tab panels** while preserving the existing live hardware and persisted inference controls.
- [ ] **Step 5: Run focused tests and verify a production build** before moving on.

### Task 3: Add safe History deletion and truthful Lab controls

**Files:**
- Modify: `apps/dream-windows/src/app/pages/HistoryPage.tsx`
- Modify: `apps/dream-windows/src/app/pages/HistoryPage.test.tsx`
- Modify: `apps/dream-windows/src/app/pages/LabPage.tsx`
- Create or modify: `apps/dream-windows/src/app/pages/LabPage.test.tsx`

- [ ] **Step 1: Add failing tests** proving Delete and the Delete shortcut cancel safely, while confirmed deletion still refreshes the viewer; prove Lab uses the current 20-step/CFG 7 profile and disables unavailable research controls with an explanatory status.
- [ ] **Step 2: Run focused tests** and verify they fail before implementation.
- [ ] **Step 3: Add confirmation around both deletion entry points** and preserve existing selection continuity after confirmed deletion.
- [ ] **Step 4: Align Lab defaults and make unavailable controls visibly read-only** without pretending the semantic engine is implemented.
- [ ] **Step 5: Run focused tests and the complete frontend suite.**

### Task 6: Capture real latent projection frames for the Windows microscope

**Files:**
- Modify: `dream/core/src/main.cpp`
- Modify: `dream/core/tests/test_cli_contract.py`
- Modify: `scripts/run_stable_diffusion_wrapper.ps1`
- Modify: `apps/dream-windows/server/job_runner.py`
- Modify: `apps/dream-windows/server/runtime.py`
- Modify: `apps/dream-windows/server/app.py`
- Modify: `apps/dream-windows/server/tests/test_generation_jobs.py`
- Modify: `apps/dream-windows/server/tests/test_api_contract.py`
- Modify: `apps/dream-windows/src/domain/generation.ts`
- Modify: `apps/dream-windows/src/domain/trace.ts`
- Modify: `apps/dream-windows/src/providers/DreamProvider.ts`
- Modify: `apps/dream-windows/src/providers/DreamHttpProvider.ts`
- Modify: `apps/dream-windows/src/providers/MockDreamProvider.ts`
- Modify: `apps/dream-windows/src/app/pages/GeneratePage.tsx`
- Modify: `apps/dream-windows/src/app/pages/MicroscopePage.tsx`
- Modify: `apps/dream-windows/src/app/pages/MicroscopePage.test.tsx`
- Modify: `apps/dream-windows/src/app/shell.css`

**Interfaces:**
- `GenerationRequest.traceLevel` controls capture. `basic` keeps phase timing only; `h6` and `h7` request real stable-diffusion.cpp latent projection previews.
- `dream-core generate` accepts `--trace-level` and `--trace-dir`, validates the directory below `DREAM_HOME`, and forwards them in the native request JSON.
- The PowerShell wrapper passes `--preview proj --preview-interval 1 --preview-path <trace-dir>\\latent-step-%03d.png` for `h6`/`h7`, then the server records existing frames as `{step, imageUrl, truth: "observed", kind: "latent-projection"}`.
- `GET /api/traces/{run_id}/latent` returns the observed projection frame list or a structured unavailable response. `GET /api/traces/{run_id}/latent/frames/{file_name}` serves only a validated frame belonging to that run.
- The Latent microscope shows a step scrubber and the selected real projection frame. Raw latent channels, numerical statistics, and H7 attention remain explicitly unavailable because projection previews do not contain those tensors.

- [ ] **Step 1: Add failing native, server, and UI tests** for trace-level command propagation, preview-frame discovery, safe latent-frame endpoints, and rendering a step scrubber from observed projection frames.
- [ ] **Step 2: Run the focused tests** and verify they fail because trace level is not forwarded, no latent endpoint exists, and the Latent page has no frame viewer.
- [ ] **Step 3: Implement the native request and wrapper preview boundary** with E-drive path validation and no preview capture for `basic` runs.
- [ ] **Step 4: Persist and serve only existing projection files** with validated run/file paths and explicit `observed`/`unavailable` truth values.
- [ ] **Step 5: Add the Generate trace-detail selector and Latent step viewer**, keeping raw tensor and attention claims unavailable.
- [ ] **Step 6: Run focused tests, full suites, build, and headed browser regression with a real multi-step capture.

### Task 4: Full verification and browser regression

**Files:**
- Modify only if required by verification: existing implementation/test files.

- [ ] **Step 1: Run backend pytest for `tests/dream-windows` and `apps/dream-windows/server/tests`.
- [ ] **Step 2: Run frontend Vitest and `npm run build`.
- [ ] **Step 3: Restart the localhost service from the rebuilt frontend and run the headed browser flow across Generate, Models, History, Lab, all Microscope tabs, and all Settings tabs/actions.
- [ ] **Step 4: Confirm one real GUI generation creates a trace, the Microscope runtime panel reads it, clean Microscope loads do not emit 404 console errors, and the generated test artifact is removed through the confirmed delete flow.
- [ ] **Step 5: Report remaining unsupported research capabilities explicitly and preserve the working tree without unrelated cleanup.

### Task 5: Increase Microscope observability from native wrapper evidence

**Files:**
- Modify: `apps/dream-windows/server/job_runner.py`
- Modify: `apps/dream-windows/server/tests/test_generation_jobs.py`
- Modify: `apps/dream-windows/src/domain/trace.ts`
- Modify: `apps/dream-windows/src/app/pages/MicroscopePage.tsx`
- Create or modify: `apps/dream-windows/src/app/pages/MicroscopePage.test.tsx`

**Interfaces:**
- The Windows trace writer parses only timing lines actually emitted by stable-diffusion.cpp and stores observed phase events for conditioning, sampling, VAE decode, and final image generation.
- Runtime UI renders the observed phase timeline, measured totals, model/sampler/step/CFG evidence, and a raw-evidence summary; it must not calculate fake 82%/11% phase shares.
- Latent frames, token influence, and cross-attention remain explicitly unavailable until the Windows native engine exports those tensors.

- [ ] **Step 1: Add a failing regression test** with a representative stable-diffusion.cpp wrapper log and assert that trace output contains only the measured phase durations and raw log evidence.
- [ ] **Step 2: Run the focused test** and verify it fails because the current trace has one aggregate node and no phase events.
- [ ] **Step 3: Implement a small parser** for the known native log markers, ignore unmeasured phases, and retain the wrapper log path under `E:\Dream` as evidence.
- [ ] **Step 4: Update trace types and Microscope UI** to show a real timeline, selected node details, measured resource fields, and truthful unavailable states for unsupported tabs.
- [ ] **Step 5: Run the focused tests, full suites, build, and headed browser regression.

### Task 7: Export native latent telemetry for the Windows microscope

**Files:**
- Modify: `E:\Dream\src\stable-diffusion.cpp\include\stable-diffusion.h`
- Modify: `E:\Dream\src\stable-diffusion.cpp\src\core\util.h`
- Modify: `E:\Dream\src\stable-diffusion.cpp\src\core\util.cpp`
- Modify: `E:\Dream\src\stable-diffusion.cpp\src\stable-diffusion.cpp`
- Modify: `E:\Dream\src\stable-diffusion.cpp\examples\cli\main.cpp`
- Modify: `scripts/run_stable_diffusion_wrapper.ps1`
- Modify: `apps/dream-windows/server/job_runner.py`
- Modify: `apps/dream-windows/server/runtime.py`
- Modify: `apps/dream-windows/server/tests/test_generation_jobs.py`
- Modify: `apps/dream-windows/server/tests/test_api_contract.py`
- Modify: `apps/dream-windows/src/domain/trace.ts`
- Modify: `apps/dream-windows/src/app/pages/MicroscopePage.tsx`
- Modify: `apps/dream-windows/src/app/pages/MicroscopePage.test.tsx`
- Modify: `apps/dream-windows/src/app/shell.css`

**Interfaces:**
- The stable-diffusion.cpp additive C API exposes `sd_set_latent_trace_callback`, whose callback receives one live denoising latent as `(step, values, value_count, n_dims, shape, user_data)` and is invoked only while a trace path is enabled.
- The CLI writes one JSON object per observed denoising step to `latent-metrics.jsonl` and four normalized channel PNGs named `latent-step-%03d-ch%u.png`; the JSON includes `shape`, aggregate `mean/std/l2`, adjacent `deltaL2/deltaMeanAbs/cosine`, and per-channel `min/max/mean/std/l2/histogram` with `truth: "observed"` and `kind: "latent-state"`.
- The Windows server persists only validated files under the run trace directory and returns them from `GET /api/traces/{run_id}/latent`; projection frames remain separately labeled `latent-projection`.
- The Latent microscope renders real process metrics, a four-channel grid, channel statistics, histograms, and previous/current/final step comparison. If the native telemetry file is absent, it keeps the explicit unavailable state rather than falling back to projection data.

- [ ] **Step 1: Add failing native, wrapper, server, and UI tests** for the additive callback contract, JSONL/channel-map discovery, safe API payloads, and the four-channel inspector.
- [ ] **Step 2: Run the focused tests** and verify they fail because native output contains only projection frames.
- [ ] **Step 3: Implement the native callback and CLI writer** with bounded copies, finite-value handling, 32-bin histograms, per-channel maps, and no capture for `basic` runs.
- [ ] **Step 4: Forward, persist, and serve only declared latent telemetry** with run-root and filename validation.
- [ ] **Step 5: Add the Windows Latent inspector UI** for metrics, channels, histograms, and truthful unavailable fallback.
- [ ] **Step 6: Rebuild stable-diffusion.cpp and the Windows core, run all tests, and verify a real multi-step GUI generation.
