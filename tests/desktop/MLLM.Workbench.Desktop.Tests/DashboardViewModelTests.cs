using System.Text.Json;
using MLLM.Workbench.Contracts.Protocol;
using MLLM.Workbench.Contracts.Snapshots;
using MLLM.Workbench.Contracts.Status;
using MLLM.Workbench.Desktop.Pages.Dashboard;
using MLLM.Workbench.Infrastructure.Backend;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class DashboardViewModelTests
{
    [Fact]
    public async Task Refresh_maps_only_typed_backend_snapshot_into_dashboard_state()
    {
        var snapshot = new DashboardSnapshot(new MachineSnapshot("Windows 11 Pro 23H2", "AMD64", "Test CPU", 31.75, ["Test GPU"], 412.6), "OFFLINE_CACHE", [new ComponentSnapshot("git", ComponentHealth.Pass, "git ready", false, null), new ComponentSnapshot("local-api", ComponentHealth.Running, "API running", false, null), new ComponentSnapshot("python", ComponentHealth.ReadyToInstall, "Python not installed", true, "python"), new ComponentSnapshot("modelscope", ComponentHealth.Blocked, "Python required", true, "python")], "Qwen3.5-4B Q4_K_M");
        await using var backend = new FakeBackendClient(snapshot);
        var vm = new DashboardPageViewModel(backend);
        await vm.RefreshAsync(CancellationToken.None);
        Assert.Equal("OFFLINE_CACHE", vm.NetworkMode); Assert.Equal("Windows 11 Pro 23H2", vm.OperatingSystem); Assert.Equal("Test CPU", vm.Cpu); Assert.Equal("31.8 GB", vm.Ram); Assert.Equal("Test GPU", vm.Gpu); Assert.Equal("412.6 GB", vm.DiskFree); Assert.Equal("Qwen3.5-4B Q4_K_M", vm.CurrentModelDisplay); Assert.Equal(1, vm.PassCount); Assert.Equal(1, vm.RunningCount); Assert.Equal(1, vm.ReadyCount); Assert.Equal(1, vm.BlockedCount); Assert.Single(vm.ServiceComponents); Assert.Null(vm.BackendError);
    }

    [Fact]
    public async Task Backend_failure_is_a_page_error_not_a_component_failure()
    {
        await using var backend = new FakeBackendClient(new BackendRpcException("BACKEND_DETECTION_ERROR", "scope failure"));
        var vm = new DashboardPageViewModel(backend);
        await vm.RefreshAsync(CancellationToken.None);
        Assert.Contains("scope failure", vm.BackendError, StringComparison.OrdinalIgnoreCase); Assert.Empty(vm.Components); Assert.Equal(0, vm.BlockedCount);
    }

    [Fact]
    public async Task Quick_navigation_commands_emit_approved_phase_a_routes()
    {
        await using var backend = new FakeBackendClient(new DashboardSnapshot(new MachineSnapshot("Windows", "AMD64", "CPU", 1, [], 1), "OFFLINE_CACHE", [], null));
        var vm = new DashboardPageViewModel(backend);
        string? route = null; vm.NavigationRequested += value => route = value;
        vm.OpenDoctorCommand.Execute(null); Assert.Equal("doctor", route); vm.OpenInstallationCommand.Execute(null); Assert.Equal("installation", route);
    }

    private sealed class FakeBackendClient : IWorkbenchBackendClient
    {
        private readonly DashboardSnapshot? _snapshot; private readonly Exception? _error;
        public FakeBackendClient(DashboardSnapshot snapshot) => _snapshot = snapshot; public FakeBackendClient(Exception error) => _error = error;
        public Task<BackendHandshakeResponse> ConnectAsync(CancellationToken cancellationToken) => Task.FromResult(new BackendHandshakeResponse(true, RpcProtocol.Version, "test", null));
        public Task<TResponse> InvokeAsync<TResponse>(string method, object? payload, CancellationToken cancellationToken) => throw new NotSupportedException();
        public Task<DashboardSnapshot> GetDashboardAsync(CancellationToken cancellationToken) => _error is not null ? Task.FromException<DashboardSnapshot>(_error) : Task.FromResult(_snapshot!);
        public Task<DoctorSnapshot> GetDoctorAsync(CancellationToken cancellationToken) => throw new NotSupportedException(); public Task<InstallerSnapshot> GetInstallerAsync(CancellationToken cancellationToken) => throw new NotSupportedException(); public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
