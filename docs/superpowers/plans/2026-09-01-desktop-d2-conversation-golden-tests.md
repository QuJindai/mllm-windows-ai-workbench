# Desktop D2 Conversation & Golden Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a native, loopback-only streaming Conversation Test workspace with honest performance metrics, optional Knowledge grounding, and persistent deterministic Golden Test regression.

**Architecture:** Keep management authority in the existing typed backend and inference on the already-managed local OpenAI-compatible HTTP boundary. A focused Desktop conversation service validates the authoritative service endpoint, streams SSE, optionally builds bounded evidence context through the existing Knowledge service, and returns structured results. A separate atomic JSON catalog owns Golden definitions; the WPF ViewModel composes these services without duplicating model or service lifecycle controls.

**Tech Stack:** .NET 8, WPF, MVVM, `HttpClient`, OpenAI-compatible SSE, `System.Text.Json`, xUnit, Windows PowerShell 5.1 release smoke, GitHub Actions Windows Server 2022/2025.

**Spec:** `docs/superpowers/specs/2026-09-01-desktop-d2-conversation-golden-tests-design.md`

## Global Constraints

- Baseline branch is `feature/knowledge-phase-c` at or after `befce72348ac0003d01a22cf3c64be2d015918dd`; do not implement on `main`/`master`.
- Inference endpoints come only from the authoritative `local-model-api` `ServiceDescriptor`.
- Accept only `http`, an IP loopback host, and an explicit non-default port; reject hostnames including `localhost`, LAN/cloud addresses, redirects, credentials, query strings, and fragments.
- Do not add API-key, endpoint, PID, port, executable, command, model-path, log-path, or destination-path user input.
- Do not auto-start services, auto-activate models, install runtimes, download models, mutate network mode, or enlarge the PowerShell backend allowlist.
- All inference and Golden execution is sequential; one run may be active at a time.
- Knowledge grounding must stop before inference when no evidence is found.
- Token count and tokens/second remain unavailable unless the model server returns `usage.completion_tokens`.
- CI remains deterministic, local-only, and AI-free.
- Existing D1, Knowledge C7, Safe Core, installer, runtime/web completeness, and backend regressions must remain green.

---

### Task 1: Lock and implement the loopback conversation endpoint boundary

**Files:**
- Create: `src/MLLM.Workbench.Desktop/Services/Conversation/ConversationContracts.cs`
- Create: `src/MLLM.Workbench.Desktop/Services/Conversation/LocalConversationEndpoint.cs`
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/LocalConversationEndpointTests.cs`

**Interfaces:**
- Consumes: `MLLM.Workbench.Contracts.Services.ServiceDescriptor`.
- Produces: `ConversationMessage`, `ConversationRequest`, `ConversationDelta`, `ConversationMetrics`, `ConversationRunResult`, `ConversationRuntimeSnapshot`, `LocalConversationEndpoint`.

- [ ] **Step 1: Write the failing endpoint tests**

Before writing the test body, name the production breaks: accepting a hostname/LAN/cloud URL, accepting a default or absent port, retaining credentials/query/fragment, or deriving an endpoint from the wrong service.

Write table-driven tests with literal expectations:

```csharp
[Theory]
[InlineData("http://localhost:8080", "ENDPOINT_NOT_LOOPBACK")]
[InlineData("http://192.168.1.2:8080", "ENDPOINT_NOT_LOOPBACK")]
[InlineData("https://127.0.0.1:8443", "ENDPOINT_SCHEME_INVALID")]
[InlineData("http://127.0.0.1", "ENDPOINT_PORT_REQUIRED")]
[InlineData("file:///C:/model.gguf", "ENDPOINT_SCHEME_INVALID")]
[InlineData("http://user:pass@127.0.0.1:8080", "ENDPOINT_AUTHORITY_INVALID")]
[InlineData("http://127.0.0.1:8080?x=1", "ENDPOINT_AUTHORITY_INVALID")]
public void Unsafe_service_urls_are_rejected(string value, string code)
{
    var error = Assert.Throws<ConversationEndpointException>(
        () => LocalConversationEndpoint.FromService(Service(value)));
    Assert.Equal(code, error.Code);
}

