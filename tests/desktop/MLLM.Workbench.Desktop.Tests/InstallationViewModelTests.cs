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
        Assert.Equal(InstallerAction.ImportOffline, actions.Requests[1].Action);
        Assert.Equal(@"C:\Users\Test User\Downloads\M LLM offline.zip", actions.Requests[1].OfflinePackagePath);
        Assert.True(backend.InstallerReads >= 3);
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
        public FakeBackendClient(InstallerSnapshot installer, DoctorSnapshot doctor) { _installer = installer; _doctor = doctor; }
        public int InstallerReads { get; private set; }
        public Task<BackendHandshakeResponse> ConnectAsync(CancellationToken cancellationToken) => Task.FromResult(new BackendHandshakeResponse(true, RpcProtocol.Version, "test", null));
        public Task<TResponse> InvokeAsync<TResponse>(string method, object? payload, CancellationToken cancellationToken) => throw new NotSupportedException();
        public Task<DashboardSnapshot> GetDashboardAsync(CancellationToken cancellationToken) => throw new NotSupportedException();
        public Task<DoctorSnapshot> GetDoctorAsync(CancellationToken cancellationToken) => Task.FromResult(_doctor);
        public Task<InstallerSnapshot> GetInstallerAsync(CancellationToken cancellationToken) { InstallerReads++; return Task.FromResult(_installer); }
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
