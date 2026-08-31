using System.IO;
using System.Threading;
using System.Windows;
using MLLM.Workbench.Desktop.Pages.Models;
using MLLM.Workbench.Desktop.Pages.Services;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class D1PageRuntimeLoadTests
{
    [Fact]
    public void D1_pages_expose_required_controls_and_load_with_application_resources()
    {
        var root = FindRepositoryRoot();
        var modelXaml = File.ReadAllText(Path.Combine(root, "src", "MLLM.Workbench.Desktop", "Pages", "Models", "ModelManagementPage.xaml"));
        foreach (var required in new[] { "ModelManagementPageRoot", "ModelInventoryGrid", "ImportModelButton", "VerifyModelButton", "ActivateModelButton", "RefreshModelsButton" })
            Assert.Contains(required, modelXaml, StringComparison.Ordinal);

        var serviceXaml = File.ReadAllText(Path.Combine(root, "src", "MLLM.Workbench.Desktop", "Pages", "Services", "LocalServicesPage.xaml"));
        foreach (var required in new[] { "LocalServicesPageRoot", "ServiceInventoryGrid", "StartServiceButton", "StopServiceButton", "RestartServiceButton", "LoadServiceLogsButton", "CopyServiceEndpointButton", "ServiceLogText" })
            Assert.Contains(required, serviceXaml, StringComparison.Ordinal);

        Exception? failure = null;
        using var completed = new ManualResetEventSlim(false);
        var thread = new Thread(() =>
        {
            App? app = null;
            try
            {
                app = new App();
                app.InitializeComponent();
                foreach (var page in new FrameworkElement[] { new ModelManagementPage(), new LocalServicesPage() })
                {
                    page.Measure(new Size(1200, 4000));
                    page.Arrange(new Rect(0, 0, 1200, 4000));
                    page.UpdateLayout();
                }
            }
            catch (Exception ex)
            {
                failure = ex;
            }
            finally
            {
                try { app?.Shutdown(); } catch { }
                completed.Set();
            }
        }) { IsBackground = true, Name = "D1PageRuntimeLoadTest" };
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();

        Assert.True(completed.Wait(TimeSpan.FromSeconds(20)), "D1 page runtime load did not complete within 20 seconds.");
        thread.Join(TimeSpan.FromSeconds(2));
        Assert.Null(failure);
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
