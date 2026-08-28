# M-LLM Windows AI Workbench — Desktop Phase B Design

Date: 2026-08-28  
Status: DESIGN FOR REVIEW  
Branch: `feature/desktop-phase-b`  
Stacked baseline: `feature/desktop-phase-a@ebd3616016ee2ca3fe30d8c54643c6120e993d3c`  
Parent design: `docs/superpowers/specs/2026-08-27-desktop-workbench-redesign-design.md`

## 1. Goal

Phase B extends the verified native `.NET 8 WPF` Desktop foundation with the next two product surfaces defined by the parent design:

1. **Model Management**
2. **Local Services**

The purpose is to make local model assets and runtime services observable and controllable from the native Desktop without duplicating or weakening Safe Core.

Phase B must reuse the authenticated Named Pipe bridge and existing Safe Core runtime/state functions. It must not introduce arbitrary PowerShell execution, generic process control, direct driver/system modification, or a second installer implementation.

## 2. Scope correction against the parent design

The parent design defines Phase B as **Models and Services**. Therefore this phase does **not** build the full Network Center or Evidence Center.

Phase B may:

- display the current network mode because service startup depends on it;
- expose service log/evidence shortcuts needed to diagnose runtime failures;
- preserve the current `OFFLINE_CACHE` and Safe Core policy semantics.

Phase B does not add network-mode mutation UI, proxy management, evidence catalog/history, benchmark, chat, RAG, settings, or About. Those remain in later phases according to the parent design.

## 3. Current verified baseline

Phase B starts from the Phase A head that passed the Windows 2022 and Windows 2025 feature matrix and the pull-request Safe Core regressions.

Existing Phase A backend RPC allowlist:

- `system.ping`
- `dashboard.snapshot`
- `doctor.snapshot`
- `installer.snapshot`

Existing Safe Core behavior already available outside the native Desktop includes:

- `Start-MLLMLocalModelService`
- `Stop-MLLMLocalModelService`
- owned-process validation through `Test-MLLMRecordedProcess`
- port selection through `Get-MLLMFreePort`
- Web Workbench start/health/stop logic in `Start_M_LLM_Workbench.ps1`
- five network modes already enforced by Safe Core
- model manifest data in `config/models.json`

The current model manifest contains one built-in `local-fast` model:

- id: `qwen35-4b-q4km`
- format: `gguf`
- canonical filename: `Qwen3.5-4B-Q4_K_M.gguf`
- minimum size: `2684354560` bytes
- expected SHA256: currently `null`

Because the manifest currently has no trusted reference SHA256 for that model, the product must not label a file cryptographically verified merely because it has the right name and size.

## 4. Architecture

Phase B keeps the Phase A four-layer structure and adds one reusable tracked adapter.

```text
WPF Desktop
  |-- Model Management ViewModel
  |-- Local Services ViewModel
  |-- Dashboard summary integration
  |
  v
Typed Contracts / Infrastructure client
  |
  v
Authenticated Named Pipe
  |
  v
runtime/WorkbenchBackend.ps1
  |
  v
runtime/WorkbenchRuntimeAdapter.psm1
  |-- Safe Core Runtime / State modules
  |-- model inventory / verify / import / activate
  |-- local-model service lifecycle
  `-- Web Workbench lifecycle
