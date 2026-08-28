# M-LLM Desktop Workbench Phase B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add native Model Management and Local Services to the verified Phase A desktop, backed by typed authenticated RPC and a shared Safe Core runtime adapter, without introducing a second installer/runtime implementation.

**Architecture:** Phase B stays stacked on `feature/desktop-phase-a@ebd3616016ee2ca3fe30d8c54643c6120e993d3c`. A new tracked `runtime/WorkbenchRuntimeAdapter.psm1` owns model inventory/import/verify/activate and the two fixed service lifecycles (`local-model-api`, `web-workbench`). `runtime/WorkbenchBackend.ps1` exposes only additive allowlisted Phase B RPC methods over the existing authenticated named pipe; C# contracts/client methods and WPF ViewModels remain typed and never parse console text.

**Tech Stack:** .NET 8.0.424, C# 12, WPF/MVVM, System.Text.Json, Windows PowerShell 5.1, Safe Core State/Runtime modules, named pipes, xUnit 2.9.2, GitHub Actions `windows-2022` and `windows-2025`.

**Spec:** `docs/superpowers/specs/2026-08-28-desktop-workbench-phase-b-design.md`

## Global Constraints

- Phase B scope is exactly Model Management + Local Services; no Chat, RAG, Benchmark, full Evidence Center, Network Center, Settings, About, model download catalog, model deletion or hot swap.
- Base RPC protocol remains `1.0`; Phase B availability is discovered through `system.capabilities`.
- New backend RPC methods are exactly: `system.capabilities`, `models.snapshot`, `models.verify`, `models.import`, `models.activate`, `services.snapshot`, `service.start`, `service.stop`, `service.restart`, `service.logs` in addition to the existing Phase A methods.
- No RPC accepts an arbitrary command, script, executable, argument vector, PID, port, destination path or log path. `models.import` accepts one user-selected source file path only; destination is server-controlled.
- Model import accepts local `.gguf` only. A valid GGUF begins with ASCII bytes `GGUF`.
- The built-in `qwen35-4b-q4km` manifest currently has `sha256=null`; it must never report `Sha256Pass` solely from filename/size.
- Model integrity enum is exactly: `Missing`, `StructuralPass`, `Sha256Pass`, `HashComputedUnanchored`, `Failed`, `Unknown`.
- Managed service enum is exactly: `Stopped`, `Starting`, `Running`, `Stopping`, `Degraded`, `Blocked`, `Failed`.
- Managed service IDs are exactly `local-model-api` and `web-workbench`.
- Active model mutation is atomic and forbidden while the owned local model service is running.
- Stop/Restart validates Safe Core process ownership; never kill by caller-provided PID or by port alone.
- Service/model operations do not change Network Mode and do not install missing dependencies. `OFFLINE_CACHE` remains non-networking.
- Desktop remains unelevated; Phase B does not authorize the historical physical-machine Install Core path.
- Existing Phase A, Universal Installer, Safe Core, direct-bootstrap and GUI-preflight gates must remain green.
- Every implementation task uses RED-first TDD and ends in a dedicated commit/checkpoint.

---

## File Structure Locked for Phase B

