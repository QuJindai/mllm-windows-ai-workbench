using System.Collections.ObjectModel;
using System.Windows.Input;
using MLLM.Workbench.Contracts.Components;
using MLLM.Workbench.Contracts.Snapshots;
using MLLM.Workbench.Contracts.Status;
using MLLM.Workbench.Desktop.Shell;
using MLLM.Workbench.Infrastructure.Backend;
using MLLM.Workbench.Infrastructure.Installer;

namespace MLLM.Workbench.Desktop.Pages.Installation;

public sealed class InstallationPageViewModel : ObservableObject
{
    private static readonly string[] AllowedInstallNetworkModes =
        ["AUTO_CN_FIRST", "CHINA_ONLY", "GLOBAL_FIRST", "OFFLINE_CACHE"];

    private static readonly string[] AllowedComponentPresets =
        ["Core", "Local AI Fast", "Web Workbench", "Developer Tools", "Full Setup"];

    private readonly IWorkbenchBackendClient _backend;
    private readonly IPrivilegedInstallerInvoker _installer;
    private string _stage = "IDLE";
    private string _activeVersion = "-";
    private string _evidenceRoot = "-";
    private string? _lastError;
    private string? _operationMessage;
    private string? _runId;
    private string? _versionId;
    private string _selectedInstallNetworkMode = "AUTO_CN_FIRST";
    private bool _canInstallResume;
    private bool _canRetryAcquisition;
    private bool _canImportOffline = true;
    private bool _canRollback;
    private bool _isBusy;

    private readonly AsyncRelayCommand _refreshCommand;
    private readonly AsyncRelayCommand _installResumeCommand;
    private readonly AsyncRelayCommand _retryAcquisitionCommand;
    private readonly AsyncRelayCommand _rollbackCommand;
    private readonly AsyncRelayCommand _installCorePresetCommand;
    private readonly AsyncRelayCommand _installLocalAiFastPresetCommand;
    private readonly AsyncRelayCommand _installWebWorkbenchPresetCommand;
    private readonly AsyncRelayCommand _installDeveloperToolsPresetCommand;
    private readonly AsyncRelayCommand _installFullSetupPresetCommand;

    public InstallationPageViewModel(IWorkbenchBackendClient backend, IPrivilegedInstallerInvoker installer)
    {
        _backend = backend ?? throw new ArgumentNullException(nameof(backend));
        _installer = installer ?? throw new ArgumentNullException(nameof(installer));
        _refreshCommand = new AsyncRelayCommand(RefreshAsync, () => !IsBusy);
        _installResumeCommand = new AsyncRelayCommand(InstallResumeAsync, () => CanInstallResume && !IsBusy);
        _retryAcquisitionCommand = new AsyncRelayCommand(RetryAcquisitionAsync, () => CanRetryAcquisition && !IsBusy);
        _rollbackCommand = new AsyncRelayCommand(RollbackAsync, () => CanRollback && !IsBusy);
        _installCorePresetCommand = new AsyncRelayCommand(ct => InstallComponentPresetAsync("Core", ct), () => !IsBusy);
        _installLocalAiFastPresetCommand = new AsyncRelayCommand(ct => InstallComponentPresetAsync("Local AI Fast", ct), () => !IsBusy);
        _installWebWorkbenchPresetCommand = new AsyncRelayCommand(ct => InstallComponentPresetAsync("Web Workbench", ct), () => !IsBusy);
        _installDeveloperToolsPresetCommand = new AsyncRelayCommand(ct => InstallComponentPresetAsync("Developer Tools", ct), () => !IsBusy);
        _installFullSetupPresetCommand = new AsyncRelayCommand(ct => InstallComponentPresetAsync("Full Setup", ct), () => !IsBusy);
    }

