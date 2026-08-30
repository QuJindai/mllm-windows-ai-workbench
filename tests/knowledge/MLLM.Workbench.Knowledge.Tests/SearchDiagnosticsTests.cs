using MLLM.Workbench.Knowledge.Embeddings;
using Xunit;

namespace MLLM.Workbench.Knowledge.Tests;

public sealed class SearchDiagnosticsTests
{
    [Fact]
    public async Task Fts_search_exposes_lexical_rank_and_raw_score()
    {
        await using var fixture = new TempKnowledgeStore();
        await fixture.Store.InitializeAsync(CancellationToken.None);
        await fixture.Store.UpsertDocumentAsync(
            new KnowledgeDocument(
                "doc-a",
                @"C:\Knowledge\a.md",
                "A",
                [
                    new KnowledgeChunk("a-0", 0, "vehicle software traceability evidence"),
                    new KnowledgeChunk("a-1", 1, "vehicle software traceability evidence secondary")
                ]),
            CancellationToken.None);

        var hits = await fixture.Store.SearchFtsAsync("software traceability evidence", 10, CancellationToken.None);

        Assert.Equal(2, hits.Count);
        Assert.Equal(1, hits[0].Diagnostics?.LexicalRank);
        Assert.Equal(hits[0].Score, hits[0].Diagnostics?.LexicalScore);
        Assert.Equal("FTS5", hits[0].Diagnostics?.Method);
        Assert.Null(hits[0].Diagnostics?.SemanticRank);
        Assert.Null(hits[0].Diagnostics?.LexicalRrfContribution);
        Assert.Equal(2, hits[1].Diagnostics?.LexicalRank);
    }

    [Fact]
    public async Task Vector_search_exposes_semantic_rank_and_cosine_score()
    {
        await using var fixture = new TempKnowledgeStore();
        await fixture.Store.InitializeAsync(CancellationToken.None);
        var provider = new TopicEmbeddingProvider();

        await fixture.Store.UpsertDocumentAsync(
            new KnowledgeDocument(
                "doc-a",
                @"C:\Knowledge\a.md",
                "A",
                [new KnowledgeChunk("a-0", 0, "vehicle production traceability")]),
            CancellationToken.None);
        await fixture.Store.UpsertDocumentAsync(
            new KnowledgeDocument(
                "doc-b",
                @"C:\Knowledge\b.md",
                "B",
                [new KnowledgeChunk("b-0", 0, "banana inventory")]),
            CancellationToken.None);
        await fixture.Store.IndexEmbeddingsAsync("doc-a", provider, CancellationToken.None);
        await fixture.Store.IndexEmbeddingsAsync("doc-b", provider, CancellationToken.None);

        var hits = await fixture.Store.SearchVectorAsync("automobile manufacturing", provider, 10, CancellationToken.None);

        var hit = Assert.Single(hits);
        Assert.Equal("a-0", hit.ChunkId);
        Assert.Equal(1, hit.Diagnostics?.SemanticRank);
        Assert.Equal(hit.Score, hit.Diagnostics?.SemanticScore);
        Assert.Equal("Embedding", hit.Diagnostics?.Method);
        Assert.Null(hit.Diagnostics?.LexicalRank);
        Assert.Null(hit.Diagnostics?.SemanticRrfContribution);
    }

    [Fact]
    public void Hybrid_fusion_exposes_channel_ranks_raw_scores_and_rrf_contributions()
    {
        var lexical = new[]
        {
            Hit("doc-a", "overlap", 0.91),
            Hit("doc-b", "lexical-only", 0.72)
        };
        var semantic = new[]
        {
            Hit("doc-c", "semantic-only", 0.95),
            Hit("doc-a", "overlap", 0.84)
        };

        var fused = HybridSearch.Fuse(lexical, semantic, 10, rrfK: 60);

        var overlap = Assert.Single(fused.Where(x => x.ChunkId == "overlap"));
        Assert.Equal("Hybrid/RRF", overlap.Diagnostics?.Method);
        Assert.Equal(60, overlap.Diagnostics?.RrfK);
        Assert.Equal(1, overlap.Diagnostics?.LexicalRank);
        Assert.Equal(0.91, overlap.Diagnostics?.LexicalScore);
        Assert.Equal(2, overlap.Diagnostics?.SemanticRank);
        Assert.Equal(0.84, overlap.Diagnostics?.SemanticScore);
        Assert.Equal(1d / 61d, overlap.Diagnostics?.LexicalRrfContribution, 12);
        Assert.Equal(1d / 62d, overlap.Diagnostics?.SemanticRrfContribution, 12);
        Assert.Equal((1d / 61d) + (1d / 62d), overlap.Score, 12);

        var lexicalOnly = Assert.Single(fused.Where(x => x.ChunkId == "lexical-only"));
        Assert.Equal(2, lexicalOnly.Diagnostics?.LexicalRank);
        Assert.Null(lexicalOnly.Diagnostics?.SemanticRank);
        Assert.Equal(1d / 62d, lexicalOnly.Diagnostics?.LexicalRrfContribution, 12);
        Assert.Null(lexicalOnly.Diagnostics?.SemanticRrfContribution);
    }

    private static KnowledgeSearchHit Hit(string documentId, string chunkId, double score) =>
        new(documentId, chunkId, documentId + ".md", documentId, 0, chunkId, score);

    private sealed class TopicEmbeddingProvider : IEmbeddingProvider
    {
        public string ProviderId => "ci-diagnostics";
        public string ModelId => "topic-3d";
        public int Dimension => 3;

        public Task<ReadOnlyMemory<float>> EmbedAsync(string text, CancellationToken cancellationToken)
        {
            var normalized = text.ToLowerInvariant();
            float[] vector =
                normalized.Contains("vehicle", StringComparison.Ordinal) ||
                normalized.Contains("automobile", StringComparison.Ordinal)
                    ? [1f, 0f, 0f]
                    : normalized.Contains("banana", StringComparison.Ordinal)
                        ? [0f, 1f, 0f]
                        : [0f, 0f, 1f];
            return Task.FromResult<ReadOnlyMemory<float>>(vector);
        }
    }

    private sealed class TempKnowledgeStore : IAsyncDisposable
    {
        private readonly string _root;

        public TempKnowledgeStore()
        {
            _root = Path.Combine(Path.GetTempPath(), "mllm-search-diagnostics", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_root);
            Store = new KnowledgeStore(new KnowledgeStoreOptions(Path.Combine(_root, "knowledge.db")));
        }

        public KnowledgeStore Store { get; }

        public async ValueTask DisposeAsync()
        {
            await Store.DisposeAsync();
            try { Directory.Delete(_root, true); } catch { }
        }
    }
}
