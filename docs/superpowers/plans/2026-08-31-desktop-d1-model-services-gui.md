# Desktop D1 Model & Services GUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the native WPF Model Management and Local Services product surfaces using the already-verified Phase B backend, wire both routes into the shell, and add installed-package navigation smoke coverage.

**Architecture:** Reuse the existing typed `IWorkbenchBackendClient` and Phase B RPC allowlist. Model Management keeps the existing `ModelManagementPageViewModel` as its behavior owner; Local Services gets one focused ViewModel that consumes only typed service methods. The shell receives two new routes and the Release smoke is extended to exercise real installed navigation through both pages.

**Tech Stack:** .NET 8, WPF, MVVM, xUnit, Windows PowerShell 5.1 Safe Core backend, GitHub Actions Windows Server 2022/2025.

**Spec:** `docs/superpowers/specs/2026-08-31-desktop-d1-model-services-gui-design.md`

## Global Constraints

- Baseline branch is `feature/knowledge-phase-c`; do not implement on `main`/`master`.
- Preserve the current named-pipe authentication and explicit backend method allowlist.
- Do not expose arbitrary PowerShell, command, script, executable, PID, port, destination path, or log path input.
- Do not add drivers, firmware, DISM, PNPUTIL, scheduled-task, registry, or system-wide Python mutation from the Desktop.
- Model import remains local `.gguf` only and does not auto-activate.
- Service Start/Stop/Restart uses existing owned-process validation and fixed service IDs only.
- All UI mutations remain asynchronous and refresh authoritative backend state after success.
- Existing C7 Knowledge, Release runtime/web completeness, and Phase B regressions must remain green.

---

### Task 1: Lock D1 shell and page behavior with RED tests

**Files:**
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/ModelManagementShellTests.cs`
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/LocalServicesViewModelTests.cs`
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/D1PageRuntimeLoadTests.cs`
- Modify: `.github/workflows/knowledge-phase-c.yml`

**Interfaces:**
- Consumes: existing `ModelManagementPageViewModel`, `IWorkbenchBackendClient`, `ServiceDescriptor`, `ServicesSnapshot`, `ServiceLogTail`.
- Produces: acceptance requirements that force `ModelManagementPage`, `LocalServicesPageViewModel`, `LocalServicesPage`, and two new shell routes to exist.

- [ ] **Step 1: Write failing shell tests**

Create tests that load `Shell/MainWindow.xaml` and `MainWindowViewModel.cs` source text and assert the product exposes `models` and `services` routes, labels `模型管理` and `本地服务`, and has DataTemplates for `ModelManagementPageViewModel` and `LocalServicesPageViewModel`.

- [ ] **Step 2: Write failing Local Services ViewModel tests**

Use a fake `IWorkbenchBackendClient` to return a deterministic `ServicesSnapshot` with one running local-model API and one stopped Web Workbench. Assert:

```csharp
await vm.RefreshAsync(CancellationToken.None);
Assert.Equal(2, vm.Services.Count);
Assert.Equal("local-model-api", vm.SelectedService!.ServiceId);
Assert.True(vm.CanStopSelected);
Assert.False(vm.CanStartSelected);
```

Then assert Start/Stop/Restart call the corresponding typed client method, preserve fixed service ids, generate non-empty operation ids, and refresh state after mutation. Assert `LoadLogsAsync` calls only `GetServiceLogsAsync(serviceId, boundedTail, ...)` and maps returned stdout/stderr text.

- [ ] **Step 3: Write failing WPF runtime-load tests**

Instantiate each new WPF page on an STA thread and force `UpdateLayout()`. Require no `DispatcherUnhandledException` and verify each page has a non-null `DataContext` when constructed with a ViewModel.

- [ ] **Step 4: Add early D1 CI gates**

Add dedicated workflow steps before Full Desktop regression:

```yaml
- name: D1 model and services shell
  shell: powershell
  run: dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release --filter "ModelManagementShellTests|LocalServicesViewModelTests|D1PageRuntimeLoadTests"
