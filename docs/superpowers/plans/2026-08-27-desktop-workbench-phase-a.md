# M-LLM Desktop Workbench Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first production slice of the redesigned M-LLM Windows AI Workbench: a self-contained .NET 8 WPF desktop shell with structured Safe Core IPC, live Dashboard, Doctor and Installation Center pages, privileged installer delegation, and legacy fallback.

**Architecture:** The desktop EXE runs as the normal user and communicates with an unelevated Windows PowerShell 5.1 backend over a session-scoped named pipe. The backend exposes only allowlisted structured methods and reuses existing Safe Core detection/state modules. Mutating installer operations are delegated to the existing Universal Installer transaction path, which performs its own UAC elevation and rollback-safe state machine.

**Tech Stack:** .NET 8 WPF (`net8.0-windows`, `win-x64` self-contained publish), C# 12, MVVM, `Microsoft.Extensions.Hosting`/DI/Logging 8.0.0, System.Text.Json, Windows PowerShell 5.1, named pipes, xUnit 2.9.2, GitHub Actions Windows 2022/2025.

**Spec:** `docs/superpowers/specs/2026-08-27-desktop-workbench-redesign-design.md`

## Global Constraints

- Supported physical OS baseline: Windows 10 22H2 x64 and Windows 11 x64.
- Safe Core backend must continue to run under Windows PowerShell 5.1.
- Desktop publish target is `win-x64` self-contained; target machines must not require a preinstalled .NET 8 Desktop Runtime.
- Desktop normally runs unelevated. Approved installer mutations delegate to the existing Universal Installer UAC transaction; Administrator mode never disables policy checks.
- Safe Core, Universal Installer, rollback, offline mode, evidence, package SHA256, safe extraction and physical-preflight behavior must not regress.
- IPC is a local named pipe with a random session nonce and session token; no TCP listener and no arbitrary PowerShell/script/eval method.
- Component state enum is exactly: `Unknown`, `Pass`, `Running`, `ReadyToInstall`, `RepairAvailable`, `Blocked`, `NotFound`, `DetectionError`, `OperationFailed`.
- Missing optional components are normal product states and must not be shown as application crashes.
- Phase A pages are exactly: Shell, Dashboard, Doctor, Installation Center. Model, Services, Conversation, RAG, Benchmark, Evidence page, Settings page and About page are not implemented in Phase A.
- Dark UI must be usable at 1366x768 and target 1440x900; critical controls require keyboard focus and AutomationId.
- No ViewModel may execute `winget`, `msiexec`, `pnputil`, `dism`, registry mutation, firmware tools, or arbitrary shell commands.
- Every task ends with a fresh test run and commit. Do not merge PR #1 during Phase A development.

---

## File Structure Locked for Phase A

```text
MLLM.Workbench.sln
Directory.Build.props
Directory.Packages.props
src/
  MLLM.Workbench.Contracts/
    MLLM.Workbench.Contracts.csproj
    Protocol/RpcEnvelope.cs
    Protocol/BackendHandshake.cs
    Status/ComponentHealth.cs
    Snapshots/MachineSnapshot.cs
    Snapshots/ComponentSnapshot.cs
    Snapshots/DashboardSnapshot.cs
    Snapshots/DoctorSnapshot.cs
    Snapshots/InstallerSnapshot.cs
    Operations/OperationProgress.cs
    Operations/OperationError.cs
  MLLM.Workbench.Infrastructure/
    MLLM.Workbench.Infrastructure.csproj
    Backend/BackendProcessHost.cs
    Backend/NamedPipeBackendClient.cs
    Backend/BackendClientOptions.cs
    Backend/BackendRpcException.cs
    Installer/PrivilegedInstallerInvoker.cs
    Installer/InstallerProcessRequest.cs
  MLLM.Workbench.Desktop/
    MLLM.Workbench.Desktop.csproj
    App.xaml
    App.xaml.cs
    Shell/MainWindow.xaml
    Shell/MainWindow.xaml.cs
    Shell/MainWindowViewModel.cs
    Shell/NavigationItem.cs
    Themes/Colors.xaml
    Themes/Controls.xaml
    Services/WorkbenchCoordinator.cs
    Pages/Dashboard/DashboardPage.xaml
    Pages/Dashboard/DashboardPage.xaml.cs
    Pages/Dashboard/DashboardPageViewModel.cs
    Pages/Doctor/DoctorPage.xaml
    Pages/Doctor/DoctorPage.xaml.cs
    Pages/Doctor/DoctorPageViewModel.cs
    Pages/Installation/InstallationPage.xaml
    Pages/Installation/InstallationPage.xaml.cs
    Pages/Installation/InstallationPageViewModel.cs
runtime/
  WorkbenchBackend.ps1
installer/
  Start-UniversalInstaller.ps1                 # extended CLI action interface
Start_M_LLM_Workbench.cmd                      # prefer Desktop, legacy fallback
ci/
  package_desktop_phase_a.ps1
tests/
  contracts/MLLM.Workbench.Contracts.Tests/
  infrastructure/MLLM.Workbench.Infrastructure.Tests/
  desktop/MLLM.Workbench.Desktop.Tests/
  backend/Invoke-WorkbenchBackendContractSmoke.ps1
  ci/Invoke-DesktopPhaseASmoke.ps1
.github/workflows/
  desktop-phase-a.yml
```