```text
src/MLLM.Workbench.Contracts/
  Models/ModelSourceKind.cs
  Models/ModelIntegrityState.cs
  Models/ModelDescriptor.cs
  Models/ModelSnapshot.cs
  Models/ModelRequests.cs
  Services/ManagedServiceState.cs
  Services/ServiceDescriptor.cs
  Services/ServicesSnapshot.cs
  Services/ServiceRequests.cs
  Services/ServiceLogTail.cs
  Protocol/BackendCapabilitiesSnapshot.cs
  Snapshots/DashboardSnapshot.cs                 # typed Phase B summary added late
src/MLLM.Workbench.Infrastructure/Backend/
  IWorkbenchBackendClient.cs
  NamedPipeBackendClient.cs
src/MLLM.Workbench.Desktop/
  Pages/Models/ModelManagementPage.xaml
  Pages/Models/ModelManagementPage.xaml.cs
  Pages/Models/ModelManagementPageViewModel.cs
  Pages/Services/LocalServicesPage.xaml
  Pages/Services/LocalServicesPage.xaml.cs
  Pages/Services/LocalServicesPageViewModel.cs
  App.xaml.cs
  Shell/MainWindow.xaml
  Shell/MainWindowViewModel.cs
  Pages/Dashboard/DashboardPage.xaml
  Pages/Dashboard/DashboardPageViewModel.cs
runtime/
  WorkbenchRuntimeAdapter.psm1
  WorkbenchBackend.ps1
Start_M_LLM_Workbench.ps1
ci/package_desktop_phase_a.ps1                  # include whole tracked runtime dir
.github/workflows/desktop-phase-b.yml
tests/contracts/MLLM.Workbench.Contracts.Tests/PhaseBContractSerializationTests.cs
tests/infrastructure/MLLM.Workbench.Infrastructure.Tests/PhaseBBackendClientTests.cs
tests/desktop/MLLM.Workbench.Desktop.Tests/ModelManagementViewModelTests.cs
tests/desktop/MLLM.Workbench.Desktop.Tests/LocalServicesViewModelTests.cs
tests/runtime/Invoke-WorkbenchRuntimeAdapterModelSmoke.ps1
tests/runtime/Invoke-WorkbenchRuntimeAdapterServiceSmoke.ps1
tests/backend/Invoke-WorkbenchBackendPhaseBContractSmoke.ps1
tests/backend/Invoke-WorkbenchBackendPhaseBSnapshotSmoke.ps1
tests/ci/Invoke-DesktopPhaseBSmoke.ps1
```

No SQLite dependency is added in Phase B because model/service authoritative state is filesystem/Safe Core state, not desktop-owned history.

---

### Task 1: Add Phase B typed contracts

**Files:**
- Create all `Models/*`, `Services/*`, and `Protocol/BackendCapabilitiesSnapshot.cs` listed above.
- Test: `tests/contracts/MLLM.Workbench.Contracts.Tests/PhaseBContractSerializationTests.cs`.

**Interfaces:**

```csharp
public enum ModelSourceKind { BuiltIn, Imported }
public enum ModelIntegrityState { Missing, StructuralPass, Sha256Pass, HashComputedUnanchored, Failed, Unknown }
public sealed record ModelDescriptor(string Id, string Role, string DisplayName, ModelSourceKind SourceKind, string? FilePath, string FileName, string Format, string? Quantization, long SizeBytes, long MinimumBytes, string? ExpectedSha256, string? ActualSha256, ModelIntegrityState IntegrityState, bool IsActive, string? ActivationBlockedReason);
public sealed record ModelSnapshot(IReadOnlyList<ModelDescriptor> Models, string? ActiveModelId, string NetworkMode);
public sealed record ModelVerifyRequest(string ModelId, string OperationId);
public sealed record ModelImportRequest(string SourcePath, string? DisplayName, string OperationId);
public sealed record ModelActivateRequest(string ModelId, string OperationId);

public enum ManagedServiceState { Stopped, Starting, Running, Stopping, Degraded, Blocked, Failed }
public sealed record ServiceDescriptor(string ServiceId, string DisplayName, ManagedServiceState State, int? Pid, int? Port, string? BaseUrl, DateTimeOffset? StartedAt, long? UptimeSeconds, string? ModelId, string? ModelPath, string HealthSummary, string? StdoutLog, string? StderrLog, bool CanStart, bool CanStop, bool CanRestart, string? BlockedReason);
public sealed record ServicesSnapshot(IReadOnlyList<ServiceDescriptor> Services, string NetworkMode);
public sealed record ServiceActionRequest(string ServiceId, string OperationId);
public sealed record ServiceLogRequest(string ServiceId, int TailLines);
public sealed record ServiceLogTail(string ServiceId, string? StdoutPath, string? StderrPath, IReadOnlyList<string> StdoutLines, IReadOnlyList<string> StderrLines);
public sealed record BackendCapabilitiesSnapshot(string BackendVersion, IReadOnlyList<string> Methods);
```