```

- [ ] **Step 5: Run RED on Windows 2022 and 2025**

Expected failure: missing `ModelManagementPage`, `LocalServicesPageViewModel`, `LocalServicesPage`, `models/services` navigation and DataTemplates. Existing earlier gates must remain green.

- [ ] **Step 6: Commit RED tests**

Commit message: `test: lock D1 model and services desktop surface`.

---

### Task 2: Build native Model Management WPF page

**Files:**
- Create: `src/MLLM.Workbench.Desktop/Pages/Models/ModelManagementPage.xaml`
- Create: `src/MLLM.Workbench.Desktop/Pages/Models/ModelManagementPage.xaml.cs`
- Modify: `src/MLLM.Workbench.Desktop/Pages/Models/ModelManagementPageViewModel.cs`

**Interfaces:**
- Consumes: existing `ModelManagementPageViewModel` public inventory/actions and `IWorkbenchBackendClient` typed model operations.
- Produces: `ModelManagementPage` bound to the existing ViewModel, plus any minimal selection/status properties required by the XAML.

- [ ] **Step 1: Inspect existing ViewModel public surface**

Confirm exact property and command names before writing XAML. Do not duplicate model lifecycle logic in code-behind.

- [ ] **Step 2: Implement the page layout**

Create a scroll-safe dark WPF page with:

- title/subtitle and Refresh button;
- active model/network summary cards;
- DataGrid inventory columns for name/id/source/role/format/quantization/size/integrity/active/path;
- selected-model detail panel;
- buttons bound to Import/Verify/Activate commands;
- backend/error text with visible structured failure state.

Use a file picker in code-behind only to select a `.gguf` source and assign the ViewModel import path; all actual import work remains in the ViewModel/backend.

- [ ] **Step 3: Add explicit automation identifiers**

Use stable names/automation ids such as `ModelManagementPageRoot`, `ModelInventoryGrid`, `ImportModelButton`, `VerifyModelButton`, `ActivateModelButton`, `RefreshModelsButton` for runtime and future UI automation gates.

- [ ] **Step 4: Run Model Management tests**

Run:

```powershell
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release --filter "ModelManagementViewModelTests|ModelManagementShellTests|D1PageRuntimeLoadTests"
```

Expected: model page-related assertions pass; Local Services assertions may remain RED until Task 3.

- [ ] **Step 5: Commit**

Commit message: `feat: add native model management page`.

---

### Task 3: Build typed Local Services ViewModel and WPF page

**Files:**
- Create: `src/MLLM.Workbench.Desktop/Pages/Services/LocalServicesPageViewModel.cs`
- Create: `src/MLLM.Workbench.Desktop/Pages/Services/LocalServicesPage.xaml`
- Create: `src/MLLM.Workbench.Desktop/Pages/Services/LocalServicesPage.xaml.cs`

**Interfaces:**
- Consumes: `IWorkbenchBackendClient.GetServicesAsync`, `StartServiceAsync`, `StopServiceAsync`, `RestartServiceAsync`, `GetServiceLogsAsync` and existing typed service contracts.
- Produces: `LocalServicesPageViewModel` with `Services`, `SelectedService`, `RefreshCommand`, `StartCommand`, `StopCommand`, `RestartCommand`, `LoadLogsCommand`, `CopyEndpointCommand`, `LogText`, `LastError`, `IsBusy`, and capability properties.

- [ ] **Step 1: Implement read-only state projection**

`RefreshAsync` fetches `ServicesSnapshot`, replaces the observable collection, preserves selection by `ServiceId` when possible, otherwise selects the first service, then recalculates command capability properties from the selected descriptor.

- [ ] **Step 2: Implement fixed typed service mutations**

For Start/Stop/Restart:

```csharp
var request = new ServiceActionRequest(Guid.NewGuid().ToString("N"), SelectedService.ServiceId);
await _backend.StartServiceAsync(request, cancellationToken);
await RefreshAsync(cancellationToken);
```

Use only the typed selected `ServiceId`; never accept a user-entered PID/port/path.

- [ ] **Step 3: Implement logs and endpoint copy**

Load logs with a bounded tail (default 200, never above backend limit 500), merge stdout/stderr into a clearly labeled read-only text surface, and place only the backend-provided `BaseUrl` on the clipboard. Empty endpoint disables Copy.

- [ ] **Step 4: Implement page layout**

Create a service DataGrid/card surface with state, PID, endpoint, port, model/runtime, health/block reason and command buttons. Add a lower read-only log panel. Use `AutomationProperties.AutomationId` for Start/Stop/Restart/Logs/CopyEndpoint controls.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release --filter "LocalServicesViewModelTests|D1PageRuntimeLoadTests"
```

Expected: all Local Services tests pass.

- [ ] **Step 6: Commit**

Commit message: `feat: add native local services page`.

---

### Task 4: Wire D1 pages into DI, shell navigation, and Dashboard

