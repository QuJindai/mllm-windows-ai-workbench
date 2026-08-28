using System.Text.Json;
using MLLM.Workbench.Contracts.Models;
using MLLM.Workbench.Contracts.Protocol;
using MLLM.Workbench.Contracts.Services;
using MLLM.Workbench.Contracts.Snapshots;
using MLLM.Workbench.Desktop.Pages.Models;
using MLLM.Workbench.Desktop.Services;
using MLLM.Workbench.Infrastructure.Backend;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class ModelManagementViewModelTests
{
    [Fact]
    public async Task Refresh_maps_real_model_snapshot_and_distinguishes_unanchored_hash()
    {
        var models = new ModelSnapshot([
            M("builtin", ModelIntegrityState.HashComputedUnanchored, true),
            M("trusted", ModelIntegrityState.Sha256Pass, false),
            M("missing", ModelIntegrityState.Missing, false)
        ], "builtin", "OFFLINE_CACHE");
        var services = new ServicesSnapshot([S(ManagedServiceState.Stopped), W()], "OFFLINE_CACHE");
        await using var backend = new FakeBackend(models, services);
        var vm = new ModelManagementPageViewModel(backend, new WorkbenchMutationGate());

        await vm.RefreshAsync(CancellationToken.None);

        Assert.Equal(3, vm.TotalCount);
        Assert.Equal(2, vm.StructurallyValidCount);
        Assert.Equal(1, vm.TrustedShaCount);
        Assert.Equal("OFFLINE_CACHE", vm.NetworkMode);
        Assert.Contains("builtin", vm.ActiveModelDisplay, StringComparison.OrdinalIgnoreCase);
        Assert.Contains(vm.Models, x => x.Id == "builtin" && x.IntegrityState == ModelIntegrityState.HashComputedUnanchored);
        Assert.Null(vm.BackendError);
    }

    [Fact]
    public async Task Import_and_verify_send_source_model_and_unique_operation_ids()
    {
        var models = new ModelSnapshot([M("builtin", ModelIntegrityState.HashComputedUnanchored, true)], "builtin", "OFFLINE_CACHE");
        await using var backend = new FakeBackend(models, new ServicesSnapshot([S(ManagedServiceState.Stopped), W()], "OFFLINE_CACHE"));
        var vm = new ModelManagementPageViewModel(backend, new WorkbenchMutationGate());
        await vm.RefreshAsync(CancellationToken.None);
        vm.SelectedModel = vm.Models.Single();

        await vm.ImportAsync(@"C:\Users\Test User\Downloads\local model.gguf", CancellationToken.None);
        await vm.VerifyAsync(CancellationToken.None);

        Assert.Single(backend.Imports);
        Assert.Equal(@"C:\Users\Test User\Downloads\local model.gguf", backend.Imports[0].SourcePath);
        Assert.Single(backend.Verifies);
        Assert.Equal("builtin", backend.Verifies[0].ModelId);
        Assert.Matches("^[0-9a-f]{32}$", backend.Imports[0].OperationId);
        Assert.Matches("^[0-9a-f]{32}$", backend.Verifies[0].OperationId);
        Assert.NotEqual(backend.Imports[0].OperationId, backend.Verifies[0].OperationId);
    }

    [Fact]
    public async Task Activation_is_disabled_for_invalid_model_or_running_local_service()
    {
        var models = new ModelSnapshot([M("valid", ModelIntegrityState.HashComputedUnanchored, false), M("bad", ModelIntegrityState.Failed, false)], null, "OFFLINE_CACHE");
        var running = new ServicesSnapshot([S(ManagedServiceState.Running), W()], "OFFLINE_CACHE");
        await using var backend = new FakeBackend(models, running);
        var vm = new ModelManagementPageViewModel(backend, new WorkbenchMutationGate());
        await vm.RefreshAsync(CancellationToken.None);

        vm.SelectedModel = vm.Models.Single(x => x.Id == "valid");
        Assert.False(vm.CanActivate);

        backend.Services = new ServicesSnapshot([S(ManagedServiceState.Stopped), W()], "OFFLINE_CACHE");
        await vm.RefreshAsync(CancellationToken.None);
        vm.SelectedModel = vm.Models.Single(x => x.Id == "bad");
        Assert.False(vm.CanActivate);
        vm.SelectedModel = vm.Models.Single(x => x.Id == "valid");
        Assert.True(vm.CanActivate);
    }

    [Fact]
    public async Task Shared_mutation_gate_serializes_model_mutations_across_callers()
    {
        var gate = new WorkbenchMutationGate();
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var order = new List<string>();

        var first = gate.RunAsync(async ct => { order.Add("first-enter"); entered.SetResult(); await release.Task.WaitAsync(ct); order.Add("first-exit"); }, CancellationToken.None);
        await entered.Task;
        var second = gate.RunAsync(async ct => { order.Add("second-enter"); await Task.Yield(); order.Add("second-exit"); }, CancellationToken.None);
        await Task.Delay(50);
        Assert.Equal(["first-enter"], order);
        Assert.True(gate.IsBusy);
        release.SetResult();
        await Task.WhenAll(first, second);
        Assert.Equal(["first-enter", "first-exit", "second-enter", "second-exit"], order);
        Assert.False(gate.IsBusy);
    }

    private static ModelDescriptor M(string id, ModelIntegrityState state, bool active) =>
        new(id, "local-fast", id, ModelSourceKind.BuiltIn, @"C:\Models\" + id + ".gguf", id + ".gguf", "gguf", "Q4_K_M", 100, 4, null, state == ModelIntegrityState.Missing ? null : new string('a',64), state, active, state is ModelIntegrityState.Missing or ModelIntegrityState.Failed ? "blocked" : null);

    private static ServiceDescriptor S(ManagedServiceState state) =>
        new("local-model-api", "Local Model API", state, state == ManagedServiceState.Running ? 42 : null, state == ManagedServiceState.Running ? 8080 : null, state == ManagedServiceState.Running ? "http://127.0.0.1:8080" : null, null, null, "builtin", @"C:\Models\builtin.gguf", state.ToString(), null, null, state == ManagedServiceState.Stopped, state == ManagedServiceState.Running, state == ManagedServiceState.Running, null);

    private static ServiceDescriptor W() =>
        new("web-workbench", "Web Workbench", ManagedServiceState.Stopped, null, null, null, null, null, null, null, "Stopped", null, null, true, false, false, null);

    private sealed class FakeBackend : IWorkbenchBackendClient
    {
        public FakeBackend(ModelSnapshot models, ServicesSnapshot services) { Models = models; Services = services; }
        public ModelSnapshot Models { get; set; }
        public ServicesSnapshot Services { get; set; }
        public List<ModelImportRequest> Imports { get; } = [];
        public List<ModelVerifyRequest> Verifies { get; } = [];
        public List<ModelActivateRequest> Activations { get; } = [];

        public Task<BackendHandshakeResponse> ConnectAsync(CancellationToken cancellationToken) => Task.FromResult(new BackendHandshakeResponse(true, RpcProtocol.Version, "phase-b", null));
        public Task<TResponse> InvokeAsync<TResponse>(string method, object? payload, CancellationToken cancellationToken)
        {
            object result = method switch
            {
                "models.snapshot" => Models,
                "services.snapshot" => Services,
                "models.import" => RecordImport((ModelImportRequest)payload!),
                "models.verify" => RecordVerify((ModelVerifyRequest)payload!),
                "models.activate" => RecordActivate((ModelActivateRequest)payload!),
                _ => throw new NotSupportedException(method)
            };
            return Task.FromResult((TResponse)result);
        }
        private ModelDescriptor RecordImport(ModelImportRequest request) { Imports.Add(request); return Models.Models.First(); }
        private ModelDescriptor RecordVerify(ModelVerifyRequest request) { Verifies.Add(request); return Models.Models.Single(x => x.Id == request.ModelId); }
        private ModelDescriptor RecordActivate(ModelActivateRequest request) { Activations.Add(request); return Models.Models.Single(x => x.Id == request.ModelId); }
        public Task<DashboardSnapshot> GetDashboardAsync(CancellationToken cancellationToken) => throw new NotSupportedException();
        public Task<DoctorSnapshot> GetDoctorAsync(CancellationToken cancellationToken) => throw new NotSupportedException();
        public Task<InstallerSnapshot> GetInstallerAsync(CancellationToken cancellationToken) => throw new NotSupportedException();
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
