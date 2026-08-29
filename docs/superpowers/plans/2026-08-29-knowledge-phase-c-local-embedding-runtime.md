# Knowledge Phase C · Local Embedding Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing local embedding stack into the real desktop runtime, incrementally backfill vectors for existing knowledge, and expose truthful vector/Hybrid readiness and progress in the GUI.

**Architecture:** Keep `KnowledgeStore` as the persistence/retrieval owner, add incremental embedding-index status/backfill APIs, propagate the state through `KnowledgeWorkbenchService`, and isolate environment-to-service composition in a testable `KnowledgeServiceFactory`. WPF consumes snapshots/progress only; it never opens SQLite or parses environment variables directly.

**Tech Stack:** .NET 8, C#, Microsoft.Data.Sqlite 8.0.30, WPF, xUnit, GitHub Actions Windows 2022/2025.

**Spec:** `docs/superpowers/specs/2026-08-29-knowledge-phase-c-local-embedding-runtime-design.md`

## Global Constraints

- Preserve existing FTS5 persistence, vector persistence, Hybrid retrieval, RAG evidence provenance, and Phase B contracts.
- Local embedding endpoints must remain loopback-only; no cloud fallback is permitted.
- Desktop startup must not perform a network probe or fail solely because embedding configuration is absent/invalid.
- Existing Markdown/Text import behavior remains unchanged.
- CI must remain green on both `windows-2022` and `windows-2025`.

---

### Task 1: Incremental embedding index state and backfill

**Files:**
- Modify: `src/MLLM.Workbench.Knowledge/KnowledgeContracts.cs`
- Modify: `src/MLLM.Workbench.Knowledge/KnowledgeStore.cs`
- Modify: `tests/knowledge/MLLM.Workbench.Knowledge.Tests/EmbeddingStoreTests.cs`

**Interfaces:**
- Consumes: `IEmbeddingProvider` and existing `embeddings` table.
- Produces:

```csharp
public sealed record EmbeddingIndexStatus(int TotalChunks, int IndexedChunks)
{
    public int PendingChunks => Math.Max(0, TotalChunks - IndexedChunks);
}

public sealed record EmbeddingIndexProgress(int CompletedChunks, int TotalChunks, string ChunkId);

Task<EmbeddingIndexStatus> GetEmbeddingIndexStatusAsync(
    IEmbeddingProvider provider,
    CancellationToken cancellationToken);

Task<EmbeddingIndexStatus> IndexMissingEmbeddingsAsync(
    IEmbeddingProvider provider,
    IProgress<EmbeddingIndexProgress>? progress,
    CancellationToken cancellationToken);
```

- [ ] **Step 1: Add RED tests** proving an FTS-only database reports all chunks pending, backfill reports real progress, and reopening reports full current-provider coverage.

Example assertions:

```csharp
var before = await store.GetEmbeddingIndexStatusAsync(provider, CancellationToken.None);
Assert.Equal(2, before.TotalChunks);
Assert.Equal(0, before.IndexedChunks);

var progress = new List<EmbeddingIndexProgress>();
var after = await store.IndexMissingEmbeddingsAsync(
    provider,
    new InlineProgress<EmbeddingIndexProgress>(progress.Add),
    CancellationToken.None);

Assert.Equal(2, after.IndexedChunks);
Assert.Equal([1, 2], progress.Select(x => x.CompletedChunks));
Assert.All(progress, x => Assert.False(string.IsNullOrWhiteSpace(x.ChunkId)));
```

- [ ] **Step 2: Verify RED** with:

```powershell
dotnet test tests/knowledge/MLLM.Workbench.Knowledge.Tests/MLLM.Workbench.Knowledge.Tests.csproj -c Release --filter EmbeddingStoreTests
```

Expected: compile/test failure because the new status/backfill contracts do not exist.

