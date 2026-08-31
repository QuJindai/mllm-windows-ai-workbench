# M-LLM Windows AI Workbench — D2 Conversation & Golden Tests Design

Date: 2026-09-01  
Status: PROPOSED FOR USER REVIEW  
Branch: `feature/knowledge-phase-c`  
Baseline: `befce72348ac0003d01a22cf3c64be2d015918dd`  
Parent design: `docs/superpowers/specs/2026-08-31-desktop-d1-model-services-gui-design.md`

## Goal

Add a native WPF Conversation Test workspace that exercises the running local OpenAI-compatible model service, streams responses, reports honest latency and token metrics, optionally grounds requests in the existing Knowledge Workbench, and saves deterministic Golden Test cases for repeatable local regression.

D2 must turn the already-managed `local-model-api` service into a product-visible test workflow. It must not add a cloud route, arbitrary endpoint, generic command surface, second service controller, or non-deterministic CI dependency.

## Existing product boundary

The D1 baseline already provides:

- typed model inventory and active-model state through `IWorkbenchBackendClient`;
- typed service state, including the authoritative loopback `BaseUrl` for `local-model-api`;
- Start/Stop/Restart/Logs controls for managed services;
- a Knowledge Workbench with FTS5, optional local embeddings, Hybrid search, `RagContextBuilder`, evidence locators, and persistent SQLite storage;
- a single native WPF shell and a Safe Core release/installed-smoke pipeline.

The current Web backend has a small non-streaming `/api/chat` bridge. It is not the product authority for Desktop state and does not provide streaming, metrics, Golden Test persistence, knowledge grounding, or typed Desktop contracts.

## Architecture decision

### Selected approach: native Desktop loopback client

D2 adds a focused `Conversation` service area in the Desktop application. It obtains the current `local-model-api` descriptor and active model from the existing typed backend, validates the backend-provided service URL, and sends OpenAI-compatible HTTP requests directly to that loopback service.

This is the selected approach because the model server is already an HTTP boundary and streaming Server-Sent Events can be consumed without tunnelling unbounded response data through the PowerShell named-pipe RPC process. Service discovery and lifecycle authority remain in the existing backend; inference remains a separate, fixed loopback-only client.

### Rejected approach: new named-pipe inference RPC

Proxying every chat chunk through `WorkbenchBackend.ps1` would enlarge the privileged backend allowlist, require a new streaming protocol over the current request/response pipe, and mix long-running inference with management RPC. It adds safety and failure modes without improving the local-only boundary.

### Rejected approach: call the Web Workbench backend

Reusing `/api/chat` would make the optional Web service a mandatory dependency for the native Desktop, retain its current non-streaming fixed-parameter behavior, and create two layers of model-service state. D2 may later share a lower-level client library with Web, but Desktop does not depend on Web.

## Components and responsibilities

### Local conversation client

Create a small interface owned by the Desktop conversation service:

```csharp
public interface ILocalConversationClient
{
    Task<ConversationRunResult> StreamAsync(
        LocalConversationEndpoint endpoint,
        ConversationRequest request,
        IProgress<ConversationDelta>? progress,
        CancellationToken cancellationToken);
}
```

The implementation:

- accepts only an endpoint derived from the `local-model-api` `ServiceDescriptor`;
- accepts only `http` with an IP loopback host (`127.0.0.0/8` or `::1`) and a non-default explicit port;
- appends only the fixed `/v1/chat/completions` or `/chat/completions` path selected by a one-time capability probe; it never accepts a user-entered path;
- sends `stream: true` and `stream_options.include_usage: true`;
- parses standard `data: {json}` SSE frames and terminates only on `data: [DONE]` or a clean end-of-stream;
- reports only non-empty assistant deltas to the UI;
- preserves a partial response when cancellation occurs and marks the run `Cancelled`;
- returns structured HTTP, protocol, timeout, cancellation, and unavailable-service failures without exposing credentials or arbitrary response bodies.

No API-key input is added. The client never follows redirects and never falls back to a non-loopback host.

### Conversation coordinator

`ConversationTestService` owns one inference run at a time. Before a run it obtains fresh backend snapshots and requires:

- exactly one `local-model-api` descriptor in `Running` state;
- a valid loopback `BaseUrl`;
- an active model, or the service-provided `ModelId` when the server intentionally exposes the stable alias `local`.

