using System.Net;
using System.Net.Http;
using System.Text;
using MLLM.Workbench.Knowledge.Embeddings;
using Xunit;

namespace MLLM.Workbench.Knowledge.Tests;

public sealed class LocalEmbeddingProviderTests
{
    [Fact]
    public void Constructor_rejects_non_loopback_endpoint()
    {
        var options = new LocalOpenAiEmbeddingOptions(
            new Uri("https://example.com/v1/embeddings"),
            "bge-small-zh-v1.5",
            512);

        var error = Assert.Throws<ArgumentException>(() => new LocalOpenAiEmbeddingProvider(options));

        Assert.Contains("loopback", error.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Embed_posts_openai_compatible_request_and_parses_vector()
    {
        var handler = new RecordingHandler(_ => new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(
                "{\"data\":[{\"embedding\":[0.5,0.25,-0.75]}],\"model\":\"bge-test\"}",
                Encoding.UTF8,
                "application/json")
        });
        using var client = new HttpClient(handler);
        var provider = new LocalOpenAiEmbeddingProvider(
            new LocalOpenAiEmbeddingOptions(new Uri("http://127.0.0.1:8081/v1/embeddings"), "bge-test", 3),
            client);

        var vector = await provider.EmbedAsync("整车软件制造", CancellationToken.None);

        Assert.Equal("local-openai-compatible", provider.ProviderId);
        Assert.Equal("bge-test", provider.ModelId);
        Assert.Equal(3, provider.Dimension);
        Assert.Equal(new float[] { 0.5f, 0.25f, -0.75f }, vector.ToArray());
        Assert.Equal(HttpMethod.Post, handler.LastRequest?.Method);
        Assert.Equal("http://127.0.0.1:8081/v1/embeddings", handler.LastRequest?.RequestUri?.ToString());
        Assert.Contains("\"model\":\"bge-test\"", handler.LastBody, StringComparison.Ordinal);
        Assert.Contains("\"input\":\"整车软件制造\"", handler.LastBody, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Embed_rejects_dimension_mismatch_from_local_server()
    {
        var handler = new RecordingHandler(_ => new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent("{\"data\":[{\"embedding\":[1,2]}]}", Encoding.UTF8, "application/json")
        });
        using var client = new HttpClient(handler);
        var provider = new LocalOpenAiEmbeddingProvider(
            new LocalOpenAiEmbeddingOptions(new Uri("http://localhost:8081/v1/embeddings"), "bge-test", 3),
            client);

        var error = await Assert.ThrowsAsync<InvalidOperationException>(async () =>
            await provider.EmbedAsync("test", CancellationToken.None));

        Assert.Contains("dimension", error.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Embed_surfaces_local_server_http_failure_without_fallback_to_cloud()
    {
        var handler = new RecordingHandler(_ => new HttpResponseMessage(HttpStatusCode.ServiceUnavailable)
        {
            Content = new StringContent("local model not ready", Encoding.UTF8, "text/plain")
        });
        using var client = new HttpClient(handler);
        var provider = new LocalOpenAiEmbeddingProvider(
            new LocalOpenAiEmbeddingOptions(new Uri("http://127.0.0.1:8081/v1/embeddings"), "bge-test", 3),
            client);

        var error = await Assert.ThrowsAsync<HttpRequestException>(async () =>
            await provider.EmbedAsync("test", CancellationToken.None));

        Assert.Contains("503", error.Message, StringComparison.Ordinal);
        Assert.Equal(1, handler.CallCount);
    }

    private sealed class RecordingHandler : HttpMessageHandler
    {
        private readonly Func<HttpRequestMessage, HttpResponseMessage> _responseFactory;

        public RecordingHandler(Func<HttpRequestMessage, HttpResponseMessage> responseFactory)
        {
            _responseFactory = responseFactory;
        }

        public int CallCount { get; private set; }
        public HttpRequestMessage? LastRequest { get; private set; }
        public string LastBody { get; private set; } = string.Empty;

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            CallCount++;
            LastRequest = request;
            LastBody = request.Content is null
                ? string.Empty
                : await request.Content.ReadAsStringAsync(cancellationToken);
            return _responseFactory(request);
        }
    }
}
