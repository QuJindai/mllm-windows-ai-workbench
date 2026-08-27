# M-LLM Windows AI Workbench Desktop Redesign

Date: 2026-08-27  
Status: DESIGN FOR REVIEW  
Branch: `safe-core`  
Architecture baseline: `.NET 8 WPF desktop EXE + existing PowerShell 5.1 Safe Core backend`

## 1. Goal

Rebuild the post-install M-LLM Windows AI Workbench as a maintainable native Windows desktop application matching the approved dark workbench UI direction, while preserving the already-verified Universal Installer and Safe Core behavior.

The redesign must not replace or weaken the current Safe Core installation, rollback, evidence, bootstrap, Doctor, package-validation, or offline safety mechanisms. The new desktop application becomes the primary user interface; PowerShell 5.1 becomes a backend execution layer rather than the owner of complex UI.

Primary supported platforms:

- Windows 10 22H2 x64
- Windows 11 x64
- Windows PowerShell 5.1 remains supported for Safe Core backend execution
- .NET 8 Desktop Runtime is the primary desktop runtime

## 2. Product split

The product is split into four independently testable layers.

### 2.1 Universal Installer

Existing `M_LLM_UNIVERSAL_INSTALLER_FULL.cmd` and `installer/*` remain responsible for:

- bootstrap and elevation
- install paths
- resumable state
- multi-source acquisition
- package SHA256 validation
- safe extraction and stage validation
- versioned installation
- atomic activation
- rollback
- evidence packaging

The desktop redesign must consume this installation state; it must not duplicate installer transaction logic.

### 2.2 Desktop application

New project: `src/MLLM.Workbench.Desktop/`

Responsibilities:

- navigation and page lifecycle
- ViewModels and command state
- presentation of machine, component, model, service, benchmark, RAG and evidence data
- local settings and user preferences
- interaction with the Safe Core backend through typed contracts
- local-only user experience by default

Technology baseline:

- .NET 8
- WPF
- MVVM
- Microsoft.Extensions.Hosting / DependencyInjection / Logging
- Microsoft.Data.Sqlite for desktop history/metadata that is not authoritative installer state

The desktop layer must not call `winget`, `msiexec`, `pnputil`, `dism`, registry mutation, firmware tools or direct package-install shell commands from ViewModels.

### 2.3 Contracts

New project: `src/MLLM.Workbench.Contracts/`

Typed messages define all traffic between the desktop and Safe Core backend. The desktop must not parse free-form PowerShell console text to determine state.

Core contract groups:

- `MachineSnapshot`
- `ComponentSnapshot`
- `DoctorResult`
- `InstallerSnapshot`
- `ModelDescriptor`
- `ModelRuntimeState`
- `ServiceDescriptor`
- `ServiceState`
- `ConversationRequest/Response`
- `RagIndexState/SearchRequest/SearchResult`
- `BenchmarkRun/BenchmarkResult`
- `EvidenceDescriptor`
- `WorkbenchSettings`
- `OperationProgress`
- `OperationError`

Every operation has a correlation ID and emits structured progress.

### 2.4 Safe Core backend bridge

New entrypoint: `runtime/WorkbenchBackend.ps1`

The bridge runs as a child process started by the desktop application and loads the existing PowerShell 5.1 modules. It exposes only approved commands through a local IPC boundary.

Transport design:

- local named pipe, not a TCP listener
- pipe name is session-scoped and includes a random nonce
- access is limited to the current user and Administrators
- JSON-RPC-style request/response envelopes
- protocol version included in handshake
- backend and desktop exchange a per-session random token before accepting operations
- log stream is separate from request/response payloads

The bridge is not a general-purpose PowerShell execution endpoint. There is no arbitrary `command`, `script`, `eval`, or shell tool exposed over IPC.

## 3. Source-of-truth rules

To avoid the state divergence seen in earlier prototypes:

- installer transaction state remains under ProgramData and is authoritative for install/resume/rollback
- Safe Core detection is authoritative for component runtime status
- service processes are authoritative for service running/stopped state
- model files plus model metadata are authoritative for model inventory
- the desktop SQLite database stores history, UI preferences, benchmark results, conversation history and RAG metadata, but never overrides installer truth
- all page status indicators are derived from structured backend snapshots

## 4. Desktop information architecture

The approved desktop uses a persistent left navigation rail and a shared top command area. The following pages are the target product surface.

### 4.1 Workbench Dashboard

Purpose: operational overview and fastest path to common work.

Contents:

- OS / CPU / RAM / GPU / disk overview
- component health summary
- Local API / llama.cpp Runtime / Web Workbench service state
- current model summary
- Safe Gate mode
- quick actions: Run Doctor, Install Recommended Components, Start Local Chat, Manage Models, Open Evidence
- recent structured logs
- current network mode and offline status

No installation or service command is executed directly by the page; buttons call application services which call typed backend operations.

### 4.2 Installation Center

Purpose: install, repair, upgrade and dependency management.

Contents:

- install root, cache root and free disk space
- component dependency table
- `PASS`, `READY_TO_INSTALL`, `REPAIR_AVAILABLE`, `BLOCKED`, `INSTALLED` states
- recommended next actions
- one-click recommended install
- repair missing dependencies
- retry acquisition
- import offline package
- cache management
- detailed install log

All install/resume/repair operations delegate to the existing transaction engine.

### 4.3 Doctor

Purpose: explain machine and component readiness without ambiguous red errors.

Contents:

- machine-level checks
- Git / Git LFS / Python / ModelScope / llama.cpp / Local API / model / Web Workbench checks
- explicit distinction between `not installed`, `ready to install`, `blocked`, `failed detection` and `running`
- remediation recommendation per item
- rerun individual check and rerun all checks
- evidence generation

`CommandNotFoundException` or backend scope failures are product faults, not component health states, and must be surfaced separately as backend errors.

### 4.4 Model Management

Purpose: manage local model assets and active runtime model.

Contents:

- model inventory
- file path, size, SHA256, GGUF/other format, quantization, backend compatibility
- import local model
- verify model
- delete model
- activate/switch model
- current model detail panel
- recent model events

Model activation is atomic. A failed model switch leaves the previous active model unchanged.

### 4.5 Local Services

Purpose: observe and control local runtime services.

Contents:

- Local API
- llama.cpp Runtime
- Web Workbench
- optional index/background workers when implemented
- state, endpoint, port, startup mode, CPU/RAM, start time
- Start / Stop / Restart / Logs / Copy endpoint

Service controls must identify the exact owned process and cannot terminate arbitrary processes by port alone.

### 4.6 Conversation Test

Purpose: local model functional test and regression workspace.

Contents:

- model selection
- temperature and context controls
- Chat / Compare / Regression modes
- prompt presets
- system prompt
- response metrics: TTFT, tokens/s, total tokens, total latency
- Golden Test execution and summary
- save/export conversation
- citations when RAG is enabled

### 4.7 Knowledge Base (RAG)

Purpose: local document ingestion, indexing, retrieval, reranking and evidence-linked answers.

Pipeline shown in UI:

`Parse -> Chunk -> Embed -> Retrieve -> Rerank -> Citation`

Contents:

- local source list
- import file/folder
- indexing progress
- FTS5 keyword index
- embedding index
- hybrid retrieval
- rerank
- search test panel
- result score and source citation
- index rebuild and delete

Initial implementation is local-only. Source files and derived vectors remain on the machine unless a future feature is explicitly enabled by the user.

### 4.8 Performance Benchmark

Purpose: reproducible local inference comparison.

Metrics:

- TTFT
- decode tokens/s
- full-response latency
- success rate
- CPU/RAM/GPU/VRAM
- temperature when available through a safe read-only provider
- benchmark history

Thermal state is recorded as an environmental variable and is not automatically classified as an algorithm regression.

### 4.9 Evidence and Logs

Purpose: make every important action auditable and recoverable.

Contents:

- evidence package list
- run ID
- operation type
- time
- size
- SHA256
- status
- structured JSON preview
- chronological log viewer
- open folder
- export ZIP
- copy SHA256

Evidence storage remains independent of the desktop SQLite database.

### 4.10 Settings

Purpose: explicit control of networking, storage, model defaults, desktop behavior and safety policy.

Sections:

- network modes: `AUTO_CN_FIRST`, `GLOBAL`, `OFFLINE_CACHE`, `CUSTOM_PROXY`
- proxy address and bypass list
- install/model/cache/evidence paths
- default model/context/backend
- theme/language/start page
- startup behavior
- safe policy indicators

High-risk system operations remain disabled by default and are not silently enabled by selecting Administrator mode.

### 4.11 About

Purpose: product identity and supportability.

Contents:

- desktop version
- Safe Core/backend version
- protocol version
- active installation version
- runtime versions
- supported backends
- build/checkpoint
- recent verification status
- project paths
- license and third-party notices

## 5. Visual system

The generated dark workbench images are the design direction, not a claim that all shown data already exists.

Visual rules:

- dark navy desktop shell
- left persistent navigation
- card-based data layout
- compact status colors with text labels; color alone never conveys state
- native Windows window chrome where practical
- Chinese primary UI with technical English identifiers preserved where useful
- minimum target: 1440x900
- usable at 1366x768 with scroll/adaptive layout
- 100%, 125%, 150% and 200% DPI support
- keyboard navigation and visible focus states

## 6. Application architecture

Recommended solution layout:

```text
src/
  MLLM.Workbench.Desktop/
    App.xaml
    Shell/
    Pages/
    ViewModels/
    Services/
    Controls/
    Themes/
  MLLM.Workbench.Contracts/
    Rpc/
    Models/
    Operations/
  MLLM.Workbench.Infrastructure/
    BackendBridge/
    Settings/
    Sqlite/
    Logging/
runtime/
  WorkbenchBackend.ps1
installer/
  ...existing Universal Installer modules...
tests/
  desktop/
  contracts/
  backend/
  integration/
```

Desktop page ViewModels depend on interfaces such as:

- `IBackendClient`
- `IDoctorService`
- `IInstallerService`
- `IModelService`
- `IRuntimeService`
- `IRagService`
- `IBenchmarkService`
- `IEvidenceService`