Phase A intentionally does **not** add SQLite yet. No Phase A page needs persisted desktop-owned history, so the `Microsoft.Data.Sqlite` dependency from the mother design is deferred until the first feature that owns history/metadata.

---

### Task 1: Create the .NET solution and typed Phase A contracts

**Files:**
- Create: `MLLM.Workbench.sln`
- Create: `Directory.Build.props`
- Create: `Directory.Packages.props`
- Create: `src/MLLM.Workbench.Contracts/MLLM.Workbench.Contracts.csproj`
- Create: contract files listed under `src/MLLM.Workbench.Contracts/`
- Create: `tests/contracts/MLLM.Workbench.Contracts.Tests/MLLM.Workbench.Contracts.Tests.csproj`
- Create: `tests/contracts/MLLM.Workbench.Contracts.Tests/ContractSerializationTests.cs`

**Interfaces:**
- Produces: `ComponentHealth`, `RpcRequest`, `RpcResponse`, `BackendHandshakeRequest`, `BackendHandshakeResponse`, `MachineSnapshot`, `ComponentSnapshot`, `DashboardSnapshot`, `DoctorSnapshot`, `InstallerSnapshot`, `OperationProgress`, `OperationError`.
- Contract protocol version: constant string `"1.0"` exposed as `RpcProtocol.Version`.

- [ ] **Step 1: Write the failing contract serialization test**

```csharp
[Fact]
public void DashboardSnapshot_round_trips_with_stable_enum_names()
{
    var input = new DashboardSnapshot(
        new MachineSnapshot("Windows 11", "x64", "CPU", 32.0, ["GPU"], 100.0),
        "OFFLINE_CACHE",
        [new ComponentSnapshot("python", ComponentHealth.ReadyToInstall, "Python not installed", true, "python")],
        null);

    var json = JsonSerializer.Serialize(input, WorkbenchJson.Options);
    var output = JsonSerializer.Deserialize<DashboardSnapshot>(json, WorkbenchJson.Options)!;

    Assert.Equal(ComponentHealth.ReadyToInstall, output.Components[0].Health);
    Assert.Contains("ReadyToInstall", json, StringComparison.Ordinal);
}
```

- [ ] **Step 2: Run the test and verify RED**

Run from repository root:

```powershell
dotnet test tests/contracts/MLLM.Workbench.Contracts.Tests/MLLM.Workbench.Contracts.Tests.csproj -c Release
```

Expected: FAIL because the solution/contracts do not exist.

- [ ] **Step 3: Add solution/build/package files and exact contract types**

`Directory.Build.props`:

```xml
<Project>
  <PropertyGroup>
    <TargetFramework>net8.0-windows</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <LangVersion>12.0</LangVersion>
    <TreatWarningsAsErrors>true</TreatWarningsAsErrors>
  </PropertyGroup>
</Project>
```

`Directory.Packages.props`:

```xml
<Project>
  <PropertyGroup><ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally></PropertyGroup>
  <ItemGroup>
    <PackageVersion Include="Microsoft.Extensions.Hosting" Version="8.0.0" />
    <PackageVersion Include="Microsoft.Extensions.Logging.Abstractions" Version="8.0.0" />
    <PackageVersion Include="Microsoft.NET.Test.Sdk" Version="17.11.1" />
    <PackageVersion Include="xunit" Version="2.9.2" />
    <PackageVersion Include="xunit.runner.visualstudio" Version="2.8.2" />
  </ItemGroup>
</Project>
```

`ComponentHealth.cs`:

```csharp
namespace MLLM.Workbench.Contracts.Status;
public enum ComponentHealth
{
    Unknown,
    Pass,
    Running,
    ReadyToInstall,
    RepairAvailable,
    Blocked,
    NotFound,
    DetectionError,
    OperationFailed
}
```

`RpcEnvelope.cs` defines newline-delimited JSON envelopes with fields `Protocol`, `Type`, `Id`, `Method`, `SessionToken`, `Payload`. `WorkbenchJson.Options` must use `JsonStringEnumConverter` and camelCase naming.

Snapshot records use only immutable init/record properties. `InstallerSnapshot` fields are `RunId`, `VersionId`, `Stage`, `CanResume`, `ActiveVersion`, `LastError`, `EvidenceRoot`.

- [ ] **Step 4: Run contract tests and solution build**

```powershell
dotnet test tests/contracts/MLLM.Workbench.Contracts.Tests/MLLM.Workbench.Contracts.Tests.csproj -c Release
dotnet build MLLM.Workbench.sln -c Release
```

Expected: PASS, zero warnings.

- [ ] **Step 5: Commit**

```bash
git add MLLM.Workbench.sln Directory.Build.props Directory.Packages.props src/MLLM.Workbench.Contracts tests/contracts
git commit -m "feat: add desktop workbench contracts"
```

---

### Task 2: Implement authenticated named-pipe transport and backend handshake

