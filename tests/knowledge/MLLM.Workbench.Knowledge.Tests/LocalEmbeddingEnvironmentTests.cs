using MLLM.Workbench.Knowledge.Embeddings;
using Xunit;

namespace MLLM.Workbench.Knowledge.Tests;

public sealed class LocalEmbeddingEnvironmentTests
{
    [Fact]
    public void Empty_environment_keeps_embedding_unconfigured_without_error()
    {
        var resolution = LocalEmbeddingEnvironment.Resolve(_ => null);

        Assert.Null(resolution.Provider);
        Assert.Null(resolution.Error);
        Assert.False(resolution.IsConfigured);
    }

    [Fact]
    public void Partial_environment_reports_configuration_error_instead_of_fake_provider()
    {
        var values = new Dictionary<string, string?>
        {
            [LocalEmbeddingEnvironment.UrlVariable] = "http://127.0.0.1:8081/v1/embeddings",
            [LocalEmbeddingEnvironment.ModelVariable] = "bge-small-zh-v1.5"
        };

        var resolution = LocalEmbeddingEnvironment.Resolve(name => values.GetValueOrDefault(name));

        Assert.Null(resolution.Provider);
        Assert.False(resolution.IsConfigured);
        Assert.Contains(LocalEmbeddingEnvironment.DimensionVariable, resolution.Error, StringComparison.Ordinal);
    }

    [Fact]
    public void Complete_loopback_environment_creates_local_provider()
    {
        var values = new Dictionary<string, string?>
        {
            [LocalEmbeddingEnvironment.UrlVariable] = "http://localhost:8081/v1/embeddings",
            [LocalEmbeddingEnvironment.ModelVariable] = "bge-small-zh-v1.5",
            [LocalEmbeddingEnvironment.DimensionVariable] = "512"
        };

        var resolution = LocalEmbeddingEnvironment.Resolve(name => values.GetValueOrDefault(name));

        var provider = Assert.IsType<LocalOpenAiEmbeddingProvider>(resolution.Provider);
        Assert.Null(resolution.Error);
        Assert.True(resolution.IsConfigured);
        Assert.Equal("bge-small-zh-v1.5", provider.ModelId);
        Assert.Equal(512, provider.Dimension);
    }

    [Fact]
    public void Public_endpoint_is_rejected_and_never_falls_back_to_cloud()
    {
        var values = new Dictionary<string, string?>
        {
            [LocalEmbeddingEnvironment.UrlVariable] = "https://api.example.com/v1/embeddings",
            [LocalEmbeddingEnvironment.ModelVariable] = "remote-model",
            [LocalEmbeddingEnvironment.DimensionVariable] = "768"
        };

        var resolution = LocalEmbeddingEnvironment.Resolve(name => values.GetValueOrDefault(name));

        Assert.Null(resolution.Provider);
        Assert.False(resolution.IsConfigured);
        Assert.Contains("loopback", resolution.Error, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Invalid_dimension_is_reported_without_constructing_provider()
    {
        var values = new Dictionary<string, string?>
        {
            [LocalEmbeddingEnvironment.UrlVariable] = "http://127.0.0.1:8081/v1/embeddings",
            [LocalEmbeddingEnvironment.ModelVariable] = "bge-small-zh-v1.5",
            [LocalEmbeddingEnvironment.DimensionVariable] = "not-a-number"
        };

        var resolution = LocalEmbeddingEnvironment.Resolve(name => values.GetValueOrDefault(name));

        Assert.Null(resolution.Provider);
        Assert.Contains("dimension", resolution.Error, StringComparison.OrdinalIgnoreCase);
    }
}