- [ ] **Step 3: Implement `GetEmbeddingIndexStatusAsync`** using a `LEFT JOIN`/correlated match that counts only embeddings whose provider id, model id, dimension, and `content_sha256` match the current chunk.

- [ ] **Step 4: Implement `IndexMissingEmbeddingsAsync`** by loading only missing/stale chunks, embedding one chunk at a time, validating the vector, upserting the active provider/model row transactionally per chunk, and reporting progress after each committed row.

Upsert shape:

```sql
INSERT INTO embeddings(chunk_id, provider_id, model_id, dimension, vector, content_sha256, updated_at_utc)
VALUES($chunkId, $providerId, $modelId, $dimension, $vector, $contentSha256, $updatedAtUtc)
ON CONFLICT(chunk_id, provider_id, model_id) DO UPDATE SET
    dimension=excluded.dimension,
    vector=excluded.vector,
    content_sha256=excluded.content_sha256,
    updated_at_utc=excluded.updated_at_utc;
```

- [ ] **Step 5: Verify GREEN** with the filtered test command, then the full knowledge test project.

- [ ] **Step 6: Commit** as `feat: add incremental embedding backfill`.

---

### Task 2: Production composition and truthful workspace snapshot

**Files:**
- Create: `src/MLLM.Workbench.Desktop/Services/Knowledge/KnowledgeServiceFactory.cs`
- Modify: `src/MLLM.Workbench.Desktop/Services/Knowledge/KnowledgeContracts.cs`
- Modify: `src/MLLM.Workbench.Desktop/Services/Knowledge/KnowledgeWorkbenchService.cs`
- Modify: `src/MLLM.Workbench.Desktop/App.xaml.cs`
- Modify: `tests/desktop/MLLM.Workbench.Desktop.Tests/KnowledgeWorkbenchServiceTests.cs`
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/KnowledgeServiceFactoryTests.cs`

**Interfaces:**
- Consumes: `LocalEmbeddingEnvironment.Resolve(Func<string,string?>)` and Task 1 index-status APIs.
- Produces:

```csharp
public sealed record KnowledgeWorkspaceSnapshot(
    string DatabasePath,
    bool Fts5Ready,
    bool EmbeddingConfigured,
    string? EmbeddingConfigurationError,
    string? EmbeddingProvider,
    string? EmbeddingModel,
    int EmbeddingIndexedChunks,
    int EmbeddingTotalChunks)
{
    public double EmbeddingCoverage => EmbeddingTotalChunks <= 0
        ? 1d
        : (double)EmbeddingIndexedChunks / EmbeddingTotalChunks;

    public bool HybridReady =>
        Fts5Ready && EmbeddingConfigured && EmbeddingIndexedChunks == EmbeddingTotalChunks;
}

public sealed record KnowledgeEmbeddingProgress(int Completed, int Total, string CurrentChunkId)
{
    public double Fraction => Total <= 0 ? 1d : (double)Completed / Total;
}

Task<KnowledgeWorkspaceSnapshot> BuildEmbeddingIndexAsync(
    IProgress<KnowledgeEmbeddingProgress>? progress,
    CancellationToken cancellationToken);