- [ ] **Step 1: Write failing serialization tests.** Assert enum names serialize as strings, `sha256=null` remains null, and service/model request `OperationId` round-trips.
- [ ] **Step 2: Run RED.**

```powershell
dotnet test tests/contracts/MLLM.Workbench.Contracts.Tests/MLLM.Workbench.Contracts.Tests.csproj -c Release --filter PhaseBContractSerializationTests
```

Expected: compile FAIL because Phase B types do not exist.

- [ ] **Step 3: Add the exact records/enums above.** Do not change `RpcProtocol.Version` from `1.0`.
- [ ] **Step 4: Run contracts tests + solution build GREEN.**

```powershell
dotnet test tests/contracts/MLLM.Workbench.Contracts.Tests/MLLM.Workbench.Contracts.Tests.csproj -c Release
dotnet build MLLM.Workbench.sln -c Release
```

- [ ] **Step 5: Commit.** `feat: add phase B model and service contracts`

---

### Task 2: Build read-only model inventory and verification in the shared runtime adapter

**Files:**
- Create: `runtime/WorkbenchRuntimeAdapter.psm1`.
- Create: `tests/runtime/Invoke-WorkbenchRuntimeAdapterModelSmoke.ps1`.

**Interfaces produced:**

```powershell
Get-MLLMModelInventory -ProjectRoot <path> -DataRoot <path>
Test-MLLMWorkbenchModel -ProjectRoot <path> -DataRoot <path> -ModelId <id>
Get-MLLMActiveModel -DataRoot <path>
```

**Authoritative paths:**

```text
Built-in local-fast: <DataRoot>\models\Qwen3.5-4B\<canonical_filename>
Managed imports:     <DataRoot>\models\managed\<model-id>\<filename>.gguf
Managed sidecar:     <DataRoot>\models\managed\<model-id>\model.mllm.json
Active pointer:      <DataRoot>\state\active_model.json
```

`Test-MLLMWorkbenchModel` rules are deterministic: missing => `Missing`; first four bytes not `GGUF` => `Failed` with `MODEL_FORMAT_INVALID`; built-in file below manifest `minimum_bytes` => `Failed` with `MODEL_SIZE_INVALID`; hash computed with no expected hash => `HashComputedUnanchored`; expected hash match => `Sha256Pass`; mismatch => `Failed`/`MODEL_HASH_MISMATCH`.