**Files:**
- Create: `src/MLLM.Workbench.Infrastructure/MLLM.Workbench.Infrastructure.csproj`
- Create: `src/MLLM.Workbench.Infrastructure/Backend/BackendClientOptions.cs`
- Create: `src/MLLM.Workbench.Infrastructure/Backend/BackendProcessHost.cs`
- Create: `src/MLLM.Workbench.Infrastructure/Backend/NamedPipeBackendClient.cs`
- Create: `src/MLLM.Workbench.Infrastructure/Backend/BackendRpcException.cs`
- Create: `runtime/WorkbenchBackend.ps1`
- Create: `tests/infrastructure/MLLM.Workbench.Infrastructure.Tests/MLLM.Workbench.Infrastructure.Tests.csproj`
- Create: `tests/infrastructure/MLLM.Workbench.Infrastructure.Tests/NamedPipeHandshakeTests.cs`

**Interfaces:**
- Consumes: `RpcProtocol.Version`, RPC envelopes from Task 1.
- Produces: `BackendProcessHost.StartAsync(CancellationToken)`, `NamedPipeBackendClient.ConnectAsync(CancellationToken)`, `NamedPipeBackendClient.InvokeAsync<TResponse>(string method, object? payload, CancellationToken)`.
- Backend arguments: `-PipeName`, `-SessionToken`, `-ProtocolVersion`, `-ProjectRoot`, `-DataRoot`, `-NetworkMode`.

- [ ] **Step 1: Write a failing real-process handshake test**

The test creates a random pipe suffix and 32-byte random token, launches `powershell.exe -NoProfile -ExecutionPolicy Bypass -File runtime/WorkbenchBackend.ps1 ...`, then asserts:

```csharp
var handshake = await client.ConnectAsync(ct);
Assert.True(handshake.Accepted);
Assert.Equal(RpcProtocol.Version, handshake.Protocol);
Assert.NotEmpty(handshake.BackendVersion);
```

A second client using the same pipe but the wrong token must receive `accepted=false` or disconnect without serving methods.

- [ ] **Step 2: Run test and verify RED**

```powershell
dotnet test tests/infrastructure/MLLM.Workbench.Infrastructure.Tests/MLLM.Workbench.Infrastructure.Tests.csproj -c Release --filter NamedPipeHandshakeTests
```

Expected: FAIL because the bridge/client do not exist.

- [ ] **Step 3: Implement the PowerShell pipe server with an allowlisted protocol**

`WorkbenchBackend.ps1` must:

1. validate `ProtocolVersion -eq '1.0'`;
2. create `PipeSecurity` allowing current-user SID and `S-1-5-32-544` Administrators read/write;
3. create one `NamedPipeServerStream` with a random caller-provided name;
4. use UTF-8 `StreamReader`/`StreamWriter`, one compressed JSON object per line;
5. require the first envelope to be `type=handshake` and require an exact constant-time token comparison;
6. after handshake, accept only methods in a hashtable named `$MethodTable`;
7. never expose an `exec`, `command`, `script`, `eval`, `shell`, or raw PowerShell method;
8. return protocol error code `METHOD_NOT_FOUND` for non-allowlisted names.

Initial `$MethodTable` contains only `system.ping`, returning `{ status='PASS'; backendVersion='phase-a' }`.

- [ ] **Step 4: Implement C# process host/client**

`BackendProcessHost` generates pipe name `mllm-workbench-<pid>-<16hex>` and 32 random bytes encoded Base64Url for the token, starts Windows PowerShell hidden with argument-safe `ProcessStartInfo.ArgumentList`, and owns process lifetime.

`NamedPipeBackendClient` uses `NamedPipeClientStream('.', pipeName, PipeDirection.InOut, PipeOptions.Asynchronous)` and a `SemaphoreSlim(1,1)` so one request is in flight per Phase A connection. It must never log the session token.

- [ ] **Step 5: Run handshake tests on both normal and wrong-token paths**

```powershell
dotnet test tests/infrastructure/MLLM.Workbench.Infrastructure.Tests/MLLM.Workbench.Infrastructure.Tests.csproj -c Release
```

Expected: PASS.

- [ ] **Step 6: Add a PowerShell static protocol contract smoke**

Create `tests/backend/Invoke-WorkbenchBackendContractSmoke.ps1`. Parse the backend source and fail if the method table contains any forbidden method name matching:

```powershell
'exec|command|script|eval|shell|powershell'
```

Also assert literal presence of `system.ping` and protocol `1.0`.

- [ ] **Step 7: Commit**

```bash
git add src/MLLM.Workbench.Infrastructure runtime tests/infrastructure tests/backend
git commit -m "feat: add authenticated Safe Core pipe bridge"
```

---

### Task 3: Expose live read-only Dashboard, Doctor and Installer snapshots

**Files:**
- Modify: `runtime/WorkbenchBackend.ps1`
- Create: `tests/backend/Invoke-WorkbenchBackendSnapshotSmoke.ps1`
- Create: `tests/infrastructure/MLLM.Workbench.Infrastructure.Tests/BackendSnapshotTests.cs`

**Interfaces:**
- Produces RPC methods: `dashboard.snapshot`, `doctor.snapshot`, `installer.snapshot`.
- No mutating RPC methods are added in this task.

- [ ] **Step 1: Write failing snapshot tests**

The PowerShell smoke starts the backend with a temporary `DataRoot` and `OFFLINE_CACHE`, then requests all three snapshot methods. Assert:

