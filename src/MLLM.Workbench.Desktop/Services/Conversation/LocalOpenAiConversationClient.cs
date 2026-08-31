using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace MLLM.Workbench.Desktop.Services.Conversation;

public sealed class LocalOpenAiConversationClient : ILocalConversationClient, IDisposable
{
    private const int MaximumErrorCharacters = 4096;
    private readonly HttpClient _httpClient;
    private readonly ConcurrentDictionary<string, string> _chatPaths = new(StringComparer.Ordinal);
    private bool _disposed;

    public LocalOpenAiConversationClient()
        : this(CreateHandler())
    {
    }

    public LocalOpenAiConversationClient(HttpMessageHandler handler)
    {
        ArgumentNullException.ThrowIfNull(handler);
        _httpClient = new HttpClient(handler, disposeHandler: true)
        {
            Timeout = Timeout.InfiniteTimeSpan
        };
    }

    public async Task<ConversationRunResult> StreamAsync(
        LocalConversationEndpoint endpoint,
        ConversationRequest request,
        IProgress<ConversationDelta>? progress,
        CancellationToken cancellationToken)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        ArgumentNullException.ThrowIfNull(endpoint);
        ArgumentNullException.ThrowIfNull(request);

        var chatPath = await ResolveChatPathAsync(endpoint, cancellationToken).ConfigureAwait(false);
        var messages = BuildMessages(request);
        var payload = new
        {
            model = string.IsNullOrWhiteSpace(endpoint.ModelId) ? "local" : endpoint.ModelId,
            messages,
            temperature = request.Temperature,
            max_tokens = request.MaxOutputTokens,
            stream = true,
            stream_options = new { include_usage = true }
        };

        var payloadBytes = JsonSerializer.SerializeToUtf8Bytes(payload);
        using var content = new ByteArrayContent(payloadBytes);
        content.Headers.ContentType = new MediaTypeHeaderValue("application/json") { CharSet = "utf-8" };
        using var httpRequest = new HttpRequestMessage(HttpMethod.Post, new Uri(endpoint.BaseUri, chatPath))
        {
            Content = content
        };
        var stopwatch = Stopwatch.StartNew();
        TimeSpan? timeToFirstToken = null;
        var partial = new StringBuilder();
        var forwardingProgress = new InlineProgress<ConversationDelta>(delta =>
        {
            if (string.IsNullOrEmpty(delta.Content)) return;
            timeToFirstToken ??= stopwatch.Elapsed;
            partial.Append(delta.Content);
            progress?.Report(delta);
        });

        try
        {
            using var response = await _httpClient
                .SendAsync(httpRequest, HttpCompletionOption.ResponseHeadersRead, cancellationToken)
                .ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
            {
                var diagnostic = await ReadBoundedDiagnosticAsync(response, cancellationToken).ConfigureAwait(false);
                throw new ConversationClientException(
                    "CHAT_HTTP_ERROR",
                    $"Local model API returned HTTP {(int)response.StatusCode} {response.ReasonPhrase}. {diagnostic}".Trim());
            }

            await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
            var parsed = await new OpenAiSseReader()
                .ReadAsync(stream, forwardingProgress, cancellationToken)
                .ConfigureAwait(false);
            stopwatch.Stop();
            var metrics = BuildMetrics(timeToFirstToken, stopwatch.Elapsed, parsed.CompletionTokens);
            return new ConversationRunResult(
                ConversationRunState.Completed,
                parsed.ResponseText,
                metrics,
                []);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            stopwatch.Stop();
            return new ConversationRunResult(
                ConversationRunState.Cancelled,
                partial.ToString(),
                BuildMetrics(timeToFirstToken, stopwatch.Elapsed, null),
                [],
                "RUN_CANCELLED",
                "Conversation request was cancelled.");
        }
        catch (ConversationException)
        {
            throw;
        }
        catch (HttpRequestException ex)
        {
            throw new ConversationClientException("CHAT_HTTP_ERROR", "Local model API request failed.", ex);
        }
        catch (IOException ex)
        {
            throw new ConversationClientException("CHAT_STREAM_ERROR", "Local model API stream failed.", ex);
        }
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _httpClient.Dispose();
    }

    private async Task<string> ResolveChatPathAsync(
        LocalConversationEndpoint endpoint,
        CancellationToken cancellationToken)
    {
        var key = endpoint.BaseUri.AbsoluteUri;
        if (_chatPaths.TryGetValue(key, out var cached)) return cached;

        using var versioned = await _httpClient
            .GetAsync(new Uri(endpoint.BaseUri, "v1/models"), HttpCompletionOption.ResponseHeadersRead, cancellationToken)
            .ConfigureAwait(false);
        if (versioned.IsSuccessStatusCode)
            return _chatPaths.GetOrAdd(key, "v1/chat/completions");
        if (versioned.StatusCode != HttpStatusCode.NotFound)
            throw ProbeError(versioned.StatusCode, versioned.ReasonPhrase);

        using var unversioned = await _httpClient
            .GetAsync(new Uri(endpoint.BaseUri, "models"), HttpCompletionOption.ResponseHeadersRead, cancellationToken)
            .ConfigureAwait(false);
        if (unversioned.IsSuccessStatusCode)
            return _chatPaths.GetOrAdd(key, "chat/completions");

        throw ProbeError(unversioned.StatusCode, unversioned.ReasonPhrase);
    }

    private static IReadOnlyList<object> BuildMessages(ConversationRequest request)
    {
        var messages = new List<object>();
        if (!string.IsNullOrWhiteSpace(request.SystemPrompt))
            messages.Add(new { role = "system", content = request.SystemPrompt.Trim() });
        foreach (var message in request.History ?? [])
            messages.Add(new { role = message.Role, content = message.Content });
        messages.Add(new { role = "user", content = request.UserPrompt });
        return messages;
    }

    private static ConversationMetrics BuildMetrics(
        TimeSpan? timeToFirstToken,
        TimeSpan totalLatency,
        int? completionTokens)
    {
        double? tokensPerSecond = null;
        if (completionTokens.HasValue && timeToFirstToken.HasValue)
        {
            var decodeSeconds = (totalLatency - timeToFirstToken.Value).TotalSeconds;
            if (decodeSeconds > 0d) tokensPerSecond = completionTokens.Value / decodeSeconds;
        }

        return new ConversationMetrics(timeToFirstToken, totalLatency, completionTokens, tokensPerSecond);
    }

    private static async Task<string> ReadBoundedDiagnosticAsync(
        HttpResponseMessage response,
        CancellationToken cancellationToken)
    {
        await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        using var reader = new StreamReader(stream, Encoding.UTF8, true, 1024, leaveOpen: false);
        var buffer = new char[MaximumErrorCharacters];
        var read = await reader.ReadBlockAsync(buffer.AsMemory(), cancellationToken).ConfigureAwait(false);
        return new string(buffer, 0, read).Replace('\r', ' ').Replace('\n', ' ').Trim();
    }

    private static ConversationClientException ProbeError(HttpStatusCode statusCode, string? reason) =>
        new(
            "CHAT_ENDPOINT_UNSUPPORTED",
            $"Local model API capability probe returned HTTP {(int)statusCode} {reason}.".Trim());

    private static SocketsHttpHandler CreateHandler() => new()
    {
        UseProxy = false,
        AllowAutoRedirect = false,
        UseCookies = false,
        AutomaticDecompression = DecompressionMethods.None,
        ConnectTimeout = TimeSpan.FromSeconds(10)
    };

    private sealed class InlineProgress<T>(Action<T> report) : IProgress<T>
    {
        public void Report(T value) => report(value);
    }
}