    public string Title => "安装中心";
    public string Subtitle => "Workbench 基础版本由 Universal Installer 管理；本地 AI 组件由 Safe Core 固定任务引擎安装";
    public ObservableCollection<ComponentSnapshot> Components { get; } = [];
    public IReadOnlyList<string> InstallNetworkModes => AllowedInstallNetworkModes;
    public ICommand RefreshCommand => _refreshCommand;
    public ICommand InstallResumeCommand => _installResumeCommand;
    public ICommand RetryAcquisitionCommand => _retryAcquisitionCommand;
    public ICommand RollbackCommand => _rollbackCommand;
    public ICommand InstallCorePresetCommand => _installCorePresetCommand;
    public ICommand InstallLocalAiFastPresetCommand => _installLocalAiFastPresetCommand;
    public ICommand InstallWebWorkbenchPresetCommand => _installWebWorkbenchPresetCommand;
    public ICommand InstallDeveloperToolsPresetCommand => _installDeveloperToolsPresetCommand;
    public ICommand InstallFullSetupPresetCommand => _installFullSetupPresetCommand;
    public string Stage { get => _stage; private set => SetProperty(ref _stage, value); }
    public string ActiveVersion { get => _activeVersion; private set => SetProperty(ref _activeVersion, value); }
    public string EvidenceRoot { get => _evidenceRoot; private set => SetProperty(ref _evidenceRoot, value); }
    public string? LastError { get => _lastError; private set => SetProperty(ref _lastError, value); }
    public string? OperationMessage { get => _operationMessage; private set => SetProperty(ref _operationMessage, value); }
    public bool CanInstallResume { get => _canInstallResume; private set => SetProperty(ref _canInstallResume, value); }
    public bool CanRetryAcquisition { get => _canRetryAcquisition; private set => SetProperty(ref _canRetryAcquisition, value); }
    public bool CanImportOffline { get => _canImportOffline; private set => SetProperty(ref _canImportOffline, value); }
    public bool CanRollback { get => _canRollback; private set => SetProperty(ref _canRollback, value); }
    public bool IsBusy { get => _isBusy; private set => SetProperty(ref _isBusy, value); }

