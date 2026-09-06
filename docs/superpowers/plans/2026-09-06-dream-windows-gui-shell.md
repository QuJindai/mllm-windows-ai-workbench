# Dream Windows GUI Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the first runnable Dream Windows GUI Alpha as a Tauri 2 desktop shell with typed domain state, a clearly marked Mock Provider, and usable Generate, Models, History Grid, and History Viewer flows.

**Architecture:** `apps/dream-windows` is a standalone Vite/React TypeScript frontend hosted by a minimal Tauri 2 Rust shell. Domain types and provider interfaces remain framework-independent; feature screens consume only `DreamProvider`, and `MockDreamProvider` supplies deterministic fixtures until the real W0/W1 backend adapter is integrated. All project-owned build, cache, fixture, and output paths are under `E:\Dream`.

**Tech Stack:** Tauri 2, Rust, Vite, React, TypeScript, Vitest, Testing Library, CSS Grid/Flexbox, and Windows WebView2.

**Spec:** `E:\Dream\handoffs\GUI_20260906\Dream_Windows_GUI_Codex_Handoff_20260906\codex\CODEX_GUI_START_PROMPT.md` plus `docs/01_GUI_IMPLEMENTATION_PLAN.md` through `docs/07_CODE_STRUCTURE_RECOMMENDATION.md` in the extracted handoff.

## Global Constraints

- Desktop target is Tauri 2 on Windows 11; the frontend must build independently with Vite.
- The production engine remains `stable-diffusion.cpp + CUDA`; this phase uses Mock Data and must not import or invoke backend binaries from components.
- Every Dream-owned project path, generated artifact, cache, fixture, log, and build output is below `E:\Dream`.
- Mock UI must show `DEMO / MOCK` and must preserve `observed`, `derived`, and `unavailable` truth semantics.
- The shell uses a dark professional-workstation theme: no large pure-black surfaces, no fixed-coordinate page layout, and no body overflow at 125%/150% DPI.
- Generate state transitions are observable (`queued → preparing → sampling → decoding → complete`); clicking Generate must not synchronously inject a result.
- History viewer state is `viewerSequenceIds` plus `viewerIndex`; deleting the current item selects the next item, then previous, then closes.
- H7 Attention is an unavailable research view in this phase and must not present mock heatmaps as production observations.
- Existing Safe Core and Android reference files remain outside this feature branch's scope.

---

### Task 1: GUI project shell and deterministic test harness

**Files:**
- Create: `apps/dream-windows/package.json`
- Create: `apps/dream-windows/index.html`
- Create: `apps/dream-windows/vite.config.ts`
- Create: `apps/dream-windows/tsconfig.json`
- Create: `apps/dream-windows/tsconfig.node.json`
- Create: `apps/dream-windows/src/test/setup.ts`
- Create: `apps/dream-windows/src/styles/tokens.css`
- Create: `apps/dream-windows/src/styles/global.css`
- Test: `apps/dream-windows/src/app/app-shell.test.tsx`

**Interfaces:**
- `npm test` runs Vitest in jsdom from the app directory.
- Vite serves `index.html` and resolves `@/` to `src`.
- CSS exposes design tokens used by every component rather than page-local color literals.

- [ ] **Step 1: Write the failing shell test.** Import `App` from `src/app/App`, render it in a `DreamProviderContext`, and assert the six nav labels, `Hardware Status`, `DEMO / MOCK`, and the default `Generate` heading.
- [ ] **Step 2: Run the test to verify the expected failure.** Run `npm test -- --run src/app/app-shell.test.tsx` from `apps/dream-windows`; it must fail because the app source does not yet exist.
- [ ] **Step 3: Add the Vite/React test harness and token stylesheet.** Pin React/Vite/Vitest dependencies in `package.json`, configure jsdom and the Testing Library setup file, and define the dark blue/cyan/green/amber/red tokens from the handoff.
- [ ] **Step 4: Run the test again.** It may fail with a missing `App` module, which is the intended red state before Task 2 implementation.

### Task 2: Tauri 2 Windows shell and typed domain/provider layer

