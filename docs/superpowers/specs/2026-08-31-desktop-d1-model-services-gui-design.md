# M-LLM Windows AI Workbench — D1 Model & Services GUI Design

Date: 2026-08-31  
Status: APPROVED IMPLEMENTATION SLICE  
Branch: `feature/knowledge-phase-c`  
Baseline: `c9a4abce23e58ebc0651cd4f1c118945fccd6c93`  
Parent design: `docs/superpowers/specs/2026-08-27-desktop-workbench-redesign-design.md`  
Phase B design: `docs/superpowers/specs/2026-08-28-desktop-workbench-phase-b-design.md`

## Goal

Complete the native WPF product surface for the already-implemented Phase B model and service backend capabilities. D1 must make Model Management and Local Services fully reachable from the current desktop shell without adding a second backend, second installer, or arbitrary command execution path.

## Current baseline

The current desktop exposes four routes only: Dashboard, Doctor, Installation Center, and Knowledge Workbench. The repository already contains `ModelManagementPageViewModel` and typed backend model/service RPC contracts, while no native Model Management XAML page and no Local Services native page/ViewModel are wired into the shell.

The backend already supports the fixed Phase B allowlist:

- `models.snapshot`
- `models.verify`
- `models.import`
- `models.activate`
- `services.snapshot`
- `service.start`
- `service.stop`
- `service.restart`
- `service.logs`

D1 consumes those existing operations. It does not introduce generic process, PID, port, script, executable, or filesystem-path execution APIs.

## Product surface

### Model Management

The native Model Management page must provide:

- model inventory with id, display name, source, role, format, quantization, size, integrity state, active state, and local path;
- current active model summary;
- current network mode;
- `Import local GGUF` file picker;
- `Verify` selected model;
- `Activate` selected model;
- `Refresh`;
- selected-model detail/status area;
- structured error display.

The page does not add Delete in D1. Import remains local `.gguf` only and never auto-activates a model.

### Local Services

The native Local Services page must provide the two existing managed product services:

- Local Model API (`local-model-api` / backend authoritative id returned by snapshot);
- Web Workbench (`web-workbench`).

For every returned service descriptor the page shows:

- display name and service id;
- state;
- PID;
- endpoint/base URL;
- port;
- model/runtime identity when available;
- health/block reason;
- Start / Stop / Restart according to capability flags;
- Refresh;
- View logs;
- Copy endpoint.

The log panel is populated only through `service.logs`; Desktop never accepts or sends an arbitrary log path.

### Shell and Dashboard

The persistent left rail gains two routes:

- `模型管理`
- `本地服务`

Dashboard gains quick navigation commands for these two routes. Current Phase C Knowledge navigation remains unchanged.

## Interaction and concurrency

- All model/service backend work uses existing async commands and keeps the WPF thread responsive.
- Mutating commands include operation IDs using the existing typed request contracts.
- Command availability is driven by descriptor state and `CanStart/CanStop/CanRestart` flags, not by guessed text.
- Refresh after a successful mutation is mandatory so UI state comes from backend authority.
- Failed operations preserve the previous visible state and surface a structured error message.

## Safety boundaries

D1 must not:

- expose arbitrary PowerShell, shell, command, executable, PID, port, or destination path input;
- install drivers, firmware, DISM/PNPUTIL changes, scheduled tasks, or registry settings;
- bypass the existing managed-model storage or active-model pointer;
- terminate a process by port alone;
- silently install missing runtime dependencies when a service Start is blocked;
- weaken the named-pipe session authentication or backend method allowlist.

## Testing and release gates

D1 acceptance requires all of the following:

1. ViewModel unit tests for model and local-service state/action behavior.
2. Shell tests proving both new persistent navigation routes are present and route to the correct ViewModels.
3. WPF runtime-load smoke for both new pages.
4. Backend Phase B model/service/lifecycle/allowlist regressions remain green.
5. Full Desktop regression remains green on Windows Server 2022 and 2025.
6. Installed Release smoke starts the final packaged EXE and performs real navigation to Dashboard, Model Management, Local Services, and Knowledge Workbench without dispatcher failures.
7. Existing C7 package runtime/web completeness gates remain green.

## Non-goals

D1 does not implement Conversation Test, Golden Test, new model downloading, benchmark, evidence catalog, settings, network-mode mutation, About, knowledge-source lifecycle, or a new installer. Those are handled by later D2–D5 slices already approved by the user.
