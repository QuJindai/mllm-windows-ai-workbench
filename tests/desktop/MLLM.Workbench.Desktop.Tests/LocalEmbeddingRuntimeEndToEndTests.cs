using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using MLLM.Workbench.Desktop.Services.Knowledge;
using MLLM.Workbench.Knowledge.Embeddings;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class LocalEmbeddingRuntimeEndToEndTests
{
    [Fact]
    public async Task Factory_loopback_runtime_backfills_hybrid_searches_and_reuses_persisted_vectors_after_reopen()
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        var cancellationToken = timeout.Token;
        var root = Path.Combine(Path.GetTempPath(), "mllm-local-embedding-e2e", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var source = Path.Combine(root, "vehicle.md");
        await File.WriteAllTextAsync(source, "整车车辆制造软件版本追溯证据", cancellationToken);

        try
        {
            using (var ftsOnly = new KnowledgeWorkbenchService(root))
            {
                await ftsOnly.ImportFileAsync(source, cancellationToken);
                var lexical = await ftsOnly.SearchAsync("车辆制造", KnowledgeSearchMode.Fts5, 10, cancellationToken);
                Assert.NotEmpty(lexical);
            }

            await using var server = new LoopbackEmbeddingServer();
            var values = new Dictionary<string, string?>
            {
                [LocalEmbeddingEnvironment.UrlVariable] = server.Endpoint.ToString(),
                [LocalEmbeddingEnvironment.ModelVariable] = "ci-loopback-3d",
                [LocalEmbeddingEnvironment.DimensionVariable] = "3"
            };

            using (var configured = KnowledgeServiceFactory.Create(root, name => values.GetValueOrDefault(name)))
            {
                var before = await configured.GetSnapshotAsync(cancellationToken);
                Assert.True(before.Fts5Ready);
                Assert.True(before.EmbeddingConfigured);
                Assert.Equal(1, before.EmbeddingTotalChunks);
                Assert.Equal(0, before.EmbeddingIndexedChunks);
                Assert.False(before.HybridReady);
                Assert.Equal(0, server.CallCount);

                var progressEvents = new List<KnowledgeEmbeddingProgress>();
                var after = await configured.BuildEmbeddingIndexAsync(
                    new InlineProgress<KnowledgeEmbeddingProgress>(progressEvents.Add),
                    cancellationToken);

                Assert.Equal(1, after.EmbeddingTotalChunks);
                Assert.Equal(1, after.EmbeddingIndexedChunks);
                Assert.True(after.HybridReady);
                Assert.Equal(1, server.CallCount);
                var progress = Assert.Single(progressEvents);
                Assert.Equal(1, progress.Completed);
                Assert.Equal(1, progress.Total);
                Assert.False(string.IsNullOrWhiteSpace(progress.CurrentChunkId));

                var hybrid = await configured.SearchAsync(
                    "车辆制造",
                    KnowledgeSearchMode.Hybrid,
                    10,
                    cancellationToken);

                var hit = Assert.Single(hybrid);
                Assert.Equal(Path.GetFullPath(source), hit.SourceUri);
                Assert.Contains("车辆制造", hit.Excerpt, StringComparison.Ordinal);
                Assert.Equal(2, server.CallCount);
            }

            var callsBeforeReopen = server.CallCount;
            using (var reopened = KnowledgeServiceFactory.Create(root, name => values.GetValueOrDefault(name)))
            {
                var persisted = await reopened.GetSnapshotAsync(cancellationToken);
                Assert.True(persisted.HybridReady);
                Assert.Equal(1, persisted.EmbeddingIndexedChunks);
                Assert.Equal(1, persisted.EmbeddingTotalChunks);
                Assert.Equal(callsBeforeReopen, server.CallCount);

                var hybrid = await reopened.SearchAsync(
                    "车辆制造",
                    KnowledgeSearchMode.Hybrid,
                    10,
                    cancellationToken);

                Assert.NotEmpty(hybrid);
                Assert.Equal(callsBeforeReopen + 1, server.CallCount);
            }
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    private sealed class InlineProgress<T>(Action<T> report) : IProgress<T>
    {
        public void Report(T value) => report(value);
    }

    private sealed class LoopbackEmbeddingServer : IAsyncDisposable
    {
        private const int MaxHeaderBytes = 64 * 1024;
        private readonly TcpListener _listener;
        private readonly CancellationTokenSource _cts = new();
        private readonly Task _acceptLoop;
        private int _callCount;

        public LoopbackEmbeddingServer()
        {
            _listener = new TcpListener(IPAddress.Loopback, 0);
            _listener.Start();
            var port = ((IPEndPoint)_listener.LocalEndpoint).Port;
            Endpoint = new Uri($"http://127.0.0.1:{port}/v1/embeddings");
            _acceptLoop = Task.Run(() => AcceptLoopAsync(_cts.Token));
        }

        public Uri Endpoint { get; }
        public int CallCount => Volatile.Read(ref _callCount);

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
                Assert.StartsWith("POST /v1/embeddings HTTP/1.1", request.RequestLine, StringComparison.OrdinalIgnoreCase);

                using var document = JsonDocument.Parse(request.Body);
                var model = document.RootElement.GetProperty("model").GetString();
                var input = document.RootElement.GetProperty("input").GetString() ?? string.Empty;
                Assert.Equal("ci-loopback-3d", model);

                var normalized = input.ToLowerInvariant();
                var vector = normalized.Contains("车辆", StringComparison.Ordinal) ||
                             normalized.Contains("整车", StringComparison.Ordinal) ||
                             normalized.Contains("automobile", StringComparison.Ordinal) ||
                             normalized.Contains("vehicle", StringComparison.Ordinal)
                    ? "[1,0,0]"
                    : normalized.Contains("水果", StringComparison.Ordinal) || normalized.Contains("fruit", StringComparison.Ordinal)
                        ? "[0,1,0]"
                        : "[0,0,1]";

                Interlocked.Increment(ref _callCount);
                var responseBody = Encoding.UTF8.GetBytes($"{{\"data\":[{{\"embedding\":{vector}}}],\"model\":\"ci-loopback-3d\"}}");
                var headers = Encoding.ASCII.GetBytes(
                    "HTTP/1.1 200 OK\r\n" +
                    "Content-Type: application/json\r\n" +
                    $"Content-Length: {responseBody.Length}\r\n" +
                    "Connection: close\r\n\r\n");

                await stream.WriteAsync(headers, cancellationToken).ConfigureAwait(false);
                await stream.WriteAsync(responseBody, cancellationToken).ConfigureAwait(false);
                await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
            }
        }

        private static async Task<HttpRequest> ReadRequestAsync(NetworkStream stream, CancellationToken cancellationToken)
        {
            using var received = new MemoryStream();
            var buffer = new byte[4096];
            var headerEnd = -1;

            while (headerEnd < 0)
            {
                var read = await stream.ReadAsync(buffer, cancellationToken).ConfigureAwait(false);
                if (read == 0) throw new EndOfStreamException("Embedding request ended before HTTP headers completed.");
                received.Write(buffer, 0, read);
                if (received.Length > MaxHeaderBytes)
                    throw new InvalidDataException("Embedding request headers exceeded the test server limit.");

                headerEnd = FindHeaderTerminator(received.GetBuffer(), checked((int)received.Length));
            }

            var allBytes = received.ToArray();
            var headerText = Encoding.ASCII.GetString(allBytes, 0, headerEnd);
            var headerLines = headerText.Split(["\r\n"], StringSplitOptions.None);
            if (headerLines.Length == 0 || string.IsNullOrWhiteSpace(headerLines[0]))
                throw new InvalidDataException("Embedding request did not contain a request line.");

            var contentLength = 0;
            foreach (var line in headerLines.Skip(1))
            {
                var separator = line.IndexOf(':');
                if (separator <= 0) continue;
                var name = line[..separator].Trim();
                if (!name.Equals("Content-Length", StringComparison.OrdinalIgnoreCase)) continue;
                contentLength = int.Parse(
                    line[(separator + 1)..].Trim(),
                    System.Globalization.CultureInfo.InvariantCulture);
            }

            if (contentLength <= 0)
                throw new InvalidDataException("Embedding request did not contain a positive Content-Length.");

            var bodyOffset = headerEnd + 4;
            var body = new byte[contentLength];
            var bufferedBodyBytes = Math.Min(contentLength, Math.Max(0, allBytes.Length - bodyOffset));
            if (bufferedBodyBytes > 0)
                Buffer.BlockCopy(allBytes, bodyOffset, body, 0, bufferedBodyBytes);

            var bodyRead = bufferedBodyBytes;
            while (bodyRead < contentLength)
            {
                var read = await stream.ReadAsync(body.AsMemory(bodyRead, contentLength - bodyRead), cancellationToken).ConfigureAwait(false);
                if (read == 0) throw new EndOfStreamException("Embedding request body ended early.");
                bodyRead += read;
            }

            return new HttpRequest(headerLines[0], body);
        }

        private static int FindHeaderTerminator(byte[] bytes, int length)
        {
            for (var index = 0; index <= length - 4; index++)
            {
                if (bytes[index] == (byte)'\r' &&
                    bytes[index + 1] == (byte)'\n' &&
                    bytes[index + 2] == (byte)'\r' &&
                    bytes[index + 3] == (byte)'\n')
                {
                    return index;
                }
            }

            return -1;
        }

        private sealed record HttpRequest(string RequestLine, byte[] Body);
    }
}
