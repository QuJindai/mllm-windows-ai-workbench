# Dream Windows Browser Workstation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a browser-first Dream workstation that uses real E-drive hardware/model/generation data and visually implements all nine supplied prototype screens.

**Architecture:** Keep the existing React/Vite client under `apps/dream-windows/src`, add an isolated FastAPI server under `apps/dream-windows/server`, and serve the production frontend from the same localhost origin. The server owns the constrained `dream-core.exe` process boundary, jobs, metadata, history scanning, traces, and capability truth.

**Tech Stack:** React 19, TypeScript, Vite, Vitest, Testing Library, Python 3, FastAPI, Pydantic, pytest, PowerShell, existing C++ `dream-core.exe`, stable-diffusion.cpp + CUDA.

**Spec:** `docs/superpowers/specs/2026-09-06-dream-windows-browser-design.md`

## Global Constraints

- Browser default URL is `http://127.0.0.1:8765`.
- All Dream assets, jobs, outputs, traces, logs, caches, and runtime state stay below `E:\Dream`.
- The browser cannot launch arbitrary commands or pass arbitrary filesystem paths.
- `MockDreamProvider` is test-only and never the production entry point.
- Unsupported research data is labeled `unavailable`; no synthetic attention or latent evidence is permitted.
- Preserve the user’s existing W0 working-tree changes and do not stage them accidentally.

---

### Task 1: Add browser server contracts and test fixtures

**Files:**
- Create: `apps/dream-windows/server/app.py`
- Create: `apps/dream-windows/server/config.py`
- Create: `apps/dream-windows/server/models.py`
- Create: `apps/dream-windows/server/runtime.py`
- Create: `apps/dream-windows/server/requirements.txt`
- Create: `apps/dream-windows/server/tests/conftest.py`
- Create: `apps/dream-windows/server/tests/test_api_contract.py`

**Interfaces:**
- `DreamServerConfig.from_environment() -> DreamServerConfig`
- `DreamRuntime(config: DreamServerConfig)` exposes `health()`, `hardware()`, `models()`, `history()`, and job methods.
- FastAPI `create_app(config: DreamServerConfig | None = None, runtime: DreamRuntime | None = None) -> FastAPI`.

- [ ] **Step 1: Write failing API contract tests** for `/api/health`, `/api/capabilities`, `/api/hardware`, `/api/models`, `/api/history`, and structured errors using a temporary E-drive-shaped fixture.
- [ ] **Step 2: Run the tests and confirm they fail** because the Dream API module does not exist.
- [ ] **Step 3: Implement Pydantic response/request models and config path validation** with a localhost default and E-drive root checks.
- [ ] **Step 4: Implement read-only health, hardware, model, capability, and history endpoints** without generation yet.
- [ ] **Step 5: Run `python -m pytest apps/dream-windows/server/tests/test_api_contract.py -q`** and confirm the contract tests pass.

### Task 2: Connect the real native generation job boundary

**Files:**
- Modify: `apps/dream-windows/server/runtime.py`
- Modify: `apps/dream-windows/server/app.py`
- Create: `apps/dream-windows/server/job_runner.py`
- Create: `apps/dream-windows/server/tests/test_generation_jobs.py`
- Modify: `apps/dream-windows/server/requirements.txt`

**Interfaces:**
- `JobRunner.submit(request: GenerationRequest) -> JobRecord`
- `JobRunner.get(job_id: str) -> JobRecord`
- `JobRunner.cancel(job_id: str) -> JobRecord`
- `DreamRuntime.generate(request: GenerationRequest) -> JobRecord`

