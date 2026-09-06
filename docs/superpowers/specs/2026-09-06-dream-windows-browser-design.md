# Dream Windows Browser Workstation Design

**Date:** 2026-09-06  
**Status:** Approved for implementation  
**Scope:** Browser-first local workstation with a real Dream backend and prototype-aligned UI

## Goal

Replace the current Tauri/Mock GUI alpha with a browser-accessible Dream workstation at `http://127.0.0.1:8765`. The browser UI must read real hardware and model state from `E:\Dream`, submit real image generation through `dream-core.exe`, persist PNG/metadata, and expose all nine prototype surfaces with truthful availability states for research data that the native runtime does not export.

## Current root cause

The existing frontend creates `MockDreamProvider` in `apps/dream-windows/src/main.tsx`. The Tauri shell in `apps/dream-windows/src-tauri/src/lib.rs` has no commands or invoke handler. Generate, Models, and History use fixture data; Lab, Microscope, and Settings are preview placeholders. The native boundary already exists as `E:\Dream\app\current\dream-core.exe`, but no browser service owns its environment, process lifecycle, job state, or file-backed history.

## Architecture

`apps/dream-windows/src` remains the React/Vite client. A separate `apps/dream-windows/server` FastAPI service owns the Dream HTTP API and serves the built client as same-origin static files. The service binds to `127.0.0.1` by default and resolves all Dream paths under `E:\Dream`.

The service injects the existing native contract variables before starting `dream-core.exe`:

- `DREAM_HOME=E:\Dream`
- `DREAM_MODEL_REGISTRY=<repository>\config\dream\model-registry.json`
- `DREAM_STABLE_DIFFUSION_CPP_EXE=E:\Dream\app\stable-diffusion-cpp\sd-cli.exe`
- `DREAM_SDCPP_GENERATE_WRAPPER=<repository>\scripts\run_stable_diffusion_wrapper.cmd`

The browser never receives arbitrary command paths and never launches a process. The client talks to a typed `DreamHttpProvider`; `MockDreamProvider` remains test-only.

## HTTP contract

### Health, hardware, capabilities, and settings

```text
GET /api/health
GET /api/hardware
GET /api/capabilities
GET /api/settings
PUT /api/settings
```

`/api/hardware` reads `dream-core.exe hardware` and maps the persisted probe to GPU, VRAM, RAM, CUDA, driver, CPU, and E-drive fields. `/api/capabilities` reports native generation, process trace, latent trace, semantic experiment, and attention availability individually.

### Models

```text
GET  /api/models
GET  /api/models/{id}
POST /api/models/{id}/verify
POST /api/models/reindex
```

Model responses combine the repository registry with live file existence, byte size, and verification status. Paths returned to the browser are informational and remain constrained to `E:\Dream`.

### Generation and jobs

```text
POST /api/generate
GET  /api/jobs/{id}
POST /api/jobs/{id}/cancel
```

The POST validates the model ID, prompt, dimensions, steps, CFG, seed, and output policy, then returns a job ID. The server runs one controlled native process per job, records queued/running/completed/failed state under `E:\Dream\data\jobs`, captures native logs under `E:\Dream\logs`, and writes the PNG and JSON metadata under `E:\Dream\outputs\<date>`.

### History

```text
GET    /api/history?page=1&page_size=24&search=&filter=
GET    /api/history/{id}
DELETE /api/history/{id}
POST   /api/history/{id}/favorite
```

History is reconstructed from real output and metadata files, with compatibility scanning for existing E-drive history directories. It is not a second browser-owned database.

### Experiments and microscope

```text
POST /api/experiments
GET  /api/experiments/{id}
GET  /api/traces/{run_id}
GET  /api/traces/{run_id}/latent
GET  /api/traces/{run_id}/attention
```

Every response carries `truth` (`observed`, `derived`, `unavailable`, or `demo`) and `available`. The Runtime and Latent pages can display real process/resource evidence when present. The H7 page must display `Cross-attention 未采集` until a real debug graph exports attention tensors; no synthetic heatmap is allowed.

Errors use one envelope:

```json
{
  "code": "MODEL_FILE_MISSING",
  "message": "模型文件不存在",
  "retryable": false,
  "detail": {}
}
```

## Browser UI

The visual system follows the supplied designs: dark blue-black workstation background, fixed left navigation, top hardware status strip, compact bordered surfaces, cyan active states, dense two-column content, and right-side inspectors. The nine routes are:

1. Generate: prompt/negative prompt, presets, advanced controls, preview gallery, runtime inspector.
2. Models: search/filter, model grid, storage card, SHA verification, model inspector.
3. History grid: filter chips, search, card grid, selection drawer, favorite/export/delete actions.
4. History viewer: large image, metadata, prompt panels, previous/next, compare/export/delete.
5. Semantic Lab: fixed-seed experiment controls, baseline/variants, metrics, notebook panel.
6. Microscope Runtime: run selector, time accounting, runtime graph, node inspector, resource evidence.
7. Microscope Latent: process dynamics, latent map, step scrubber, channel statistics, correlations, histograms.
8. H7 Attention: token/chunk list, attention controls, heatmap area, focused region inspector; truthful unavailable mode when unsupported.
9. Settings: workspace paths, hardware summary, inference/memory settings, startup/update controls, diagnostics and actions.

Shared shell components own navigation, status bars, truth badges, loading/error states, and responsive sizing. Page components own only page-specific data and actions.

## Security and failure behavior

- Bind only to `127.0.0.1` unless a future explicit LAN mode is added.
- Reject paths outside `E:\Dream` and reject unknown model IDs.
- Do not infer successful generation from console text; require native exit code plus both PNG and metadata.
- Preserve structured native error codes and log paths in job responses.
- Mark missing backend capabilities as unavailable, not mocked.
- Keep the existing Tauri build available only as a compatibility shell; browser mode is the product entry point.

## Acceptance criteria

- `scripts/run_dream_web.ps1` starts the service on localhost and optionally opens the default browser.
- `GET /api/health`, `GET /api/hardware`, and `GET /api/models` pass against the current machine.
- The browser production entry uses `DreamHttpProvider`; no `MockDreamProvider` import remains in `main.tsx`.
- A small real generation produces a PNG and metadata under `E:\Dream\outputs` or returns a structured native failure with an actionable log path.
- History displays the generated artifact after refresh.
- All nine routes match the supplied visual hierarchy and have real or truthful-unavailable data states.
- Frontend tests, backend tests, contract tests, TypeScript build, Vite build, and browser smoke verification pass.