    public string SelectedInstallNetworkMode
    {
        get => _selectedInstallNetworkMode;
        set
        {
            if (!AllowedInstallNetworkModes.Contains(value, StringComparer.Ordinal))
                throw new ArgumentOutOfRangeException(nameof(value), value, "Unsupported component installation network mode.");
            SetProperty(ref _selectedInstallNetworkMode, value);
        }
    }

    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        if (IsBusy) return;
        IsBusy = true;
        RaiseCommandStates();
        try
        {
            var installerTask = _backend.GetInstallerAsync(cancellationToken);
            var doctorTask = _backend.GetDoctorAsync(cancellationToken);
            await Task.WhenAll(installerTask, doctorTask).ConfigureAwait(true);
            Apply(await installerTask.ConfigureAwait(true), await doctorTask.ConfigureAwait(true));
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception ex)
        {
            OperationMessage = "读取安装状态失败：" + ex.Message;
        }
        finally
        {
            IsBusy = false;
            RaiseCommandStates();
        }
    }

    public Task InstallResumeAsync(CancellationToken cancellationToken) =>
        RunInstallerActionAsync(new InstallerProcessRequest(InstallerAction.InstallResume, RunId: _runId, VersionId: _versionId), cancellationToken);

    public Task RetryAcquisitionAsync(CancellationToken cancellationToken) =>
        RunInstallerActionAsync(new InstallerProcessRequest(InstallerAction.RetryAcquisition, RunId: _runId, VersionId: _versionId), cancellationToken);

    public Task RollbackAsync(CancellationToken cancellationToken) =>
        RunInstallerActionAsync(new InstallerProcessRequest(InstallerAction.Rollback), cancellationToken);

    public async Task ImportOfflineAsync(string packagePath, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(packagePath)) throw new ArgumentException("Offline package path is required.", nameof(packagePath));
        await RunInstallerActionAsync(new InstallerProcessRequest(InstallerAction.ImportOffline, packagePath), cancellationToken).ConfigureAwait(true);
    }

    public async Task InstallComponentPresetAsync(string preset, CancellationToken cancellationToken)
    {
        if (!AllowedComponentPresets.Contains(preset, StringComparer.Ordinal))
            throw new ArgumentOutOfRangeException(nameof(preset), preset, "Unsupported component installation preset.");
        if (IsBusy) return;

        IsBusy = true;
        RaiseCommandStates();
        try
        {
            var request = new ComponentPresetInstallRequest(
                preset,
                SelectedInstallNetworkMode,
                Guid.NewGuid().ToString("N"));
            OperationMessage = $"正在执行本地 AI 组件预设：{preset} · {SelectedInstallNetworkMode}";
            var result = await _backend.InstallComponentPresetAsync(request, cancellationToken).ConfigureAwait(true);
            var summaries = string.Join("；", result.Items.Select(item => $"{item.Id}={item.Status}"));
            OperationMessage = $"组件预设 {preset}: {result.Status}" +
                               (string.IsNullOrWhiteSpace(summaries) ? string.Empty : " · " + summaries) +
                               (string.IsNullOrWhiteSpace(result.RunDirectory) ? string.Empty : " · " + result.RunDirectory);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            OperationMessage = $"组件预设 {preset} 已取消。";
            return;
        }
        catch (Exception ex)
        {
            OperationMessage = $"组件预设 {preset} 失败：{ex.Message}";
            return;
        }
        finally
        {
            IsBusy = false;
            RaiseCommandStates();
        }

        await RefreshAfterActionAsync(cancellationToken).ConfigureAwait(true);
    }

    private async Task RunInstallerActionAsync(InstallerProcessRequest request, CancellationToken cancellationToken)
    {
        IsBusy = true;
        RaiseCommandStates();
        try
        {
            OperationMessage = "正在启动 Universal Installer：" + request.Action;
            var result = await _installer.RunAsync(request, cancellationToken).ConfigureAwait(true);
            if (!result.Succeeded)
            {
                var detail = string.IsNullOrWhiteSpace(result.StandardError) ? result.StandardOutput : result.StandardError;
                OperationMessage = $"Installer 操作失败 (RC={result.ExitCode})：{detail.Trim()}";
                return;
            }
            OperationMessage = result.ElevationRequested ? "已请求管理员授权，等待安装状态更新…" : "Installer 操作已提交。";
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            OperationMessage = "安装操作已取消或管理员授权未继续。";
            return;
        }
        catch (Exception ex)
        {
            OperationMessage = "Installer 委派失败：" + ex.Message;
            return;
        }
        finally
        {
            IsBusy = false;
            RaiseCommandStates();
        }

        await RefreshAfterActionAsync(cancellationToken).ConfigureAwait(true);
    }

    private async Task RefreshAfterActionAsync(CancellationToken cancellationToken)
    {
        await RefreshAsync(cancellationToken).ConfigureAwait(true);
    }

    private void Apply(InstallerSnapshot installer, DoctorSnapshot doctor)
    {
        Stage = string.IsNullOrWhiteSpace(installer.Stage) ? "UNKNOWN" : installer.Stage;
        ActiveVersion = string.IsNullOrWhiteSpace(installer.ActiveVersion) ? "-" : installer.ActiveVersion;
        EvidenceRoot = installer.EvidenceRoot;
        LastError = installer.LastError;

        var hasCheckpoint = !string.IsNullOrWhiteSpace(installer.RunId) && !string.IsNullOrWhiteSpace(installer.VersionId);
        _runId = hasCheckpoint ? installer.RunId : null;
        _versionId = hasCheckpoint ? installer.VersionId : null;

        Components.Clear();
        foreach (var component in doctor.Components) Components.Add(component);
        var installable = doctor.Components.Any(x => x.Health is ComponentHealth.ReadyToInstall or ComponentHealth.RepairAvailable);
        CanInstallResume = (installer.CanResume && hasCheckpoint) || installable;
        CanRetryAcquisition = hasCheckpoint && Stage.Equals("ACQUIRE", StringComparison.OrdinalIgnoreCase) && !string.IsNullOrWhiteSpace(installer.LastError);
        CanImportOffline = Stage.Equals("IDLE", StringComparison.OrdinalIgnoreCase) || Stage.Equals("COMPLETE", StringComparison.OrdinalIgnoreCase);
        CanRollback = installer.CanRollback;
        RaiseCommandStates();
    }

    private void RaiseCommandStates()
    {
        _refreshCommand.RaiseCanExecuteChanged();
        _installResumeCommand.RaiseCanExecuteChanged();
        _retryAcquisitionCommand.RaiseCanExecuteChanged();
        _rollbackCommand.RaiseCanExecuteChanged();
        _installCorePresetCommand.RaiseCanExecuteChanged();
        _installLocalAiFastPresetCommand.RaiseCanExecuteChanged();
        _installWebWorkbenchPresetCommand.RaiseCanExecuteChanged();
        _installDeveloperToolsPresetCommand.RaiseCanExecuteChanged();
        _installFullSetupPresetCommand.RaiseCanExecuteChanged();
    }
}
