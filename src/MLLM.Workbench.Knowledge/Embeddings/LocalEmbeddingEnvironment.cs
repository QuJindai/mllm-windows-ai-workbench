using System.Globalization;

namespace MLLM.Workbench.Knowledge.Embeddings;

public sealed record LocalEmbeddingResolution(
    IEmbeddingProvider? Provider,
    string? Error)
{
    public bool IsConfigured => Provider is not null;
}

public static class LocalEmbeddingEnvironment
{
    public const string UrlVariable = "MLLM_EMBEDDING_URL";
    public const string ModelVariable = "MLLM_EMBEDDING_MODEL";
    public const string DimensionVariable = "MLLM_EMBEDDING_DIMENSION";

    public static LocalEmbeddingResolution Resolve()
        => Resolve(Environment.GetEnvironmentVariable);

    public static LocalEmbeddingResolution Resolve(Func<string, string?> readVariable)
    {
        ArgumentNullException.ThrowIfNull(readVariable);

        var rawUrl = Normalize(readVariable(UrlVariable));
        var model = Normalize(readVariable(ModelVariable));
        var rawDimension = Normalize(readVariable(DimensionVariable));

        if (rawUrl is null && model is null && rawDimension is null)
            return new LocalEmbeddingResolution(null, null);

        var missing = new List<string>(3);
        if (rawUrl is null)
            missing.Add(UrlVariable);
        if (model is null)
            missing.Add(ModelVariable);
        if (rawDimension is null)
            missing.Add(DimensionVariable);

        if (missing.Count > 0)
        {
            return new LocalEmbeddingResolution(
                null,
                $"Local embedding configuration is incomplete. Missing: {string.Join(", ", missing)}.");
        }

        if (!Uri.TryCreate(rawUrl, UriKind.Absolute, out var endpoint))
        {
            return new LocalEmbeddingResolution(
                null,
                $"{UrlVariable} must be an absolute HTTP(S) URI.");
        }

        if (endpoint.Scheme is not ("http" or "https"))
        {
            return new LocalEmbeddingResolution(
                null,
                $"{UrlVariable} must use HTTP or HTTPS.");
        }

        if (!endpoint.IsLoopback)
        {
            return new LocalEmbeddingResolution(
                null,
                $"{UrlVariable} must target a loopback endpoint only; cloud/public embedding endpoints are not allowed.");
        }

        if (!int.TryParse(rawDimension, NumberStyles.None, CultureInfo.InvariantCulture, out var dimension) || dimension < 1)
        {
            return new LocalEmbeddingResolution(
                null,
                $"{DimensionVariable} must be a positive integer embedding dimension.");
        }

        try
        {
            var provider = new LocalOpenAiEmbeddingProvider(
                new LocalOpenAiEmbeddingOptions(endpoint, model!, dimension));
            return new LocalEmbeddingResolution(provider, null);
        }
        catch (ArgumentException ex)
        {
            return new LocalEmbeddingResolution(null, ex.Message);
        }
    }

    private static string? Normalize(string? value)
        => string.IsNullOrWhiteSpace(value) ? null : value.Trim();
}
