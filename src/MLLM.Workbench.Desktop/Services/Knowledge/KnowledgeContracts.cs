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
    string? EmbeddingModel)
{
    public bool HybridReady => Fts5Ready && EmbeddingConfigured;
}

public interface IKnowledgeWorkbenchService
{
    Task<KnowledgeWorkspaceSnapshot> GetSnapshotAsync(CancellationToken cancellationToken);
    Task ImportFileAsync(string path, CancellationToken cancellationToken);
    Task<IReadOnlyList<KnowledgeSearchHit>> SearchAsync(
        string query,
        KnowledgeSearchMode mode,
        int limit,
        CancellationToken cancellationToken);
}

public interface IEvidenceLauncher
{
    Task OpenAsync(string sourceUri, CancellationToken cancellationToken);
}
