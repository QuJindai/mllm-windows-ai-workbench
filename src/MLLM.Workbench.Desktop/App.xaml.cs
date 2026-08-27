using System.Windows;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using MLLM.Workbench.Desktop.Pages.Dashboard;
using MLLM.Workbench.Desktop.Pages.Doctor;
using MLLM.Workbench.Desktop.Pages.Installation;
using MLLM.Workbench.Desktop.Services;
using MLLM.Workbench.Desktop.Shell;
using MLLM.Workbench.Infrastructure.Backend;

namespace MLLM.Workbench.Desktop;

public partial class App : Application
{
    private IHost? _host;

    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        var runtime = WorkbenchRuntimeOptions.Resolve();
        _host = Host.CreateDefaultBuilder()
            .ConfigureServices(services =>
            {
                services.AddSingleton(runtime);
                services.AddSingleton(_ => new BackendProcessHost(runtime.ProjectRoot, runtime.DataRoot, runtime.NetworkMode));
                services.AddSingleton<IWorkbenchBackendClient>(sp => new NamedPipeBackendClient(sp.GetRequiredService<BackendProcessHost>().Options));
                services.AddSingleton<WorkbenchCoordinator>();
                services.AddSingleton<DashboardPageViewModel>();
                services.AddSingleton<DoctorPageViewModel>();
                services.AddSingleton<InstallationPageViewModel>();
                services.AddSingleton<MainWindowViewModel>();
                services.AddSingleton<MainWindow>();
            })
            .Build();

        await _host.StartAsync().ConfigureAwait(true);
        var coordinator = _host.Services.GetRequiredService<WorkbenchCoordinator>();
        var viewModel = _host.Services.GetRequiredService<MainWindowViewModel>();
        try
        {
            await coordinator.StartAsync(CancellationToken.None).ConfigureAwait(true);
            viewModel.SetBackendStatus("Safe Core backend: connected");
            await viewModel.Dashboard.RefreshAsync(CancellationToken.None).ConfigureAwait(true);
        }
        catch (Exception ex)
        {
            viewModel.SetBackendStatus("Safe Core backend: unavailable - " + ex.Message);
        }

        var window = _host.Services.GetRequiredService<MainWindow>();
        MainWindow = window;
        window.Show();
    }

    protected override async void OnExit(ExitEventArgs e)
    {
        if (_host is not null)
        {
            try
            {
                var coordinator = _host.Services.GetService<WorkbenchCoordinator>();
                if (coordinator is not null) await coordinator.DisposeAsync().ConfigureAwait(false);
                await _host.StopAsync(TimeSpan.FromSeconds(3)).ConfigureAwait(false);
            }
            finally
            {
                _host.Dispose();
                _host = null;
            }
        }
        base.OnExit(e);
    }
}