The service builds messages from:

1. optional system prompt;
2. bounded prior conversation turns when history is enabled;
3. optional knowledge-grounding instruction and evidence context;
4. the current user prompt.

Requests expose only these user parameters:

- temperature: decimal `0.0` through `2.0`, default `0.2`;
- maximum output tokens: integer `1` through `8192`, default `512`;
- include prior conversation turns: on/off, default on;
- use Knowledge Workbench evidence: on/off, default off.

The local server context-window size is not mutated per request because the OpenAI-compatible API does not provide a portable per-request context-size control. D2 represents “context” as bounded conversation history plus optional knowledge evidence; server context-window configuration remains a service/runtime concern.

### Knowledge grounding

When Knowledge grounding is enabled:

- read the current Knowledge snapshot;
- use Hybrid search only when `HybridReady`; otherwise use FTS5;
- request at most eight results and pass them through the existing `RagContextBuilder` with its 12,000-character bound;
- if no evidence is returned, stop before inference with `NO_EVIDENCE` and tell the user that no grounded answer was generated;
- add a strict instruction that the answer must use only the supplied evidence and cite `[K1]`, `[K2]`, and so on;
- display evidence cards from the trusted `RagContext.Evidence` records, not from model-generated citation text.

The answer surface may highlight citation ids present in the model text, but citation presence does not replace the trusted evidence list and is not treated as proof of correctness.

### Metrics

Metrics are measured with a monotonic stopwatch:

- request latency starts immediately before sending HTTP;
- TTFT ends at the first non-empty assistant content delta;
- total latency ends at `[DONE]` or clean stream completion;
- generated-token count comes only from a server `usage.completion_tokens` field;
- decode tokens/second is calculated only when generated-token count is known and post-first-token duration is positive.

If the server omits usage, the UI displays generated tokens and tokens/second as “Unavailable”. D2 does not estimate tokens from characters or words. Cancelled and failed runs keep elapsed timings but are excluded from Golden performance pass/fail checks.

### Golden Test catalog

Golden cases are stored below the existing data root at `conversation/golden-tests.json`. The document has an explicit schema version and is written atomically using a temporary sibling plus replace/move. A case contains:

- stable id and user-visible name;
- system prompt and user prompt;
- temperature and maximum output tokens;
- whether knowledge grounding is required;
- case-insensitive `mustContain` fragments;
- case-insensitive `mustNotContain` fragments;
- optional maximum total latency in milliseconds;
- created and updated timestamps.

The catalog supports create, update, delete, import-free load, and save. It contains no credentials, arbitrary endpoint, model path, executable path, or copied knowledge documents.

Golden execution is sequential to avoid local CPU/GPU contention. Every case is run with an empty prior conversation. A result passes only when:

- the inference run completed successfully;
- the response is non-empty;
- every `mustContain` fragment is present;
- no `mustNotContain` fragment is present;
- the optional latency ceiling is met.

If a knowledge-grounded case has no evidence, the case fails with `NO_EVIDENCE` without invoking the model. Result rows retain failure reasons, response text, evidence ids, TTFT, total latency, token count, and tokens/second for the current session. D2 persists case definitions, not an unbounded history of generated responses; historical benchmark storage belongs to D4.

## Native WPF product surface

Add one persistent route:

- id: `conversation`
- label: `对话测试`

The page contains:

- current local service, endpoint, active model, and readiness summary;
- system prompt, multi-line user prompt, temperature, maximum output tokens, history toggle, and Knowledge grounding toggle;
- Send, Cancel, Clear Conversation, and Refresh Runtime actions;
- a streaming transcript with explicit User/Assistant/Status entries;
- live TTFT, total latency, generated tokens, tokens/second, and terminal state;
- trusted Knowledge evidence cards with citation id, title, source, locator, excerpt, and Open Evidence action;
- Save as Golden / Update Golden controls;
- Golden catalog with Run Selected, Run All, Edit, and Delete;
- sequential Golden result rows and structured failure reasons.

All commands are asynchronous. Send is disabled while a run is active; Cancel is enabled only while active. Runtime refresh and Golden catalog operations do not block the WPF dispatcher.

Dashboard gains a `对话测试` quick action. Models, Local Services, Knowledge, and Conversation remain separate pages with no duplicated lifecycle controls.

