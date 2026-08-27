using System.Xml.Linq;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class ShellContractTests
{
    [Fact]
    public void Phase_a_shell_exposes_only_approved_navigation_and_critical_automation_ids()
    {
        var root = FindRepositoryRoot();
        var path = Path.Combine(root, "src", "MLLM.Workbench.Desktop", "Shell", "MainWindow.xaml");
        Assert.True(File.Exists(path), $"MainWindow.xaml missing: {path}");

        var document = XDocument.Load(path, LoadOptions.PreserveWhitespace);
        XNamespace x = "http://schemas.microsoft.com/winfx/2006/xaml";
        var names = document.Descendants()
            .Select(e => (string?)e.Attribute(x + "Name"))
            .Where(v => !string.IsNullOrWhiteSpace(v))
            .ToHashSet(StringComparer.Ordinal);
        var automationIds = document.Descendants()
            .Select(e => e.Attributes().FirstOrDefault(a => a.Name.LocalName == "AutomationId")?.Value)
            .Where(v => !string.IsNullOrWhiteSpace(v))
            .ToHashSet(StringComparer.Ordinal);

        foreach (var required in new[] { "MainNavigation", "BackendStatus", "NetworkModeStatus", "ContentHost", "DashboardNavigation", "DoctorNavigation", "InstallationNavigation" })
        {
            Assert.True(names.Contains(required) || automationIds.Contains(required), $"Missing shell contract element: {required}");
        }

        var xml = File.ReadAllText(path);
        foreach (var forbidden in new[] { "ModelNavigation", "ServicesNavigation", "ConversationNavigation", "RagNavigation", "BenchmarkNavigation", "EvidenceNavigation", "SettingsNavigation", "AboutNavigation" })
        {
            Assert.DoesNotContain(forbidden, xml, StringComparison.Ordinal);
        }
    }

    [Fact]
    public void Shell_xaml_is_valid_wpf_xml_and_has_scrollable_content_host()
    {
        var root = FindRepositoryRoot();
        var path = Path.Combine(root, "src", "MLLM.Workbench.Desktop", "Shell", "MainWindow.xaml");
        var document = XDocument.Load(path);
        Assert.Equal("Window", document.Root?.Name.LocalName);
        Assert.Contains(document.Descendants(), e => e.Name.LocalName == "ScrollViewer" && e.Descendants().Any(d => (string?)d.Attribute(XName.Get("Name", "http://schemas.microsoft.com/winfx/2006/xaml")) == "ContentHost"));
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