[Theory]
[InlineData("http://127.0.0.1:8080", "http://127.0.0.1:8080/")]
[InlineData("http://127.1.2.3:9090/", "http://127.1.2.3:9090/")]
[InlineData("http://[::1]:8123", "http://[::1]:8123/")]
public void Ip_loopback_with_explicit_port_is_normalized(string value, string expected)
{
    Assert.Equal(expected, LocalConversationEndpoint.FromService(Service(value)).BaseUri.AbsoluteUri);
}
```

Also assert `ServiceId != "local-model-api"`, non-running state, and missing `BaseUrl` fail with literal codes.

- [ ] **Step 2: Run RED**

Run:

```powershell
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release --filter LocalConversationEndpointTests
```

Expected: compile failure because `LocalConversationEndpoint` and conversation contracts do not exist.

- [ ] **Step 3: Implement the minimal contracts and validator**

Define the result types with no WPF dependencies:

```csharp
public enum ConversationRunState { Completed, Cancelled, Failed }

public sealed record ConversationMessage(string Role, string Content);
public sealed record ConversationDelta(string Content);
public sealed record ConversationMetrics(
    TimeSpan? TimeToFirstToken,
    TimeSpan TotalLatency,
    int? CompletionTokens,
    double? TokensPerSecond);

public sealed record ConversationRequest(
    string SystemPrompt,
    string UserPrompt,
    IReadOnlyList<ConversationMessage> History,
    double Temperature,
    int MaxOutputTokens,
    bool UseKnowledge);
```

Implement `LocalConversationEndpoint.FromService(ServiceDescriptor)` with `Uri.TryCreate`, `IPAddress.TryParse`, `IPAddress.IsLoopback`, exact scheme/authority/port checks, normalized `BaseUri`, and stable coded `ConversationEndpointException` failures. Do not resolve DNS.

- [ ] **Step 4: Run GREEN and mutation check**

Re-run the focused tests. Mentally mutate scheme, host, port, service id, and service state checks; at least one named test must fail for every mutation.

- [ ] **Step 5: Commit**

```powershell
git add src/MLLM.Workbench.Desktop/Services/Conversation tests/desktop/MLLM.Workbench.Desktop.Tests/LocalConversationEndpointTests.cs
git commit -m "feat: enforce local conversation endpoint boundary"
```

---

### Task 2: Implement deterministic OpenAI SSE streaming and honest metrics

**Files:**
- Create: `src/MLLM.Workbench.Desktop/Services/Conversation/ILocalConversationClient.cs`
- Create: `src/MLLM.Workbench.Desktop/Services/Conversation/OpenAiSseReader.cs`
- Create: `src/MLLM.Workbench.Desktop/Services/Conversation/LocalOpenAiConversationClient.cs`
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/OpenAiSseReaderTests.cs`
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/LocalConversationRuntimeEndToEndTests.cs`

**Interfaces:**
- Consumes: Task 1 `LocalConversationEndpoint`, `ConversationRequest`, `ConversationDelta`, `ConversationRunResult`.
- Produces: `ILocalConversationClient.StreamAsync(...)`; fixed OpenAI-compatible `/v1/models` capability probe and `/v1/chat/completions` or `/chat/completions` stream path.

- [ ] **Step 1: Write RED parser tests against literal SSE frames**

Name the breaks: lost fragmented frames, accepted malformed JSON, ignored `[DONE]`, wrong choice content, fabricated usage, or content emitted from a non-zero choice.

Test these literal frames through a `MemoryStream`:

```text
data: {"choices":[{"index":0,"delta":{"content":"你"}}]}

