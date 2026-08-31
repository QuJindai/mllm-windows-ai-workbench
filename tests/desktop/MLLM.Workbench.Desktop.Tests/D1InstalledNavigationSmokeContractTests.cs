using System.IO;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class D1InstalledNavigationSmokeContractTests
{
    [Fact]
    public void Dashboard_and_release_require_real_D1_navigation_smoke()
    {
        var root = FindRepositoryRoot();
        var dashboard = File.ReadAllText(Path.Combine(root, "src", "MLLM.Workbench.Desktop", "Pages", "Dashboard", "DashboardPage.xaml"));
        Assert.Contains("OpenModelsButton", dashboard, StringComparison.Ordinal);
        Assert.Contains("OpenServicesButton", dashboard, StringComparison.Ordinal);

        var app = File.ReadAllText(Path.Combine(root, "src", "MLLM.Workbench.Desktop", "App.xaml.cs"));
        Assert.Contains("--smoke-d1-navigation", app, StringComparison.Ordinal);
        Assert.Contains("D1_NAVIGATION_SMOKE=PASS", app, StringComparison.Ordinal);
        Assert.Contains("NavigateModelsCommand", app, StringComparison.Ordinal);
        Assert.Contains("NavigateServicesCommand", app, StringComparison.Ordinal);
        Assert.Contains("NavigateKnowledgeCommand", app, StringComparison.Ordinal);

        var releaseSmoke = File.ReadAllText(Path.Combine(root, "tests", "ci", "Invoke-C7ReleasePackageSmoke.ps1"));
        Assert.Contains("--smoke-d1-navigation", releaseSmoke, StringComparison.Ordinal);
        Assert.Contains("d1_navigation_smoke=PASS", releaseSmoke, StringComparison.OrdinalIgnoreCase);
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