- Dashboard has machine OS/architecture/RAM, `networkMode=OFFLINE_CACHE`, and at least the task IDs `llama-cpp`, `local-api`, `modelscope`, `python`, `qwen35-4b`, `web-workbench`.
- Doctor component entries contain normalized `health` values only from the locked enum.
- Installer snapshot reads state without changing state-file SHA256.

- [ ] **Step 2: Run and verify RED**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/backend/Invoke-WorkbenchBackendSnapshotSmoke.ps1
```

Expected: FAIL with `METHOD_NOT_FOUND`.

- [ ] **Step 3: Implement Safe Core snapshot loading**

At backend startup:

```powershell
& (Join-Path $ProjectRoot 'Bootstrap_SafeCore.ps1') -ProjectRoot $ProjectRoot | Out-Null
Import-Module (Join-Path $ProjectRoot 'gui\GuiAdapter.psm1') -Force -ErrorAction Stop
Import-Module (Join-Path $ProjectRoot 'installer\InstallerPaths.psm1') -Force -ErrorAction Stop
Import-Module (Join-Path $ProjectRoot 'installer\InstallerState.psm1') -Force -ErrorAction Stop
```

`dashboard.snapshot` calls the already-verified:

```powershell
Get-MLLMGuiSnapshot -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode $NetworkMode
```

It derives component health using this exact normalization:

```text
PASS -> Pass
RUNNING -> Running
READY_TO_INSTALL -> ReadyToInstall
REPAIR_AVAILABLE -> RepairAvailable
BLOCKED -> Blocked
NOT_FOUND -> NotFound
FAILED + summary starts with "Detection failed" -> DetectionError
FAILED otherwise -> OperationFailed
anything else -> Unknown
```

Machine data is read-only OS data: `Environment.OSVersion`, `PROCESSOR_ARCHITECTURE`, `Win32_Processor.Name`, `Win32_ComputerSystem.TotalPhysicalMemory`, `Win32_VideoController.Name`, fixed-disk free bytes. Component truth still comes only from `Get-MLLMGuiSnapshot`.

`doctor.snapshot` returns the normalized component list plus `snapshot_errors`. Any non-empty `snapshot_errors` becomes RPC error `BACKEND_DETECTION_ERROR` and is **not** converted to component health.

`installer.snapshot` reads `Get-MLLMInstallerPaths`, `Read-MLLMInstallerState`, and current-version pointer. It does not call `Set-MLLMInstallerStage`, acquisition, activation or evidence mutation functions.

- [ ] **Step 4: Add C# typed snapshot calls and tests**

Add methods to `NamedPipeBackendClient` extension/service layer:

```csharp
Task<DashboardSnapshot> GetDashboardAsync(CancellationToken ct);
Task<DoctorSnapshot> GetDoctorAsync(CancellationToken ct);
Task<InstallerSnapshot> GetInstallerAsync(CancellationToken ct);
```

Deserialize only into Task 1 contract types.

- [ ] **Step 5: Run snapshot tests and existing GUI preflight**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/backend/Invoke-WorkbenchBackendSnapshotSmoke.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File M_LLM_GUI_PREFLIGHT.ps1 -DataRoot "$env:TEMP\MLLM_PHASE_A_GUI_PREFLIGHT" -NetworkMode OFFLINE_CACHE
```

Expected: both PASS and GUI preflight reports `snapshot_errors=0`.

- [ ] **Step 6: Commit**

```bash
git add runtime tests/backend tests/infrastructure src/MLLM.Workbench.Infrastructure
git commit -m "feat: expose typed Safe Core snapshots"
```

---

### Task 4: Build the dark WPF Shell, navigation and application host

**Files:**
- Create: `src/MLLM.Workbench.Desktop/MLLM.Workbench.Desktop.csproj`
- Create: `src/MLLM.Workbench.Desktop/App.xaml`
- Create: `src/MLLM.Workbench.Desktop/App.xaml.cs`
- Create: `src/MLLM.Workbench.Desktop/Themes/Colors.xaml`
- Create: `src/MLLM.Workbench.Desktop/Themes/Controls.xaml`
- Create: `src/MLLM.Workbench.Desktop/Shell/MainWindow.xaml`
- Create: `src/MLLM.Workbench.Desktop/Shell/MainWindow.xaml.cs`
- Create: `src/MLLM.Workbench.Desktop/Shell/MainWindowViewModel.cs`
- Create: `src/MLLM.Workbench.Desktop/Shell/NavigationItem.cs`
- Create: `src/MLLM.Workbench.Desktop/Services/WorkbenchCoordinator.cs`
- Create initial page shells for Dashboard/Doctor/Installation.
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj`
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/ShellContractTests.cs`

**Interfaces:**
- Consumes: backend host/client from Tasks 2-3.
- Produces routes: `dashboard`, `doctor`, `installation`.

- [ ] **Step 1: Write failing Shell contract test**

The test loads XAML with `XamlReader`, asserts critical names and AutomationIds:

```text
MainNavigation
BackendStatus
NetworkModeStatus
ContentHost
DashboardNavigation
DoctorNavigation
InstallationNavigation
```

It also asserts no navigation item exists yet for later-phase pages.

