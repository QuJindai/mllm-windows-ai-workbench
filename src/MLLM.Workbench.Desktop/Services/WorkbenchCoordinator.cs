using MLLM.Workbench.Infrastructure.Backend;

namespace MLLM.Workbench.Desktop.Services;

public sealed class WorkbenchCoordinator : IAsyncDisposable
{
    private readonly BackendProcessHost _processHost;
    private readonly IWorkbenchBackendClient _client;
    private bool _started;
    private bool _disposed;

    public WorkbenchCoordinator(BackendProcessHost processHost, IWorkbenchBackendClient client)
    {
        _processHost = processHost;
        _client = client;
    }

    public event Action<string>? BackendLogReceived
    {
        add => _processHost.BackendLogReceived += value;
        remove => _processHost.BackendLogReceived -= value;
    }

    public async Task StartAsync(CancellationToken cancellationToken)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        if (_started) return;
        await _processHost.StartAsync(cancellationToken).ConfigureAwait(false);
        var handshake = await _client.ConnectAsync(cancellationToken).ConfigureAwait(false);
        if (!handshake.Accepted)
        {
            throw new BackendRpcException("HANDSHAKE_REJECTED", handshake.Error ?? "Safe Core backend rejected the desktop session.");
        }
        _started = true;
    }

    public async ValueTask DisposeAsync()
    {
        if (_disposed) return;
        _disposed = true;
        await _client.DisposeAsync().ConfigureAwait(false);
        await _processHost.DisposeAsync().ConfigureAwait(false);
    }
}