**Files:**
- Create: `apps/dream-windows/src-tauri/Cargo.toml`
- Create: `apps/dream-windows/src-tauri/src/main.rs`
- Create: `apps/dream-windows/src-tauri/tauri.conf.json`
- Create: `apps/dream-windows/src-tauri/capabilities/default.json`
- Create: `apps/dream-windows/src/main.tsx`
- Create: `apps/dream-windows/src/app/App.tsx`
- Create: `apps/dream-windows/src/app/providers.tsx`
- Create: `apps/dream-windows/src/domain/hardware.ts`
- Create: `apps/dream-windows/src/domain/models.ts`
- Create: `apps/dream-windows/src/domain/generation.ts`
- Create: `apps/dream-windows/src/domain/history.ts`
- Create: `apps/dream-windows/src/domain/experiment.ts`
- Create: `apps/dream-windows/src/domain/trace.ts`
- Create: `apps/dream-windows/src/providers/DreamProvider.ts`
- Create: `apps/dream-windows/src/providers/MockDreamProvider.ts`
- Create: `apps/dream-windows/src/fixtures/*.json`
- Create: `apps/dream-windows/src/app/app-shell.test.tsx`
- Test: `apps/dream-windows/src/domain/domain-contract.test.ts`

**Interfaces:**
- `DreamProvider` exposes `getHardware`, `listModels`, `getModel`, `generate`, `getJob`, `listHistory`, `getHistoryItem`, `deleteHistory`, `favoriteHistory`, `runExperiment`, `getRuntimeTrace`, and `getResearchStatus`.
- `MockDreamProvider` implements that interface and returns fixture-backed data with delayed job progress.
- `useDreamProvider()` is the only provider access used by screens; no screen imports `stable-diffusion.cpp`, Rust commands, or filesystem paths.
- Domain types include `HardwareSnapshot`, `ModelRecord`, `GenerationRequest`, `GenerationState`, `HistoryItem`, `Experiment`, `RuntimeNode`, `LatentFrame`, `InfluenceFrame`, and `AttentionFrame` with `TruthLevel`.

- [ ] **Step 1: Write the failing domain contract test.** Assert the provider returns the six-nav hardware fixture, a verified SDXL model under `E:\Dream`, a history page with adjacent IDs, and a generation job that reports at least `queued`, `sampling`, and `complete` states over time.
- [ ] **Step 2: Run the domain test and verify it fails.** Run `npm test -- --run src/domain/domain-contract.test.ts`; it must fail because the domain/provider modules are absent.
- [ ] **Step 3: Implement the domain types, fixtures, provider interface, and mock provider.** Use the real local baseline (RTX 1000 Ada 6141 MiB, 64 GB RAM, `E:\Dream`) for hardware; mark all demo images and research attention as mock/unavailable. The mock generation job uses timers with a minimum 120 ms phase delay and returns deterministic history items.
- [ ] **Step 4: Implement `providers.tsx` and mount `App` from `main.tsx`.** Use React context for the provider and a single app-level state object for navigation, toast, selected model, generation job, and history viewer.
- [ ] **Step 5: Run the domain and shell tests.** Both must pass; failures must be corrected in production code, not weakened assertions.

### Task 3: Shared design-system components and six-route app shell

**Files:**
- Create: `apps/dream-windows/src/components/ui/*.tsx`
- Create: `apps/dream-windows/src/components/shell/AppShell.tsx`
- Create: `apps/dream-windows/src/components/shell/StatusBar.tsx`
- Create: `apps/dream-windows/src/components/shell/SideNav.tsx`
- Create: `apps/dream-windows/src/components/shell/PageHeader.tsx`
- Create: `apps/dream-windows/src/components/shell/InspectorPanel.tsx`
- Create: `apps/dream-windows/src/components/charts/MetricBar.tsx`
- Create: `apps/dream-windows/src/components/charts/Sparkline.tsx`
- Create: `apps/dream-windows/src/components/image/ImageViewer.tsx`
- Create: `apps/dream-windows/src/features/PlaceholderPage.tsx`
- Modify: `apps/dream-windows/src/app/App.tsx`
- Modify: `apps/dream-windows/src/styles/global.css`
- Test: `apps/dream-windows/src/app/navigation.test.tsx`