- [ ] **Step 1: Write RED fixture tests** using a test DataRoot and a test manifest with `minimum_bytes=4`; include valid synthetic bytes `GGUF` + payload, bad magic, missing model and an expected-hash match/mismatch pair.
- [ ] **Step 2: Run RED.**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/runtime/Invoke-WorkbenchRuntimeAdapterModelSmoke.ps1
```

Expected: FAIL because `WorkbenchRuntimeAdapter.psm1` is missing.

- [ ] **Step 3: Implement private helpers** `Read-MLLMJsonFile`, `Get-MLLMModelCatalog`, `Get-MLLMManagedModelSidecars`, `Test-MLLMGgufMagic`, `Get-MLLMFileSha256`; export only the three fixed public functions above.
- [ ] **Step 4: Assert production `config/models.json` with `sha256=null` produces `HashComputedUnanchored`, never `Sha256Pass`, when a fixture is mapped to that definition.**
- [ ] **Step 5: Run GREEN and commit.** `feat: add read-only model inventory and verification`

---

### Task 3: Add staged managed-model import and atomic activation

**Files:**
- Modify: `runtime/WorkbenchRuntimeAdapter.psm1`.
- Extend: `tests/runtime/Invoke-WorkbenchRuntimeAdapterModelSmoke.ps1`.

**Interfaces produced:**

```powershell
Import-MLLMManagedModel -ProjectRoot <path> -DataRoot <path> -SourcePath <local.gguf> [-DisplayName <text>]
Set-MLLMActiveModel -ProjectRoot <path> -DataRoot <path> -ModelId <id>
```

Imported IDs are deterministic and server-generated: `imported-` + first 12 lowercase hex characters of the staged file SHA256. Caller never supplies an ID or destination.

Import transaction:
1. require existing regular `.gguf` source;
2. verify GGUF magic;
3. copy to `<DataRoot>\models\.staging\<guid>\model.gguf`;
4. compute SHA256;
5. derive model ID;
6. write sidecar schema `mllm.model.v1` with `id`, `display_name`, `file_name`, `actual_sha256`, `imported_at`;
7. if final model directory exists, require same recorded hash or fail `MODEL_ID_COLLISION`;
8. atomically rename staging directory to `<DataRoot>\models\managed\<id>`;
9. never activate automatically.

Activation writes `<DataRoot>\state\active_model.json` through temp file + same-directory replacement/move. It first verifies the candidate and refuses when local-model service ownership check reports running.

- [ ] **Step 1: Add RED tests** for import success, bad magic, same-content idempotency, collision no-overwrite, failed import preserving active pointer, valid activation, activation failure preserving prior pointer.
- [ ] **Step 2: Run RED.** Expected missing import/activate functions.
- [ ] **Step 3: Implement import transaction and atomic JSON writer.** Never use `Move-Item` to replace a different existing model directory.
- [ ] **Step 4: Implement active pointer read/replace and model-service-running guard.** Guard reads server-owned service state/ownership only; no PID parameter.
- [ ] **Step 5: Run GREEN and commit.** `feat: add atomic model import and activation`

---

### Task 4: Add fixed service snapshot/log boundaries in the runtime adapter

**Files:**
- Modify: `runtime/WorkbenchRuntimeAdapter.psm1`.
- Create: `tests/runtime/Invoke-WorkbenchRuntimeAdapterServiceSmoke.ps1`.

**Interfaces produced:**

```powershell
Get-MLLMWorkbenchServices -ProjectRoot <path> -DataRoot <path> -NetworkMode <mode>
Get-MLLMWorkbenchServiceLogs -DataRoot <path> -ServiceId <local-model-api|web-workbench> -TailLines <1..500>
```

Phase B service metadata lives below `<DataRoot>\state\services\<service-id>.json`; it is metadata only. Running truth is `recorded PID + Test-MLLMRecordedProcess`. Snapshot must return `Stopped` when the record is stale rather than trusting a PID blindly.

`service.logs` resolves paths from the server-owned service record, canonicalizes with `Path.GetFullPath`, and rejects anything outside `<DataRoot>\logs` with `LOG_PATH_OUTSIDE_DATA_ROOT`. Tail count is clamped/rejected outside 1..500.

- [ ] **Step 1: Write RED tests** for exact two service IDs, stale PID => `Stopped`, ownership-failure => not stoppable, log tail 200 lines, traversal/outside path rejection and no caller-supplied log path.
- [ ] **Step 2: Run RED.**
- [ ] **Step 3: Implement descriptor reconstruction and bounded log tail.** Do not mutate service state from snapshot/log reads.
- [ ] **Step 4: Run GREEN and commit.** `feat: add managed service snapshots and safe logs`

---

### Task 5: Move service lifecycle behind the shared adapter and preserve legacy behavior

**Files:**
- Modify: `runtime/WorkbenchRuntimeAdapter.psm1`.
- Modify: `Start_M_LLM_Workbench.ps1`.
- Extend: `tests/runtime/Invoke-WorkbenchRuntimeAdapterServiceSmoke.ps1`.
- Modify/retain: `tests/ci/Invoke-DesktopLauncherFallbackSmoke.ps1`.

**Interfaces produced:**

```powershell
Start-MLLMWorkbenchService -ProjectRoot <path> -DataRoot <path> -NetworkMode <mode> -ServiceId <id>
Stop-MLLMWorkbenchService -ProjectRoot <path> -DataRoot <path> -ServiceId <id>
Restart-MLLMWorkbenchService -ProjectRoot <path> -DataRoot <path> -NetworkMode <mode> -ServiceId <id>
```

Rules:
- `local-model-api` resolves active model first, else built-in `local-fast`, verifies candidate, then calls existing `Start-MLLMLocalModelService`; stop calls existing `Stop-MLLMLocalModelService` only after ownership validation.
- `web-workbench` moves the existing `Start-WorkbenchWeb`/`Stop-WorkbenchWeb` logic out of `Start_M_LLM_Workbench.ps1` into private adapter functions while preserving host/port/log/environment/`/api/health` behavior.
- Restart is `Stop -> assert Stopped -> Start`.
- Missing runtime returns structured blocked state/error (`SERVICE_RUNTIME_MISSING`), never installer/network acquisition.
- `OFFLINE_CACHE` does not issue package/download requests.

For deterministic lifecycle tests, the plain PowerShell test runs inside the adapter module scope and temporarily replaces private core-call wrappers with test-owned process fixtures. These wrappers remain private/unexported and are not RPC-accessible; product exports remain the three fixed service functions above.

- [ ] **Step 1: Add RED tests** for fixed service ID validation, already-running, not-running, ownership refusal, start->running->stop, restart ordering, early-exit, health-timeout and missing runtime blocked semantics.
- [ ] **Step 2: Run RED.**
- [ ] **Step 3: Extract Web logic and local-model wrappers into adapter; change legacy `-StartService/-StopService/-StartWeb/-StopWeb` branches to call the adapter.** Delete the duplicated legacy `Start-WorkbenchWeb` and `Stop-WorkbenchWeb` functions.
- [ ] **Step 4: Run runtime service smoke plus existing launcher regression.**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/runtime/Invoke-WorkbenchRuntimeAdapterServiceSmoke.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/ci/Invoke-DesktopLauncherFallbackSmoke.ps1
```

