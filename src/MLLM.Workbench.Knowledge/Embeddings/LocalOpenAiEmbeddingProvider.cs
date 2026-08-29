using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace MLLM.Workbench.Knowledge.Embeddings;

public sealed record LocalOpenAiEmbeddingOptions(
    Uri Endpoint,
    string ModelId,
    int Dimension);

public sealed class LocalOpenAiEmbeddingProvider : IEmbeddingProvider
{
    private static readonly HttpClient SharedHttpClient = new();
    private readonly Uri _endpoint;
    private readonly HttpClient _httpClient;

    public LocalOpenAiEmbeddingProvider(LocalOpenAiEmbeddingOptions options, HttpClient? httpClient = null)
    {
        ArgumentNullException.ThrowIfNull(options);
        ArgumentNullException.ThrowIfNull(options.Endpoint);
        if (!options.Endpoint.IsAbsoluteUri)
            throw new ArgumentException("Embedding endpoint must be an absolute URI.", nameof(options));
        if (!options.Endpoint.IsLoopback)
            throw new ArgumentException("Embedding endpoint must be loopback-only (localhost/127.0.0.1/::1).", nameof(options));
        if (options.Endpoint.Scheme is not ("http" or "https"))
            throw new ArgumentException("Embedding endpoint must use HTTP or HTTPS.", nameof(options));
        if (string.IsNullOrWhiteSpace(options.ModelId))
            throw new ArgumentException("Embedding model id is required.", nameof(options));
        if (options.Dimension < 1)
            throw new ArgumentOutOfRangeException(nameof(options), "Embedding dimension must be positive.");

        _endpoint = options.Endpoint;
        ModelId = options.ModelId.Trim();
        Dimension = options.Dimension;
        _httpClient = httpClient ?? SharedHttpClient;
    }

    public string ProviderId => "local-openai-compatible";
    public string ModelId { get; }
    public int Dimension { get; }

    public async Task<ReadOnlyMemory<float>> EmbedAsync(string text, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(text))
            throw new ArgumentException("Embedding input text is required.", nameof(text));

        var json = JsonSerializer.Serialize(new EmbeddingRequest(ModelId, text));
        using var request = new HttpRequestMessage(HttpMethod.Post, _endpoint)
        {
            Content = new StringContent(json, Encoding.UTF8, "application/json")
        };
        using var response = await _httpClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken).ConfigureAwait(false);
        var body = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);

        if (!response.IsSuccessStatusCode)
        {
            var detail = body.Length <= 256 ? body : body[..256];
            throw new HttpRequestException(
                $"Local embedding endpoint returned HTTP {(int)response.StatusCode} ({response.StatusCode}). {detail}".Trim());
        }

        float[] vector;
        try
        {
            using var document = JsonDocument.Parse(body);
            if (!document.RootElement.TryGetProperty("data", out var data) ||
                data.ValueKind != JsonValueKind.Array ||
                data.GetArrayLength() < 1)
            {
                throw new InvalidDataException("Local embedding response is missing data[0].");
            }

            var first = data[0];
            if (!first.TryGetProperty("embedding", out var embedding) || embedding.ValueKind != JsonValueKind.Array)
                throw new InvalidDataException("Local embedding response is missing data[0].embedding.");

            vector = new float[embedding.GetArrayLength()];
            var index = 0;
            foreach (var value in embedding.EnumerateArray())
            {
                if (value.ValueKind != JsonValueKind.Number || !value.TryGetSingle(out var number) || !float.IsFinite(number))
                    throw new InvalidDataException("Local embedding response contains a non-finite or non-numeric value.");
                vector[index++] = number;
            }
        }
        catch (JsonException ex)
        {
            throw new InvalidDataException("Local embedding endpoint returned invalid JSON.", ex);
        }

        if (vector.Length != Dimension)
            throw new InvalidOperationException($"Embedding dimension mismatch. expected={Dimension} actual={vector.Length}");
        if (vector.All(static value => value == 0f))
            throw new InvalidOperationException("Local embedding endpoint returned a zero-magnitude vector.");

        return vector;
    }

    private sealed record EmbeddingRequest(
        [property: JsonPropertyName("model")] string Model,
        [property: JsonPropertyName("input")] string Input);
}