- [ ] **Step 2: Run and verify RED**

```powershell
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release --filter ShellContractTests
```

Expected: FAIL because Desktop project does not exist.

- [ ] **Step 3: Implement application hosting and DI**

Desktop csproj:

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>WinExe</OutputType>
    <UseWPF>true</UseWPF>
    <RuntimeIdentifier>win-x64</RuntimeIdentifier>
    <SelfContained>true</SelfContained>
    <PublishSingleFile>false</PublishSingleFile>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.Extensions.Hosting" />
    <ProjectReference Include="..\MLLM.Workbench.Contracts\MLLM.Workbench.Contracts.csproj" />
    <ProjectReference Include="..\MLLM.Workbench.Infrastructure\MLLM.Workbench.Infrastructure.csproj" />
  </ItemGroup>
</Project>
```

`App.xaml.cs` creates one Generic Host, registers backend host/client, `WorkbenchCoordinator`, three page ViewModels and `MainWindowViewModel`, starts backend before showing MainWindow, and gracefully stops backend on app exit.

- [ ] **Step 4: Implement approved dark shell**

Use only WPF resources in `Colors.xaml`/`Controls.xaml`: navy window background, left persistent rail, card backgrounds, text/status brushes. Do not add third-party UI libraries in Phase A.

At 1366x768 the content area must scroll rather than clip. Navigation buttons use visible focus rectangles and AutomationId.

- [ ] **Step 5: Run WPF Shell tests and publish smoke**

```powershell
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release
dotnet publish src/MLLM.Workbench.Desktop/MLLM.Workbench.Desktop.csproj -c Release -r win-x64 --self-contained true -o "$env:TEMP\mllm-phase-a-publish"
```

Expected: `MLLM.Workbench.Desktop.exe` exists and no .NET runtime prerequisite is emitted by the package.

- [ ] **Step 6: Commit**

```bash
git add src/MLLM.Workbench.Desktop tests/desktop MLLM.Workbench.sln
git commit -m "feat: add desktop workbench shell"
```

---

### Task 5: Implement live Dashboard page

**Files:**
- Modify: `src/MLLM.Workbench.Desktop/Pages/Dashboard/DashboardPage.xaml`
- Modify/Create: `DashboardPage.xaml.cs`
- Create: `DashboardPageViewModel.cs`
- Modify: `WorkbenchCoordinator.cs`
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/DashboardViewModelTests.cs`

**Interfaces:**
- Consumes: `GetDashboardAsync`.
- Produces commands: `RefreshCommand`, `OpenDoctorCommand`, `OpenInstallationCommand`.

- [ ] **Step 1: Write failing ViewModel test with fake backend**

Given a `DashboardSnapshot` containing one `Pass`, one `ReadyToInstall`, one `Blocked` component, assert the ViewModel exposes exact counts `PassCount=1`, `ReadyCount=1`, `BlockedCount=1`, the machine fields, and `NetworkMode="OFFLINE_CACHE"`.

- [ ] **Step 2: Run and verify RED**

```powershell
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release --filter DashboardViewModelTests
```

- [ ] **Step 3: Implement ViewModel and page**

Page sections match the approved concept without invented data:

- System Overview card
- Component Health summary
- Service rows only when backend component IDs exist
- Current Model card shows `Not installed` if no model is detected
- Quick actions: Run Doctor, Install/Resume, Open legacy Workbench fallback
- Safe Gate card showing network mode and whether installer mutation requires elevation

No placeholder random performance values are allowed.

- [ ] **Step 4: Add load/error behavior**

A backend transport/protocol error sets a top-page `BackendError` banner and does not relabel components as failed. `CancellationToken` from page refresh is respected.

- [ ] **Step 5: Run Dashboard tests**

```powershell
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release --filter Dashboard
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/MLLM.Workbench.Desktop/Pages/Dashboard src/MLLM.Workbench.Desktop/Services tests/desktop
git commit -m "feat: add live desktop dashboard"
```

---

### Task 6: Implement Doctor page with correct health semantics

