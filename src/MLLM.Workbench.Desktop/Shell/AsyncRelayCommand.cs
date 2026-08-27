using System.Windows.Input;

namespace MLLM.Workbench.Desktop.Shell;

public sealed class AsyncRelayCommand : ICommand
{
    private readonly Func<CancellationToken, Task> _execute;
    private readonly Func<bool>? _canExecute;
    private CancellationTokenSource? _execution;
    private bool _isRunning;

    public AsyncRelayCommand(Func<CancellationToken, Task> execute, Func<bool>? canExecute = null)
    {
        _execute = execute ?? throw new ArgumentNullException(nameof(execute));
        _canExecute = canExecute;
    }

    public event EventHandler? CanExecuteChanged;
    public bool CanExecute(object? parameter) => !_isRunning && (_canExecute?.Invoke() ?? true);

    public async void Execute(object? parameter) => await ExecuteAsync().ConfigureAwait(true);

    public async Task ExecuteAsync()
    {
        if (!CanExecute(null)) return;
        _isRunning = true;
        _execution = new CancellationTokenSource();
        RaiseCanExecuteChanged();
        try
        {
            await _execute(_execution.Token).ConfigureAwait(true);
        }
        finally
        {
            _execution.Dispose();
            _execution = null;
            _isRunning = false;
            RaiseCanExecuteChanged();
        }
    }

    public void Cancel() => _execution?.Cancel();
    public void RaiseCanExecuteChanged() => CanExecuteChanged?.Invoke(this, EventArgs.Empty);
}