- [ ] **Step 1: Write failing tests** proving unknown model IDs, non-E-drive outputs, and missing native dependencies return stable error codes; prove a successful injected runner persists PNG/metadata and becomes `complete`.
- [ ] **Step 2: Run `python -m pytest apps/dream-windows/server/tests/test_generation_jobs.py -q`** and confirm the new tests fail for missing job implementation.
- [ ] **Step 3: Implement one controlled subprocess per job** with `DREAM_HOME`, registry, engine, and wrapper environment variables injected by the server; generate output paths under `E:\Dream\outputs\YYYY-MM-DD`.
- [ ] **Step 4: Persist job JSON, stdout/stderr log paths, process state, native exit code, and parsed metadata**; never mark success without PNG and metadata.
- [ ] **Step 5: Add `POST /api/generate`, `GET /api/jobs/{id}`, and `POST /api/jobs/{id}/cancel`, then rerun the job tests and the full backend contract suite.

### Task 3: Replace the production Mock Provider with the HTTP Provider

**Files:**
- Create: `apps/dream-windows/src/providers/DreamHttpProvider.ts`
- Modify: `apps/dream-windows/src/providers/DreamProvider.ts`
- Modify: `apps/dream-windows/src/main.tsx`
- Modify: `apps/dream-windows/src/app/providers.tsx`
- Create: `apps/dream-windows/src/providers/DreamHttpProvider.test.ts`

**Interfaces:**
- `DreamHttpProvider implements DreamProvider` using same-origin `fetch`.
- `createDreamProvider(): DreamProvider` returns HTTP provider in browser runtime and is injectable in tests.

- [ ] **Step 1: Write failing provider tests** for health/hardware, model list, job submission/polling, history filtering, favorite, and structured API errors.
- [ ] **Step 2: Run the provider tests and confirm they fail** because the HTTP provider and runtime selection do not exist.
- [ ] **Step 3: Implement a small fetch client** that decodes the common error envelope and maps API responses to existing domain types.
- [ ] **Step 4: Switch `main.tsx` to `createDreamProvider()`** and remove the production `MockDreamProvider` instance.
- [ ] **Step 5: Run all Vitest tests and the TypeScript build.

### Task 4: Rebuild the shared shell to match the prototypes

**Files:**
- Modify: `apps/dream-windows/src/app/App.tsx`
- Modify: `apps/dream-windows/src/app/shell.css`
- Modify: `apps/dream-windows/src/styles/tokens.css`
- Modify: `apps/dream-windows/src/styles/global.css`
- Create: `apps/dream-windows/src/app/components/TopBar.tsx`
- Create: `apps/dream-windows/src/app/components/SideNav.tsx`
- Create: `apps/dream-windows/src/app/components/TruthBadge.tsx`
- Modify: `apps/dream-windows/src/app/app-shell.test.tsx`

- [ ] **Step 1: Add failing shell assertions** for Dream brand lockup, top GPU/RAM/CUDA metrics, E-drive path, prototype navigation labels, and responsive active state.
- [ ] **Step 2: Run the shell tests and confirm the current generic shell fails the new prototype contract.
- [ ] **Step 3: Implement the fixed workstation chrome** with compact prototype spacing, icon treatment, status bars, and truthful live/demo badges.
- [ ] **Step 4: Run shell tests at desktop and narrow viewport configurations and then run the full Vitest suite.

### Task 5: Implement Generate, Models, History, and Settings production pages

**Files:**
- Modify: `apps/dream-windows/src/app/pages/GeneratePage.tsx`
- Modify: `apps/dream-windows/src/app/pages/ModelsPage.tsx`
- Modify: `apps/dream-windows/src/app/pages/HistoryPage.tsx`
- Create: `apps/dream-windows/src/app/pages/SettingsPage.tsx`
- Modify: `apps/dream-windows/src/app/App.tsx`
- Modify: page tests and `apps/dream-windows/src/app/shell.css`