- [ ] **Step 5: Commit.** `refactor: share model and web service lifecycle`

---

### Task 6: Extend backend allowlist and C# client with typed Phase B RPC

**Files:**
- Modify: `runtime/WorkbenchBackend.ps1`.
- Modify: `src/MLLM.Workbench.Infrastructure/Backend/IWorkbenchBackendClient.cs`.
- Modify: `src/MLLM.Workbench.Infrastructure/Backend/NamedPipeBackendClient.cs`.
- Create: `tests/backend/Invoke-WorkbenchBackendPhaseBContractSmoke.ps1`.
- Create: `tests/backend/Invoke-WorkbenchBackendPhaseBSnapshotSmoke.ps1`.
- Create: `tests/infrastructure/MLLM.Workbench.Infrastructure.Tests/PhaseBBackendClientTests.cs`.

**Typed client additions:**

```csharp
Task<BackendCapabilitiesSnapshot> GetCapabilitiesAsync(CancellationToken ct);
Task<ModelSnapshot> GetModelsAsync(CancellationToken ct);
Task<ModelDescriptor> VerifyModelAsync(ModelVerifyRequest request, CancellationToken ct);
Task<ModelDescriptor> ImportModelAsync(ModelImportRequest request, CancellationToken ct);
Task<ModelDescriptor> ActivateModelAsync(ModelActivateRequest request, CancellationToken ct);
Task<ServicesSnapshot> GetServicesAsync(CancellationToken ct);
Task<ServiceDescriptor> StartServiceAsync(ServiceActionRequest request, CancellationToken ct);
Task<ServiceDescriptor> StopServiceAsync(ServiceActionRequest request, CancellationToken ct);
Task<ServiceDescriptor> RestartServiceAsync(ServiceActionRequest request, CancellationToken ct);
Task<ServiceLogTail> GetServiceLogsAsync(ServiceLogRequest request, CancellationToken ct);
```

