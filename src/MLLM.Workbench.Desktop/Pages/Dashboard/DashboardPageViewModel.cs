using System.Collections.ObjectModel;
using System.Globalization;
using System.Windows.Input;
using MLLM.Workbench.Contracts.Snapshots;
using MLLM.Workbench.Contracts.Status;
using MLLM.Workbench.Desktop.Shell;
using MLLM.Workbench.Infrastructure.Backend;

namespace MLLM.Workbench.Desktop.Pages.Dashboard;

public sealed class DashboardPageViewModel : ObservableObject
{
    private static readonly HashSet<string> ServiceIds = new(StringComparer.OrdinalIgnoreCase)
    {
        "local-api", "llama-cpp", "web-workbench"
    };

    private readonly IWorkbenchBackendClient _backend;
    private string _networkMode = "-";
    private string _operatingSystem = "等待检测";
    private string _cpu = "等待检测";
    private string _ram = "-";
    private string _gpu = "等待检测";
    private string _diskFree = "-";
    private string _currentModelDisplay = "未安装 / 未检测到";
    private string? _backendError;
    private bool _isBusy;
    private int _passCount;
    private int _runningCount;
    private int _readyCount;
    private int _blockedCount;

    public DashboardPageViewModel(IWorkbenchBackendClient backend)
    {
        _backend = backend ?? throw new ArgumentNullException(nameof(backend));
        RefreshCommand = new AsyncRelayCommand(RefreshAsync);
        OpenDoctorCommand = new RelayCommand(() => NavigationRequested?.Invoke("doctor"));
        OpenInstallationCommand = new RelayCommand(() => NavigationRequested?.Invoke("installation"));
        OpenModelsCommand = new RelayCommand(() => NavigationRequested?.Invoke("models"));
        OpenServicesCommand = new RelayCommand(() => NavigationRequested?.Invoke("services"));
    }

    public event Action<string>? NavigationRequested;
    public string Title => "工作台";
    public string Subtitle => "系统、组件、服务和 Safe Core 后端总览";
    public ObservableCollection<ComponentSnapshot> Components { get; } = [];
    public ObservableCollection<ComponentSnapshot> ServiceComponents { get; } = [];
    public ICommand RefreshCommand { get; }
    public ICommand OpenDoctorCommand { get; }
    public ICommand OpenInstallationCommand { get; }
    public ICommand OpenModelsCommand { get; }
    public ICommand OpenServicesCommand { get; }

    public string NetworkMode { get => _networkMode; private set => SetProperty(ref _networkMode, value); }
    public string OperatingSystem { get => _operatingSystem; private set => SetProperty(ref _operatingSystem, value); }
    public string Cpu { get => _cpu; private set => SetProperty(ref _cpu, value); }
    public string Ram { get => _ram; private set => SetProperty(ref _ram, value); }
    public string Gpu { get => _gpu; private set => SetProperty(ref _gpu, value); }
    public string DiskFree { get => _diskFree; private set => SetProperty(ref _diskFree, value); }
    public string CurrentModelDisplay { get => _currentModelDisplay; private set => SetProperty(ref _currentModelDisplay, value); }
    public string? BackendError { get => _backendError; private set => SetProperty(ref _backendError, value); }
    public bool IsBusy { get => _isBusy; private set => SetProperty(ref _isBusy, value); }
    public int PassCount { get => _passCount; private set => SetProperty(ref _passCount, value); }
    public int RunningCount { get => _runningCount; private set => SetProperty(ref _runningCount, value); }
    public int ReadyCount { get => _readyCount; private set => SetProperty(ref _readyCount, value); }
    public int BlockedCount { get => _blockedCount; private set => SetProperty(ref _blockedCount, value); }

    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        if (IsBusy) return;
        IsBusy = true;
        try
        {
            var snapshot = await _backend.GetDashboardAsync(cancellationToken).ConfigureAwait(true);
            Apply(snapshot);
            BackendError = null;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception ex)
        {
            BackendError = ex.Message;
        }
        finally
        {
            IsBusy = false;
        }
    }

    private void Apply(DashboardSnapshot snapshot)
    {
        NetworkMode = snapshot.NetworkMode;
        OperatingSystem = snapshot.Machine.Os;
        Cpu = snapshot.Machine.Cpu;
        Ram = FormatGb(snapshot.Machine.RamGb);
        Gpu = snapshot.Machine.Gpus.Count == 0 ? "未检测到" : string.Join("; ", snapshot.Machine.Gpus);
        DiskFree = FormatGb(snapshot.Machine.FixedDiskFreeGb);
        CurrentModelDisplay = string.IsNullOrWhiteSpace(snapshot.CurrentModel) ? "未安装 / 未检测到" : snapshot.CurrentModel;

        Components.Clear();
        ServiceComponents.Clear();
        foreach (var component in snapshot.Components)
        {
            Components.Add(component);
            if (ServiceIds.Contains(component.Id)) ServiceComponents.Add(component);
        }

        PassCount = snapshot.Components.Count(x => x.Health == ComponentHealth.Pass);
        RunningCount = snapshot.Components.Count(x => x.Health == ComponentHealth.Running);
        ReadyCount = snapshot.Components.Count(x => x.Health == ComponentHealth.ReadyToInstall);
        BlockedCount = snapshot.Components.Count(x => x.Health == ComponentHealth.Blocked);
    }

    private static string FormatGb(double value) => value.ToString("0.0", CultureInfo.InvariantCulture) + " GB";
}
