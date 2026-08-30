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
        AddRanked(fused, lexical, rrfK, isLexical: true);
        AddRanked(fused, semantic, rrfK, isLexical: false);

        return fused.Values
            .OrderByDescending(x => x.Score)
            .ThenBy(x => x.BestRank)
            .ThenBy(x => x.Hit.DocumentId, StringComparer.Ordinal)
            .ThenBy(x => x.Hit.ChunkId, StringComparer.Ordinal)
            .Take(limit)
            .Select(x => x.Hit with
            {
                Score = x.Score,
                Diagnostics = new KnowledgeSearchDiagnostics(
                    Method: "Hybrid/RRF",
                    LexicalRank: x.LexicalRank,
                    LexicalScore: x.LexicalScore,
                    SemanticRank: x.SemanticRank,
                    SemanticScore: x.SemanticScore,
                    LexicalRrfContribution: x.LexicalRrfContribution,
                    SemanticRrfContribution: x.SemanticRrfContribution,
                    RrfK: rrfK)
            })
            .ToArray();
    }

    private static void AddRanked(
        Dictionary<HitKey, FusionState> fused,
        IReadOnlyList<KnowledgeSearchHit> ranked,
        int rrfK,
        bool isLexical)
    {
        for (var index = 0; index < ranked.Count; index++)
        {
            var hit = ranked[index];
            var rank = index + 1;
            var key = new HitKey(hit.DocumentId, hit.ChunkId);
            var contribution = 1d / (rrfK + rank);

            if (!fused.TryGetValue(key, out var state))
                state = new FusionState(hit, 0d, rank, null, null, null, null, null, null);

            state = state with
            {
                Score = state.Score + contribution,
                BestRank = Math.Min(state.BestRank, rank)
            };

            state = isLexical
                ? state with
                {
                    LexicalRank = rank,
                    LexicalScore = hit.Score,
                    LexicalRrfContribution = contribution
                }
                : state with
                {
                    SemanticRank = rank,
                    SemanticScore = hit.Score,
                    SemanticRrfContribution = contribution
                };

            fused[key] = state;
        }
    }

    private readonly record struct HitKey(string DocumentId, string ChunkId);

    private sealed record FusionState(
        KnowledgeSearchHit Hit,
        double Score,
        int BestRank,
        int? LexicalRank,
        double? LexicalScore,
        double? LexicalRrfContribution,
        int? SemanticRank,
        double? SemanticScore,
        double? SemanticRrfContribution);
}