Backend maps every method to the runtime adapter. Validate payload server-side: operation ID non-empty; model ID resolves from inventory; service ID in exact allowlist; `TailLines` 1..500; import source exists and is a `.gguf` local file. `system.capabilities` returns backendVersion `phase-b` plus exact additive method list. Handshake protocol remains `1.0`.

- [ ] **Step 1: Write RED static allowlist test** requiring all Phase A+Phase B keys and rejecting names matching `exec|command|shell|script|eval|powershell|pid|process`.
- [ ] **Step 2: Write RED live tests** for capabilities, model snapshot, service snapshot, bad model/service ID and forbidden arbitrary method.
- [ ] **Step 3: Run RED** on Windows workflow or locally under Windows PowerShell 5.1.
- [ ] **Step 4: Import adapter in backend initialization, add exact method handlers, and add typed C# convenience methods.** Do not add a generic public execution service beyond existing `InvokeAsync<T>` transport.
- [ ] **Step 5: Run all Phase A backend tests plus new Phase B tests GREEN and commit.** `feat: expose typed phase B backend RPC`

---

### Task 7: Implement native Model Management page

**Files:**
- Create: `src/MLLM.Workbench.Desktop/Pages/Models/ModelManagementPage.xaml`.
- Create: `src/MLLM.Workbench.Desktop/Pages/Models/ModelManagementPage.xaml.cs`.
- Create: `src/MLLM.Workbench.Desktop/Pages/Models/ModelManagementPageViewModel.cs`.
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/ModelManagementViewModelTests.cs`.
- Modify: `src/MLLM.Workbench.Desktop/App.xaml.cs` for DI.

**ViewModel contract:**
- `ObservableCollection<ModelDescriptor> Models`
- summary properties `ActiveModelDisplay`, `TotalCount`, `StructurallyValidCount`, `TrustedShaCount`, `NetworkMode`, `OperationMessage`, `BackendError`, `IsBusy`
- commands `RefreshCommand`, `VerifyCommand`, `ActivateCommand`
- `ImportAsync(string sourcePath, CancellationToken)` invoked only after `OpenFileDialog` selects `*.gguf`.

A single Phase B mutation semaphore/service at ViewModel scope disables Verify/Import/Activate while one mutation is running. Every mutation generates `Guid.NewGuid().ToString("N")` as `OperationId` and refreshes typed inventory after success.

- [ ] **Step 1: Write RED ViewModel tests** for snapshot mapping, `HashComputedUnanchored` display semantics, import request source path, operation IDs, activation disabled for invalid/running-service candidate, mutation serialization and backend errors.
- [ ] **Step 2: Run RED.**
- [ ] **Step 3: Implement ViewModel and WPF page.** Required AutomationIds: `ModelRefreshButton`, `ModelImportButton`, `ModelVerifyButton`, `ModelActivateButton`, `ModelInventory`.
- [ ] **Step 4: Run Desktop tests + WPF build GREEN and commit.** `feat: add native model management page`

---

### Task 8: Implement native Local Services page

**Files:**
- Create: `src/MLLM.Workbench.Desktop/Pages/Services/LocalServicesPage.xaml`.
- Create: `src/MLLM.Workbench.Desktop/Pages/Services/LocalServicesPage.xaml.cs`.
- Create: `src/MLLM.Workbench.Desktop/Pages/Services/LocalServicesPageViewModel.cs`.
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/LocalServicesViewModelTests.cs`.
- Modify: `src/MLLM.Workbench.Desktop/App.xaml.cs` for DI.