- [ ] **Step 1: Write failing UI tests** for prototype controls, live hardware/model labels, real job polling/result metadata, history grid/viewer actions, and settings diagnostics.
- [ ] **Step 2: Run the focused tests and confirm they fail against the alpha layout/provider behavior.
- [ ] **Step 3: Implement the Generate page** with prompt tabs, preset/advanced controls, preview/variants, runtime inspector, and native job state.
- [ ] **Step 4: Implement Models and Settings** with storage summary, filters, verify/reindex actions, paths, inference memory controls, diagnostics, and reset-safe UI.
- [ ] **Step 5: Implement the History grid/viewer** with prototype toolbar, details drawer, compare/export affordances, favorite/delete continuity, and real file metadata.
- [ ] **Step 6: Run the focused page tests, the full Vitest suite, and `npm run build`.

### Task 6: Implement Semantic Lab, Runtime Microscope, Latent Microscope, and H7

**Files:**
- Create: `apps/dream-windows/src/app/pages/SemanticLabPage.tsx`
- Create: `apps/dream-windows/src/app/pages/MicroscopeRuntimePage.tsx`
- Create: `apps/dream-windows/src/app/pages/MicroscopeLatentPage.tsx`
- Create: `apps/dream-windows/src/app/pages/H7AttentionPage.tsx`
- Modify: `apps/dream-windows/src/domain/experiment.ts`
- Modify: `apps/dream-windows/src/domain/trace.ts`
- Modify: `apps/dream-windows/src/app/App.tsx`
- Create: page tests and visualization helpers under `apps/dream-windows/src/app/components/`

- [ ] **Step 1: Write failing page tests** for experiment submission, observed/derived/unavailable truth states, runtime node rendering, latent scrubber state, and H7 unavailable wording.
- [ ] **Step 2: Run the focused tests and confirm they fail because the production pages are absent.
- [ ] **Step 3: Implement the prototype-aligned page structures and data mappings**; use real traces where the API advertises them and explicit unavailable panels otherwise.
- [ ] **Step 4: Add API endpoints for experiments/traces and wire the pages to `DreamHttpProvider`.
- [ ] **Step 5: Run focused tests, full Vitest, and TypeScript build.

### Task 7: Add localhost launch, static serving, and browser verification

**Files:**
- Modify: `apps/dream-windows/server/app.py`
- Create: `apps/dream-windows/server/run.py`
- Create: `scripts/run_dream_web.ps1`
- Modify: `apps/dream-windows/package.json`
- Create: `apps/dream-windows/scripts/browser-smoke.mjs`
- Modify: `apps/dream-windows/README.md`
- Create: `apps/dream-windows/server/tests/test_static_server.py`

- [ ] **Step 1: Write failing server/static tests** proving the built index is served at `/` and API remains same-origin.
- [ ] **Step 2: Run the tests and confirm static serving is absent.
- [ ] **Step 3: Implement static serving, the PowerShell launcher, dependency bootstrap guidance, and optional browser opening.
- [ ] **Step 4: Run the frontend build, start the server, and execute the browser smoke script against `http://127.0.0.1:8765`.
- [ ] **Step 5: Capture desktop screenshots for Generate, Models, History, Lab, Microscope, H7, and Settings and compare the visual hierarchy against the supplied designs.

### Task 8: Full acceptance and release artifact

**Files:**
- Modify: `docs/dream-windows/W2_GUI_ACCEPTANCE.md`
- Create: `docs/dream-windows/W3_BROWSER_ACCEPTANCE.md`
- Modify: `tests/dream-windows/Invoke-DreamAcceptance.ps1`
- Create: `tests/dream-windows/test_browser_contract.py`

- [ ] **Step 1: Add acceptance checks** for browser server files, localhost binding, API route set, production provider selection, E-drive paths, and no Mock entrypoint.
- [ ] **Step 2: Run the new contract tests and confirm they fail before the acceptance wiring is complete.
- [ ] **Step 3: Implement the acceptance runner integration and documentation.
- [ ] **Step 4: Run the full verification set: backend pytest, frontend Vitest, TypeScript/Vite build, browser smoke, Python contract tests, DPI/E-drive checks, and a real native generation smoke if dependencies pass.
- [ ] **Step 5: Record exact results and artifact paths; report remaining environment-dependent limitations without claiming unsupported research tensors are live.
