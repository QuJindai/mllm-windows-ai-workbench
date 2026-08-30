using MLLM.Workbench.Knowledge;

namespace MLLM.Workbench.Desktop.Services.Knowledge;

public enum KnowledgeSearchMode
{
    Fts5,
    Embedding,
    Hybrid
}

public sealed record KnowledgeWorkspaceSnapshot(
    string DatabasePath,
    bool Fts5Ready,
    bool EmbeddingConfigured,
    string? EmbeddingProvider,
    string? EmbeddingModel,
    string? EmbeddingConfigurationError = null,
    int EmbeddingIndexedChunks = 0,
    int EmbeddingTotalChunks = 0)
{
    public double EmbeddingCoverage => EmbeddingTotalChunks <= 0
        ? 1d
        : (double)EmbeddingIndexedChunks / EmbeddingTotalChunks;

    public bool HybridReady =>
        Fts5Ready &&
        EmbeddingConfigured &&
        EmbeddingIndexedChunks == EmbeddingTotalChunks;
}

public sealed record KnowledgeEmbeddingProgress(
    int Completed,
    int Total,
    string CurrentChunkId)
{
    public double Fraction => Total <= 0 ? 1d : (double)Completed / Total;
}

public interface IKnowledgeWorkbenchService
{
    Task<KnowledgeWorkspaceSnapshot> GetSnapshotAsync(CancellationToken cancellationToken);
    Task ImportFileAsync(string path, CancellationToken cancellationToken);
    Task<KnowledgeWorkspaceSnapshot> BuildEmbeddingIndexAsync(
        IProgress<KnowledgeEmbeddingProgress>? progress,
        CancellationToken cancellationToken);
    Task<IReadOnlyList<KnowledgeSearchHit>> SearchAsync(
        string query,
        KnowledgeSearchMode mode,
        int limit,
        CancellationToken cancellationToken);
}

public interface IEvidenceLauncher
{
    Task OpenAsync(string sourceUri, CancellationToken cancellationToken);

    Task OpenAsync(string sourceUri, string? locator, CancellationToken cancellationToken) =>
        OpenAsync(sourceUri, cancellationToken);
}
