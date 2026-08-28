using System.Collections.ObjectModel;
using System.Windows.Input;
using MLLM.Workbench.Contracts.Operations;
using MLLM.Workbench.Contracts.Snapshots;
using MLLM.Workbench.Contracts.Status;
using MLLM.Workbench.Desktop.Shell;
using MLLM.Workbench.Infrastructure.Backend;

namespace MLLM.Workbench.Desktop.Pages.Doctor;

public sealed class DoctorPageViewModel : ObservableObject
{
    private readonly IWorkbenchBackendClient _backend;
    private string? _backendError;
    private string? _productFaultMessage;
    private bool _hasProductFault;
    private bool _isBusy;

    public DoctorPageViewModel(IWorkbenchBackendClient backend)
    {
        _backend = backend ?? throw new ArgumentNullException(nameof(backend));
        RefreshCommand = new AsyncRelayCommand(RefreshAsync);
    }

    public string Title => "系统体检 (Doctor)";
    public string Subtitle => "区分正常、可安装、受阻与产品故障；未安装不是程序崩溃";
    public ObservableCollection<DoctorRowViewModel> Rows { get; } = [];
    public ICommand RefreshCommand { get; }

    public string? BackendError { get => _backendError; private set => SetProperty(ref _backendError, value); }
    public string? ProductFaultMessage { get => _productFaultMessage; private set => SetProperty(ref _productFaultMessage, value); }
    public bool HasProductFault { get => _hasProductFault; private set => SetProperty(ref _hasProductFault, value); }
    public bool IsBusy { get => _isBusy; private set => SetProperty(ref _isBusy, value); }

    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        if (IsBusy) return;
        IsBusy = true;
        try
        {
            var snapshot = await _backend.GetDoctorAsync(cancellationToken).ConfigureAwait(true);
            Apply(snapshot);
            BackendError = null;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception ex)
        {
            Rows.Clear();
            BackendError = ex.Message;
            ProductFaultMessage = ex.Message;
            HasProductFault = true;
        }
        finally
        {
            IsBusy = false;
        }
    }

    private void Apply(DoctorSnapshot snapshot)
    {
        Rows.Clear();
        var faults = new List<string>();
        foreach (var component in snapshot.Components)
        {
            var row = ToRow(component);
            Rows.Add(row);
            if (row.IsProductFault) faults.Add(component.Id + ": " + component.Summary);
        }
        foreach (OperationError error in snapshot.Errors)
        {
            faults.Add(error.Code + ": " + error.Message);
        }

        ProductFaultMessage = faults.Count == 0 ? null : string.Join(Environment.NewLine, faults);
        HasProductFault = faults.Count > 0;
    }

    internal static DoctorRowViewModel ToRow(ComponentSnapshot component)
    {
        var display = component.Health switch
        {
            ComponentHealth.Pass => "正常",
            ComponentHealth.Running => "运行中",
            ComponentHealth.ReadyToInstall => "可安装",
            ComponentHealth.RepairAvailable => "可修复",
            ComponentHealth.Blocked => "受阻",
            ComponentHealth.NotFound => "未检测到",
            ComponentHealth.DetectionError => "检测器错误",
            ComponentHealth.OperationFailed => "操作失败",
            _ => "未知"
        };
        var recommendation = component.Health switch
        {
            ComponentHealth.Pass or ComponentHealth.Running => "无需操作",
            ComponentHealth.ReadyToInstall => "可在安装中心安装",
            ComponentHealth.RepairAvailable => "可在安装中心修复",
            ComponentHealth.Blocked => "先解决依赖或策略阻塞",
            ComponentHealth.NotFound => "确认组件路径或执行安装",
            ComponentHealth.DetectionError => "这是检测器/后端故障，请查看产品故障与证据",
            ComponentHealth.OperationFailed => "查看操作日志与证据后重试",
            _ => "重新运行 Doctor"
        };
        return new DoctorRowViewModel(
            component.Id,
            component.Health,
            display,
            component.Summary,
            recommendation,
            component.Health == ComponentHealth.DetectionError,
            component.RepairAvailable,
            component.RepairTask);
    }
}