**Files:**
- Modify: `src/MLLM.Workbench.Desktop/App.xaml.cs`
- Modify: `src/MLLM.Workbench.Desktop/Shell/MainWindowViewModel.cs`
- Modify: `src/MLLM.Workbench.Desktop/Shell/MainWindow.xaml`
- Modify: `src/MLLM.Workbench.Desktop/Pages/Dashboard/DashboardPageViewModel.cs`
- Modify: `src/MLLM.Workbench.Desktop/Pages/Dashboard/DashboardPage.xaml`

**Interfaces:**
- Consumes: `ModelManagementPageViewModel`, `LocalServicesPageViewModel`, both new WPF pages.
- Produces: persistent `models` and `services` routes and dashboard quick navigation to those routes.

- [ ] **Step 1: Register ViewModels in DI**

Add singleton registrations for `ModelManagementPageViewModel` and `LocalServicesPageViewModel` in `App.BuildHost`.

- [ ] **Step 2: Extend MainWindowViewModel constructor and routes**

Add `Models` and `Services` properties and commands. The route switch must map exact ids:

```csharp
"models" => Models,
"services" => Services,
```

On navigation, execute each page's Refresh command once using the same pattern as Doctor/Installation/Knowledge.

- [ ] **Step 3: Add persistent navigation items**

Add `模型管理` and `本地服务` to `NavigationItems`. Keep existing four routes unchanged.

- [ ] **Step 4: Add WPF DataTemplates**

Add DataTemplates in `MainWindow.xaml` that map the two ViewModels to their corresponding pages. Do not use code-behind route creation.

- [ ] **Step 5: Extend Dashboard navigation**

Add `OpenModelsCommand` and `OpenServicesCommand`, surface two quick-action buttons, and emit only route ids `models` and `services`.

- [ ] **Step 6: Run shell and full desktop tests**

Run:

```powershell
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release
```

Expected: 0 failures.

- [ ] **Step 7: Commit**

Commit message: `feat: wire model and services navigation`.

---

### Task 5: Extend installed EXE navigation smoke to D1 pages

**Files:**
- Modify: `src/MLLM.Workbench.Desktop/App.xaml.cs`
- Modify: `tests/ci/Invoke-C7ReleasePackageSmoke.ps1`

**Interfaces:**
- Consumes: real installed `MainWindowViewModel` navigation commands and packaged backend.
- Produces: `--smoke-d1-navigation` verification that opens Dashboard, Models, Services, Knowledge and forces dispatcher/layout work before exit.

- [ ] **Step 1: Add installed navigation smoke argument**

Recognize `--smoke-d1-navigation` only as a test mode. Create and show the real `MainWindow`, navigate sequentially to `models`, `services`, and `knowledge`, wait for each page's async Refresh to leave busy state, force `DispatcherPriority.ApplicationIdle`, and fail on any `DispatcherUnhandledException`, backend error, or timeout.

- [ ] **Step 2: Preserve safety network mode in CI**

`Invoke-C7ReleasePackageSmoke.ps1` must set `MLLM_NETWORK_MODE=OFFLINE_CACHE` around installed smoke processes and restore the previous environment afterward. The smoke must never download or install components.

- [ ] **Step 3: Invoke the new smoke from Release gate**

After existing `--smoke` and `--smoke-knowledge`, invoke `--smoke-d1-navigation` with a bounded timeout. Require exit code 0.

- [ ] **Step 4: Run Release workflow**

Expected output includes `D1_NAVIGATION_SMOKE=PASS` and existing `C7_RELEASE_INSTALL_SMOKE=PASS`.

- [ ] **Step 5: Commit**

Commit message: `test: verify installed D1 desktop navigation`.

---

### Task 6: Final D1 dual-platform verification and release package

**Files:**
- No feature-code changes unless a gate reveals a defect.

**Interfaces:**
- Consumes: all D1 implementation.
- Produces: a single verified branch head and a downloadable release artifact.

- [ ] **Step 1: Run `knowledge-phase-c` on Windows 2022 and 2025**

Require success for Safe Core preset inventory, network mode, Knowledge core, all desktop tests, model adapter, service adapter, service lifecycle, typed backend client, and backend allowlist.

- [ ] **Step 2: Run `knowledge-c-release` on Windows 2025**

Require package, install, activation, basic desktop smoke, Knowledge navigation smoke, D1 navigation smoke, runtime/web completeness and artifact upload all success.

- [ ] **Step 3: Verify artifact hashes**

Download the final artifact, extract installer and portable ZIPs, recompute SHA-256, and require exact equality with both sidecars and CI log values.

- [ ] **Step 4: Record D1 completion**

Report final branch head, run ids, test totals and artifact hashes. Only then transition to D2 Conversation & Golden Tests.