**Interfaces:**
- `AppShell` receives `activeRoute`, `onNavigate`, `hardware`, and `children`.
- `StatusBar` renders observed hardware values and a `DEMO / MOCK` badge when the provider is mock.
- `SideNav` exposes keyboard-focusable buttons for Generate, Models, History, Lab, Microscope, and Settings.
- UI primitives expose semantic `disabled`, `loading`, `error`, `empty`, and `unavailable` states without fixed page coordinates.

- [ ] **Step 1: Write the failing navigation test.** Assert keyboard activation changes the route to Models, History, Lab, Microscope, and Settings; assert an unavailable state is visible for placeholder/research screens.
- [ ] **Step 2: Run the navigation test and verify it fails.** Run `npm test -- --run src/app/navigation.test.tsx` before creating shell components.
- [ ] **Step 3: Implement shared components and responsive CSS.** Use CSS Grid/Flexbox, `minmax`, `clamp`, collapsible inspector behavior under 1280px, visible focus rings, `aria-label`s, and tooltips for icon-only buttons. Avoid absolute coordinates except for bounded overlays.
- [ ] **Step 4: Implement route selection in `App.tsx`.** Keep the six top-level navigation routes reachable; show concise Lab/Microscope/Settings placeholder screens until their later feature gates, with H7 labeled `Research Engine unavailable`.
- [ ] **Step 5: Run all current tests and perform a Vite build.** Run `npm test -- --run` and `npm run build`; both must pass before feature screens are added.

### Task 4: Generate workbench and generation state machine

**Files:**
- Create: `apps/dream-windows/src/features/generate/GeneratePage.tsx`
- Create: `apps/dream-windows/src/features/generate/generationState.ts`
- Create: `apps/dream-windows/src/features/generate/GeneratePage.test.tsx`
- Modify: `apps/dream-windows/src/app/App.tsx`

**Interfaces:**
- `GeneratePage` owns form state for prompt, negative prompt, model, width, height, steps, CFG, seed, fusion mode, and trace level.
- `generationState.ts` exposes `nextGenerationState(current, event)` and rejects invalid transitions.
- Generate submit calls `DreamProvider.generate(request)` and observes `getJob(id)` until complete or failed.

- [ ] **Step 1: Write failing state-machine and UI tests.** Cover the ordered queued/preparing/sampling/decoding/complete path, disabled Generate while active, prompt validation, visible loading state, and CUDA unavailable/error state.
- [ ] **Step 2: Run the tests and verify they fail.** Run `npm test -- --run src/features/generate/GeneratePage.test.tsx`.
- [ ] **Step 3: Implement the reducer and Generate UI.** Use the model fixture, DMD2 settings, preview placeholder/image, metadata tab, variants count, runtime inspector, VRAM/RAM bars, and time accounting. Clearly badge mock mode and preserve `observed/derived/unavailable` labels.
- [ ] **Step 4: Run Generate tests and build.** Confirm the state sequence is visible to the test and no backend module appears in the feature import graph.

### Task 5: Models page and model inspector

**Files:**
- Create: `apps/dream-windows/src/features/models/ModelsPage.tsx`
- Create: `apps/dream-windows/src/features/models/ModelCard.tsx`
- Create: `apps/dream-windows/src/features/models/ModelsPage.test.tsx`
- Modify: `apps/dream-windows/src/app/App.tsx`

**Interfaces:**
- `ModelsPage` filters `ModelRecord[]` by search, type, architecture, and tags; selecting a card populates the inspector.
- Inspector actions expose mock-safe Load, Validate SHA, Import, Export, Delete, and Reindex controls with disabled/unsupported/error status messaging.

- [ ] **Step 1: Write failing model tests.** Cover search, card selection, SHA verified/unverified states, E-drive path visibility, and model action loading/error feedback.
- [ ] **Step 2: Run them and verify failure.** Run `npm test -- --run src/features/models/ModelsPage.test.tsx`.
- [ ] **Step 3: Implement model grid/list toggle, search/filter bar, cards, E-drive storage card, and inspector.** Use fixture records; never claim a mock action changed a real registry.
- [ ] **Step 4: Run model tests and build.** Keep model details typed and provider-backed.

