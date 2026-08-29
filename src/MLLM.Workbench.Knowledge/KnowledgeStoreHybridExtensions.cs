using MLLM.Workbench.Knowledge.Embeddings;

namespace MLLM.Workbench.Knowledge;

public static class KnowledgeStoreHybridExtensions
{
    public static async Task<IReadOnlyList<KnowledgeSearchHit>> SearchHybridAsync(
        this KnowledgeStore store,
        string query,
        IEmbeddingProvider provider,
        int limit,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(store);
        ArgumentNullException.ThrowIfNull(provider);
        if (string.IsNullOrWhiteSpace(query)) return Array.Empty<KnowledgeSearchHit>();
        if (limit < 1 || limit > 100) throw new ArgumentOutOfRangeException(nameof(limit));

        var candidateLimit = Math.Min(100, Math.Max(20, limit * 4));
        var lexicalTask = store.SearchFtsAsync(query, candidateLimit, cancellationToken);
        var semanticTask = store.SearchVectorAsync(query, provider, candidateLimit, cancellationToken);
        await Task.WhenAll(lexicalTask, semanticTask).ConfigureAwait(false);

        return HybridSearch.Fuse(
            await lexicalTask.ConfigureAwait(false),
            await semanticTask.ConfigureAwait(false),
            limit);
    }
}
