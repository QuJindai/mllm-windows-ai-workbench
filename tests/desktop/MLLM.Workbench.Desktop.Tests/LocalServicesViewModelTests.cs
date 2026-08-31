using System.Text.Json;
using MLLM.Workbench.Contracts.Protocol;
using MLLM.Workbench.Contracts.Services;
using MLLM.Workbench.Contracts.Snapshots;
using MLLM.Workbench.Desktop.Pages.Services;
using MLLM.Workbench.Desktop.Services;
using MLLM.Workbench.Desktop.Shell;
using MLLM.Workbench.Infrastructure.Backend;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class LocalServicesViewModelTests
{
    [Fact]
    public async Task Refresh_maps_services_preserves_selection_and_capabilities()
    {
        await using var backend = new FakeBackend(new ServicesSnapshot([RunningApi(), StoppedWeb()], "AUTO_CN_FIRST"));
        var clipboard = new FakeClipboard();
        var vm = new LocalServicesPageViewModel(backend, new WorkbenchMutationGate(), clipboard);

        await vm.RefreshAsync(CancellationToken.None);

        Assert.Equal(2, vm.Services.Count);
        Assert.Equal("AUTO_CN_FIRST", vm.NetworkMode);
        Assert.Equal("local-model-api", vm.SelectedService!.ServiceId);
        Assert.True(vm.CanStopSelected);
        Assert.True(vm.CanRestartSelected);
        Assert.False(vm.CanStartSelected);

        vm.SelectedService = vm.Services.Single(x => x.ServiceId == "web-workbench");
        backend.Services = new ServicesSnapshot([StoppedApi(), RunningWeb()], "AUTO_CN_FIRST");
        await vm.RefreshAsync(CancellationToken.None);

        Assert.Equal("web-workbench", vm.SelectedService!.ServiceId);
        Assert.False(vm.CanStartSelected);
        Assert.True(vm.CanStopSelected);
    }

    [Fact]
    public async Task Start_stop_restart_use_selected_typed_service_and_refresh_authoritative_state()
    {
        await using var backend = new FakeBackend(new ServicesSnapshot([RunningApi(), StoppedWeb()], "AUTO_CN_FIRST"));
        var vm = new LocalServicesPageViewModel(backend, new WorkbenchMutationGate(), new FakeClipboard());
        await vm.RefreshAsync(CancellationToken.None);
        var initialSnapshots = backend.ServiceSnapshotCalls;

        vm.SelectedService = vm.Services.Single(x => x.ServiceId == "web-workbench");
        await vm.StartSelectedAsync(CancellationToken.None);
        Assert.Single(backend.Starts);
        Assert.Equal("web-workbench", backend.Starts[0].ServiceId);
        Assert.Matches("^[0-9a-f]{32}$", backend.Starts[0].OperationId);
        Assert.True(backend.ServiceSnapshotCalls > initialSnapshots);

        vm.SelectedService = vm.Services.Single(x => x.ServiceId == "local-model-api");
        await vm.StopSelectedAsync(CancellationToken.None);
        await vm.RestartSelectedAsync(CancellationToken.None);

        Assert.Single(backend.Stops);
        Assert.Single(backend.Restarts);
        Assert.Equal("local-model-api", backend.Stops[0].ServiceId);
        Assert.Equal("local-model-api", backend.Restarts[0].ServiceId);
        Assert.Matches("^[0-9a-f]{32}$", backend.Stops[0].OperationId);
        Assert.Matches("^[0-9a-f]{32}$", backend.Restarts[0].OperationId);
        Assert.Equal(3, new[] { backend.Starts[0].OperationId, backend.Stops[0].OperationId, backend.Restarts[0].OperationId }.Distinct().Count());
    }

    [Fact]
    public async Task Logs_are_bounded_and_copy_endpoint_uses_only_backend_descriptor_url()
    {
        await using var backend = new FakeBackend(new ServicesSnapshot([RunningApi(), StoppedWeb()], "AUTO_CN_FIRST"))
        {
            Logs = new ServiceLogTail("local-model-api", @"C:\Data\stdout.log", @"C:\Data\stderr.log", ["ready", "request ok"], ["warning"])
        };
        var clipboard = new FakeClipboard();
        var vm = new LocalServicesPageViewModel(backend, new WorkbenchMutationGate(), clipboard);
        await vm.RefreshAsync(CancellationToken.None);

        await vm.LoadLogsAsync(CancellationToken.None);
        Assert.Single(backend.LogRequests);
        Assert.Equal("local-model-api", backend.LogRequests[0].ServiceId);
        Assert.InRange(backend.LogRequests[0].TailLines, 1, 500);
        Assert.Equal(200, backend.LogRequests[0].TailLines);
        Assert.Contains("ready", vm.LogText, StringComparison.Ordinal);
        Assert.Contains("warning", vm.LogText, StringComparison.Ordinal);
        Assert.DoesNotContain(@"C:\Data\stdout.log", vm.LogText, StringComparison.OrdinalIgnoreCase);

        Assert.True(vm.CanCopyEndpoint);
        vm.CopyEndpointCommand.Execute(null);
        Assert.Equal("http://127.0.0.1:8080", clipboard.LastText);
    }

    [Fact]
    public async Task Command_failure_is_captured_as_page_error_and_does_not_escape_async_command()
    {
        await using var backend = new FakeBackend(new ServicesSnapshot([RunningApi(), StoppedWeb()], "AUTO_CN_FIRST"))
        {
            ServiceActionFailure = new BackendRpcException("SERVICE_RUNTIME_MISSING", "llama runtime missing")
        };
        var vm = new LocalServicesPageViewModel(backend, new WorkbenchMutationGate(), new FakeClipboard());
        await vm.RefreshAsync(CancellationToken.None);
        vm.SelectedService = vm.Services.Single(x => x.ServiceId == "web-workbench");

        var command = Assert.IsType<AsyncRelayCommand>(vm.StartCommand);
        var escaped = await Record.ExceptionAsync(command.ExecuteAsync);

        Assert.Null(escaped);
        Assert.Contains("llama runtime missing", vm.LastError, StringComparison.OrdinalIgnoreCase);
        Assert.False(vm.IsBusy);
    }

    private static ServiceDescriptor RunningApi() =>
        new("local-model-api", "Local Model API", ManagedServiceState.Running, 42, 8080, "http://127.0.0.1:8080", DateTimeOffset.UtcNow, 10, "qwen", @"C:\Models\qwen.gguf", "Healthy", null, null, false, true, true, null);

    private static ServiceDescriptor StoppedApi() =>
        new("local-model-api", "Local Model API", ManagedServiceState.Stopped, null, null, null, null, null, "qwen", @"C:\Models\qwen.gguf", "Stopped", null, null, true, false, false, null);

    private static ServiceDescriptor StoppedWeb() =>
        new("web-workbench", "Web Workbench", ManagedServiceState.Stopped, null, null, null, null, null, null, null, "Stopped", null, null, true, false, false, null);

    private static ServiceDescriptor RunningWeb() =>
        new("web-workbench", "Web Workbench", ManagedServiceState.Running, 43, 8090, "http://127.0.0.1:8090", DateTimeOffset.UtcNow, 8, null, null, "Healthy", null, null, false, true, true, null);

    private sealed class FakeClipboard : IClipboardService
    {
        public string? LastText { get; private set; }
        public void SetText(string text) => LastText = text;
    }

    private sealed class FakeBackend : IWorkbenchBackendClient
    {
        public FakeBackend(ServicesSnapshot services) => Services = services;
        public ServicesSnapshot Services { get; set; }
        public ServiceLogTail Logs { get; set; } = new("local-model-api", null, null, [], []);
        public Exception? ServiceActionFailure { get; set; }
        public int ServiceSnapshotCalls { get; private set; }
        public List<ServiceActionRequest> Starts { get; } = [];
        public List<ServiceActionRequest> Stops { get; } = [];
        public List<ServiceActionRequest> Restarts { get; } = [];
        public List<ServiceLogRequest> LogRequests { get; } = [];

        public Task<BackendHandshakeResponse> ConnectAsync(CancellationToken cancellationToken) =>
            Task.FromResult(new BackendHandshakeResponse(true, RpcProtocol.Version, "phase-b", null));

        public Task<TResponse> InvokeAsync<TResponse>(string method, object? payload, CancellationToken cancellationToken)
        {
            if (ServiceActionFailure is not null && method is "service.start" or "service.stop" or "service.restart")
                return Task.FromException<TResponse>(ServiceActionFailure);

            object result = method switch
            {
                "services.snapshot" => Snapshot(),
                "service.start" => Record(Starts, (ServiceActionRequest)payload!),
                "service.stop" => Record(Stops, (ServiceActionRequest)payload!),
                "service.restart" => Record(Restarts, (ServiceActionRequest)payload!),
                "service.logs" => RecordLogs((ServiceLogRequest)payload!),
                _ => throw new NotSupportedException(method)
            };
            return Task.FromResult((TResponse)result);
        }

        private ServicesSnapshot Snapshot() { ServiceSnapshotCalls++; return Services; }
        private ServiceDescriptor Record(List<ServiceActionRequest> list, ServiceActionRequest request)
        {
            list.Add(request);
            return Services.Services.First(x => x.ServiceId == request.ServiceId);
        }
        private ServiceLogTail RecordLogs(ServiceLogRequest request) { LogRequests.Add(request); return Logs; }

        public Task<DashboardSnapshot> GetDashboardAsync(CancellationToken cancellationToken) => throw new NotSupportedException();
        public Task<DoctorSnapshot> GetDoctorAsync(CancellationToken cancellationToken) => throw new NotSupportedException();
        public Task<InstallerSnapshot> GetInstallerAsync(CancellationToken cancellationToken) => throw new NotSupportedException();
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
