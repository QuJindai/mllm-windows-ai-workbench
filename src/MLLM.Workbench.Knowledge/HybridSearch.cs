namespace MLLM.Workbench.Knowledge;

public static class HybridSearch
{
    private const int DefaultRrfK = 60;

    public static IReadOnlyList<KnowledgeSearchHit> Fuse(
        IReadOnlyList<KnowledgeSearchHit> lexical,
        IReadOnlyList<KnowledgeSearchHit> semantic,
        int limit,
        int rrfK = DefaultRrfK)
    {
        ArgumentNullException.ThrowIfNull(lexical);
        ArgumentNullException.ThrowIfNull(semantic);
        if (limit < 1 || limit > 100) throw new ArgumentOutOfRangeException(nameof(limit));
        if (rrfK < 1) throw new ArgumentOutOfRangeException(nameof(rrfK));

        var fused = new Dictionary<HitKey, FusionState>();
        AddRanked(fused, lexical, rrfK);
        AddRanked(fused, semantic, rrfK);

        return fused.Values
            .OrderByDescending(x => x.Score)
            .ThenBy(x => x.BestRank)
            .ThenBy(x => x.Hit.DocumentId, StringComparer.Ordinal)
            .ThenBy(x => x.Hit.ChunkId, StringComparer.Ordinal)
            .Take(limit)
            .Select(x => x.Hit with { Score = x.Score })
            .ToArray();
    }

    private static void AddRanked(
        Dictionary<HitKey, FusionState> fused,
        IReadOnlyList<KnowledgeSearchHit> ranked,
        int rrfK)
    {
        for (var index = 0; index < ranked.Count; index++)
        {
            var hit = ranked[index];
            var rank = index + 1;
            var key = new HitKey(hit.DocumentId, hit.ChunkId);
            var contribution = 1d / (rrfK + rank);

            if (fused.TryGetValue(key, out var existing))
            {
                fused[key] = existing with
                {
                    Score = existing.Score + contribution,
                    BestRank = Math.Min(existing.BestRank, rank)
                };
            }
            else
            {
                fused[key] = new FusionState(hit, contribution, rank);
            }
        }
    }

    private readonly record struct HitKey(string DocumentId, string ChunkId);
    private sealed record FusionState(KnowledgeSearchHit Hit, double Score, int BestRank);
}