data: {"choices":[{"index":0,"delta":{"content":"好"}}]}

data: {"choices":[],"usage":{"completion_tokens":2}}

data: [DONE]

```

Assert deltas are exactly `你`, `好`, completion tokens are exactly `2`, and completion requires `[DONE]` or a clean EOF after at least one valid event. Add malformed JSON and `choices[0].index != 0` failure cases.

- [ ] **Step 2: Write RED real-loopback integration test**

Follow the existing `LocalEmbeddingRuntimeEndToEndTests` TCP server pattern. The deterministic server must:

- accept `GET /v1/models` and return HTTP 200;
- accept exactly one `POST /v1/chat/completions`;
- assert `stream=true`, `stream_options.include_usage=true`, literal model id, temperature, max tokens, and message order;
- emit two delayed SSE chunks, one usage chunk, and `[DONE]`;
- expose request count so the test proves no redirect/fallback duplication.

Assert the final answer, progress deltas, TTFT present, total latency greater than or equal to TTFT, completion tokens `2`, positive tokens/second, and one POST.

- [ ] **Step 3: Run RED**

Run:

```powershell
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release --filter "OpenAiSseReaderTests|LocalConversationRuntimeEndToEndTests"
```

Expected: compile failure because the client and reader do not exist.

- [ ] **Step 4: Implement the SSE reader**

`OpenAiSseReader.ReadAsync` reads UTF-8 lines with cancellation, joins consecutive `data:` lines per event, parses JSON with `JsonDocument`, emits only choice index zero string content, captures only integer `usage.completion_tokens`, and returns a terminal summary. Throw `ConversationProtocolException("STREAM_PROTOCOL_ERROR", ...)` on malformed JSON, invalid types, or a stream with no valid event.

- [ ] **Step 5: Implement the HTTP client**

Create a `SocketsHttpHandler` with:

```csharp
AllowAutoRedirect = false,
UseCookies = false,
AutomaticDecompression = DecompressionMethods.None,
ConnectTimeout = TimeSpan.FromSeconds(10)
```

Probe `/v1/models`; use `/v1/chat/completions` on success. Probe `/models` only when the first probe returns 404; cache the selected relative path by normalized base URI. Reject every other probe failure. Send with `HttpCompletionOption.ResponseHeadersRead`, use a monotonic `Stopwatch`, record TTFT at the first non-empty delta, and compute tokens/second only from server usage and positive post-first-token duration.

Map cancellation to a `ConversationRunResult` with `Cancelled` and the partial answer. Map HTTP/protocol failures to structured `ConversationClientException` without including an unbounded response body.

- [ ] **Step 6: Run GREEN and the full Desktop test project**

```powershell
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release --filter "OpenAiSseReaderTests|LocalConversationRuntimeEndToEndTests|LocalConversationEndpointTests"
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release
```

Expected: 0 failures, no external requests.

- [ ] **Step 7: Commit**

```powershell
git add src/MLLM.Workbench.Desktop/Services/Conversation tests/desktop/MLLM.Workbench.Desktop.Tests/OpenAiSseReaderTests.cs tests/desktop/MLLM.Workbench.Desktop.Tests/LocalConversationRuntimeEndToEndTests.cs
git commit -m "feat: stream local conversation responses"
```

---

### Task 3: Add runtime discovery and evidence-grounded conversation coordination

**Files:**
- Create: `src/MLLM.Workbench.Desktop/Services/Conversation/IConversationTestService.cs`
- Create: `src/MLLM.Workbench.Desktop/Services/Conversation/ConversationTestService.cs`
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/ConversationTestServiceTests.cs`

**Interfaces:**
- Consumes: `IWorkbenchBackendClient`, `ILocalConversationClient`, `IKnowledgeWorkbenchService`, `RagContextBuilder`.
- Produces: `RefreshRuntimeAsync`; `RunAsync` returning answer, metrics, and trusted `IReadOnlyList<RagEvidence>`.

