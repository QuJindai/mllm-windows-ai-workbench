using System.IO;
using System.Xml.Linq;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class D1PageRuntimeLoadTests
{
    [Fact]
    public void D1_pages_expose_required_controls_and_compile_as_wpf_xaml()
    {
        var root = FindRepositoryRoot();
        AssertPage(
            Path.Combine(root, "src", "MLLM.Workbench.Desktop", "Pages", "Models", "ModelManagementPage.xaml"),
            "MLLM.Workbench.Desktop.Pages.Models.ModelManagementPage",
            ["ModelManagementPageRoot", "ModelInventoryGrid", "ImportModelButton", "VerifyModelButton", "ActivateModelButton", "RefreshModelsButton"]);
        AssertPage(
            Path.Combine(root, "src", "MLLM.Workbench.Desktop", "Pages", "Services", "LocalServicesPage.xaml"),
            "MLLM.Workbench.Desktop.Pages.Services.LocalServicesPage",
            ["LocalServicesPageRoot", "ServiceInventoryGrid", "StartServiceButton", "StopServiceButton", "RestartServiceButton", "LoadServiceLogsButton", "CopyServiceEndpointButton", "ServiceLogText"]);
    }

    private static void AssertPage(string path, string expectedClass, IReadOnlyList<string> required)
    {
        Assert.True(File.Exists(path), $"WPF page missing: {path}");
        var text = File.ReadAllText(path);
        foreach (var value in required) Assert.Contains(value, text, StringComparison.Ordinal);
        var document = XDocument.Load(path);
        XNamespace x = "http://schemas.microsoft.com/winfx/2006/xaml";
        Assert.Equal("UserControl", document.Root?.Name.LocalName);
        Assert.Equal(expectedClass, (string?)document.Root?.Attribute(x + "Class"));
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
