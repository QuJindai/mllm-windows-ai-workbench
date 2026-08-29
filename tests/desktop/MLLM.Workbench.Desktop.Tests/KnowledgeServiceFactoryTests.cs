using System.IO;
using MLLM.Workbench.Desktop.Services.Knowledge;
using MLLM.Workbench.Knowledge.Embeddings;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class KnowledgeServiceFactoryTests
{
    [Fact]
    public async Task Complete_loopback_environment_configures_real_local_provider_without_startup_probe()
    {
        var root = NewTempRoot();
        var values = new Dictionary<string, string?>
        {
            [LocalEmbeddingEnvironment.UrlVariable] = "http://127.0.0.1:8081/v1/embeddings",
            [LocalEmbeddingEnvironment.ModelVariable] = "bge-small-zh-v1.5",
            [LocalEmbeddingEnvironment.DimensionVariable] = "512"
        };

        try
        {
            using var service = KnowledgeServiceFactory.Create(root, name => values.GetValueOrDefault(name));
            var snapshot = await service.GetSnapshotAsync(CancellationToken.None);

            Assert.True(snapshot.Fts5Ready);
            Assert.True(snapshot.EmbeddingConfigured);
            Assert.Null(snapshot.EmbeddingConfigurationError);
            Assert.Equal("local-openai-compatible", snapshot.EmbeddingProvider);
            Assert.Equal("bge-small-zh-v1.5", snapshot.EmbeddingModel);
            Assert.Equal(0, snapshot.EmbeddingTotalChunks);
            Assert.Equal(0, snapshot.EmbeddingIndexedChunks);
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    [Fact]
    public async Task Partial_environment_keeps_fts_available_and_surfaces_configuration_error()
    {
        var root = NewTempRoot();
        var values = new Dictionary<string, string?>
        {
            [LocalEmbeddingEnvironment.UrlVariable] = "http://localhost:8081/v1/embeddings",
            [LocalEmbeddingEnvironment.ModelVariable] = "bge-small-zh-v1.5"
        };

        try
        {
            using var service = KnowledgeServiceFactory.Create(root, name => values.GetValueOrDefault(name));
            var snapshot = await service.GetSnapshotAsync(CancellationToken.None);

            Assert.True(snapshot.Fts5Ready);
            Assert.False(snapshot.EmbeddingConfigured);
            Assert.Contains(LocalEmbeddingEnvironment.DimensionVariable, snapshot.EmbeddingConfigurationError, StringComparison.Ordinal);
            Assert.False(snapshot.HybridReady);
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    private static string NewTempRoot()
    {
        var root = Path.Combine(Path.GetTempPath(), "mllm-desktop-knowledge-factory", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        return root;
    }
}