- [ ] **Step 1: Write RED runtime-discovery tests**

Use complete fake `ModelSnapshot` and `ServicesSnapshot` records. Assert the service:

- selects only exact service id `local-model-api`;
- requires `ManagedServiceState.Running` and a valid endpoint;
- returns active model id plus service model id/readiness;
- never invokes Start/Activate methods.

- [ ] **Step 2: Write RED Knowledge-grounding tests**

Use a fake Knowledge service with literal snapshots/hits. Assert:

```csharp
Assert.Equal(KnowledgeSearchMode.Hybrid, knowledge.SearchModes.Single());
Assert.Equal(8, knowledge.Limits.Single());
Assert.Contains("[K1]", client.LastRequest!.SystemPrompt, StringComparison.Ordinal);
Assert.Equal("K1", result.Evidence.Single().CitationId);
```

Add a non-Hybrid-ready snapshot that selects FTS5. Add an empty-hit case that throws `ConversationRunException` with code `NO_EVIDENCE` and leaves the fake client's call count at zero.

- [ ] **Step 3: Run RED**

```powershell
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release --filter ConversationTestServiceTests
```

- [ ] **Step 4: Implement the coordinator**

Validate request literals before external work:

```csharp
if (string.IsNullOrWhiteSpace(request.UserPrompt))
    throw new ConversationRunException("PROMPT_REQUIRED", "User prompt is required.");
if (request.Temperature is < 0d or > 2d)
    throw new ConversationRunException("TEMPERATURE_INVALID", "Temperature must be between 0 and 2.");
if (request.MaxOutputTokens is < 1 or > 8192)
    throw new ConversationRunException("MAX_TOKENS_INVALID", "Maximum output tokens must be between 1 and 8192.");
```

Use fresh typed backend snapshots for each runtime refresh and run. When grounding is enabled, call `GetSnapshotAsync`, select Hybrid only if ready, otherwise FTS5, search with limit eight, build `RagContextBuilder.Build(hits, 8, 12_000)`, and fail before HTTP on no evidence. Construct the grounding instruction and trusted result evidence from the RAG object.

- [ ] **Step 5: Run GREEN**

Run the focused tests and then `KnowledgePageViewModelTests|KnowledgeWorkbenchServiceTests` to prove no Knowledge regression.

- [ ] **Step 6: Commit**

```powershell
git add src/MLLM.Workbench.Desktop/Services/Conversation tests/desktop/MLLM.Workbench.Desktop.Tests/ConversationTestServiceTests.cs
git commit -m "feat: coordinate grounded local conversations"
```

---

### Task 4: Build the atomic Golden Test catalog and evaluator

**Files:**
- Create: `src/MLLM.Workbench.Desktop/Services/Conversation/GoldenTestContracts.cs`
- Create: `src/MLLM.Workbench.Desktop/Services/Conversation/IGoldenTestCatalog.cs`
- Create: `src/MLLM.Workbench.Desktop/Services/Conversation/JsonGoldenTestCatalog.cs`
- Create: `src/MLLM.Workbench.Desktop/Services/Conversation/GoldenTestEvaluator.cs`
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/JsonGoldenTestCatalogTests.cs`
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/GoldenTestEvaluatorTests.cs`

**Interfaces:**
- Consumes: Task 3 `IConversationTestService.RunAsync` and `ConversationRunResult`.
- Produces: `GoldenTestCase`, `GoldenTestResult`, catalog load/upsert/delete, sequential evaluator.

- [ ] **Step 1: Write RED catalog tests**

Use a unique temporary data root. Assert:

- missing file loads an empty schema-version-one catalog;
- upsert writes `conversation/golden-tests.json` and reload preserves every field;
- update keeps the stable id and changes `UpdatedAt`;
- delete removes only the requested id;
- cases load in invariant name/id order;
- malformed JSON throws `GoldenCatalogException("GOLDEN_CATALOG_CORRUPT", ...)` and the original bytes remain unchanged;
- an injected write failure leaves the prior valid catalog readable and removes only the temporary sibling.