**Files:**
- Modify: `src/MLLM.Workbench.Desktop/Pages/Doctor/DoctorPage.xaml`
- Create: `DoctorPageViewModel.cs`
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/DoctorViewModelTests.cs`

**Interfaces:**
- Consumes: `GetDoctorAsync`.
- Produces: `RefreshAllCommand` in Phase A. Individual repair execution remains routed to Installation Center rather than directly executing task scripts.

- [ ] **Step 1: Write failing health-semantic tests**

Test at minimum:

```csharp
Assert.Equal("可安装", vm.Rows.Single(x => x.Id == "python").DisplayState);
Assert.False(vm.Rows.Single(x => x.Id == "python").IsProductFault);
Assert.True(vm.Rows.Single(x => x.Id == "backend").IsProductFault);
```

where `python` is `ReadyToInstall` and the backend synthetic row represents `DetectionError`.

- [ ] **Step 2: Run and verify RED**

```powershell
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release --filter DoctorViewModelTests
```

- [ ] **Step 3: Implement Doctor UI**

Table columns: Component, State, Detail, Recommendation. State labels are exactly:

```text
Pass=正常
Running=运行中
ReadyToInstall=可安装
RepairAvailable=可修复
Blocked=受阻
NotFound=未检测到
DetectionError=检测器错误
OperationFailed=操作失败
Unknown=未知
```

`DetectionError` and backend transport errors use a separate product-fault banner. They are never shown as a missing dependency.

- [ ] **Step 4: Run Doctor tests plus existing real GUI snapshot smoke**

```powershell
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release --filter Doctor
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/ci/Invoke-GuiSnapshotSmoke.ps1
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/MLLM.Workbench.Desktop/Pages/Doctor tests/desktop
git commit -m "feat: add typed Doctor page"
```

---

### Task 7: Add a backward-compatible Universal Installer command action interface

**Files:**
- Modify: `installer/Start-UniversalInstaller.ps1`
- Create: `tests/ci/Invoke-UniversalInstallerCliActionSmoke.ps1`
- Modify: `.github/workflows/universal-installer-ci.yml`

**Interfaces:**
- Adds parameters:

```powershell
[ValidateSet('None','InstallResume','RetryAcquisition','ImportOffline','Rollback')][string]$Action='None',
[string]$OfflinePackagePath=''
```

- Existing no-argument GUI behavior remains unchanged.
- UAC forwarding must preserve `Action` and `OfflinePackagePath` through the existing encoded elevation payload.

- [ ] **Step 1: Write failing CLI action smoke**

The smoke must verify:

1. `-Action None -NoGui -NoElevate` preserves existing bootstrap-only behavior.
2. `-Action ImportOffline` without `-OfflinePackagePath` exits nonzero with structured error.
3. An invalid action is rejected by parameter validation.
4. Static source contains forwarding of `Action` and `OfflinePackagePath` into `Restart-MLLMInstallerElevated` arguments.

The smoke must not install a real package on the hosted runner.

- [ ] **Step 2: Run and verify RED**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/ci/Invoke-UniversalInstallerCliActionSmoke.ps1
```

Expected: FAIL because parameters do not exist.

- [ ] **Step 3: Implement command dispatch using the existing `$actions` table**

After `$actions` is fully constructed and before WPF launch:

```powershell
if($Action -ne 'None'){
    switch($Action){
        'InstallResume'     { $result=& $actions.InstallResume }
        'RetryAcquisition'  { $result=& $actions.RetryAcquisition }
        'ImportOffline'     {
            if(-not $OfflinePackagePath){throw 'OfflinePackagePath is required for ImportOffline'}
            $result=& $actions.ImportOffline $OfflinePackagePath
        }
        'Rollback'          { $result=& $actions.Rollback }
    }
    Write-Host ('UNIVERSAL_INSTALLER_ACTION=PASS action='+$Action+' result='+[string]$result)
    exit 0
}
```

Do not duplicate transaction-engine logic in the CLI branch.

- [ ] **Step 4: Update UAC forwarding and tests**

Forward `-Action <value>` whenever non-`None`; forward `-OfflinePackagePath <full path>` whenever present. Existing `Invoke-ElevationArgumentsSmoke.ps1` must continue to pass, including paths with spaces.

- [ ] **Step 5: Run full installer regression**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/ci/Invoke-UniversalInstallerCliActionSmoke.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/ci/Invoke-ElevationArgumentsSmoke.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/ci/Invoke-UniversalInstallerE2E.ps1
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add installer/Start-UniversalInstaller.ps1 tests/ci .github/workflows/universal-installer-ci.yml
git commit -m "feat: add installer action interface"
```

---

### Task 8: Implement Installation Center and privileged delegation

**Files:**
- Create: `src/MLLM.Workbench.Infrastructure/Installer/InstallerProcessRequest.cs`
- Create: `src/MLLM.Workbench.Infrastructure/Installer/PrivilegedInstallerInvoker.cs`
- Modify: `src/MLLM.Workbench.Desktop/Pages/Installation/InstallationPage.xaml`
- Create: `InstallationPageViewModel.cs`
- Create: `tests/infrastructure/MLLM.Workbench.Infrastructure.Tests/PrivilegedInstallerInvokerTests.cs`
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/InstallationViewModelTests.cs`

**Interfaces:**
- `PrivilegedInstallerInvoker.RunAsync(InstallerProcessRequest request, CancellationToken ct)` launches `powershell.exe installer/Start-UniversalInstaller.ps1 -Action ... -NoGui`; the PowerShell installer owns any required UAC elevation.
- ViewModel commands: `InstallResumeCommand`, `RetryAcquisitionCommand`, `ImportOfflineCommand`, `RollbackCommand`, `RefreshCommand`.

- [ ] **Step 1: Write failing argument-safety tests**

Given offline path `C:\Users\Test User\Downloads\M LLM offline.zip`, assert the ProcessStartInfo uses `ArgumentList` entries rather than one concatenated command string and contains the path as one argument.

- [ ] **Step 2: Run and verify RED**

```powershell
dotnet test tests/infrastructure/MLLM.Workbench.Infrastructure.Tests/MLLM.Workbench.Infrastructure.Tests.csproj -c Release --filter PrivilegedInstallerInvokerTests
```

- [ ] **Step 3: Implement installer invoker**

Do not set `Verb=runas` in C#. Launch normal PowerShell; `Start-UniversalInstaller.ps1` retains authority for determining/elevating the mutation. This keeps UAC state forwarding in one tested place.

