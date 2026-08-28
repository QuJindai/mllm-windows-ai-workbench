using System.Text.Json;
using MLLM.Workbench.Contracts.Protocol;
using MLLM.Workbench.Infrastructure.Backend;

namespace MLLM.Workbench.Infrastructure.Tests;

public sealed class NamedPipeHandshakeTests
{
    [Fact]
    public async Task Real_ps51_backend_accepts_authenticated_client_and_serves_ping()
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        var root = FindRepositoryRoot();
        var dataRoot = Path.Combine(Path.GetTempPath(), "mllm pipe test " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dataRoot);

        await using var host = new BackendProcessHost(root, dataRoot, "OFFLINE_CACHE");
        await host.StartAsync(timeout.Token);
        await using var client = new NamedPipeBackendClient(host.Options);

        var handshake = await client.ConnectAsync(timeout.Token);
        Assert.True(handshake.Accepted);
        Assert.Equal(RpcProtocol.Version, handshake.Protocol);
        Assert.NotEmpty(handshake.BackendVersion);

        var ping = await client.InvokeAsync<JsonElement>("system.ping", null, timeout.Token);
        Assert.Equal("PASS", ping.GetProperty("status").GetString());
    }

    [Fact]
    public async Task Real_ps51_backend_rejects_wrong_session_token()
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        var root = FindRepositoryRoot();
        var dataRoot = Path.Combine(Path.GetTempPath(), "mllm pipe auth " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dataRoot);

        await using var host = new BackendProcessHost(root, dataRoot, "OFFLINE_CACHE");
        await host.StartAsync(timeout.Token);
        var bad = host.Options with { SessionToken = host.Options.SessionToken + "-wrong" };
        await using var client = new NamedPipeBackendClient(bad);

        var handshake = await client.ConnectAsync(timeout.Token);
        Assert.False(handshake.Accepted);
    }

    private static string FindRepositoryRoot()
    {
        var cursor = new DirectoryInfo(AppContext.BaseDirectory);
        while (cursor is not null)
        {
            if (File.Exists(Path.Combine(cursor.FullName, "Bootstrap_SafeCore.ps1")))
            {
                return cursor.FullName;
            }
            cursor = cursor.Parent;
        }
        throw new DirectoryNotFoundException("Repository root containing Bootstrap_SafeCore.ps1 was not found.");
    }
}