- [ ] **Step 2: Write RED evaluator tests**

Name the breaks: missing required fragment, present forbidden fragment, accepted empty response, ignored latency ceiling, HTTP invocation after no evidence, parallel case execution.

Use literal cases and a fake conversation service that tracks current/max concurrency. Assert `maxConcurrency == 1`, case result order equals catalog order, and failure reasons are exact codes: `RESPONSE_EMPTY`, `REQUIRED_TEXT_MISSING`, `FORBIDDEN_TEXT_PRESENT`, `LATENCY_LIMIT_EXCEEDED`, `NO_EVIDENCE`, `RUN_FAILED`, `RUN_CANCELLED`.

- [ ] **Step 3: Run RED**

```powershell
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release --filter "JsonGoldenTestCatalogTests|GoldenTestEvaluatorTests"
```

- [ ] **Step 4: Implement the catalog**

Define the persisted case contract exactly once:

```csharp
public sealed record GoldenTestCase(
    string Id,
    string Name,
    string SystemPrompt,
    string UserPrompt,
    double Temperature,
    int MaxOutputTokens,
    bool UseKnowledge,
    IReadOnlyList<string> MustContain,
    IReadOnlyList<string> MustNotContain,
    long? MaximumTotalLatencyMilliseconds,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt);
```

Use `JsonSerializerOptions` with camelCase (therefore persisted fields `mustContain` and `mustNotContain`) and indented output. Validate schema version, unique non-empty ids, name/prompt, temperature, max tokens, non-empty trimmed fragments, and positive optional latency. Serialize to `<path>.tmp`, flush/close, then `File.Move(temp, path, true)` while holding a `SemaphoreSlim`. On parse/validation failure do not write.

- [ ] **Step 5: Implement the evaluator**

For each case, construct an empty-history `ConversationRequest`, call the service with no delta progress, evaluate non-empty response and case-insensitive required/forbidden fragments, then optional total latency. Stop only on cancellation; ordinary case failures become rows so `Run All` continues sequentially.

- [ ] **Step 6: Run GREEN and restart-persistence mutation check**

Re-run both focused suites. Reopen a new catalog instance from the same root and prove persistence. Mutating atomic replace, schema validation, fragment comparison, or sequential await must fail a named test.

- [ ] **Step 7: Commit**

```powershell
git add src/MLLM.Workbench.Desktop/Services/Conversation tests/desktop/MLLM.Workbench.Desktop.Tests/JsonGoldenTestCatalogTests.cs tests/desktop/MLLM.Workbench.Desktop.Tests/GoldenTestEvaluatorTests.cs
git commit -m "feat: persist and evaluate golden conversations"
```

---

### Task 5: Build the Conversation ViewModel with streaming, cancellation, and Golden commands

