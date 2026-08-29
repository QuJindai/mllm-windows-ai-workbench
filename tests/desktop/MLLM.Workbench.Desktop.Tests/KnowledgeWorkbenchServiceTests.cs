using MLLM.Workbench.Desktop.Services.Knowledge;
using MLLM.Workbench.Knowledge.Embeddings;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class KnowledgeWorkbenchServiceTests
{
    [Fact]
    public async Task Markdown_import_is_searchable_and_survives_service_reopen()
    {
        var root = NewTempRoot();
        var source = Path.Combine(root, "整车软件制造管控.md");
        await File.WriteAllTextAsync(source, "# 标准\n\n整车软件制造管控要求软件版本可追溯，并保留完整证据链。\n\n第二段用于验证持久化。", CancellationToken.None);

        try
        {
            using (var first = new KnowledgeWorkbenchService(root))
            {
                var snapshot = await first.GetSnapshotAsync(CancellationToken.None);
                Assert.True(snapshot.Fts5Ready);
                Assert.False(snapshot.EmbeddingConfigured);
                Assert.Equal(Path.Combine(root, "knowledge", "knowledge.db"), snapshot.DatabasePath);

                await first.ImportFileAsync(source, CancellationToken.None);
                var hits = await first.SearchAsync("软件版本可追溯", KnowledgeSearchMode.Fts5, 10, CancellationToken.None);

                var hit = Assert.Single(hits);
                Assert.Equal(Path.GetFullPath(source), hit.SourceUri);
                Assert.Contains("软件版本可追溯", hit.Excerpt, StringComparison.Ordinal);
                Assert.False(string.IsNullOrWhiteSpace(hit.DocumentId));
                Assert.False(string.IsNullOrWhiteSpace(hit.ChunkId));
            }

            using (var reopened = new KnowledgeWorkbenchService(root))
            {
                var hits = await reopened.SearchAsync("持久化", KnowledgeSearchMode.Fts5, 10, CancellationToken.None);
                Assert.NotEmpty(hits);
                Assert.Equal(Path.GetFullPath(source), hits[0].SourceUri);
            }
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    [Fact]
    public async Task Embedding_and_hybrid_are_rejected_when_no_real_provider_is_configured()
    {
        var root = NewTempRoot();
        try
        {
            using var service = new KnowledgeWorkbenchService(root);
            var snapshot = await service.GetSnapshotAsync(CancellationToken.None);
            Assert.False(snapshot.EmbeddingConfigured);
            Assert.False(snapshot.HybridReady);

            await Assert.ThrowsAsync<InvalidOperationException>(() =>
                service.SearchAsync("test", KnowledgeSearchMode.Embedding, 10, CancellationToken.None));
            await Assert.ThrowsAsync<InvalidOperationException>(() =>
                service.SearchAsync("test", KnowledgeSearchMode.Hybrid, 10, CancellationToken.None));
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    [Fact]
    public async Task Configured_provider_indexes_on_import_and_enables_hybrid_search()
    {
        var root = NewTempRoot();
        var source = Path.Combine(root, "semantic.md");
        await File.WriteAllTextAsync(source, "整车车辆制造软件追溯", CancellationToken.None);

        try
        {
            using var service = new KnowledgeWorkbenchService(root, new VehicleEmbeddingProvider());
            var snapshot = await service.GetSnapshotAsync(CancellationToken.None);
            Assert.True(snapshot.EmbeddingConfigured);
            Assert.True(snapshot.HybridReady);
            Assert.Equal("ci-local", snapshot.EmbeddingProvider);
            Assert.Equal("vehicle-3d", snapshot.EmbeddingModel);

            await service.ImportFileAsync(source, CancellationToken.None);
            var semantic = await service.SearchAsync("automobile production", KnowledgeSearchMode.Embedding, 10, CancellationToken.None);
            var hybrid = await service.SearchAsync("车辆制造", KnowledgeSearchMode.Hybrid, 10, CancellationToken.None);

            Assert.NotEmpty(semantic);
            Assert.NotEmpty(hybrid);
            Assert.Equal(Path.GetFullPath(source), hybrid[0].SourceUri);
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    [Fact]
    public async Task Unsupported_binary_document_is_rejected_instead_of_fake_import()
    {
        var root = NewTempRoot();
        var source = Path.Combine(root, "manual.pdf");
        await File.WriteAllBytesAsync(source, [0x25, 0x50, 0x44, 0x46], CancellationToken.None);

        try
        {
            using var service = new KnowledgeWorkbenchService(root);
            var error = await Assert.ThrowsAsync<NotSupportedException>(() =>
                service.ImportFileAsync(source, CancellationToken.None));
            Assert.Contains("pdf", error.Message, StringComparison.OrdinalIgnoreCase);
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    private static string NewTempRoot()
    {
        var root = Path.Combine(Path.GetTempPath(), "mllm-desktop-knowledge", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        return root;
    }

    private sealed class VehicleEmbeddingProvider : IEmbeddingProvider
    {
        public string ProviderId => "ci-local";
        public string ModelId => "vehicle-3d";
        public int Dimension => 3;

        public Task<ReadOnlyMemory<float>> EmbedAsync(string text, CancellationToken cancellationToken)
        {
            var normalized = text.ToLowerInvariant();
            float[] vector =
                normalized.Contains("车辆", StringComparison.Ordinal) ||
                normalized.Contains("整车", StringComparison.Ordinal) ||
                normalized.Contains("automobile", StringComparison.Ordinal) ||
                normalized.Contains("vehicle", StringComparison.Ordinal)
                    ? [1f, 0f, 0f]
                    : [0f, 0f, 1f];
            return Task.FromResult<ReadOnlyMemory<float>>(vector);
        }
    }
}
