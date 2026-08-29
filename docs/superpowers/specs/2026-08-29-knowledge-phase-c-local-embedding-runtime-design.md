# Knowledge Phase C · Local Embedding Runtime Design

## Goal

Turn the already-green local embedding provider, vector store, Hybrid search, and Knowledge desktop page into a real production path: the desktop process must resolve local embedding configuration at startup, surface configuration errors without breaking FTS5, allow existing FTS5-only content to receive embeddings later, and show truthful indexing/runtime state in the GUI.

## Baseline to preserve

- Keep `feature/knowledge-phase-c` as the isolated development line.
- Preserve existing FTS5 persistence, vector persistence, reciprocal-rank Hybrid retrieval, RAG evidence provenance, and Phase B contracts.
- Keep the workbench local-first. No OpenAI API, cloud embedding fallback, or public endpoint fallback is permitted.
- Keep Windows 2022 and Windows 2025 CI green.
- Existing Markdown/Text import behavior remains unchanged.

## Production composition

`LocalEmbeddingEnvironment` remains the only environment parser. The desktop composition layer will call it once at startup and pass the resulting `LocalEmbeddingResolution` into the Knowledge service.

A new `KnowledgeServiceFactory` will own this composition so it can be unit-tested without booting WPF:

```csharp
public static KnowledgeWorkbenchService Create(
    string dataRoot,
    Func<string, string?> readVariable);
```

The factory will:

1. call `LocalEmbeddingEnvironment.Resolve(readVariable)`;
2. construct `KnowledgeWorkbenchService` with the resolved provider and configuration error;
3. never contact the embedding endpoint during startup;
4. never replace an invalid local configuration with a cloud provider.

`App.BuildHost()` will use this factory with `Environment.GetEnvironmentVariable`.

## Truthful state model

The current `EmbeddingConfigured` flag only means a provider object exists. It does not prove the endpoint is online. The GUI must not label that state as fully operational.

`KnowledgeWorkspaceSnapshot` will expose:

- `EmbeddingConfigured`: a valid local provider configuration exists;
- `EmbeddingConfigurationError`: partial/invalid configuration text, otherwise null;
- `EmbeddingProvider`, `EmbeddingModel`;
- `EmbeddingIndexedChunks`, `EmbeddingTotalChunks` for the active provider/model;
- `EmbeddingCoverage`: derived `indexed / total`, with `1.0` for an empty knowledge base only when there are no chunks to index;
- `HybridReady`: FTS5 is ready, a provider is configured, and all current chunks have valid embeddings for that provider/model.

The GUI text must distinguish:

- `未配置`;
- `配置错误: ...`;
- `已配置 · 0/N 已索引`;
- `已配置 · N/N 已索引`.

No startup network probe is performed, so the GUI will not claim the endpoint is online until a real embedding operation succeeds. Endpoint/network failures are surfaced when indexing or searching.

## Incremental embedding backfill

Existing files may have been imported before a provider was configured. Requiring re-import would be wasteful and misleading. `KnowledgeStore` will therefore add an incremental batch index operation.

New contracts:

```csharp
public sealed record EmbeddingIndexStatus(int TotalChunks, int IndexedChunks)
{
    public int PendingChunks => Math.Max(0, TotalChunks - IndexedChunks);
}

public sealed record EmbeddingIndexProgress(
    int CompletedChunks,
    int TotalChunks,
    string ChunkId);
```

New store APIs:

```csharp
Task<EmbeddingIndexStatus> GetEmbeddingIndexStatusAsync(
    IEmbeddingProvider provider,
    CancellationToken cancellationToken);

Task<EmbeddingIndexStatus> IndexMissingEmbeddingsAsync(
    IEmbeddingProvider provider,
    IProgress<EmbeddingIndexProgress>? progress,
    CancellationToken cancellationToken);
```

A chunk counts as indexed only when provider id, model id, dimension, and stored `content_sha256` match the current chunk. Stale vectors are treated as pending.

`IndexMissingEmbeddingsAsync` will embed only missing/stale chunks. It will not delete working embeddings for other providers/models. Each generated vector is validated before being committed. Cancellation stops future work without corrupting already committed rows.

## Desktop service and progress

`IKnowledgeWorkbenchService` will add:

```csharp
Task<KnowledgeWorkspaceSnapshot> BuildEmbeddingIndexAsync(
    IProgress<KnowledgeEmbeddingProgress>? progress,
    CancellationToken cancellationToken);
```

with:

```csharp
public sealed record KnowledgeEmbeddingProgress(
    int Completed,
    int Total,
    string CurrentChunkId)
{
    public double Fraction => Total <= 0 ? 1d : (double)Completed / Total;
}
```

The service delegates to `KnowledgeStore.IndexMissingEmbeddingsAsync`, then returns a fresh snapshot.

## GUI behavior

The Knowledge page will add a `构建/补齐向量索引` action. While it runs, the page displays:

- current completed/total count;
- percentage;
- current chunk id;
- a progress bar;
- endpoint/configuration errors through the existing error area.

FTS5 search remains usable when embedding is absent or misconfigured. Embedding/Hybrid search remains blocked until a provider is configured; Hybrid additionally requires complete active-provider vector coverage so the UI does not claim a partially indexed database is fully hybrid-ready.

## Testing

TDD and CI must cover:

1. production factory resolves complete loopback environment into a configured service;
2. partial/invalid environment does not break FTS5 and exposes the configuration error;
3. pre-existing FTS5-only chunks are discovered as pending after a provider is configured;
4. incremental backfill indexes only missing/stale chunks and survives reopen;
5. progress reaches total and reports real chunk ids;
6. snapshot coverage and Hybrid readiness are truthful;
7. Knowledge page displays configuration error, coverage, and indexing progress;
8. all existing Knowledge and Phase B regressions remain green on Windows 2022 and Windows 2025.