**Files:**
- Create: `src/MLLM.Workbench.Desktop/Pages/Conversation/ConversationPageViewModel.cs`
- Create: `src/MLLM.Workbench.Desktop/Pages/Conversation/ConversationTranscriptEntry.cs`
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/ConversationPageViewModelTests.cs`

**Interfaces:**
- Consumes: `IConversationTestService`, `IGoldenTestCatalog`, `GoldenTestEvaluator`, `IEvidenceLauncher`.
- Produces: WPF-bindable state and commands for runtime, transcript, parameters, metrics, evidence, Golden catalog/results.

- [ ] **Step 1: Write RED ViewModel tests**

Assert these observable behaviors through the real ViewModel and focused fakes:

- `RefreshAsync` maps runtime readiness, endpoint, active model, and loads cases;
- blank prompt is rejected without calling the service;
- progress deltas append to one assistant transcript entry in order;
- completed run maps TTFT/latency/token values and trusted evidence;
- unavailable usage displays `Unavailable` rather than an estimate;
- `CancelCommand` cancels the active token and preserves partial assistant text;
- Send and Run All are mutually exclusive;
- Clear removes transcript/evidence/current metrics but not Golden cases;
- Save/Update/Delete call the catalog and refresh stable selection;
- Run Selected/All populate ordered result rows and preserve structured failure codes;
- Open Evidence passes trusted `SourceUri` and `Locator` to `IEvidenceLauncher`.

- [ ] **Step 2: Run RED**

```powershell
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release --filter ConversationPageViewModelTests
```

- [ ] **Step 3: Implement minimal ViewModel state**

Use `ObservableCollection<ConversationTranscriptEntry>`, `ObservableCollection<RagEvidence>`, `ObservableCollection<GoldenTestCase>`, and `ObservableCollection<GoldenTestResult>`. Defaults are temperature `0.2`, max output tokens `512`, history enabled, Knowledge disabled.

Create one `CancellationTokenSource? _activeRun`; every terminal path disposes it. Capture `SynchronizationContext.Current` and marshal progress updates in the same pattern as `KnowledgePageViewModel`. Commands expose explicit `RaiseCanExecuteChanged` calls whenever run/selection/readiness changes.

- [ ] **Step 4: Implement transcript/history mapping**

Build history only from completed User/Assistant transcript entries before the new user prompt. Add one user entry and one empty assistant entry per run; progress appends to that assistant entry. On failure/cancellation keep the partial text and add a Status entry with the structured code.

- [ ] **Step 5: Implement Golden actions**

Save current inputs and literal rule fields into a case; update only the selected case id; delete only after the command receives a selected case; run selected/all through `GoldenTestEvaluator`. Do not persist transcript or result history.

- [ ] **Step 6: Run GREEN and full ViewModel regressions**

```powershell
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release --filter "ConversationPageViewModelTests|KnowledgePageViewModelTests|LocalServicesViewModelTests|ModelManagementViewModelTests"
```

- [ ] **Step 7: Commit**

```powershell
git add src/MLLM.Workbench.Desktop/Pages/Conversation tests/desktop/MLLM.Workbench.Desktop.Tests/ConversationPageViewModelTests.cs
git commit -m "feat: add conversation test view model"
```

---

### Task 6: Add the native WPF page, shell route, Dashboard action, and dependency injection

**Files:**
- Create: `src/MLLM.Workbench.Desktop/Pages/Conversation/ConversationPage.xaml`
- Create: `src/MLLM.Workbench.Desktop/Pages/Conversation/ConversationPage.xaml.cs`
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/D2ConversationShellTests.cs`
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/D2ConversationPageRuntimeLoadTests.cs`
- Modify: `src/MLLM.Workbench.Desktop/App.xaml.cs`
- Modify: `src/MLLM.Workbench.Desktop/Shell/MainWindowViewModel.cs`
- Modify: `src/MLLM.Workbench.Desktop/Shell/MainWindow.xaml`
- Modify: `src/MLLM.Workbench.Desktop/Pages/Dashboard/DashboardPageViewModel.cs`
- Modify: `src/MLLM.Workbench.Desktop/Pages/Dashboard/DashboardPage.xaml`
- Modify: `tests/desktop/MLLM.Workbench.Desktop.Tests/DashboardViewModelTests.cs`

**Interfaces:**
- Consumes: Task 5 `ConversationPageViewModel` and all Task 1–4 services.
- Produces: persistent `conversation` route, `对话测试` Dashboard quick action, real WPF page and DI lifetime.

- [ ] **Step 1: Write RED shell and XAML contract tests**

Require:

- `NavigationItems` contains exact route/label `conversation` / `对话测试`;
- route switch maps to `ConversationPageViewModel`;
- `MainWindow.xaml` DataTemplate maps the ViewModel to `ConversationPage`;
- Dashboard exposes `OpenConversationCommand` and emits only `conversation`;
- page XAML parses and contains automation ids:

```text
ConversationPageRoot
ConversationRefreshButton
ConversationSystemPrompt
ConversationUserPrompt
ConversationSendButton
ConversationCancelButton
ConversationTranscript
ConversationEvidenceList
GoldenCaseList
GoldenRunSelectedButton
GoldenRunAllButton
GoldenResultList
```

- [ ] **Step 2: Run RED**

```powershell
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release --filter "D2ConversationShellTests|D2ConversationPageRuntimeLoadTests|DashboardViewModelTests"
```

- [ ] **Step 3: Implement the WPF page**

Follow current dark `CardStyle`, `ActionButtonStyle`, `PrimaryTextBrush`, and `MutedTextBrush` resources. Use a scroll-safe grid with runtime/metric cards, prompt controls, transcript, trusted evidence, Golden catalog, and results. Bind read-only status/metrics OneWay explicitly where WPF might otherwise infer TwoWay. Keep code-behind constructor-only; no inference or persistence logic in code-behind.

- [ ] **Step 4: Register dependencies**

In `App.BuildHost`, register one redirect-disabled `HttpClient` owner/client, `ILocalConversationClient`, `IConversationTestService`, `IGoldenTestCatalog` using `runtime.DataRoot`, `GoldenTestEvaluator`, and singleton `ConversationPageViewModel`. Ensure disposable conversation services are disposed by the host.

- [ ] **Step 5: Wire shell and Dashboard**

Add `Conversation` property/constructor argument, `NavigateConversationCommand`, navigation item, exact route switch, refresh-on-navigation, DataTemplate, and Dashboard quick action/button. Keep every existing route unchanged.

- [ ] **Step 6: Run GREEN and full Desktop regression**

```powershell
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release
```

Expected: 0 failures and WPF markup compilation success.

- [ ] **Step 7: Commit**

```powershell
git add src/MLLM.Workbench.Desktop/App.xaml.cs src/MLLM.Workbench.Desktop/Shell src/MLLM.Workbench.Desktop/Pages/Conversation src/MLLM.Workbench.Desktop/Pages/Dashboard tests/desktop/MLLM.Workbench.Desktop.Tests
git commit -m "feat: expose native conversation workspace"
```

---

### Task 7: Extend deterministic CI and installed navigation smoke

**Files:**
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/D2InstalledNavigationSmokeContractTests.cs`
- Modify: `src/MLLM.Workbench.Desktop/App.xaml.cs`
- Modify: `tests/ci/Invoke-C7ReleasePackageSmoke.ps1`
- Modify: `.github/workflows/knowledge-phase-c.yml`

