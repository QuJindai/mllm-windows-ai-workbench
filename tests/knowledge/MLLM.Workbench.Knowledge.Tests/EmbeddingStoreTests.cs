using MLLM.Workbench.Knowledge;
using MLLM.Workbench.Knowledge.Embeddings;
using Xunit;

namespace MLLM.Workbench.Knowledge.Tests;

public sealed class EmbeddingStoreTests
{
    [Fact]
    public async Task Vector_index_survives_reopen_and_search_uses_persisted_chunk_vectors()
    {
        var root = Path.Combine(Path.GetTempPath(), "mllm-embedding-tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var databasePath = Path.Combine(root, "knowledge.db");
        try
        {
            var indexProvider = new DeterministicEmbeddingProvider();
            await using (var store = new KnowledgeStore(new KnowledgeStoreOptions(databasePath)))
            {
                await store.InitializeAsync(CancellationToken.None);
                await store.UpsertDocumentAsync(
                    new KnowledgeDocument(
                        "doc-semantic",
                        @"C:\Knowledge\semantic.md",
                        "语义检索样本",
                        [
                            new KnowledgeChunk("vehicle", 0, "整车车辆制造软件版本追溯"),
                            new KnowledgeChunk("fruit", 1, "香蕉苹果水果库存管理")
                        ]),
                    CancellationToken.None);

                await store.IndexEmbeddingsAsync("doc-semantic", indexProvider, CancellationToken.None);
                Assert.Equal(2, indexProvider.CallCount);
            }

            var queryProvider = new DeterministicEmbeddingProvider();
            await using (var reopened = new KnowledgeStore(new KnowledgeStoreOptions(databasePath)))
            {
                await reopened.InitializeAsync(CancellationToken.None);
                var hits = await reopened.SearchVectorAsync("automobile production", queryProvider, 5, CancellationToken.None);

                var first = Assert.Single(hits, x => x.ChunkId == "vehicle");
                Assert.Equal("doc-semantic", first.DocumentId);
                Assert.Equal(@"C:\Knowledge\semantic.md", first.SourceUri);
                Assert.True(first.Score > 0.9);
                Assert.Equal(1, queryProvider.CallCount);
            }
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    [Fact]
    public async Task Incremental_backfill_indexes_pending_chunks_reports_progress_and_survives_reopen()
    {
        var root = Path.Combine(Path.GetTempPath(), "mllm-embedding-tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var databasePath = Path.Combine(root, "knowledge.db");

        try
        {
            var provider = new DeterministicEmbeddingProvider();
            var progressEvents = new List<EmbeddingIndexProgress>();

            await using (var store = new KnowledgeStore(new KnowledgeStoreOptions(databasePath)))
            {
                await store.InitializeAsync(CancellationToken.None);
                await store.UpsertDocumentAsync(
                    new KnowledgeDocument(
                        "doc-backfill",
                        "backfill.md",
                        "backfill",
                        [
                            new KnowledgeChunk("backfill-vehicle", 0, "整车车辆制造"),
                            new KnowledgeChunk("backfill-fruit", 1, "香蕉苹果")
                        ]),
                    CancellationToken.None);

                var before = await store.GetEmbeddingIndexStatusAsync(provider, CancellationToken.None);
                Assert.Equal(2, before.TotalChunks);
                Assert.Equal(0, before.IndexedChunks);
                Assert.Equal(2, before.PendingChunks);

                var after = await store.IndexMissingEmbeddingsAsync(
                    provider,
                    new InlineProgress<EmbeddingIndexProgress>(progressEvents.Add),
                    CancellationToken.None);

                Assert.Equal(2, after.TotalChunks);
                Assert.Equal(2, after.IndexedChunks);
                Assert.Equal(0, after.PendingChunks);
                Assert.Equal(2, provider.CallCount);
                Assert.Equal([1, 2], progressEvents.Select(x => x.CompletedChunks).ToArray());
                Assert.All(progressEvents, x => Assert.Equal(2, x.TotalChunks));
                Assert.All(progressEvents, x => Assert.False(string.IsNullOrWhiteSpace(x.ChunkId)));

                var secondPass = await store.IndexMissingEmbeddingsAsync(provider, null, CancellationToken.None);
                Assert.Equal(2, secondPass.IndexedChunks);
                Assert.Equal(2, provider.CallCount);
            }

            await using (var reopened = new KnowledgeStore(new KnowledgeStoreOptions(databasePath)))
            {
                await reopened.InitializeAsync(CancellationToken.None);
                var status = await reopened.GetEmbeddingIndexStatusAsync(provider, CancellationToken.None);
                Assert.Equal(2, status.TotalChunks);
                Assert.Equal(2, status.IndexedChunks);
                Assert.Equal(0, status.PendingChunks);
            }
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    [Fact]
    public async Task Reimport_invalidates_old_vectors_until_document_is_reembedded()
    {
        await using var fixture = new TempKnowledgeStore();
        await fixture.Store.InitializeAsync(CancellationToken.None);
        var provider = new DeterministicEmbeddingProvider();

        await fixture.Store.UpsertDocumentAsync(
            new KnowledgeDocument("doc-a", "a.md", "a", [new KnowledgeChunk("a1", 0, "车辆制造")]),
            CancellationToken.None);
        await fixture.Store.IndexEmbeddingsAsync("doc-a", provider, CancellationToken.None);
        Assert.NotEmpty(await fixture.Store.SearchVectorAsync("automobile", provider, 5, CancellationToken.None));

        await fixture.Store.UpsertDocumentAsync(
            new KnowledgeDocument("doc-a", "a.md", "a", [new KnowledgeChunk("a2", 0, "香蕉水果")]),
            CancellationToken.None);

        Assert.Empty(await fixture.Store.SearchVectorAsync("automobile", provider, 5, CancellationToken.None));
    }

    [Fact]
    public async Task Provider_dimension_mismatch_is_rejected_before_persisting_vectors()
    {
        await using var fixture = new TempKnowledgeStore();
        await fixture.Store.InitializeAsync(CancellationToken.None);
        await fixture.Store.UpsertDocumentAsync(
            new KnowledgeDocument("doc-bad", "bad.md", "bad", [new KnowledgeChunk("bad1", 0, "车辆")]),
            CancellationToken.None);

        var error = await Assert.ThrowsAsync<InvalidOperationException>(() =>
            fixture.Store.IndexEmbeddingsAsync("doc-bad", new BadDimensionProvider(), CancellationToken.None));

        Assert.Contains("dimension", error.Message, StringComparison.OrdinalIgnoreCase);
    }

    private sealed class DeterministicEmbeddingProvider : IEmbeddingProvider
    {
        public string ProviderId => "ci-deterministic";
        public string ModelId => "semantic-3d-v1";
        public int Dimension => 3;
        public int CallCount { get; private set; }

        public Task<ReadOnlyMemory<float>> EmbedAsync(string text, CancellationToken cancellationToken)
        {
            CallCount++;
            var normalized = text.ToLowerInvariant();
            float[] vector =
                normalized.Contains("车辆", StringComparison.Ordinal) ||
                normalized.Contains("整车", StringComparison.Ordinal) ||
                normalized.Contains("automobile", StringComparison.Ordinal) ||
                normalized.Contains("vehicle", StringComparison.Ordinal)
                    ? [1f, 0f, 0f]
                    : normalized.Contains("香蕉", StringComparison.Ordinal) ||
                      normalized.Contains("苹果", StringComparison.Ordinal) ||
                      normalized.Contains("fruit", StringComparison.Ordinal) ||
                      normalized.Contains("banana", StringComparison.Ordinal)
                        ? [0f, 1f, 0f]
                        : [0f, 0f, 1f];
            return Task.FromResult<ReadOnlyMemory<float>>(vector);
        }
    }

    private sealed class BadDimensionProvider : IEmbeddingProvider
    {
        public string ProviderId => "ci-bad";
        public string ModelId => "bad-dimension";
        public int Dimension => 3;
        public Task<ReadOnlyMemory<float>> EmbedAsync(string text, CancellationToken cancellationToken) =>
            Task.FromResult<ReadOnlyMemory<float>>(new float[] { 1f, 0f });
    }

    private sealed class InlineProgress<T>(Action<T> report) : IProgress<T>
    {
        public void Report(T value) => report(value);
    }

    private sealed class TempKnowledgeStore : IAsyncDisposable
    {
        private readonly string _root;

        public TempKnowledgeStore()
        {
            _root = Path.Combine(Path.GetTempPath(), "mllm-embedding-tests", Guid.NewGuid().ToString("N"));
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