## Error handling and state rules

- Service stopped or blocked: show the authoritative D1 service status and direct the user to Local Services; do not auto-start it.
- Missing active model: show the authoritative model state and direct the user to Model Management; do not auto-activate a model.
- Invalid/non-loopback endpoint: fail closed before HTTP with `ENDPOINT_NOT_LOOPBACK`.
- HTTP non-success: surface status code plus a bounded sanitized diagnostic; do not render arbitrary HTML.
- Malformed SSE/JSON: keep the prior transcript, mark the run failed, and report `STREAM_PROTOCOL_ERROR`.
- Cancellation: cancel the HTTP request, keep partial assistant text, mark it cancelled, and allow a new run.
- Knowledge unavailable/no hits: do not generate an ungrounded answer when grounding was requested.
- Golden catalog corruption: keep the corrupt file untouched, report its full local path, and require explicit user repair; do not silently replace it with an empty catalog.

## Concurrency and lifecycle

- One Conversation/Golden inference run may execute at a time.
- `Run All` and interactive Send are mutually exclusive.
- One cancellation token source is owned by the page ViewModel for the current run and disposed at terminal state.
- Navigating away does not leave an undiscoverable run: the ViewModel remains a singleton and exposes current state; application exit cancels the active run through service disposal.
- Golden catalog writes use an in-process semaphore and atomic replacement.

## Safety boundaries

D2 must not:

- connect to a user-entered, cloud, LAN, hostname, proxy, redirect, or non-loopback inference endpoint;
- accept or persist API keys;
- add arbitrary PowerShell, shell, command, executable, PID, port, destination path, or log path input;
- auto-start services, auto-activate models, install runtimes, download models, or mutate network mode;
- weaken named-pipe authentication or the Phase B backend allowlist;
- claim token counts or throughput when the server did not report token usage;
- use an LLM judge or external AI API in CI.

## Test strategy and acceptance gates

D2 acceptance requires all of the following:

1. Endpoint validation tests prove loopback-only behavior, explicit-port enforcement, redirect rejection, and rejection of localhost hostnames, LAN, cloud, file, and malformed URLs.
2. Deterministic SSE tests prove fragmented-frame parsing, multi-choice safety, `[DONE]`, usage capture, malformed data failure, cancellation, TTFT, total latency, and unavailable-metric behavior.
3. A real loopback HTTP integration test exercises the complete Desktop request/stream/result path without external network or AI.
4. Knowledge-grounding tests prove Hybrid/FTS selection, bounded RAG context, trusted evidence projection, and no HTTP request when evidence is empty.
5. Golden catalog tests prove schema validation, atomic create/update/delete, stable ordering, corrupt-file preservation, and restart persistence.
6. Golden evaluator tests prove required/forbidden fragments, empty response, latency ceiling, cancellation/failure exclusion, and sequential execution.
7. ViewModel tests prove command enablement, streaming transcript updates, Cancel, runtime readiness, Golden operations, and structured error preservation.
8. Shell and WPF runtime-load tests prove the persistent `conversation` route, Dashboard quick action, correct DataTemplate, and dispatcher-safe page loading.
9. Installed Release smoke navigates to Conversation and loads its runtime/catalog state in `OFFLINE_CACHE` without starting a model or sending inference.
10. Existing D1, Knowledge C7, Safe Core, installer, backend allowlist, and Windows Server 2022/2025 regressions remain green.

## Release and recovery

The normal self-contained Desktop and C7 package flow remains authoritative. D2 adds its production files, tests, design/plan documents, and any required package manifest entries to the existing release. Final verification must recompute artifact SHA-256 values, extract both installer and portable archives, and run installed navigation smoke from the recovered content.

A physical-machine inference acceptance is separate from deterministic CI. CI proves protocol handling and product state using a fake loopback server; it does not claim Qwen answer quality or physical GPU/CPU performance.

## Non-goals

D2 does not implement:

- knowledge-source list/delete/rebuild/folder import lifecycle (D3);
- persistent evidence/log catalog or historical benchmark telemetry (D4);
- concurrent load testing, CPU/RAM/GPU/VRAM sampling, or performance trend charts (D4);
- settings, proxy mutation, startup-page choice, or About/version page (D5);
- remote/cloud model providers, API keys, model downloads, or a new installer;
- semantic LLM-as-judge scoring.
