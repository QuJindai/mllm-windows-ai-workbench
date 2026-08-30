using MLLM.Workbench.Contracts.Components;
using MLLM.Workbench.Contracts.Protocol;
using MLLM.Workbench.Contracts.Snapshots;
using MLLM.Workbench.Contracts.Status;
using MLLM.Workbench.Desktop.Pages.Installation;
using MLLM.Workbench.Infrastructure.Backend;
using MLLM.Workbench.Infrastructure.Installer;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class InstallationViewModelTests
{
    [Fact]
    public async Task Refresh_maps_installer_and_component_truth_without_a_second_detector()
    {
        var installer = new InstallerSnapshot("run-1", "v2", "ACQUIRE", true, "v1", "source unavailable", @"C:\Evidence", true);
        var doctor = new DoctorSnapshot([
            new ComponentSnapshot("python", ComponentHealth.ReadyToInstall, "Python not installed", true, "python"),
            new ComponentSnapshot("git", ComponentHealth.Pass, "ready", false, null)
        ], []);
        await using var backend = new FakeBackendClient(installer, doctor);
        var actions = new FakeInstallerInvoker();
        var vm = new InstallationPageViewModel(backend, actions);

        await vm.RefreshAsync(CancellationToken.None);

        Assert.Equal("ACQUIRE", vm.Stage);
        Assert.Equal("v1", vm.ActiveVersion);
        Assert.Equal(@"C:\Evidence", vm.EvidenceRoot);
        Assert.Equal("source unavailable", vm.LastError);
        Assert.True(vm.CanInstallResume);
        Assert.True(vm.CanRetryAcquisition);
        Assert.True(vm.CanRollback);
        Assert.False(vm.CanImportOffline);
        Assert.Equal(2, vm.Components.Count);
        Assert.Equal(ComponentHealth.ReadyToInstall, vm.Components.Single(x => x.Id == "python").Health);
    }

    [Fact]
    public async Task Idle_state_allows_offline_import_and_ready_component_allows_install()
    {
        var installer = new InstallerSnapshot(null, null, "IDLE", false, null, null, @"C:\Evidence", false);
        var doctor = new DoctorSnapshot([new ComponentSnapshot("python", ComponentHealth.ReadyToInstall, "missing", true, "python")], []);
        await using var backend = new FakeBackendClient(installer, doctor);
        var actions = new FakeInstallerInvoker();
        var vm = new InstallationPageViewModel(backend, actions);

        await vm.RefreshAsync(CancellationToken.None);

        Assert.True(vm.CanInstallResume);
        Assert.True(vm.CanImportOffline);
        Assert.False(vm.CanRetryAcquisition);
        Assert.False(vm.CanRollback);
    }

    [Fact]
    public async Task Commands_delegate_to_installer_invoker_then_refresh_typed_state()
    {
        var installer = new InstallerSnapshot(null, null, "IDLE", false, null, null, @"C:\Evidence", false);
        var doctor = new DoctorSnapshot([new ComponentSnapshot("python", ComponentHealth.ReadyToInstall, "missing", true, "python")], []);
        await using var backend = new FakeBackendClient(installer, doctor);
        var actions = new FakeInstallerInvoker();
        var vm = new InstallationPageViewModel(backend, actions);

        await vm.RefreshAsync(CancellationToken.None);
        await vm.InstallResumeAsync(CancellationToken.None);
        await vm.ImportOfflineAsync(@"C:\Users\Test User\Downloads\M LLM offline.zip", CancellationToken.None);

        Assert.Equal(2, actions.Requests.Count);
        Assert.Equal(InstallerAction.InstallResume, actions.Requests[0].Action);
        Assert.Null(actions.Requests[0].RunId);
        Assert.Null(actions.Requests[0].VersionId);
        Assert.Equal(InstallerAction.ImportOffline, actions.Requests[1].Action);
        Assert.Equal(@"C:\Users\Test User\Downloads\M LLM offline.zip", actions.Requests[1].OfflinePackagePath);
        Assert.True(backend.InstallerReads >= 3);
    }

    [Fact]
    public async Task Resume_and_retry_reuse_the_checkpoint_run_and_version_from_snapshot()
    {
        var installer = new InstallerSnapshot("resume-run-42", "release-v2", "ACQUIRE", true, "v1", "source unavailable", @"C:\Evidence", false);
        var doctor = new DoctorSnapshot([new ComponentSnapshot("python", ComponentHealth.ReadyToInstall, "missing", true, "python")], []);
        await using var backend = new FakeBackendClient(installer, doctor);
        var actions = new FakeInstallerInvoker();
        var vm = new InstallationPageViewModel(backend, actions);

        await vm.RefreshAsync(CancellationToken.None);
        await vm.InstallResumeAsync(CancellationToken.None);
        await vm.RetryAcquisitionAsync(CancellationToken.None);

        Assert.Equal(2, actions.Requests.Count);
        foreach (var request in actions.Requests)
        {
            Assert.Equal("resume-run-42", request.RunId);
            Assert.Equal("release-v2", request.VersionId);
        }
    }

    [Fact]
    public async Task Refresh_loads_safe_core_presets_and_selects_recommended_full_setup()
    {
        var catalog = new ComponentPresetCatalog([
            new ComponentPresetDescriptor("full-setup", "Full Setup", "Complete local AI stack", true, ["python", "modelscope", "llama.cpp", "qwen35-4b-q4km", "local-api", "web-workbench"]),
            new ComponentPresetDescriptor("developer-tools", "Developer Tools", "Git and Git LFS", false, ["git", "git-lfs"])
        ]);
        var installer = new InstallerSnapshot(null, null, "IDLE", false, null, null, @"C:\Evidence", false);
        var doctor = new DoctorSnapshot([new ComponentSnapshot("python", ComponentHealth.ReadyToInstall, "missing", true, "python")], []);
        await using var backend = new FakeBackendClient(installer, doctor, catalog);
        var vm = new InstallationPageViewModel(backend, new FakeInstallerInvoker());

        await vm.RefreshAsync(CancellationToken.None);

        Assert.Equal(2, vm.Presets.Count);
        Assert.Equal("full-setup", vm.SelectedPreset?.Id);
        Assert.True(vm.CanInstallPreset);
    }

    [Fact]
    public async Task Install_selected_preset_uses_restricted_backend_rpc_and_refreshes_doctor_truth()
    {
        var catalog = new ComponentPresetCatalog([
            new ComponentPresetDescriptor("full-setup", "Full Setup", "Complete local AI stack", true, ["python", "modelscope", "llama.cpp", "qwen35-4b-q4km", "local-api", "web-workbench"])
        ]);
        var installer = new InstallerSnapshot(null, null, "IDLE", false, null, null, @"C:\Evidence", false);
        var doctor = new DoctorSnapshot([new ComponentSnapshot("python", ComponentHealth.ReadyToInstall, "missing", true, "python")], []);
        await using var backend = new FakeBackendClient(installer, doctor, catalog);
        var vm = new InstallationPageViewModel(backend, new FakeInstallerInvoker());

        await vm.RefreshAsync(CancellationToken.None);
        await vm.InstallSelectedPresetAsync(CancellationToken.None);

        var request = Assert.Single(backend.PresetInstallRequests);
        Assert.Equal("full-setup", request.PresetId);
        Assert.Matches("^[0-9a-f]{32}$", request.OperationId);
        Assert.True(backend.DoctorReads >= 2);
        Assert.Contains("Full Setup", vm.OperationMessage, StringComparison.Ordinal);
    }

    private sealed class FakeInstallerInvoker : IPrivilegedInstallerInvoker
    {
        public List<InstallerProcessRequest> Requests { get; } = [];
        public Task<InstallerProcessResult> RunAsync(InstallerProcessRequest request, CancellationToken cancellationToken)
        {
            Requests.Add(request);
            return Task.FromResult(new InstallerProcessResult(0, "UNIVERSAL_INSTALLER_ACTION=PASS", ""));
        }
    }

    private sealed class FakeBackendClient : IWorkbenchBackendClient
    {
        private readonly InstallerSnapshot _installer;
        private readonly DoctorSnapshot _doctor;
        private readonly ComponentPresetCatalog _catalog;
        public FakeBackendClient(InstallerSnapshot installer, DoctorSnapshot doctor, ComponentPresetCatalog? catalog = null)
        {
            _installer = installer;
            _doctor = doctor;
            _catalog = catalog ?? new ComponentPresetCatalog([]);
        }
        public int InstallerReads { get; private set; }
        public int DoctorReads { get; private set; }
        public List<ComponentPresetInstallRequest> PresetInstallRequests { get; } = [];
        public Task<BackendHandshakeResponse> ConnectAsync(CancellationToken cancellationToken) => Task.FromResult(new BackendHandshakeResponse(true, RpcProtocol.Version, "test", null));
        public Task<TResponse> InvokeAsync<TResponse>(string method, object? payload, CancellationToken cancellationToken)
        {
            if (method == "components.presets") return Task.FromResult((TResponse)(object)_catalog);
            if (method == "components.install_preset")
            {
                var request = Assert.IsType<ComponentPresetInstallRequest>(payload);
                PresetInstallRequests.Add(request);
                var result = new ComponentPresetInstallResult(request.PresetId, "Full Setup", [new ComponentPresetTaskResult("python", "PASS", "ready")]);
                return Task.FromResult((TResponse)(object)result);
            }
            throw new NotSupportedException(method);
        }
        public Task<DashboardSnapshot> GetDashboardAsync(CancellationToken cancellationToken) => throw new NotSupportedException();
        public Task<DoctorSnapshot> GetDoctorAsync(CancellationToken cancellationToken) { DoctorReads++; return Task.FromResult(_doctor); }
        public Task<InstallerSnapshot> GetInstallerAsync(CancellationToken cancellationToken) { InstallerReads++; return Task.FromResult(_installer); }
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
