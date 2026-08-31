using System.Collections.ObjectModel;
using System.Windows.Input;
using MLLM.Workbench.Contracts.Services;
using MLLM.Workbench.Desktop.Services;
using MLLM.Workbench.Desktop.Shell;
using MLLM.Workbench.Infrastructure.Backend;

namespace MLLM.Workbench.Desktop.Pages.Services;

public sealed class LocalServicesPageViewModel : ObservableObject
{
    private readonly IWorkbenchBackendClient _backend;
    private readonly WorkbenchMutationGate _mutationGate;
    private readonly IClipboardService _clipboard;
    private readonly AsyncRelayCommand _startCommand;
    private readonly AsyncRelayCommand _stopCommand;
    private readonly AsyncRelayCommand _restartCommand;
    private readonly AsyncRelayCommand _loadLogsCommand;
    private readonly RelayCommand _copyEndpointCommand;
    private ServiceDescriptor? _selectedService;
    private string _networkMode = "-";
    private string _logText = "选择服务后查看最近日志。";
    private string? _lastError;
    private bool _isBusy;

    public LocalServicesPageViewModel(
        IWorkbenchBackendClient backend,
        WorkbenchMutationGate mutationGate,
        IClipboardService clipboard)
    {
        _backend = backend ?? throw new ArgumentNullException(nameof(backend));
        _mutationGate = mutationGate ?? throw new ArgumentNullException(nameof(mutationGate));
        _clipboard = clipboard ?? throw new ArgumentNullException(nameof(clipboard));

        RefreshCommand = new AsyncRelayCommand(RefreshAsync);
        _startCommand = new AsyncRelayCommand(StartSelectedAsync, () => CanStartSelected);
        _stopCommand = new AsyncRelayCommand(StopSelectedAsync, () => CanStopSelected);
        _restartCommand = new AsyncRelayCommand(RestartSelectedAsync, () => CanRestartSelected);
        _loadLogsCommand = new AsyncRelayCommand(LoadLogsAsync, () => SelectedService is not null && !IsBusy);
        _copyEndpointCommand = new RelayCommand(CopyEndpoint, () => CanCopyEndpoint);
        StartCommand = _startCommand;
        StopCommand = _stopCommand;
        RestartCommand = _restartCommand;
        LoadLogsCommand = _loadLogsCommand;
        CopyEndpointCommand = _copyEndpointCommand;
    }

    public string Title => "本地服务";
    public string Subtitle => "Local Model API 与 Web Workbench 状态、生命周期和受限日志";
    public ObservableCollection<ServiceDescriptor> Services { get; } = [];
    public ICommand RefreshCommand { get; }
    public ICommand StartCommand { get; }
    public ICommand StopCommand { get; }
    public ICommand RestartCommand { get; }
    public ICommand LoadLogsCommand { get; }
    public ICommand CopyEndpointCommand { get; }

    public ServiceDescriptor? SelectedService
    {
        get => _selectedService;
        set
        {
            if (SetProperty(ref _selectedService, value)) RaiseCommandStates();
        }
    }