**Interfaces:**
- Consumes: real installed `MainWindow`, D2 route, catalog/runtime refresh.
- Produces: `--smoke-d2-navigation` and `D2_NAVIGATION_SMOKE=PASS` without inference or service mutation.

- [ ] **Step 1: Write RED installed-smoke contract tests**

Require `App.xaml.cs` to recognize `--smoke-d2-navigation`, use the real MainWindow, navigate to `conversation`, wait for `Conversation.IsBusy == false`, force `DispatcherPriority.ApplicationIdle`, fail on dispatcher exception, and never execute Send/Start/Activate. Require the release script to invoke the argument under `MLLM_NETWORK_MODE=OFFLINE_CACHE` with bounded timeout and restore the prior environment.

- [ ] **Step 2: Add a D2 CI gate before full Desktop regression**

Add:

```yaml
- name: D2 conversation and golden tests
  shell: powershell
  run: dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release --filter "FullyQualifiedName~LocalConversation|FullyQualifiedName~OpenAiSseReader|FullyQualifiedName~ConversationTestService|FullyQualifiedName~JsonGoldenTestCatalog|FullyQualifiedName~GoldenTestEvaluator|FullyQualifiedName~ConversationPageViewModel|FullyQualifiedName~D2Conversation|FullyQualifiedName~D2InstalledNavigation"
```

