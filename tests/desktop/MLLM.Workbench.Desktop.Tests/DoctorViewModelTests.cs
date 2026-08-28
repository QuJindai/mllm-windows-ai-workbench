using MLLM.Workbench.Contracts.Operations;
using MLLM.Workbench.Contracts.Protocol;
using MLLM.Workbench.Contracts.Snapshots;
using MLLM.Workbench.Contracts.Status;
using MLLM.Workbench.Desktop.Pages.Doctor;
using MLLM.Workbench.Infrastructure.Backend;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class DoctorViewModelTests
{
    [Fact]
    public async Task Refresh_preserves_exact_health_semantics_and_separates_product_faults()
    {
        var snapshot = new DoctorSnapshot(
            [
                C("git", ComponentHealth.Pass),
                C("local-api", ComponentHealth.Running),
                C("python", ComponentHealth.ReadyToInstall),
                C("llama-cpp", ComponentHealth.RepairAvailable),
                C("modelscope", ComponentHealth.Blocked),
                C("model", ComponentHealth.NotFound),
                C("backend-detector", ComponentHealth.DetectionError),
                C("install-op", ComponentHealth.OperationFailed),
                C("unknown", ComponentHealth.Unknown)
            ],
            []);
        await using var backend = new FakeBackendClient(snapshot);
        var vm = new DoctorPageViewModel(backend);

        await vm.RefreshAsync(CancellationToken.None);

        Assert.Equal("正常", Row(vm, "git").DisplayState);
        Assert.Equal("运行中", Row(vm, "local-api").DisplayState);
        Assert.Equal("可安装", Row(vm, "python").DisplayState);
        Assert.Equal("可修复", Row(vm, "llama-cpp").DisplayState);
        Assert.Equal("受阻", Row(vm, "modelscope").DisplayState);
        Assert.Equal("未检测到", Row(vm, "model").DisplayState);
        Assert.Equal("检测器错误", Row(vm, "backend-detector").DisplayState);
        Assert.Equal("操作失败", Row(vm, "install-op").DisplayState);
        Assert.Equal("未知", Row(vm, "unknown").DisplayState);
        Assert.False(Row(vm, "python").IsProductFault);
        Assert.True(Row(vm, "backend-detector").IsProductFault);
        Assert.Contains("backend-detector", vm.ProductFaultMessage, StringComparison.OrdinalIgnoreCase);
        Assert.Null(vm.BackendError);
    }

    [Fact]
    public async Task Backend_transport_error_is_a_product_fault_not_a_missing_component()
    {
        await using var backend = new FakeBackendClient(new BackendRpcException("BACKEND_DETECTION_ERROR", "scope lost"));
        var vm = new DoctorPageViewModel(backend);

        await vm.RefreshAsync(CancellationToken.None);

        Assert.Contains("scope lost", vm.BackendError, StringComparison.OrdinalIgnoreCase);
        Assert.Empty(vm.Rows);
        Assert.True(vm.HasProductFault);
    }

    [Fact]
    public async Task Structured_doctor_errors_are_visible_as_product_faults()
    {
        var error = new OperationError("BACKEND_DETECTION_ERROR", "detector crashed", "Doctor", true, null);
        await using var backend = new FakeBackendClient(new DoctorSnapshot([C("python", ComponentHealth.ReadyToInstall)], [error]));
        var vm = new DoctorPageViewModel(backend);

        await vm.RefreshAsync(CancellationToken.None);

        Assert.Equal("可安装", Row(vm, "python").DisplayState);
        Assert.Contains("detector crashed", vm.ProductFaultMessage, StringComparison.OrdinalIgnoreCase);
        Assert.True(vm.HasProductFault);
    }

    private static ComponentSnapshot C(string id, ComponentHealth health) => new(id, health, id + " summary", health is ComponentHealth.ReadyToInstall or ComponentHealth.RepairAvailable, health is ComponentHealth.ReadyToInstall or ComponentHealth.RepairAvailable ? id : null);
    private static DoctorRowViewModel Row(DoctorPageViewModel vm, string id) => vm.Rows.Single(x => x.Id == id);

    private sealed class FakeBackendClient : IWorkbenchBackendClient
    {
        private readonly DoctorSnapshot? _snapshot;
        private readonly Exception? _error;
        public FakeBackendClient(DoctorSnapshot snapshot) => _snapshot = snapshot;
        public FakeBackendClient(Exception error) => _error = error;
        public Task<BackendHandshakeResponse> ConnectAsync(CancellationToken cancellationToken) => Task.FromResult(new BackendHandshakeResponse(true, RpcProtocol.Version, "test", null));
        public Task<TResponse> InvokeAsync<TResponse>(string method, object? payload, CancellationToken cancellationToken) => throw new NotSupportedException();
        public Task<DashboardSnapshot> GetDashboardAsync(CancellationToken cancellationToken) => throw new NotSupportedException();
        public Task<DoctorSnapshot> GetDoctorAsync(CancellationToken cancellationToken) => _error is not null ? Task.FromException<DoctorSnapshot>(_error) : Task.FromResult(_snapshot!);
        public Task<InstallerSnapshot> GetInstallerAsync(CancellationToken cancellationToken) => throw new NotSupportedException();
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