Capture the non-elevated bootstrap process exit code and then refresh `installer.snapshot` on a timer every 750 ms for up to 30 seconds. If the state changes to a new run/stage, the UI displays live progress; if UAC is cancelled, return a non-crashing `OperationError` with code `ELEVATION_CANCELLED_OR_NOT_STARTED`.

- [ ] **Step 4: Implement Installation Center UI**

Display real `InstallerSnapshot` fields: version, stage, active version, can-resume, last error, evidence root. Component table is the same typed health list from Doctor, not a second detector.

Button rules:

```text
Install / Resume: enabled when ReadyToInstall or resumable installer state exists
Retry Acquisition: enabled when current installer stage is ACQUIRE and last error exists
Import Offline: always available when installer is idle; standard OpenFileDialog ZIP selection
Rollback: enabled only when ActiveVersion and rollback metadata exist
```

- [ ] **Step 5: Run ViewModel/invoker tests and installer regression**

```powershell
dotnet test tests/infrastructure/MLLM.Workbench.Infrastructure.Tests/MLLM.Workbench.Infrastructure.Tests.csproj -c Release --filter Installer
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release --filter Installation
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/ci/Invoke-UniversalInstallerE2E.ps1
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/MLLM.Workbench.Infrastructure/Installer src/MLLM.Workbench.Desktop/Pages/Installation tests
git commit -m "feat: add desktop installation center"
```

---

### Task 9: Add desktop-first launcher with tested legacy fallback

**Files:**
- Modify: `Start_M_LLM_Workbench.cmd`
- Create: `tests/ci/Invoke-DesktopLauncherFallbackSmoke.ps1`

**Interfaces:**
- Version-package expected desktop path: `%~dp0desktop\MLLM.Workbench.Desktop.exe`.
- Legacy fallback remains `%~dp0Start_M_LLM_Workbench.ps1`.
- `--legacy` forces the PowerShell UI.

- [ ] **Step 1: Write failing launcher smoke**

In temporary directories test three cases:

1. desktop EXE placeholder present -> launcher chooses Desktop;
2. desktop absent -> launcher chooses legacy PowerShell;
3. `--legacy` -> legacy chosen even when Desktop exists.

The smoke must inspect a `MLLM_LAUNCHER_TEST=1` dry-run marker rather than executing a fake EXE.

- [ ] **Step 2: Run and verify RED**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/ci/Invoke-DesktopLauncherFallbackSmoke.ps1
```

- [ ] **Step 3: Implement launcher selection without breaking existing arguments**

At the start of `Start_M_LLM_Workbench.cmd`, parse only `--legacy` specially. In normal mode, if desktop EXE exists, start it and return its exit code. If absent, preserve the existing PowerShell argument parser exactly.

Test-only `MLLM_LAUNCHER_TEST=1` prints one of:

```text
MLLM_LAUNCH_TARGET=DESKTOP
MLLM_LAUNCH_TARGET=LEGACY
```

and exits without launching.

- [ ] **Step 4: Run new and old launcher smokes**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/ci/Invoke-DesktopLauncherFallbackSmoke.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/ci/Invoke-ColdEntrypointSmoke.ps1
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Start_M_LLM_Workbench.cmd tests/ci/Invoke-DesktopLauncherFallbackSmoke.ps1
git commit -m "feat: prefer desktop workbench with legacy fallback"
```

---

### Task 10: Package a self-contained Phase A desktop version

**Files:**
- Create: `ci/package_desktop_phase_a.ps1`
- Create: `tests/ci/Invoke-DesktopPackageSmoke.ps1`
- Modify: `.gitignore` only if necessary for `artifacts/` local outputs; do not commit built binaries.

**Interfaces:**
- Produces local package `artifacts/MLLM_WORKBENCH_DESKTOP_PHASE_A_win-x64.zip` and adjacent `.sha256`.
- Package layout:

```text
desktop/MLLM.Workbench.Desktop.exe
runtime/WorkbenchBackend.ps1
Bootstrap_SafeCore.ps1
ci/overlay/*.b64
installer/*
config/*
Start_M_LLM_Workbench.cmd
Start_M_LLM_Workbench.ps1
```

- [ ] **Step 1: Write failing package smoke**

The smoke invokes packaging into `$env:TEMP`, opens the ZIP, asserts the exact mandatory paths above, extracts it into a path containing spaces, and verifies:

- Desktop EXE launches with test argument `--smoke` and exits 0 without showing a window;
- backend handshake runs;
- launcher dry-run selects Desktop;
- SHA256 file matches the ZIP.