**ViewModel contract:**
- exactly two service cards from `ServicesSnapshot`;
- `SelectedService`, `LogTail`, `NetworkMode`, `OperationMessage`, `BackendError`, `IsBusy`;
- methods `RefreshAsync`, `StartAsync(string serviceId, ...)`, `StopAsync`, `RestartAsync`, `LoadLogsAsync(serviceId, 200, ...)`;
- commands use `CanStart/CanStop/CanRestart` from typed descriptor, not local guesses;
- Copy Endpoint copies only the selected descriptor `BaseUrl`; Open Log Folder validates returned path is under `WorkbenchRuntimeOptions.DataRoot\logs` before `Process.Start("explorer.exe", folder)`.

- [ ] **Step 1: Write RED tests** for exact two cards, command-state mapping, operation ID generation, start/stop/restart delegation, bounded log request, backend `Blocked` vs transport/product error.
- [ ] **Step 2: Run RED.**
- [ ] **Step 3: Implement page and ViewModel.** Required AutomationIds: `ServicesRefreshButton`, `LocalModelServiceCard`, `WebWorkbenchServiceCard`, `ServiceStartButton`, `ServiceStopButton`, `ServiceRestartButton`, `ServiceLogsButton`, `ServiceLogPanel`.
- [ ] **Step 4: Run Desktop tests GREEN and commit.** `feat: add native local services page`

---

### Task 9: Add Phase B navigation and typed Dashboard summaries

**Files:**
- Modify: `src/MLLM.Workbench.Contracts/Snapshots/DashboardSnapshot.cs`.
- Add small summary records under `Contracts/Models` and `Contracts/Services` if required by the Dashboard contract.
- Modify: `runtime/WorkbenchBackend.ps1` dashboard snapshot composition.
- Modify: `src/MLLM.Workbench.Desktop/Shell/MainWindow.xaml`.
- Modify: `src/MLLM.Workbench.Desktop/Shell/MainWindowViewModel.cs`.
- Modify: `src/MLLM.Workbench.Desktop/Pages/Dashboard/DashboardPageViewModel.cs` and `.xaml`.
- Modify: `tests/desktop/.../ShellContractTests.cs`, `DashboardViewModelTests.cs`.

**Dashboard contract becomes:**

```csharp
public sealed record DashboardSnapshot(
    MachineSnapshot Machine,
    string NetworkMode,
    IReadOnlyList<ComponentSnapshot> Components,
    ModelSummary? CurrentModel,
    IReadOnlyList<ServiceSummary> Services);
public sealed record ModelSummary(string Id, string DisplayName, ModelIntegrityState IntegrityState);
public sealed record ServiceSummary(string ServiceId, ManagedServiceState State, string? BaseUrl);
```

- [ ] **Step 1: Change tests first:** Phase B shell must require `ModelNavigation` and `ServicesNavigation`; still forbid Conversation/RAG/Benchmark/Evidence/Settings/About. Dashboard test requires typed active model and exact two service summaries.
- [ ] **Step 2: Run RED** because Phase A shell/contract lacks those fields/routes.
- [ ] **Step 3: Update backend dashboard composition and UI mapping; remove the old `ServiceIds` heuristic from Dashboard ViewModel.**
- [ ] **Step 4: Register both ViewModels in `App.BuildHost`, add DataTemplates/navigation routes, change shell badge text from `Desktop Phase A` to `Desktop Phase B`.
- [ ] **Step 5: Run all Desktop/Contracts/backend tests GREEN and commit.** `feat: integrate models and services into desktop shell`

---

### Task 10: Package Phase B and run Windows 2022/2025 end-to-end gates

**Files:**
- Modify: `ci/package_desktop_phase_a.ps1` to copy the whole tracked `runtime` directory so `WorkbenchRuntimeAdapter.psm1` is always packaged with `WorkbenchBackend.ps1`.
- Modify: `tests/ci/Invoke-DesktopPackageSmoke.ps1` to require the adapter.
- Create: `tests/ci/Invoke-DesktopPhaseBSmoke.ps1`.
- Create: `.github/workflows/desktop-phase-b.yml`.

