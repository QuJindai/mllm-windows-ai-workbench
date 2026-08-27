using System.Security.Cryptography;
using MLLM.Workbench.Contracts.Status;
using MLLM.Workbench.Infrastructure.Backend;

namespace MLLM.Workbench.Infrastructure.Tests;

public sealed class BackendSnapshotTests
{
    [Fact]
    public async Task Real_backend_returns_typed_dashboard_doctor_and_readonly_installer_snapshots()
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(90));
        var root = FindRepositoryRoot();
        var dataRoot = Path.Combine(Path.GetTempPath(), "mllm snapshot test " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dataRoot);
        var statePath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "M-LLM", "Installer", "state", "installer_state.json");
        var stateExistedBefore = File.Exists(statePath);
        var hashBefore = stateExistedBefore ? ComputeSha256(statePath) : null;

        await using var host = new BackendProcessHost(root, dataRoot, "OFFLINE_CACHE");
        await host.StartAsync(timeout.Token);
        await using var client = new NamedPipeBackendClient(host.Options);
        var handshake = await client.ConnectAsync(timeout.Token);
        Assert.True(handshake.Accepted);

        var dashboard = await client.GetDashboardAsync(timeout.Token);
        Assert.Equal("OFFLINE_CACHE", dashboard.NetworkMode);
        Assert.False(string.IsNullOrWhiteSpace(dashboard.Machine.Os));
        Assert.False(string.IsNullOrWhiteSpace(dashboard.Machine.Architecture));
        var ids = dashboard.Components.Select(x => x.Id).ToHashSet(StringComparer.OrdinalIgnoreCase);
        foreach (var required in new[] { "llama-cpp", "local-api", "modelscope", "python", "qwen35-4b", "web-workbench" })
        {
            Assert.Contains(required, ids);
        }

        var doctor = await client.GetDoctorAsync(timeout.Token);
        Assert.NotEmpty(doctor.Components);
        foreach (var row in doctor.Components)
        {
            Assert.True(Enum.IsDefined(typeof(ComponentHealth), row.Health), $"Unknown health for {row.Id}: {row.Health}");
        }

        var installer = await client.GetInstallerAsync(timeout.Token);
        Assert.False(string.IsNullOrWhiteSpace(installer.Stage));
        Assert.False(string.IsNullOrWhiteSpace(installer.EvidenceRoot));

        var stateExistedAfter = File.Exists(statePath);
        var hashAfter = stateExistedAfter ? ComputeSha256(statePath) : null;
        Assert.Equal(stateExistedBefore, stateExistedAfter);
        Assert.Equal(hashBefore, hashAfter);
    }

    private static string ComputeSha256(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
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
