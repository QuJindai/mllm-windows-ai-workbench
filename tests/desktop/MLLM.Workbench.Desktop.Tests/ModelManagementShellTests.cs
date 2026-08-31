using System.IO;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class ModelManagementShellTests
{
    [Fact]
    public void D1_shell_requires_native_model_and_services_pages_and_routes()
    {
        var root = FindRepositoryRoot();
        var desktopRoot = Path.Combine(root, "src", "MLLM.Workbench.Desktop");

        var modelPage = Path.Combine(desktopRoot, "Pages", "Models", "ModelManagementPage.xaml");
        var servicesViewModel = Path.Combine(desktopRoot, "Pages", "Services", "LocalServicesPageViewModel.cs");
        var servicesPage = Path.Combine(desktopRoot, "Pages", "Services", "LocalServicesPage.xaml");
        Assert.True(File.Exists(modelPage), $"Native Model Management page missing: {modelPage}");
        Assert.True(File.Exists(servicesViewModel), $"Native Local Services ViewModel missing: {servicesViewModel}");
        Assert.True(File.Exists(servicesPage), $"Native Local Services page missing: {servicesPage}");

        var xaml = File.ReadAllText(Path.Combine(desktopRoot, "Shell", "MainWindow.xaml"));
        Assert.Contains("xmlns:models=\"clr-namespace:MLLM.Workbench.Desktop.Pages.Models\"", xaml, StringComparison.Ordinal);
        Assert.Contains("xmlns:services=\"clr-namespace:MLLM.Workbench.Desktop.Pages.Services\"", xaml, StringComparison.Ordinal);
        Assert.Contains("models:ModelManagementPageViewModel", xaml, StringComparison.Ordinal);
        Assert.Contains("services:LocalServicesPageViewModel", xaml, StringComparison.Ordinal);
        Assert.Contains("ModelNavigation", xaml, StringComparison.Ordinal);
        Assert.Contains("ServicesNavigation", xaml, StringComparison.Ordinal);
        Assert.Contains("模型管理", xaml, StringComparison.Ordinal);
        Assert.Contains("本地服务", xaml, StringComparison.Ordinal);

        var shellViewModel = File.ReadAllText(Path.Combine(desktopRoot, "Shell", "MainWindowViewModel.cs"));
        Assert.Contains("NavigateModelsCommand", shellViewModel, StringComparison.Ordinal);
        Assert.Contains("NavigateServicesCommand", shellViewModel, StringComparison.Ordinal);
        Assert.Contains("\"models\" => Models", shellViewModel, StringComparison.Ordinal);
        Assert.Contains("\"services\" => Services", shellViewModel, StringComparison.Ordinal);
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
