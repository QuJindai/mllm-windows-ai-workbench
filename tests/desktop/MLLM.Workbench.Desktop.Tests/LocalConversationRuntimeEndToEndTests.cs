using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using MLLM.Workbench.Contracts.Services;
using MLLM.Workbench.Desktop.Services.Conversation;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class LocalConversationRuntimeEndToEndTests
{
    [Fact]
    public void Default_transport_disables_proxy_redirects_cookies_and_decompression()
    {
        var factory = typeof(LocalOpenAiConversationClient).GetMethod(
            "CreateHandler",
            System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static);
        Assert.NotNull(factory);

        using var handler = Assert.IsType<SocketsHttpHandler>(factory!.Invoke(null, null));

        Assert.False(handler.UseProxy);
        Assert.False(handler.AllowAutoRedirect);
        Assert.False(handler.UseCookies);
        Assert.Equal(DecompressionMethods.None, handler.AutomaticDecompression);
        Assert.Equal(TimeSpan.FromSeconds(10), handler.ConnectTimeout);
    }

    [Fact]
    public async Task Real_loopback_openai_stream_returns_answer_usage_and_measured_latency()
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        await using var server = new LoopbackChatServer();
        using var client = new LocalOpenAiConversationClient();
        var endpoint = LocalConversationEndpoint.FromService(Service(server.BaseUri.AbsoluteUri));
        var request = new ConversationRequest(
            SystemPrompt: "Answer locally.",
            UserPrompt: "Say hello.",
            History: [new ConversationMessage("assistant", "Earlier answer.")],
            Temperature: 0.2,
            MaxOutputTokens: 512,
            UseKnowledge: false);
        var deltas = new List<string>();

        var result = await client.StreamAsync(
            endpoint,
            request,
            new InlineProgress<ConversationDelta>(item => deltas.Add(item.Content)),
            timeout.Token);

        Assert.Equal(ConversationRunState.Completed, result.State);
        Assert.Equal("你好", result.ResponseText);
        Assert.Equal(["你", "好"], deltas);
        Assert.NotNull(result.Metrics.TimeToFirstToken);
        Assert.True(result.Metrics.TimeToFirstToken > TimeSpan.Zero);
        Assert.True(result.Metrics.TotalLatency >= result.Metrics.TimeToFirstToken);
        Assert.Equal(2, result.Metrics.CompletionTokens);
        Assert.True(result.Metrics.TokensPerSecond > 0);
        Assert.Equal(1, server.ModelProbeCount);
        Assert.Equal(1, server.ChatPostCount);

        using var document = JsonDocument.Parse(server.ChatRequestBody!);
        var root = document.RootElement;
        Assert.Equal("qwen-fixture", root.GetProperty("model").GetString());
        Assert.True(root.GetProperty("stream").GetBoolean());
        Assert.True(root.GetProperty("stream_options").GetProperty("include_usage").GetBoolean());
        Assert.Equal(0.2, root.GetProperty("temperature").GetDouble(), 3);
        Assert.Equal(512, root.GetProperty("max_tokens").GetInt32());
        var messages = root.GetProperty("messages").EnumerateArray().ToArray();
        Assert.Equal(
            ["system", "assistant", "user"],
            messages.Select(x => x.GetProperty("role").GetString() ?? string.Empty).ToArray());
        Assert.Equal("Say hello.", messages[2].GetProperty("content").GetString());
    }

    [Fact]
    public async Task Unversioned_capability_fallback_and_missing_usage_are_reported_without_estimation()
    {
        var paths = new List<string>();
        using var handler = new ScriptedHandler((request, cancellationToken) =>
        {
            paths.Add(request.RequestUri!.AbsolutePath);
            return Task.FromResult(request.RequestUri.AbsolutePath switch
            {
                "/v1/models" => new HttpResponseMessage(HttpStatusCode.NotFound),
                "/models" => JsonResponse("{\"data\":[]}"),
                "/chat/completions" => SseResponse(
                    "data: {\"choices\":[{\"index\":0,\"delta\":{\"content\":\"ok\"}}]}\n\n" +
                    "data: [DONE]\n\n"),
                _ => throw new InvalidOperationException("Unexpected path: " + request.RequestUri.AbsolutePath)
            });
        });
        using var client = new LocalOpenAiConversationClient(handler);

        var result = await client.StreamAsync(
            LocalConversationEndpoint.FromService(Service("http://127.0.0.1:8080")),
            Request(),
            null,
            CancellationToken.None);

        Assert.Equal(ConversationRunState.Completed, result.State);
        Assert.Equal("ok", result.ResponseText);
        Assert.Null(result.Metrics.CompletionTokens);
        Assert.Null(result.Metrics.TokensPerSecond);
        Assert.Equal(["/v1/models", "/models", "/chat/completions"], paths);
    }

    [Fact]
    public async Task Http_failure_returns_failed_result_with_elapsed_metrics()
    {
        using var handler = new ScriptedHandler((request, cancellationToken) => Task.FromResult(
            request.Method == HttpMethod.Get
                ? JsonResponse("{\"data\":[]}")
                : new HttpResponseMessage(HttpStatusCode.ServiceUnavailable)
                {
                    Content = new StringContent("bounded diagnostic")
                }));
        using var client = new LocalOpenAiConversationClient(handler);

        var result = await client.StreamAsync(
            LocalConversationEndpoint.FromService(Service("http://127.0.0.1:8080")),
            Request(),
            null,
            CancellationToken.None);

        Assert.Equal(ConversationRunState.Failed, result.State);
        Assert.Equal("CHAT_HTTP_ERROR", result.ErrorCode);
        Assert.Contains("503", result.ErrorMessage, StringComparison.Ordinal);
        Assert.True(result.Metrics.TotalLatency > TimeSpan.Zero);
    }

    [Fact]
    public async Task Transport_operation_cancellation_is_mapped_to_stable_timeout_metrics()
    {
        using var handler = new ScriptedHandler((request, cancellationToken) =>
            Task.FromException<HttpResponseMessage>(new OperationCanceledException("connect timeout")));
        using var client = new LocalOpenAiConversationClient(handler);

        var result = await client.StreamAsync(
            LocalConversationEndpoint.FromService(Service("http://127.0.0.1:8080")),
            Request(),
            null,
            CancellationToken.None);

        Assert.Equal(ConversationRunState.Failed, result.State);
        Assert.Equal("CHAT_TIMEOUT", result.ErrorCode);
        Assert.True(result.Metrics.TotalLatency > TimeSpan.Zero);
    }

    [Fact]
    public async Task Protocol_failure_preserves_partial_text_and_measured_timing()
    {
        using var handler = new ScriptedHandler((request, cancellationToken) => Task.FromResult(
            request.Method == HttpMethod.Get
                ? JsonResponse("{\"data\":[]}")
                : SseResponse(
                    "data: {\"choices\":[{\"index\":0,\"delta\":{\"content\":\"partial\"}}]}\n\n" +
                    "data: {not-json}\n\n")));
        using var client = new LocalOpenAiConversationClient(handler);

        var result = await client.StreamAsync(
            LocalConversationEndpoint.FromService(Service("http://127.0.0.1:8080")),
            Request(),
            null,
            CancellationToken.None);

        Assert.Equal(ConversationRunState.Failed, result.State);
        Assert.Equal("STREAM_PROTOCOL_ERROR", result.ErrorCode);
        Assert.Equal("partial", result.ResponseText);
        Assert.NotNull(result.Metrics.TimeToFirstToken);
        Assert.True(result.Metrics.TotalLatency >= result.Metrics.TimeToFirstToken);
    }

    [Fact]
    public async Task Caller_cancellation_preserves_partial_text_and_returns_cancelled()
    {
        var deltaSeen = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        using var handler = StreamingHandler(new BlockingAfterPrefixStream(PartialEventBytes()));
        using var client = new LocalOpenAiConversationClient(handler, requestTimeout: TimeSpan.FromSeconds(5));
        using var cancellation = new CancellationTokenSource();

        var run = client.StreamAsync(
            LocalConversationEndpoint.FromService(Service("http://127.0.0.1:8080")),
            Request(),
            new InlineProgress<ConversationDelta>(_ => deltaSeen.TrySetResult()),
            cancellation.Token);
        await deltaSeen.Task.WaitAsync(TimeSpan.FromSeconds(2));
        cancellation.Cancel();
        var result = await run.WaitAsync(TimeSpan.FromSeconds(2));

        Assert.Equal(ConversationRunState.Cancelled, result.State);
        Assert.Equal("RUN_CANCELLED", result.ErrorCode);
        Assert.Equal("partial", result.ResponseText);
        Assert.True(result.Metrics.TotalLatency > TimeSpan.Zero);
    }

    [Fact]
    public async Task Bounded_request_timeout_preserves_partial_text_and_returns_stable_failure()
    {
        using var handler = StreamingHandler(new BlockingAfterPrefixStream(PartialEventBytes()));
        using var client = new LocalOpenAiConversationClient(handler, requestTimeout: TimeSpan.FromMilliseconds(75));

        var result = await client.StreamAsync(
            LocalConversationEndpoint.FromService(Service("http://127.0.0.1:8080")),
            Request(),
            null,
            CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(2));

        Assert.Equal(ConversationRunState.Failed, result.State);
        Assert.Equal("RUN_TIMEOUT", result.ErrorCode);
        Assert.Equal("partial", result.ResponseText);
        Assert.NotNull(result.Metrics.TimeToFirstToken);
        Assert.True(result.Metrics.TotalLatency >= TimeSpan.FromMilliseconds(50));
    }

    private static ConversationRequest Request() =>
        new("system", "prompt", [], 0.2, 64, false);

    private static HttpResponseMessage JsonResponse(string json) =>
        new(HttpStatusCode.OK) { Content = new StringContent(json, Encoding.UTF8, "application/json") };

    private static HttpResponseMessage SseResponse(string value) =>
        new(HttpStatusCode.OK)
        {
            Content = new StreamContent(new MemoryStream(Encoding.UTF8.GetBytes(value), writable: false))
        };

    private static ScriptedHandler StreamingHandler(Stream stream) =>
        new((request, cancellationToken) => Task.FromResult(
            request.Method == HttpMethod.Get
                ? JsonResponse("{\"data\":[]}")
                : new HttpResponseMessage(HttpStatusCode.OK) { Content = new StreamContent(stream) }));

    private static byte[] PartialEventBytes() => Encoding.UTF8.GetBytes(
        "data: {\"choices\":[{\"index\":0,\"delta\":{\"content\":\"partial\"}}]}\n\n");

    private static ServiceDescriptor Service(string baseUrl) =>
        new(
            "local-model-api",
            "Local Model API",
            ManagedServiceState.Running,
            42,
            new Uri(baseUrl).Port,
            baseUrl,
            DateTimeOffset.UtcNow,
            1,
            "qwen-fixture",
            @"C:\Models\qwen.gguf",
            "Healthy",
            null,
            null,
            false,
            true,
            true,
            null);

    private sealed class InlineProgress<T>(Action<T> report) : IProgress<T>
    {
        public void Report(T value) => report(value);
    }

    private sealed class ScriptedHandler(
        Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> send) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken) => send(request, cancellationToken);
    }

    private sealed class BlockingAfterPrefixStream(byte[] prefix) : Stream
    {
        private bool _sent;
        public override bool CanRead => true;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => throw new NotSupportedException();
        public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
        public override void Flush() => throw new NotSupportedException();
        public override int Read(byte[] buffer, int offset, int count) => throw new NotSupportedException();
        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            if (!_sent)
            {
                _sent = true;
                prefix.CopyTo(buffer);
                return prefix.Length;
            }
            await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken);
            return 0;
        }
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    }

    private sealed class LoopbackChatServer : IAsyncDisposable
    {
        private const int MaxHeaderBytes = 64 * 1024;
        private readonly TcpListener _listener;
        private readonly CancellationTokenSource _cts = new();
        private readonly Task _acceptLoop;
        private int _modelProbeCount;
        private int _chatPostCount;

        public LoopbackChatServer()
        {
            _listener = new TcpListener(IPAddress.Loopback, 0);
            _listener.Start();
            var port = ((IPEndPoint)_listener.LocalEndpoint).Port;
            BaseUri = new Uri($"http://127.0.0.1:{port}/");
            _acceptLoop = Task.Run(() => AcceptLoopAsync(_cts.Token));
        }

        public Uri BaseUri { get; }
        public int ModelProbeCount => Volatile.Read(ref _modelProbeCount);
        public int ChatPostCount => Volatile.Read(ref _chatPostCount);
        public string? ChatRequestBody { get; private set; }

        public async ValueTask DisposeAsync()
        {
            _cts.Cancel();
            _listener.Stop();
            try { await _acceptLoop.ConfigureAwait(false); }
            catch (OperationCanceledException) { }
            catch (ObjectDisposedException) { }
            _cts.Dispose();
        }

        private async Task AcceptLoopAsync(CancellationToken cancellationToken)
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                TcpClient client;
                try
                {
                    client = await _listener.AcceptTcpClientAsync(cancellationToken).ConfigureAwait(false);
                }
                catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
                {
                    break;
                }
                catch (SocketException) when (cancellationToken.IsCancellationRequested)
                {
                    break;
                }

                await HandleClientAsync(client, cancellationToken).ConfigureAwait(false);
            }
        }

        private async Task HandleClientAsync(TcpClient client, CancellationToken cancellationToken)
        {
            using (client)
            await using (var stream = client.GetStream())
            {
                var request = await ReadRequestAsync(stream, cancellationToken).ConfigureAwait(false);
                if (request.RequestLine.StartsWith("GET /v1/models ", StringComparison.Ordinal))
                {
                    Interlocked.Increment(ref _modelProbeCount);
                    await WriteJsonAsync(stream, "{\"data\":[{\"id\":\"qwen-fixture\"}]}", cancellationToken).ConfigureAwait(false);
                    return;
                }

                if (!request.RequestLine.StartsWith("POST /v1/chat/completions ", StringComparison.Ordinal))
                    throw new InvalidDataException("Unexpected request: " + request.RequestLine);

                Interlocked.Increment(ref _chatPostCount);
                ChatRequestBody = Encoding.UTF8.GetString(request.Body);
                var headers = Encoding.ASCII.GetBytes(
                    "HTTP/1.1 200 OK\r\n" +
                    "Content-Type: text/event-stream; charset=utf-8\r\n" +
                    "Connection: close\r\n\r\n");
                await stream.WriteAsync(headers, cancellationToken).ConfigureAwait(false);
                await Task.Delay(30, cancellationToken).ConfigureAwait(false);
                await WriteSseAsync(stream, "{\"choices\":[{\"index\":0,\"delta\":{\"content\":\"你\"}}]}", cancellationToken).ConfigureAwait(false);
                await Task.Delay(30, cancellationToken).ConfigureAwait(false);
                await WriteSseAsync(stream, "{\"choices\":[{\"index\":0,\"delta\":{\"content\":\"好\"}}]}", cancellationToken).ConfigureAwait(false);
                await WriteSseAsync(stream, "{\"choices\":[],\"usage\":{\"completion_tokens\":2}}", cancellationToken).ConfigureAwait(false);
                await WriteSseAsync(stream, "[DONE]", cancellationToken).ConfigureAwait(false);
            }
        }

        private static async Task WriteJsonAsync(NetworkStream stream, string json, CancellationToken cancellationToken)
        {
            var body = Encoding.UTF8.GetBytes(json);
            var headers = Encoding.ASCII.GetBytes(
                "HTTP/1.1 200 OK\r\n" +
                "Content-Type: application/json\r\n" +
                $"Content-Length: {body.Length}\r\n" +
                "Connection: close\r\n\r\n");
            await stream.WriteAsync(headers, cancellationToken).ConfigureAwait(false);
            await stream.WriteAsync(body, cancellationToken).ConfigureAwait(false);
            await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
        }

        private static async Task WriteSseAsync(NetworkStream stream, string data, CancellationToken cancellationToken)
        {
            var bytes = Encoding.UTF8.GetBytes($"data: {data}\n\n");
            await stream.WriteAsync(bytes, cancellationToken).ConfigureAwait(false);
            await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
        }

        private static async Task<HttpRequest> ReadRequestAsync(NetworkStream stream, CancellationToken cancellationToken)
        {
            using var received = new MemoryStream();
            var buffer = new byte[4096];
            var headerEnd = -1;

            while (headerEnd < 0)
            {
                var read = await stream.ReadAsync(buffer, cancellationToken).ConfigureAwait(false);
                if (read == 0) throw new EndOfStreamException("HTTP request ended before headers completed.");
                received.Write(buffer, 0, read);
                if (received.Length > MaxHeaderBytes) throw new InvalidDataException("HTTP headers exceeded the test limit.");
                headerEnd = FindHeaderTerminator(received.GetBuffer(), checked((int)received.Length));
            }

            var allBytes = received.ToArray();
            var headerText = Encoding.ASCII.GetString(allBytes, 0, headerEnd);
            var headerLines = headerText.Split(["\r\n"], StringSplitOptions.None);
            var contentLength = 0;
            foreach (var line in headerLines.Skip(1))
            {
                var separator = line.IndexOf(':');
                if (separator <= 0 || !line[..separator].Trim().Equals("Content-Length", StringComparison.OrdinalIgnoreCase)) continue;
                contentLength = int.Parse(line[(separator + 1)..].Trim(), System.Globalization.CultureInfo.InvariantCulture);
            }

            var body = new byte[contentLength];
            var bodyOffset = headerEnd + 4;
            var buffered = Math.Min(contentLength, Math.Max(0, allBytes.Length - bodyOffset));
            if (buffered > 0) Buffer.BlockCopy(allBytes, bodyOffset, body, 0, buffered);
            var bodyRead = buffered;
            while (bodyRead < contentLength)
            {
                var read = await stream.ReadAsync(body.AsMemory(bodyRead, contentLength - bodyRead), cancellationToken).ConfigureAwait(false);
                if (read == 0) throw new EndOfStreamException("HTTP request body ended early.");
                bodyRead += read;
            }

            return new HttpRequest(headerLines[0], body);
        }

        private static int FindHeaderTerminator(byte[] bytes, int length)
        {
            for (var index = 0; index <= length - 4; index++)
            {
                if (bytes[index] == '\r' && bytes[index + 1] == '\n' && bytes[index + 2] == '\r' && bytes[index + 3] == '\n')
                    return index;
            }
            return -1;
        }

        private sealed record HttpRequest(string RequestLine, byte[] Body);
    }
}
