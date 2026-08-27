using System.IO.Pipes;
using System.Text;
using System.Text.Json;
using MLLM.Workbench.Contracts.Protocol;
using MLLM.Workbench.Contracts.Snapshots;

namespace MLLM.Workbench.Infrastructure.Backend;

public sealed class NamedPipeBackendClient : IWorkbenchBackendClient
{
    private readonly BackendClientOptions _options;
    private readonly SemaphoreSlim _requestGate = new(1, 1);
    private NamedPipeClientStream? _pipe;
    private StreamReader? _reader;
    private StreamWriter? _writer;
    private bool _authenticated;

    public NamedPipeBackendClient(BackendClientOptions options)
    {
        _options = options ?? throw new ArgumentNullException(nameof(options));
    }

    public async Task<BackendHandshakeResponse> ConnectAsync(CancellationToken cancellationToken)
    {
        if (_pipe is not null)
        {
            throw new InvalidOperationException("Backend client is already connected.");
        }

        _pipe = new NamedPipeClientStream(".", _options.PipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
        await _pipe.ConnectAsync(cancellationToken).ConfigureAwait(false);
        var utf8 = new UTF8Encoding(false);
        _reader = new StreamReader(_pipe, utf8, false, 4096, leaveOpen: true);
        _writer = new StreamWriter(_pipe, utf8, 4096, leaveOpen: true) { AutoFlush = true };

        var payload = JsonSerializer.SerializeToElement(
            new BackendHandshakeRequest(_options.ProtocolVersion, _options.SessionToken, "desktop-phase-a"),
            WorkbenchJson.Options);
        var request = new RpcRequest(
            _options.ProtocolVersion,
            "handshake",
            Guid.NewGuid().ToString("N"),
            "system.handshake",
            _options.SessionToken,
            payload);

        var response = await SendAndReadAsync(request, cancellationToken).ConfigureAwait(false);
        if (!response.Success)
        {
            var error = response.Error ?? throw new BackendRpcException("RPC_ERROR", "Backend handshake failed.");
            throw new BackendRpcException(error.Code, error.Message);
        }
        if (response.Payload is null)
        {
            throw new BackendRpcException("INVALID_RESPONSE", "Backend handshake payload is missing.");
        }
        var handshake = response.Payload.Value.Deserialize<BackendHandshakeResponse>(WorkbenchJson.Options)
            ?? throw new BackendRpcException("INVALID_RESPONSE", "Backend handshake payload is invalid.");
        _authenticated = handshake.Accepted;
        return handshake;
    }

    public async Task<TResponse> InvokeAsync<TResponse>(string method, object? payload, CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(method);
        if (!_authenticated)
        {
            throw new InvalidOperationException("Backend client has not completed an authenticated handshake.");
        }

        JsonElement? serializedPayload = payload is null
            ? null
            : JsonSerializer.SerializeToElement(payload, WorkbenchJson.Options);
        var request = new RpcRequest(
            _options.ProtocolVersion,
            "request",
            Guid.NewGuid().ToString("N"),
            method,
            _options.SessionToken,
            serializedPayload);
        var response = await SendAndReadAsync(request, cancellationToken).ConfigureAwait(false);
        if (!response.Success)
        {
            var error = response.Error ?? throw new BackendRpcException("RPC_ERROR", $"Backend method {method} failed.");
            throw new BackendRpcException(error.Code, error.Message);
        }
        if (response.Payload is null)
        {
            throw new BackendRpcException("INVALID_RESPONSE", $"Backend method {method} returned no payload.");
        }
        return response.Payload.Value.Deserialize<TResponse>(WorkbenchJson.Options)
            ?? throw new BackendRpcException("INVALID_RESPONSE", $"Backend method {method} returned an invalid payload.");
    }

    public Task<DashboardSnapshot> GetDashboardAsync(CancellationToken cancellationToken) =>
        InvokeAsync<DashboardSnapshot>("dashboard.snapshot", null, cancellationToken);

    public Task<DoctorSnapshot> GetDoctorAsync(CancellationToken cancellationToken) =>
        InvokeAsync<DoctorSnapshot>("doctor.snapshot", null, cancellationToken);

    public Task<InstallerSnapshot> GetInstallerAsync(CancellationToken cancellationToken) =>
        InvokeAsync<InstallerSnapshot>("installer.snapshot", null, cancellationToken);

    private async Task<RpcResponse> SendAndReadAsync(RpcRequest request, CancellationToken cancellationToken)
    {
        var reader = _reader ?? throw new InvalidOperationException("Backend pipe reader is not initialized.");
        var writer = _writer ?? throw new InvalidOperationException("Backend pipe writer is not initialized.");

        await _requestGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            var line = JsonSerializer.Serialize(request, WorkbenchJson.Options);
            await writer.WriteLineAsync(line).ConfigureAwait(false);
            await writer.FlushAsync(cancellationToken).ConfigureAwait(false);
            var responseLine = await reader.ReadLineAsync(cancellationToken).ConfigureAwait(false);
            if (string.IsNullOrWhiteSpace(responseLine))
            {
                throw new BackendRpcException("CONNECTION_CLOSED", "Backend closed the named pipe without a response.");
            }
            return JsonSerializer.Deserialize<RpcResponse>(responseLine, WorkbenchJson.Options)
                ?? throw new BackendRpcException("INVALID_RESPONSE", "Backend returned malformed JSON.");
        }
        finally
        {
            _requestGate.Release();
        }
    }

    public async ValueTask DisposeAsync()
    {
        _authenticated = false;
        if (_writer is not null)
        {
            await _writer.DisposeAsync().ConfigureAwait(false);
            _writer = null;
        }
        _reader?.Dispose();
        _reader = null;
        _pipe?.Dispose();
        _pipe = null;
        _requestGate.Dispose();
    }
}
