using MLLM.Workbench.Contracts.Models;
using MLLM.Workbench.Contracts.Protocol;
using MLLM.Workbench.Contracts.Services;
using MLLM.Workbench.Infrastructure.Backend;

namespace MLLM.Workbench.Infrastructure.Tests;

public sealed class PhaseBBackendClientTests
{
    [Fact]
    public async Task Real_backend_advertises_phase_b_and_returns_model_and_service_snapshots()
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(90));
        var root = FindRepositoryRoot();
        var dataRoot = Path.Combine(Path.GetTempPath(), "mllm phase b backend " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dataRoot);
        try
        {
            await using var host = new BackendProcessHost(root, dataRoot, "OFFLINE_CACHE");
            await host.StartAsync(timeout.Token);
            await using IWorkbenchBackendClient client = new NamedPipeBackendClient(host.Options);
            var handshake = await client.ConnectAsync(timeout.Token);
            Assert.True(handshake.Accepted);
            Assert.Equal(RpcProtocol.Version, handshake.Protocol);

            var capabilities = await client.GetCapabilitiesAsync(timeout.Token);
            Assert.Equal("phase-b", capabilities.BackendVersion);
            foreach (var required in new[]
            {
                "models.snapshot","models.verify","models.import","models.activate",
                "services.snapshot","service.start","service.stop","service.restart","service.logs"
            })
                Assert.Contains(required, capabilities.Methods);

            var models = await client.GetModelsAsync(timeout.Token);
            Assert.Equal("OFFLINE_CACHE", models.NetworkMode);
            Assert.Contains(models.Models, x => x.Id == "qwen35-4b-q4km" && x.IntegrityState == ModelIntegrityState.Missing);

            var services = await client.GetServicesAsync(timeout.Token);
            Assert.Equal("OFFLINE_CACHE", services.NetworkMode);
            Assert.Equal(new[] { "local-model-api", "web-workbench" }, services.Services.Select(x => x.ServiceId).ToArray());
            Assert.All(services.Services, x => Assert.Equal(ManagedServiceState.Stopped, x.State));
        }
        finally
        {
            Directory.Delete(dataRoot, recursive: true);
        }
    }

    [Fact]
    public async Task Backend_rejects_unknown_service_model_and_arbitrary_method()
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(90));
        var root = FindRepositoryRoot();
        var dataRoot = Path.Combine(Path.GetTempPath(), "mllm phase b reject " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dataRoot);
        try
        {
            await using var host = new BackendProcessHost(root, dataRoot, "OFFLINE_CACHE");
            await host.StartAsync(timeout.Token);
            await using IWorkbenchBackendClient client = new NamedPipeBackendClient(host.Options);
            Assert.True((await client.ConnectAsync(timeout.Token)).Accepted);

            var serviceError = await Assert.ThrowsAsync<BackendRpcException>(() =>
                client.StartServiceAsync(new ServiceActionRequest("not-a-service", "op-service"), timeout.Token));
            Assert.Equal("SERVICE_NOT_FOUND", serviceError.Code);

            var modelError = await Assert.ThrowsAsync<BackendRpcException>(() =>
                client.VerifyModelAsync(new ModelVerifyRequest("not-a-model", "op-model"), timeout.Token));
            Assert.Equal("MODEL_NOT_FOUND", modelError.Code);

            var methodError = await Assert.ThrowsAsync<BackendRpcException>(() =>
                client.InvokeAsync<object>("exec", new { command = "whoami" }, timeout.Token));
            Assert.Equal("METHOD_NOT_FOUND", methodError.Code);
        }
        finally
        {
            Directory.Delete(dataRoot, recursive: true);
        }
    }

    private static string FindRepositoryRoot()
    {
        var cursor = new DirectoryInfo(AppContext.BaseDirectory);
        while (cursor is not null)
        {
            if (File.Exists(Path.Combine(cursor.FullName, "Bootstrap_SafeCore.ps1"))) return cursor.FullName;
            cursor = cursor.Parent;
        }
        throw new DirectoryNotFoundException("Repository root was not found.");
    }
}
