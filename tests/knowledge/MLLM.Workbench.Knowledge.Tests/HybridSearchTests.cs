using MLLM.Workbench.Knowledge;
using MLLM.Workbench.Knowledge.Embeddings;
using Xunit;

namespace MLLM.Workbench.Knowledge.Tests;

public sealed class HybridSearchTests
{
    [Fact]
    public void Rrf_overlap_outranks_single_source_hits_and_preserves_evidence()
    {
        var lexical = new[]
        {
            Hit("doc-a", "overlap", "a.md", "A", 0, "lexical overlap", 0.99),
            Hit("doc-b", "lexical-only", "b.md", "B", 0, "lexical only", 0.90)
        };
        var semantic = new[]
        {
            Hit("doc-a", "overlap", "a.md", "A", 0, "semantic overlap", 0.98),
            Hit("doc-c", "semantic-only", "c.md", "C", 0, "semantic only", 0.88)
        };

        var fused = HybridSearch.Fuse(lexical, semantic, 10);

        Assert.Equal(3, fused.Count);
        Assert.Equal("overlap", fused[0].ChunkId);
        Assert.Equal("doc-a", fused[0].DocumentId);
        Assert.Equal("a.md", fused[0].SourceUri);
        Assert.Equal("A", fused[0].Title);
        Assert.Contains(fused, x => x.ChunkId == "lexical-only");
        Assert.Contains(fused, x => x.ChunkId == "semantic-only");
        Assert.True(fused[0].Score > fused[1].Score);
    }

    [Fact]
    public void Rrf_ties_are_deterministic_by_document_and_chunk_identity()
    {
        var lexical = new[]
        {
            Hit("doc-z", "chunk-z", "z.md", "Z", 0, "z", 1),
            Hit("doc-a", "chunk-a", "a.md", "A", 0, "a", 1)
        };
        var semantic = new[]
        {
            Hit("doc-a", "chunk-a", "a.md", "A", 0, "a", 1),
            Hit("doc-z", "chunk-z", "z.md", "Z", 0, "z", 1)
        };

        var fused = HybridSearch.Fuse(lexical, semantic, 10);

        Assert.Equal(["doc-a", "doc-z"], fused.Select(x => x.DocumentId).ToArray());
    }

    [Fact]
    public async Task Store_hybrid_search_combines_lexical_and_semantic_candidates_with_evidence()
    {
        await using var fixture = new TempKnowledgeStore();
        await fixture.Store.InitializeAsync(CancellationToken.None);
        var provider = new TopicEmbeddingProvider();

        await fixture.Store.UpsertDocumentAsync(
            new KnowledgeDocument(
                "doc-overlap",
                @"C:\Knowledge\overlap.md",
                "Overlap",
                [new KnowledgeChunk("overlap", 0, "车辆制造软件版本追溯")]),
            CancellationToken.None);
        await fixture.Store.UpsertDocumentAsync(
            new KnowledgeDocument(
                "doc-semantic",
                @"C:\Knowledge\semantic-only.md",
                "Semantic",
                [new KnowledgeChunk("semantic-only", 0, "automobile production lineage")]),
            CancellationToken.None);
        await fixture.Store.UpsertDocumentAsync(
            new KnowledgeDocument(
                "doc-lexical",
                @"C:\Knowledge\lexical-only.md",
                "Lexical",
                [new KnowledgeChunk("lexical-only", 0, "车辆制造香蕉库存")]),
            CancellationToken.None);

        await fixture.Store.IndexEmbeddingsAsync("doc-overlap", provider, CancellationToken.None);
        await fixture.Store.IndexEmbeddingsAsync("doc-semantic", provider, CancellationToken.None);
        await fixture.Store.IndexEmbeddingsAsync("doc-lexical", provider, CancellationToken.None);

        var hits = await fixture.Store.SearchHybridAsync("车辆制造", provider, 10, CancellationToken.None);

        Assert.Equal("overlap", hits[0].ChunkId);
        Assert.Equal(@"C:\Knowledge\overlap.md", hits[0].SourceUri);
        Assert.Contains(hits, x => x.ChunkId == "semantic-only");
        Assert.Contains(hits, x => x.ChunkId == "lexical-only");
        Assert.All(hits, x =>
        {
            Assert.False(string.IsNullOrWhiteSpace(x.DocumentId));
            Assert.False(string.IsNullOrWhiteSpace(x.ChunkId));
            Assert.False(string.IsNullOrWhiteSpace(x.SourceUri));
            Assert.False(string.IsNullOrWhiteSpace(x.Excerpt));
        });
    }

    private static KnowledgeSearchHit Hit(
        string documentId,
        string chunkId,
        string sourceUri,
        string title,
        int ordinal,
        string excerpt,
        double score) =>
        new(documentId, chunkId, sourceUri, title, ordinal, excerpt, score);

    private sealed class TopicEmbeddingProvider : IEmbeddingProvider
    {
        public string ProviderId => "ci-topic";
        public string ModelId => "hybrid-3d-v1";
        public int Dimension => 3;

        public Task<ReadOnlyMemory<float>> EmbedAsync(string text, CancellationToken cancellationToken)
        {
            var normalized = text.ToLowerInvariant();
            float[] vector =
                normalized.Contains("香蕉", StringComparison.Ordinal) ||
                normalized.Contains("banana", StringComparison.Ordinal)
                    ? [0f, 1f, 0f]
                    : normalized.Contains("车辆", StringComparison.Ordinal) ||
                      normalized.Contains("automobile", StringComparison.Ordinal)
                        ? [1f, 0f, 0f]
                        : [0f, 0f, 1f];
            return Task.FromResult<ReadOnlyMemory<float>>(vector);
        }
    }

    private sealed class TempKnowledgeStore : IAsyncDisposable
    {
        private readonly string _root;

        public TempKnowledgeStore()
        {
            _root = Path.Combine(Path.GetTempPath(), "mllm-hybrid-tests", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_root);
            DatabasePath = Path.Combine(_root, "knowledge.db");
            Store = new KnowledgeStore(new KnowledgeStoreOptions(DatabasePath));
        }

        public string DatabasePath { get; }
        public KnowledgeStore Store { get; }

        public async ValueTask DisposeAsync()
        {
            await Store.DisposeAsync();
            try { Directory.Delete(_root, true); } catch { }
        }
    }
}