No ViewModel imports PowerShell, starts arbitrary shell commands, or directly edits ProgramData transaction files.

## 7. Operation model

Long-running work uses a common operation state machine:

`Queued -> Running -> WaitingForUser/Blocked -> Succeeded/Failed/Cancelled`

Progress messages contain:

- operation ID
- stage ID
- percentage when meaningful
- human-readable message
- structured details
- evidence/run ID when generated

Closing a page does not cancel an operation. Closing the application requests graceful backend shutdown but does not corrupt installer state. After restart, the desktop reconstructs resumable operations from authoritative state.

## 8. Error handling

Errors are divided into four classes:

1. **Expected product state**: component absent, not configured, offline source unavailable.
2. **Blocked operation**: dependency missing, policy prevents action, insufficient disk, incompatible package.
3. **Recoverable operation failure**: one source failed, model failed verification, service failed to start.
4. **Product defect**: protocol mismatch, backend command missing, malformed response, unhandled exception.

The UI must never present class 1 as an application crash/failure.

Every class 3 or class 4 failure creates structured evidence sufficient for replay or diagnosis.

## 9. Security and safety boundaries

The redesign preserves the Safe Core principles:

- no arbitrary remote command execution
- no arbitrary PowerShell over IPC
- no silent driver installation
- no firmware or boot modification in normal Workbench flows
- no DISM or PNPUTIL from page logic
- package and model integrity validation before activation
- versioned install with rollback
- explicit offline mode
- evidence for privileged or mutating operations

Administrator mode permits approved install operations; it does not remove policy checks.

## 10. Compatibility and migration

Existing Universal Installer remains the supported entry point during migration.

A version package may contain both:

- new desktop application
- legacy PowerShell Workbench fallback

Activation switches the whole version directory. If the desktop fails its post-install launch/bridge check, the new version is not activated or is rolled back.

Existing ProgramData installer state and evidence directories are retained. Desktop settings use a new schema with versioned migrations.

## 11. Testing strategy

### 11.1 Unit tests

- ViewModels
- contract serialization
- settings migrations
- path validation
- model and service state transformations

### 11.2 Contract tests

- desktop/backend handshake
- every RPC request/response
- protocol version mismatch
- cancellation/progress
- malformed backend output

### 11.3 WPF tests

- Shell load
- all 11 page navigation routes
- named controls/automation IDs for critical actions
- command bindings
- DPI/layout smoke
- no direct shell/install commands in ViewModels

### 11.4 Integration tests

Windows 2022 and Windows 2025 CI continue to validate Safe Core, plus:

- desktop starts
- backend child process starts
- named-pipe handshake passes
- Dashboard snapshot loads
- Doctor snapshot loads
- installer state is read without mutation
- offline mode works without external network
- activation/rollback still pass existing E2E

### 11.5 Physical-machine gates

Physical validation is separate from hosted CI:

- Windows 10 22H2 machine
- Windows 11 machine
- Chinese locale / PowerShell 5.1
- administrator and standard-user launch
- GitHub reachable and unreachable networks
- machine with existing/locked old Workbench version
- NVIDIA and CPU-only machines

No claim of universal physical compatibility is made until these gates have evidence.

## 12. Delivery decomposition

The full product is too large to safely implement as one change. Development is divided into independently releasable phases.

### Phase A — Desktop foundation

Scope:

- solution/projects
- dark Shell/navigation/theme
- Contracts project
- named-pipe Safe Core bridge
- structured logging
- Dashboard
- Doctor
- Installation Center
- legacy fallback launch

Exit gate:

- Windows CI starts desktop and backend
- Dashboard/Doctor/Installer pages are live from real structured state
- no placeholder data required for PASS
- existing Universal Installer and Safe Core tests stay green

### Phase B — Models and Services

- Model Management
- Local Services
- model verify/import/activate
- service start/stop/restart/logs

### Phase C — Conversation and Golden Tests

- Conversation Test
- prompt presets
- response metrics
- regression/Golden Test

### Phase D — RAG

- local ingestion
- FTS5
- embeddings
- hybrid retrieval
- rerank
- citations

### Phase E — Benchmark, Evidence, Settings, About

- Performance Benchmark
- Evidence and Logs
- Settings
- About
- polish/accessibility/DPI

## 13. Phase A non-goals

Phase A deliberately does not implement:

- full RAG indexing
- model download catalog
- production benchmark engine
- complex chat UI
- GPU driver management
- firmware/boot/system-driver actions
- remote/cloud sync

These remain later phases so the desktop architecture is proven before broadening scope.

## 14. Acceptance criteria for the redesign

The redesign is accepted only when:

- the primary post-install interface is the .NET 8 WPF desktop app
- the approved dark navigation/page structure is implemented rather than simulated by screenshots
- the desktop uses structured contracts, not console-text scraping
- Safe Core remains independently operable
- installer, rollback, offline and evidence behavior do not regress
- missing optional components are represented as normal product states
- Win10/Win11 physical gates are explicitly tracked
- each development phase leaves a versioned checkpoint and test evidence
