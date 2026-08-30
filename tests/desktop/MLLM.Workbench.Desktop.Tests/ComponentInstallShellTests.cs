using System.Xml.Linq;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class ComponentInstallShellTests
{
    [Fact]
    public void Installation_page_exposes_explicit_local_ai_presets_and_install_network_mode()
    {
        var root = FindRepositoryRoot();
        var path = Path.Combine(root, "src", "MLLM.Workbench.Desktop", "Pages", "Installation", "InstallationPage.xaml");
        var xml = XDocument.Load(path);
        XNamespace automation = "clr-namespace:System.Windows.Automation;assembly=PresentationCore";
        var ids = xml.Descendants()
            .Select(element => (string?)element.Attribute(automation + "AutomationId"))
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .ToHashSet(StringComparer.Ordinal);

        foreach (var id in new[]
        {
            "ComponentInstallNetworkMode",
            "InstallCorePresetButton",
            "InstallLocalAiFastPresetButton",
            "InstallWebWorkbenchPresetButton",
            "InstallDeveloperToolsPresetButton",
            "InstallFullSetupPresetButton"
        })
        {
            Assert.Contains(id, ids);
        }

        var text = File.ReadAllText(path);
        Assert.Contains("本地 AI 组件", text, StringComparison.Ordinal);
        Assert.Contains("Workbench 基础版本", text, StringComparison.Ordinal);
        Assert.Contains("SelectedInstallNetworkMode", text, StringComparison.Ordinal);
        Assert.Contains("InstallFullSetupPresetCommand", text, StringComparison.Ordinal);
        Assert.Contains("OFFLINE_CACHE", text, StringComparison.Ordinal);
        Assert.Contains("显式", text, StringComparison.Ordinal);
        Assert.Contains("固定任务", text, StringComparison.Ordinal);
    }

    private static string FindRepositoryRoot()
    {
        var cursor = new DirectoryInfo(AppContext.BaseDirectory);
        while (cursor is not null)
        {
            if (File.Exists(Path.Combine(cursor.FullName, "MLLM.Workbench.sln"))) return cursor.FullName;
            cursor = cursor.Parent;
        }
        throw new DirectoryNotFoundException("Repository root was not found.");
    }
}