```

### 4.1 `WorkbenchRuntimeAdapter.psm1`

A new tracked module owns the reusable runtime/model orchestration that is currently partly embedded in the legacy entry script.

The adapter exists to avoid copying Web Workbench lifecycle code into both the backend and `Start_M_LLM_Workbench.ps1`.

The legacy PowerShell entrypoint and the new backend must call the same adapter for Web and model-service lifecycle behavior.

The adapter is not a general shell wrapper. Its exported functions are fixed product operations only.

### 4.2 Desktop responsibilities

The Desktop is responsible for:

- navigation;
- user confirmation and file selection;
- typed request construction;
- rendering model/service state;
- disabling invalid commands;
- maintaining UI responsiveness while awaiting backend calls.

It does not:

- choose arbitrary executable paths;
- terminate processes by port alone;
- edit Safe Core state files directly;
- copy model files directly into managed storage;
- write the active-model pointer directly;
- invoke arbitrary PowerShell.

### 4.3 Backend responsibilities

The backend is responsible for:

- validating every RPC method and payload;
- resolving model IDs to server-controlled paths;
- model file structural/integrity checks;
- managed model import;
- active model pointer mutation;
- service ownership validation;
- start/stop/restart lifecycle;
- returning structured errors rather than console-string state.

## 5. RPC surface

Phase B extends the explicit method table with only these operations:

### Read-only

- `system.capabilities`
- `models.snapshot`
- `services.snapshot`
- `service.logs`

### Mutating

- `models.verify`
- `models.import`
- `models.activate`
- `service.start`
- `service.stop`
- `service.restart`

No RPC accepts an arbitrary command, script, executable, argument vector, PID, port, destination path, or log path from the caller.

The backend maps approved IDs to approved implementation functions.

### 5.1 Capability discovery

`system.capabilities` returns product capabilities such as:

- `models.snapshot`
- `models.verify`
- `models.import`
- `models.activate`
- `services.snapshot`
- `service.start`
- `service.stop`
- `service.restart`
- `service.logs`

The Desktop uses this to distinguish an older Phase A backend from a Phase B backend without weakening protocol authentication.

The base JSON-RPC protocol remains `1.0` because Phase B is additive; capability discovery determines feature availability.

## 6. Model Management design

### 6.1 Inventory sources

Model inventory is reconstructed from authoritative local sources rather than a Desktop-owned database:

1. built-in definitions from `config/models.json`;
2. managed imported model sidecars under the DataRoot model area;
3. actual model files on disk;
4. the atomic active-model pointer.

The Desktop SQLite/history layer, when added later, must not override this inventory.

### 6.2 Managed storage

Imported models are copied into a server-controlled location below the selected DataRoot, for example:

```text
<DataRoot>\models\managed\<model-id>\<filename>.gguf
<DataRoot>\models\managed\<model-id>\model.mllm.json
```

A user-selected source path is read-only input. The caller never supplies the managed destination path.

Built-in models may retain their existing canonical Safe Core path for compatibility.

### 6.3 Model descriptor

The typed model snapshot includes at minimum:

- `id`
- `role`
- `displayName`
- `sourceKind` (`BuiltIn` / `Imported`)
- `filePath`
- `fileName`
- `format`
- `quantization`
- `sizeBytes`
- `minimumBytes`
- `expectedSha256`
- `actualSha256`
- `integrityState`
- `isActive`
- `activationBlockedReason`

### 6.4 Integrity states

Phase B distinguishes structural verification from trusted hash verification.

`ModelIntegrityState`:

- `Missing`
- `StructuralPass`
- `Sha256Pass`
- `HashComputedUnanchored`
- `Failed`
- `Unknown`

Rules:

- `StructuralPass` requires a readable regular file, expected format signature, and applicable minimum-size checks.
- For GGUF, the file header must contain the GGUF magic.
- `Sha256Pass` is only legal when an expected trusted SHA256 exists and matches.
- If SHA256 is computed but the catalog has no trusted expected hash, state is `HashComputedUnanchored`, not `Sha256Pass`.
- Filename and file size alone never produce a cryptographic-verification label.

### 6.5 Import transaction

Phase B imports local `.gguf` files only.

Transaction:

1. validate source path is an existing regular local file;
2. validate `.gguf` extension and GGUF header;
3. copy to a unique staging path below `<DataRoot>`;
4. compute SHA256 while staged;
5. validate structural contract;
6. create a model sidecar with generated/validated model ID and actual hash;
7. atomically move staged content into its managed model directory;
8. return a refreshed descriptor.

Import never activates the model automatically.

On failure, staged data is removed where safe and no active-model state changes.

An existing model ID with different content fails closed instead of overwriting the old model.

### 6.6 Verify operation

Verify is read-only with respect to the model file.

It checks:

- existence/readability;
- format signature;
- configured minimum size when applicable;
- actual SHA256;
- expected SHA256 match when available.

The result records the actual SHA256 so the user can compare/export it later, but it does not manufacture a trusted expected hash.

### 6.7 Activation

The active-model pointer is stored below DataRoot in an atomic server-owned file, for example:

```text
<DataRoot>\state\active_model.json
```

Activation rules:

- candidate must not be `Missing` or `Failed`;
- the local model service must be stopped before switching;
- pointer update is temp-file + atomic replacement;
- previous active pointer is preserved until the candidate is fully validated;
- failed activation leaves the previous model active;
- service start consumes the active pointer first, then falls back to the built-in `local-fast` model when no pointer exists.

Phase B does not implement live/hot model swapping.

## 7. Local Services design

### 7.1 Service IDs

Phase B manages exactly two product services:

- `local-model-api`
- `web-workbench`

The caller cannot supply arbitrary service IDs beyond this allowlist.

### 7.2 Service descriptor

Each service snapshot includes:

- `serviceId`
- `displayName`
- `state`
- `pid`
- `port`
- `baseUrl`
- `startedAt`
- `uptimeSeconds`
- `modelId` / `modelPath` when applicable
- `healthSummary`
- `stdoutLog`
- `stderrLog`
- `canStart`
- `canStop`
- `canRestart`
- `blockedReason`

`ServiceState`:

- `Stopped`
- `Starting`
- `Running`
- `Stopping`
- `Degraded`
- `Blocked`
- `Failed`

### 7.3 Ownership rule

A recorded PID is not sufficient by itself.

Before Stop/Restart, the adapter must validate the process using existing Safe Core ownership/recording rules. The product must never kill an arbitrary process because it happens to own the expected port.

### 7.4 Local model service

Start flow:

1. resolve active model;
2. if no active model exists, resolve the built-in `local-fast` model;
3. require model integrity to be non-failed;
4. require llama.cpp runtime readiness;
5. call the existing Safe Core local-model-service start path;
6. wait for the existing health/ready condition;
7. return PID/port/base URL/model identity and logs.

Stop flow validates owned process identity and uses the existing Safe Core stop path.

Restart is explicit `Stop -> verify stopped -> Start`; it is not a blind process kill/start.

### 7.5 Web Workbench

The existing Web lifecycle logic currently embedded in `Start_M_LLM_Workbench.ps1` is moved behind the shared runtime adapter so both legacy and Desktop flows use one implementation.

Start flow preserves the existing behavior:

- use the installed Web Python runtime below DataRoot;
- resolve loopback/LAN bind from existing Safe Core state;
- choose a free configured port;
- set `MLLM_PROJECT_ROOT` and `MLLM_DATA_ROOT` only for the child process;
- record owned PID/port/base URL in Safe Core state;
- wait for `/api/health`;
- fail if the process exits before healthy or the health deadline expires.

Phase B does not add new LAN enable/disable UI. It reflects the existing Safe Core state only.

### 7.6 No silent dependency startup

Starting `web-workbench` does not silently install missing dependencies.

If a required runtime is absent, the service returns `Blocked` with a structured reason and a navigation hint to Installation Center.

Phase B does not silently switch network mode or silently install components to make a service start.

## 8. Service logs

`service.logs` is restricted to the log files already associated with the selected managed service.

The caller supplies only `serviceId` and an optional bounded tail count.

The backend:

- resolves log paths itself;
- requires resolved paths to remain below the configured DataRoot log root;
- returns bounded text tails and file metadata;
- never accepts an arbitrary filesystem path from Desktop.

The Local Services page can open the containing log directory through a Desktop-side fixed action after receiving an approved path below DataRoot.

A full cross-run Evidence Center remains Phase E.

## 9. Network-mode behavior

Phase B does not add network settings.

The backend process continues to receive one of the existing Safe Core modes:

- `AUTO_CN_FIRST`
- `CHINA_ONLY`
- `GLOBAL_FIRST`
- `OFFLINE_CACHE`
- `CUSTOM_PROXY`

The current mode is visible on Model/Services pages.

Rules:

- service/model operations never mutate it;
- `OFFLINE_CACHE` model import from a user-selected local file remains permitted because it does not require external network access;
- Phase B does not add model downloading;
- service start must not trigger package/network acquisition.

## 10. WPF information architecture

Phase B adds two persistent navigation entries to the Phase A shell.

### 10.1 Model Management page

Header:

- current active model;
- total discovered models;
- structurally valid count;
- trusted-SHA verified count;
- current network mode.

Inventory surface:

- model name/id;
- source;
- role;
- format/quantization;
- size;
- integrity state;
- active badge;
- path.

Actions:

- `Import local GGUF`
- `Verify`
- `Activate`
- `Refresh`

The page does not show `Delete` in Phase B because deletion is not part of the parent Phase B exit scope.

### 10.2 Local Services page

Top cards:

- Local Model API
- Web Workbench

Each card shows state, PID, endpoint, port, runtime/model identity and last health message.

Actions:

- `Start`
- `Stop`
- `Restart`
- `Refresh`
- `View logs`
- `Copy endpoint`

A lower log panel shows bounded recent stdout/stderr tails for the selected service.

### 10.3 Dashboard integration

Phase A Dashboard is extended only with live summary data:

- current active model;
- Local Model API state;
- Web Workbench state.

Dashboard remains an overview; detailed controls live on the two Phase B pages.

## 11. Desktop command and concurrency rules

All WPF service/model mutations use `AsyncRelayCommand` and remain asynchronous from the UI thread.

Phase B serializes mutating model/service operations per Desktop session. A second mutation is disabled while one is running.

This phase does not introduce a second general-purpose background task engine.

Each mutation carries a correlation/operation ID in its typed payload and structured result/log record. The backend returns explicit stage/error information. The UI must not infer success from console text.

Long model hashing/copying may keep the model-operation RPC occupied, but the WPF thread remains responsive. Phase B does not claim concurrent model mutation and service mutation support.

## 12. Error model

Structured error codes include at minimum:

- `MODEL_NOT_FOUND`
- `MODEL_FORMAT_INVALID`
- `MODEL_SIZE_INVALID`
- `MODEL_HASH_MISMATCH`
- `MODEL_ID_COLLISION`
- `MODEL_ACTIVE_SERVICE_RUNNING`
- `MODEL_IMPORT_FAILED`
- `SERVICE_NOT_FOUND`
- `SERVICE_ALREADY_RUNNING`
- `SERVICE_NOT_RUNNING`
- `SERVICE_RUNTIME_MISSING`
- `SERVICE_MODEL_UNAVAILABLE`
- `SERVICE_PROCESS_OWNERSHIP_FAILED`
- `SERVICE_HEALTH_TIMEOUT`
- `SERVICE_EXITED_EARLY`
- `LOG_PATH_OUTSIDE_DATA_ROOT`

Expected absence/readiness is not reported as a product crash.

Backend implementation defects continue to surface as product errors rather than being mapped to component/model failure.

## 13. Safety boundaries

Phase B preserves all existing safety gates.

It must not:

- authorize withdrawn Install Core behavior;
- install drivers, firmware, MSI packages, scheduled tasks, registry settings or system Python;
- expose arbitrary PowerShell/shell execution over Named Pipe;
- accept arbitrary PID/port for Stop/Restart;
- accept arbitrary log destination/path for reading;
- overwrite a different model on ID collision;
- activate an invalid model;
- hot-swap an active model under a running model service;
- silently change Network Mode;
- download a model as part of model import or service start.

Administrator mode remains an installer concern, not a requirement for the normal Desktop runtime.

## 14. Legacy compatibility

`Start_M_LLM_Workbench.cmd` keeps the Phase A rule:

- no arguments / pure GUI use -> native Desktop when present;
- existing operational switches -> legacy PowerShell path.

The Web lifecycle implementation is refactored into the shared adapter, and the legacy entrypoint calls the same adapter so behavior does not fork.

The legacy `--start-service` path must resolve the active model pointer when present and otherwise preserve the existing built-in `local-fast` fallback.

## 15. Testing strategy

All changes use RED-first TDD.

### 15.1 Contracts and unit tests

- model/service enum serialization;
- model integrity mapping;
- ViewModel command enable/disable states;
- active-model pointer mapping;
- service-state mapping;
- operation/correlation IDs;
- no placeholder state needed for PASS.

### 15.2 Backend allowlist tests

Static and live tests require the exact approved method table.

They reject presence of generic methods such as:

- `exec`
- `command`
- `shell`
- `script`
- `eval`
- arbitrary process/PID control.

### 15.3 Model tests

Use isolated DataRoot fixtures to test:

- missing built-in model;
- valid synthetic GGUF structural header;
- invalid GGUF header;
- actual SHA computation;
- expected SHA match/mismatch;
- manifest with `sha256=null` returns unanchored-hash state rather than trusted verification;
- staged import -> atomic managed placement;
- import collision fails without overwrite;
- failed import leaves active pointer unchanged;
- activation succeeds for valid model;
- activation fails while model service is running;
- failed activation preserves previous pointer.

Tests do not need a multi-gigabyte fixture; minimum-size behavior is tested using an isolated test manifest with explicit test thresholds. Production manifest thresholds remain unchanged.

### 15.4 Service tests

Deterministic CI must cover:

- absent runtime -> `Blocked`, not crash;
- recorded PID that fails ownership validation -> refuse stop;
- service state reconstruction from Safe Core state;
- start/health/stop lifecycle using a test-owned local process fixture;
- early-exit and health-timeout failure;
- restart ordering;
- Web log path boundaries;
- no external request in `OFFLINE_CACHE` test paths.

Hosted CI does not claim real llama.cpp inference performance.

### 15.5 Windows matrix

Phase B workflow runs on:

- `windows-2022`
- `windows-2025`

It includes all Phase A gates plus Phase B model/service gates.

### 15.6 Packaged E2E

Build the same `win-x64` self-contained package, extract it under a path containing spaces, and verify:

1. Desktop starts;
2. backend authenticates;
3. `system.capabilities` advertises Phase B;
4. model snapshot loads;
5. model import/verify/activate fixture chain passes;
6. service snapshot loads;
7. test-owned service start/health/stop chain passes;
8. Dashboard reflects current model/service summary;
9. installer state remains unmodified by read-only Phase B E2E steps;
10. legacy launcher fallback remains intact.

### 15.7 Regression gates

Before Phase B is considered mergeable:

- Phase B Windows 2022 PASS;
- Phase B Windows 2025 PASS;
- all Phase A Desktop gates PASS;
- `safe-core-ci` PASS;
- Universal Installer CI/E2E PASS;
- direct-bootstrap and GUI-preflight regressions PASS.

## 16. Branch and integration strategy

`feature/desktop-phase-b` is intentionally stacked on the verified Phase A head because Phase B depends on the new Desktop projects.

Until PR #2 lands:

- Phase B does not modify `safe-core` directly;
- any Phase B PR should target `feature/desktop-phase-a` to show only Phase B delta.

After Phase A is merged into `safe-core`, Phase B is rebased/retargeted without force-moving a shared reviewed branch unless explicitly approved.

`main` is not modified by Phase B development.

## 17. Phase B exit criteria

Phase B is complete only when all of the following are true:

- Model Management is backed by real local inventory, not placeholders;
- local GGUF import is staged, verified and atomically committed;
- trusted SHA verification is distinguished from unanchored computed hashes;
- active model switching is atomic and blocked while the model service runs;
- Local Model API state/start/stop/restart is available through typed RPC;
- Web Workbench state/start/stop/restart is available through the same shared runtime adapter used by legacy flows;
- service stop/restart cannot target arbitrary processes;
- service log reading is constrained below DataRoot;
- Dashboard shows real active model and service summaries;
- Network Mode is displayed but not silently changed;
- no arbitrary shell/PowerShell RPC exists;
- Windows 2022 and 2025 packaged E2E are green;
- all Phase A and Safe Core regression workflows remain green.

## 18. Non-goals

Phase B deliberately does not implement:

- model download catalog;
- model deletion;
- hot model swap;
- Conversation Test UI;
- prompt presets / Golden Tests;
- RAG / FTS5 / embeddings / rerank / citations;
- benchmark engine;
- full Evidence Center;
- Network Center / proxy settings;
- Settings / About;
- GPU driver or firmware management;
- remote/cloud sync;
- release authorization for the historical physical-machine Install Core path.

Those remain separate later phases so Phase B stays independently testable and reversible.