### Task 6: History grid, viewer, carousel, keyboard, and delete continuity

**Files:**
- Create: `apps/dream-windows/src/features/history/historyState.ts`
- Create: `apps/dream-windows/src/features/history/HistoryPage.tsx`
- Create: `apps/dream-windows/src/features/history/HistoryViewer.tsx`
- Create: `apps/dream-windows/src/features/history/HistoryPage.test.tsx`
- Modify: `apps/dream-windows/src/app/App.tsx`
- Modify: `apps/dream-windows/src/styles/global.css`

**Interfaces:**
- `HistoryPage` owns `viewerSequenceIds: string[]` and `viewerIndex: number`.
- `historyState.ts` exposes `nextViewerIndex`, `previousViewerIndex`, and `indexAfterDelete(sequenceIds, index)` with next-then-previous-then-close semantics.
- Viewer supports prev/next buttons, ArrowLeft/ArrowRight, Escape, zoom, favorite, compare, export/open-folder mock actions, and Delete confirmation.

- [ ] **Step 1: Write failing history reducer and UI tests.** Cover filters/search, opening a viewer, ArrowLeft/Right navigation, thumbnail selection, deleting the current item with a next neighbor, deleting the last item with a previous neighbor, and closing an empty sequence.
- [ ] **Step 2: Run them and verify failure.** Run `npm test -- --run src/features/history/HistoryPage.test.tsx`.
- [ ] **Step 3: Implement history grid and viewer.** Use lazy-by-ID lookup through the provider; preserve detail metadata, tags, prompt/negative prompt, file path, and explicit demo status.
- [ ] **Step 4: Run history tests and build.** Verify the viewer never exits merely because the current image was deleted when an adjacent item exists.

### Task 7: DPI/accessibility evidence, Tauri build, and G0-G3 acceptance

**Files:**
- Create: `apps/dream-windows/scripts/verify-dpi.mjs`
- Create: `apps/dream-windows/scripts/verify-e-drive.mjs`
- Create: `docs/dream-windows/W2_GUI_ACCEPTANCE.md`
- Modify: `apps/dream-windows/package.json`
- Modify: `README.md` with one concise W2 GUI pointer only if needed

**Interfaces:**
- `npm run tauri:build` produces the Windows Tauri executable under `E:\Dream\builds\dream-windows` by setting `CARGO_TARGET_DIR` and Vite output paths.
- `npm run verify:dpi` checks 100/125/150% CSS/layout invariants and absence of body horizontal overflow in a headless browser or deterministic CSS audit.
- `npm run verify:e-drive` fails if Dream-owned build/cache/output configuration points outside `E:\Dream`.
- Acceptance document records branch, HEAD, Tauri build, screens, mock provider, carousel, DPI, E-drive policy, screenshots/executable, and remaining G4-G8 gates.

- [ ] **Step 1: Write failing acceptance checks.** Assert package scripts, Tauri config, E-drive target paths, six nav routes, and no component import of backend binaries.
- [ ] **Step 2: Run checks and capture the expected failures before evidence exists.**
- [ ] **Step 3: Implement DPI/E-drive scripts and acceptance documentation.** Keep the scripts deterministic and local.
- [ ] **Step 4: Build the Tauri desktop app with all cargo/npm caches redirected to E.** Confirm Rust compilation and Vite bundling succeed.
- [ ] **Step 5: Run all GUI tests, build, DPI check, E-drive check, and `git diff --check`.**
- [ ] **Step 6: Capture screenshots/executable evidence and update acceptance status.** Mark only G0-G3 gates supported by current evidence; record G4-G8 as remaining gates.
- [ ] **Step 7: Commit the GUI implementation** with `feat(dream): add Windows Tauri GUI shell and mock flow`.

## Self-review

- G0 is covered by Tasks 1–3 and Task 7.
- G1 is covered by Task 2 and the provider/import contract tests.
- G2 is covered by Task 4.
- G3 is covered by Task 5.
- History continuity is covered by Task 6 even though full Lab/Microscope/Settings implementation remains outside this first G0-G3 delivery.
- Placeholder routes keep all six primary navigation entries reachable without faking H7 data.
- No task relies on fixed coordinate positioning or a C-drive Dream asset.