- [ ] **Step 2: Run and verify RED**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/ci/Invoke-DesktopPackageSmoke.ps1
```

- [ ] **Step 3: Add Desktop `--smoke` startup path**

`App.xaml.cs` recognizes only `--smoke`: start DI host, start backend, request `system.ping`, stop backend, exit `0`. This path must not show MainWindow and must not mutate installer state.

- [ ] **Step 4: Implement packaging script**

Publish:

```powershell
dotnet publish src/MLLM.Workbench.Desktop/MLLM.Workbench.Desktop.csproj -c Release -r win-x64 --self-contained true -o $publishRoot
```

Copy only runtime dependencies and existing Safe Core source required for raw bootstrap. Create ZIP with `Compress-Archive`; write lowercase SHA256 with `Get-FileHash`.

The existing 89.9 KB `M_LLM_UNIVERSAL_INSTALLER_FULL.cmd` remains a foundation seed in Phase A. Do **not** embed the self-contained .NET desktop payload into that CMD until package-size/servicing behavior is evaluated separately.

- [ ] **Step 5: Run package smoke**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/ci/Invoke-DesktopPackageSmoke.ps1
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ci/package_desktop_phase_a.ps1 tests/ci/Invoke-DesktopPackageSmoke.ps1 src/MLLM.Workbench.Desktop/App.xaml.cs
git commit -m "build: package self-contained desktop phase A"
```

---

### Task 11: Add Windows 2022/2025 Phase A CI and preserve all existing Safe Core gates

**Files:**
- Create: `.github/workflows/desktop-phase-a.yml`
- Create: `tests/ci/Invoke-DesktopPhaseASmoke.ps1`
- Modify: `docs/SAFE_CORE_STATUS.md`
- Create: `docs/DESKTOP_PHASE_A_STATUS.md`

**Interfaces:**
- CI matrix: `windows-2022`, `windows-2025`.
- No artifact upload in the workflow; package is built and tested locally in runner workspace to preserve the repository billing guard.

- [ ] **Step 1: Add failing workflow/static status gate**

`desktop-phase-a.yml` jobs must contain these exact named steps:

```text
.NET 8 identity
Contracts tests
Infrastructure pipe tests
Backend PS5.1 contract smoke
Backend live snapshot smoke
Desktop ViewModel tests
WPF shell load smoke
Installer CLI action regression
Desktop launcher fallback smoke
Self-contained package smoke
Phase A end-to-end smoke
```

Before implementation is complete, the E2E step should fail because `Invoke-DesktopPhaseASmoke.ps1` is missing.

- [ ] **Step 2: Add Phase A end-to-end smoke**

The smoke must execute from a directory path containing spaces and:

1. bootstrap raw Safe Core;
2. run Desktop `--smoke`;
3. verify named-pipe handshake;
4. obtain Dashboard/Doctor/Installer snapshots;
5. assert GUI preflight still reports `snapshot_errors=0`;
6. run launcher target dry-run;
7. verify installer state SHA is unchanged by read-only Desktop smoke;
8. print exactly:

```text
DESKTOP_PHASE_A_E2E=PASS dashboard=PASS doctor=PASS installer=PASS pipe=PASS fallback=PASS
```

- [ ] **Step 3: Run local equivalent tests**

```powershell
dotnet test MLLM.Workbench.sln -c Release
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/backend/Invoke-WorkbenchBackendContractSmoke.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/backend/Invoke-WorkbenchBackendSnapshotSmoke.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/ci/Invoke-DesktopPhaseASmoke.ps1
```

Expected: PASS.

- [ ] **Step 4: Push and verify fresh GitHub Actions**

Required fresh successes on the same commit:

- `desktop-phase-a` Windows 2022
- `desktop-phase-a` Windows 2025
- existing `safe-core-ci`
- existing `universal-installer-ci`
- existing `universal-installer-e2e`
- existing `universal-seed-ci`
- existing `gui-preflight-entrypoint`

Do not claim Phase A complete from an older commit's CI.

- [ ] **Step 5: Write status checkpoint**

`docs/DESKTOP_PHASE_A_STATUS.md` records:

- final commit SHA
- protocol version
- Desktop publish RID/self-contained status
- workflow run IDs
- exact PASS/known-limit list
- physical-machine validation status as `PENDING` until real Win10/Win11 evidence exists
- explicit statement that later pages are not yet implemented

Update `docs/SAFE_CORE_STATUS.md` only to point to the new Desktop checkpoint; do not rewrite historical Safe Core evidence.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/desktop-phase-a.yml tests/ci/Invoke-DesktopPhaseASmoke.ps1 docs/DESKTOP_PHASE_A_STATUS.md docs/SAFE_CORE_STATUS.md
git commit -m "ci: gate desktop workbench phase A"
```

---

## Final Phase A Verification Checklist

Run against the exact final commit:

```powershell
dotnet test MLLM.Workbench.sln -c Release
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/backend/Invoke-WorkbenchBackendContractSmoke.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/backend/Invoke-WorkbenchBackendSnapshotSmoke.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/ci/Invoke-UniversalInstallerCliActionSmoke.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/ci/Invoke-DesktopLauncherFallbackSmoke.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/ci/Invoke-DesktopPackageSmoke.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/ci/Invoke-DesktopPhaseASmoke.ps1
```

Then verify fresh GitHub Actions conclusions for both Windows runner generations and all existing Safe Core/Universal Installer gates.

Phase A is **not** complete if any of the following is true:

- Dashboard/Doctor/Installation Center uses mock or placeholder data in production path.
- Desktop requires a preinstalled .NET 8 runtime.
- any ViewModel shells out to installation tools directly.
- backend exposes arbitrary execution.
- read-only Desktop smoke changes installer state.
- Universal Installer UAC/rollback tests regress.
- legacy fallback is removed.
- physical compatibility is claimed without physical evidence.
