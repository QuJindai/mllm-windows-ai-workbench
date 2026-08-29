namespace MLLM.Workbench.Desktop.Services;

/// <summary>
/// Serializes state-changing workbench operations so model/service mutations
/// cannot overlap and leave the native backend in an indeterminate state.
/// </summary>
public sealed class WorkbenchMutationGate : IDisposable
{
    private readonly SemaphoreSlim _semaphore = new(1, 1);
    private int _active;
    private bool _disposed;

    public bool IsBusy => Volatile.Read(ref _active) != 0;

    public async Task RunAsync(Func<CancellationToken, Task> action, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(action);
        ObjectDisposedException.ThrowIf(_disposed, this);

        await _semaphore.WaitAsync(cancellationToken).ConfigureAwait(false);
        Interlocked.Exchange(ref _active, 1);
        try
        {
            await action(cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            Interlocked.Exchange(ref _active, 0);
            _semaphore.Release();
        }
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _semaphore.Dispose();
    }
}