- [ ] **Step 3: Run RED contract test**

Expected: failure because the smoke argument and Release invocation do not exist.

- [ ] **Step 4: Implement installed D2 navigation smoke**

Reuse `VerifyNavigationStepAsync` with route `conversation`, active-page predicate, busy predicate, and `LastError`. Runtime refresh may report “service stopped” as readiness state, but installed smoke fails only on unexpected structured page error/dispatcher failure. It must not start a service or send an HTTP inference request.

- [ ] **Step 5: Run local Release smoke**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/ci/Invoke-C7ReleasePackageSmoke.ps1 -OutputRoot artifacts/c7-release
```

Expected output includes existing `C7_RELEASE_INSTALL_SMOKE=PASS`, D1 smoke success, Knowledge smoke success, and `D2_NAVIGATION_SMOKE=PASS`.

- [ ] **Step 6: Commit**

```powershell
git add .github/workflows/knowledge-phase-c.yml src/MLLM.Workbench.Desktop/App.xaml.cs tests/ci/Invoke-C7ReleasePackageSmoke.ps1 tests/desktop/MLLM.Workbench.Desktop.Tests/D2InstalledNavigationSmokeContractTests.cs
git commit -m "test: verify installed D2 conversation navigation"
```

---

### Task 8: Final dual-platform verification, package recovery, and D2 handoff

**Files:**
- Modify only if a failing gate reveals a root cause.
- Update: `docs/superpowers/plans/2026-09-01-desktop-d2-conversation-golden-tests.md` checkboxes as tasks complete.

**Interfaces:**
- Consumes: all D2 production code, tests, CI, and release packaging.
- Produces: one verified branch head, reproducible artifact hashes, and documented physical-machine boundary.

- [ ] **Step 1: Run the complete local deterministic suite**

```powershell
dotnet test MLLM.Workbench.sln -c Release
python -m pytest -q tests/ci/test_repo_contract.py tests/ci/test_safety_policy.py web/backend/tests
python tools/validate_source.py
```

Run every PowerShell smoke listed by `.github/workflows/knowledge-phase-c.yml` that is valid on the current host. Any failure enters systematic root-cause diagnosis; do not patch symptoms.

- [ ] **Step 2: Push the approved feature branch only after local GREEN**

```powershell
git status --short --branch
git push origin feature/knowledge-phase-c
```

Confirm remote branch SHA equals local `HEAD`.

- [ ] **Step 3: Require both GitHub workflows GREEN**

Require `knowledge-phase-c` success on Windows Server 2022/2025 and `knowledge-c-release` success on Windows Server 2025 for the exact final SHA. Read failing job logs completely before any fix.

- [ ] **Step 4: Recover and verify artifacts**

Download the final release artifact, recompute SHA-256 for installer and portable ZIPs, compare with sidecars, extract each to separate fresh directories, and run the installed/portable smoke from recovered content. Verify runtime, web, Conversation page, Golden catalog path, and all required production files are present; exclude build targets/caches.

- [ ] **Step 5: Perform final verification-before-completion review**

Use `superpowers:verification-before-completion`. Record exact local test totals, workflow run ids/URLs, final branch SHA, ZIP names/sizes/hashes, recovery commands, and the remaining physical-machine-only inference boundary.

- [ ] **Step 6: Commit final plan status if checkbox updates are made**

```powershell
git add docs/superpowers/plans/2026-09-01-desktop-d2-conversation-golden-tests.md
git commit -m "docs: record D2 conversation verification"
git push origin feature/knowledge-phase-c
```

Final completion criteria: all automated gates are green for one exact SHA, both recovered archives validate, and no claim is made that deterministic CI proves Qwen answer quality or physical-machine performance.
