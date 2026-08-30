using MLLM.Workbench.Contracts.Components;
using MLLM.Workbench.Infrastructure.Backend;

namespace MLLM.Workbench.Infrastructure.Tests;

public sealed class ComponentInstallBackendTests
{
    [Fact]
    public async Task Real_backend_exposes_component_install_methods_and_blocks_full_setup_safely_offline()
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(120));
        var root = FindRepositoryRoot();
        var dataRoot = Path.Combine(Path.GetTempPath(), "mllm c8 component backend " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dataRoot);
        try
        {
            await using var host = new BackendProcessHost(root, dataRoot, "OFFLINE_CACHE");
            await host.StartAsync(timeout.Token);
            await using IWorkbenchBackendClient client = new NamedPipeBackendClient(host.Options);
            Assert.True((await client.ConnectAsync(timeout.Token)).Accepted);

            var capabilities = await client.GetCapabilitiesAsync(timeout.Token);
            Assert.Contains("components.installPreset", capabilities.Methods);
            Assert.Contains("components.installTask", capabilities.Methods);

            var result = await client.InstallComponentPresetAsync(
                new ComponentPresetInstallRequest("Full Setup", "OFFLINE_CACHE", "c8-offline-full-setup"),
                timeout.Token);

            var detail = string.Join(" | ", result.Items.Select(item => $"{item.Id}:{item.Status}:{item.Summary}"));
            Assert.Equal("Full Setup", result.Preset);
            Assert.Equal("OFFLINE_CACHE", result.NetworkMode);
            Assert.True(result.Status == "BLOCKED", $"Expected BLOCKED, got {result.Status}. Items: {detail}");
            Assert.NotEmpty(result.Items);
            Assert.Contains(result.Items, item => item.Status == "BLOCKED");
            Assert.DoesNotContain(result.Items, item => item.Status == "FAILED");

            var python = result.Items.FirstOrDefault(item => item.Id == "python");
            Assert.NotNull(python);
            if (python.Status == "PASS")
            {
                Assert.Contains(result.Items, item => item.Id == "modelscope" && item.Status == "BLOCKED");
            }
            else
            {
                Assert.Equal("BLOCKED", python.Status);
            }

            Assert.Empty(Directory.EnumerateFiles(dataRoot, "python.exe", SearchOption.AllDirectories));
            Assert.Empty(Directory.EnumerateFiles(dataRoot, "llama-server.exe", SearchOption.AllDirectories));
            Assert.Empty(Directory.EnumerateFiles(dataRoot, "*.gguf", SearchOption.AllDirectories));
        }
        finally
        {
            Directory.Delete(dataRoot, recursive: true);
        }
    }

    [Fact]
    public async Task Backend_rejects_unknown_component_preset_task_and_install_network_mode()
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(90));
        var root = FindRepositoryRoot();
        var dataRoot = Path.Combine(Path.GetTempPath(), "mllm c8 component reject " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dataRoot);
        try
        {
            await using var host = new BackendProcessHost(root, dataRoot, "OFFLINE_CACHE");
            await host.StartAsync(timeout.Token);
            await using IWorkbenchBackendClient client = new NamedPipeBackendClient(host.Options);
            Assert.True((await client.ConnectAsync(timeout.Token)).Accepted);

            var preset = await Assert.ThrowsAsync<BackendRpcException>(() =>
                client.InstallComponentPresetAsync(new ComponentPresetInstallRequest("Anything", "OFFLINE_CACHE", "op-preset"), timeout.Token));
            Assert.Equal("COMPONENT_PRESET_NOT_ALLOWED", preset.Code);

            var task = await Assert.ThrowsAsync<BackendRpcException>(() =>
                client.InstallComponentTaskAsync(new ComponentTaskInstallRequest("anything", "OFFLINE_CACHE", "op-task"), timeout.Token));
            Assert.Equal("COMPONENT_TASK_NOT_ALLOWED", task.Code);

            var mode = await Assert.ThrowsAsync<BackendRpcException>(() =>
                client.InstallComponentPresetAsync(new ComponentPresetInstallRequest("Core", "INTERNET_ANY", "op-mode"), timeout.Token));
            Assert.Equal("COMPONENT_NETWORK_MODE_NOT_ALLOWED", mode.Code);
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