**Phase B packaged E2E sequence:**
1. build the existing self-contained `win-x64` ZIP;
2. verify ZIP SHA256;
3. extract under a path containing spaces;
4. verify pre-materialized Safe Core + `runtime/WorkbenchRuntimeAdapter.psm1`;
5. run Desktop `--smoke`/authenticated handshake;
6. assert `system.capabilities` contains every Phase B method;
7. use temp DataRoot and synthetic local GGUF to run import -> verify -> activate through the real named-pipe client;
8. load `services.snapshot` and assert exact two service IDs;
9. exercise deterministic adapter service lifecycle test-owned fixture separately, then assert packaged RPC missing-runtime path returns structured `Blocked` rather than installing anything;
10. load Dashboard and assert active model + service summaries;
11. verify `OFFLINE_CACHE` remained unchanged and no package/download operation was invoked;
12. verify ProgramData installer state/current pointer fingerprints are unchanged by read-only/model/service test paths;
13. verify launcher default Desktop, `--legacy`, and existing operational switches keep Phase A behavior.

`desktop-phase-b.yml` matrix is `[windows-2022, windows-2025]` and runs, in order:

```text
Contracts tests
Phase A named-pipe tests
Phase A backend contract/snapshot smoke
Phase B runtime model smoke
Phase B runtime service smoke
Phase B backend contract/snapshot smoke
All Desktop ViewModel tests
WPF Shell contract tests
Installer CLI regression
Installer delegation tests
Launcher fallback regression
Self-contained package smoke
Phase A E2E smoke
Phase B E2E smoke
```

- [ ] **Step 1: Add workflow/E2E references before the E2E script/packaging change and confirm RED on both Windows runners.** Expected failure: missing Phase B E2E/adapter package contract.
- [ ] **Step 2: Implement packaging inclusion and E2E.** Do not upload Actions artifacts/cache; preserve existing billing guard policy.
- [ ] **Step 3: Require final markers:**

```text
PHASE_B_CONTRACTS=PASS
PHASE_B_MODEL_ADAPTER=PASS
PHASE_B_SERVICE_ADAPTER=PASS
PHASE_B_BACKEND=PASS
PHASE_B_MODELS_UI=PASS
PHASE_B_SERVICES_UI=PASS
DESKTOP_PHASE_B_E2E=PASS
```

- [ ] **Step 4: Run fresh `feature/desktop-phase-b` Windows 2022/2025 workflow to completion.** Both jobs must be `completed/success`; no partial-green acceptance.
- [ ] **Step 5: Run/review the existing Phase A and Safe Core PR-triggered workflows against the Phase B head.** `safe-core-ci`, direct bootstrap, GUI preflight, Universal Installer CI/E2E, engine/activation/evidence/seed and Desktop Phase A must all remain green.
- [ ] **Step 6: Update the Phase B spec/status with exact verified head SHA and workflow IDs; create a Draft stacked PR targeting `feature/desktop-phase-a` while PR #2 is unmerged.** Do not merge or retarget to `safe-core` without a separate integration decision.
- [ ] **Step 7: Commit/checkpoint.** `test: complete desktop phase B acceptance`

---

## Plan Self-Review Result

- **Spec coverage:** Model inventory/verify/import/activate, exact service lifecycle/logs, capability discovery, dashboard integration, legacy reuse, package E2E, Windows matrix and regression gates each map to a task above.
- **No placeholders:** No TBD/TODO or unspecified later implementation steps remain in Phase B scope.
- **Type consistency:** C# request/response names in Tasks 1, 6, 7 and 8 match exactly; RPC method names match the approved spec; protocol stays `1.0`.
- **Scope:** Network mutation, Evidence catalog, Chat, RAG, Benchmark, Settings/About, model download/delete/hot swap remain outside this plan.