    public string NetworkMode { get => _networkMode; private set => SetProperty(ref _networkMode, value); }
    public string LogText { get => _logText; private set => SetProperty(ref _logText, value); }
    public string? LastError { get => _lastError; private set => SetProperty(ref _lastError, value); }
    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (SetProperty(ref _isBusy, value)) RaiseCommandStates();
        }
    }

    public bool CanStartSelected => !IsBusy && SelectedService?.CanStart == true;
    public bool CanStopSelected => !IsBusy && SelectedService?.CanStop == true;
    public bool CanRestartSelected => !IsBusy && SelectedService?.CanRestart == true;
    public bool CanCopyEndpoint => !IsBusy && !string.IsNullOrWhiteSpace(SelectedService?.BaseUrl);

    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        if (IsBusy) return;
        IsBusy = true;
        try
        {
            await RefreshCoreAsync(SelectedService?.ServiceId, cancellationToken).ConfigureAwait(true);
            LastError = null;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception ex)
        {
            LastError = ex.Message;
        }
        finally
        {
            IsBusy = false;
        }
    }

    public Task StartSelectedAsync(CancellationToken cancellationToken) =>
        RunMutationAsync("start", cancellationToken);

    public Task StopSelectedAsync(CancellationToken cancellationToken) =>
        RunMutationAsync("stop", cancellationToken);

    public Task RestartSelectedAsync(CancellationToken cancellationToken) =>
        RunMutationAsync("restart", cancellationToken);

    public async Task LoadLogsAsync(CancellationToken cancellationToken)
    {
        var service = SelectedService ?? throw new InvalidOperationException("请先选择一个服务。");
        if (IsBusy) return;
        IsBusy = true;
        try
        {
            var logs = await _backend
                .GetServiceLogsAsync(new ServiceLogRequest(service.ServiceId, 200), cancellationToken)
                .ConfigureAwait(true);
            var stdout = logs.StdoutLines.Count == 0 ? "<无>" : string.Join(Environment.NewLine, logs.StdoutLines);
            var stderr = logs.StderrLines.Count == 0 ? "<无>" : string.Join(Environment.NewLine, logs.StderrLines);
            LogText = $"[STDOUT]{Environment.NewLine}{stdout}{Environment.NewLine}{Environment.NewLine}[STDERR]{Environment.NewLine}{stderr}";
            LastError = null;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception ex)
        {
            LastError = ex.Message;
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task RunMutationAsync(string action, CancellationToken cancellationToken)
    {
        var service = SelectedService ?? throw new InvalidOperationException("请先选择一个服务。");
        if (action == "start" && !CanStartSelected) throw new InvalidOperationException("当前服务不可启动。");
        if (action == "stop" && !CanStopSelected) throw new InvalidOperationException("当前服务不可停止。");
        if (action == "restart" && !CanRestartSelected) throw new InvalidOperationException("当前服务不可重启。");
        if (IsBusy) return;

        var serviceId = service.ServiceId;
        IsBusy = true;
        try
        {
            await _mutationGate.RunAsync(async ct =>
            {
                var request = new ServiceActionRequest(serviceId, Guid.NewGuid().ToString("N"));
                _ = action switch
                {
                    "start" => await _backend.StartServiceAsync(request, ct).ConfigureAwait(false),
                    "stop" => await _backend.StopServiceAsync(request, ct).ConfigureAwait(false),
                    "restart" => await _backend.RestartServiceAsync(request, ct).ConfigureAwait(false),
                    _ => throw new InvalidOperationException("Unsupported service action.")
                };
            }, cancellationToken).ConfigureAwait(true);

            await RefreshCoreAsync(serviceId, cancellationToken).ConfigureAwait(true);
            LastError = null;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception ex)
        {
            LastError = ex.Message;
            throw;
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task RefreshCoreAsync(string? selectedId, CancellationToken cancellationToken)
    {
        var snapshot = await _backend.GetServicesAsync(cancellationToken).ConfigureAwait(true);
        NetworkMode = snapshot.NetworkMode;
        Services.Clear();
        foreach (var service in snapshot.Services) Services.Add(service);
        SelectedService = string.IsNullOrWhiteSpace(selectedId)
            ? Services.FirstOrDefault()
            : Services.FirstOrDefault(x => string.Equals(x.ServiceId, selectedId, StringComparison.OrdinalIgnoreCase)) ?? Services.FirstOrDefault();
    }

    private void CopyEndpoint()
    {
        var endpoint = SelectedService?.BaseUrl;
        if (string.IsNullOrWhiteSpace(endpoint)) return;
        try
        {
            _clipboard.SetText(endpoint);
            LastError = null;
        }
        catch (Exception ex)
        {
            LastError = ex.Message;
        }
    }

    private void RaiseCommandStates()
    {
        OnPropertyChanged(nameof(CanStartSelected));
        OnPropertyChanged(nameof(CanStopSelected));
        OnPropertyChanged(nameof(CanRestartSelected));
        OnPropertyChanged(nameof(CanCopyEndpoint));
        _startCommand.RaiseCanExecuteChanged();
        _stopCommand.RaiseCanExecuteChanged();
        _restartCommand.RaiseCanExecuteChanged();
        _loadLogsCommand.RaiseCanExecuteChanged();
        _copyEndpointCommand.RaiseCanExecuteChanged();
    }

    private void OnPropertyChanged(string propertyName)
    {
        SetProperty(ref _propertyChangePulse, !_propertyChangePulse, propertyName);
    }

    private bool _propertyChangePulse;
}
