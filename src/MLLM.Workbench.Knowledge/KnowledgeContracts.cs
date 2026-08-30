namespace MLLM.Workbench.Knowledge;

public sealed record KnowledgeStoreOptions(string DatabasePath);

public sealed record KnowledgeChunk(
    string ChunkId,
    int Ordinal,
    string Content);

public sealed record KnowledgeDocument(
    string DocumentId,
    string SourceUri,
    string Title,
    IReadOnlyList<KnowledgeChunk> Chunks);

public sealed record KnowledgeSearchHit(
    string DocumentId,
    string ChunkId,
    string SourceUri,
    string Title,
    int Ordinal,
    string Excerpt,
    double Score)
{
    public string? Locator =>
        KnowledgeChunkLocator.TryGetLocator(ChunkId, out var locator) ? locator : null;
}

public sealed record KnowledgeStoreHealth(
    bool DatabaseReady,
    bool Fts5Ready,
    string SQLiteVersion,
    string DatabasePath);

public sealed record EmbeddingIndexStatus(
    int TotalChunks,
    int IndexedChunks)
{
    public int PendingChunks => Math.Max(0, TotalChunks - IndexedChunks);
}

public sealed record EmbeddingIndexProgress(
    int CompletedChunks,
    int TotalChunks,
    string ChunkId);