```

- [ ] **Step 1: Add RED factory tests** for complete loopback config and partial config. Complete config must yield `EmbeddingConfigured=true`; partial config must leave FTS5 usable and place the exact variable/configuration error in the snapshot.

- [ ] **Step 2: Add RED service test** that imports a file without embeddings, reopens with a provider, observes `0/N`, calls `BuildEmbeddingIndexAsync`, and observes `N/N` plus `HybridReady=true`.

- [ ] **Step 3: Verify RED** with:

```powershell
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release --filter "KnowledgeWorkbenchServiceTests|KnowledgeServiceFactoryTests"
```

- [ ] **Step 4: Implement `KnowledgeServiceFactory.Create`**:

```csharp
public static KnowledgeWorkbenchService Create(string dataRoot, Func<string, string?> readVariable)
{
    var resolution = LocalEmbeddingEnvironment.Resolve(readVariable);
    return new KnowledgeWorkbenchService(dataRoot, resolution.Provider, resolution.Error);
}
```

- [ ] **Step 5: Extend `KnowledgeWorkbenchService`** to store the configuration error, include Task 1 status in every snapshot when a provider exists, and map store progress to `KnowledgeEmbeddingProgress` in `BuildEmbeddingIndexAsync`.

- [ ] **Step 6: Wire production WPF composition** by replacing:

```csharp
services.AddSingleton<IKnowledgeWorkbenchService>(_ => new KnowledgeWorkbenchService(runtime.DataRoot));
```

with:

```csharp
services.AddSingleton<IKnowledgeWorkbenchService>(_ =>
    KnowledgeServiceFactory.Create(runtime.DataRoot, Environment.GetEnvironmentVariable));
```

- [ ] **Step 7: Verify GREEN** for the focused service/factory tests and `KnowledgeShellIntegrationTests`.

- [ ] **Step 8: Commit** as `feat: wire local embedding runtime into desktop`.

---

### Task 3: GUI vector coverage, configuration error, and visible progress

**Files:**
- Modify: `src/MLLM.Workbench.Desktop/Pages/Knowledge/KnowledgePageViewModel.cs`
- Modify: `src/MLLM.Workbench.Desktop/Pages/Knowledge/KnowledgePage.xaml`
- Modify: `tests/desktop/MLLM.Workbench.Desktop.Tests/KnowledgePageViewModelTests.cs`

**Interfaces:**
- Consumes: Task 2 snapshot and `BuildEmbeddingIndexAsync`.
- Produces ViewModel state:

```csharp
public string EmbeddingIndexStatus { get; }
public string EmbeddingProgressText { get; }
public double EmbeddingProgressPercent { get; }
public bool CanBuildEmbeddingIndex { get; }
public ICommand BuildEmbeddingIndexCommand { get; }
```

- [ ] **Step 1: Add RED ViewModel tests** for three states: invalid configuration text, configured `0/N` coverage with Hybrid unavailable, and post-build `N/N` coverage with Hybrid ready. Progress test must assert the ViewModel receives an intermediate progress update containing current chunk id and percentage.

- [ ] **Step 2: Verify RED** with:

```powershell
dotnet test tests/desktop/MLLM.Workbench.Desktop.Tests/MLLM.Workbench.Desktop.Tests.csproj -c Release --filter KnowledgePageViewModelTests
```

- [ ] **Step 3: Implement ViewModel state mapping**. Required user-visible semantics:

```text
未配置
配置错误: <message>
已配置 · 0/12 已索引
已配置 · 12/12 已索引
```

Hybrid status is `可用` only for complete active-provider coverage. Otherwise it is `待补齐向量索引` when a provider exists and `不可用` when no provider exists.

- [ ] **Step 4: Add `构建/补齐向量索引` button and progress bar** bound to the new ViewModel fields. Keep the current FTS5/search/import/RAG evidence sections unchanged.

- [ ] **Step 5: Verify GREEN** for ViewModel tests, full desktop tests, then run the repository workflow through GitHub Actions on both Windows versions.

- [ ] **Step 6: Commit** as `feat: expose embedding coverage and progress in knowledge ui`.

---

### Task 4: Final regression gate

**Files:**
- No production file changes unless a test exposes a real defect.

**Interfaces:**
- Consumes all Tasks 1–3.
- Produces a single green Phase C checkpoint.

- [ ] **Step 1: Run/observe the complete `.github/workflows/knowledge-phase-c.yml` matrix** for Windows 2022 and Windows 2025.
- [ ] **Step 2: Require success for Knowledge core, Knowledge Page, Knowledge Workspace Service, Knowledge Shell, full desktop regression, and every frozen Phase B regression step.**
- [ ] **Step 3: Record the final commit SHA and workflow run id.**
