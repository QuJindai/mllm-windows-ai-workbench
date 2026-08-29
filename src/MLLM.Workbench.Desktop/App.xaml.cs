using System.Text.Json;
using System.Windows;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using MLLM.Workbench.Desktop.Pages.Dashboard;
using MLLM.Workbench.Desktop.Pages.Doctor;
using MLLM.Workbench.Desktop.Pages.Installation;
using MLLM.Workbench.Desktop.Pages.Knowledge;
using MLLM.Workbench.Desktop.Services;
using MLLM.Workbench.Desktop.Services.Knowledge;
using MLLM.Workbench.Desktop.Shell;
using MLLM.Workbench.Infrastructure.Backend;
using MLLM.Workbench.Infrastructure.Installer;

namespace MLLM.Workbench.Desktop;

public partial class App : Application
{
    private IHost? _host;

    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        var smoke = e.Args.Any(x => string.Equals(x, "--smoke", StringComparison.OrdinalIgnoreCase));
        try
        {
            var runtime = WorkbenchRuntimeOptions.Resolve();
            _host = BuildHost(runtime);
            await _host.StartAsync().ConfigureAwait(true);

            var coordinator = _host.Services.GetRequiredService<WorkbenchCoordinator>();
            await coordinator.StartAsync(CancellationToken.None).ConfigureAwait(true);

            if (smoke)
            {
                var client = _host.Services.GetRequiredService<IWorkbenchBackendClient>();
                var ping = await client.InvokeAsync<JsonElement>("system.ping", null, CancellationToken.None).ConfigureAwait(true);
                if (!ping.TryGetProperty("status", out var status) || !string.Equals(status.GetString(), "PASS", StringComparison.Ordinal))
                {
                    throw new BackendRpcException("SMOKE_PING_FAILED", "Safe Core backend ping did not return PASS.");
                }
                Shutdown(0);
                return;
            }

            var viewModel = _host.Services.GetRequiredService<MainWindowViewModel>();
            viewModel.SetBackendStatus("Safe Core backend: connected");
            await viewModel.Dashboard.RefreshAsync(CancellationToken.None).ConfigureAwait(true);

            var window = _host.Services.GetRequiredService<MainWindow>();
            MainWindow = window;
            window.Show();
        }
        catch (Exception ex)
        {
            if (smoke)
            {
                try { Console.Error.WriteLine("DESKTOP_SMOKE=FAIL " + ex.Message); } catch { }
                Shutdown(2);
                return;
            }

            if (_host is not null)
            {
                var viewModel = _host.Services.GetService<MainWindowViewModel>();
                if (viewModel is not null)
                {
                    viewModel.SetBackendStatus("Safe Core backend: unavailable - " + ex.Message);
                    var window = _host.Services.GetService<MainWindow>();
                    if (window is not null)
                    {
                        MainWindow = window;
                        window.Show();
                        return;
                    }
                }
            }
            MessageBox.Show(ex.Message, "M-LLM Workbench startup error", MessageBoxButton.OK, MessageBoxImage.Error);
            Shutdown(2);
        }
    }

    private static IHost BuildHost(WorkbenchRuntimeOptions runtime) =>
        Host.CreateDefaultBuilder()
            .ConfigureServices(services =>
            {
                services.AddSingleton(runtime);
                services.AddSingleton(_ => new BackendProcessHost(runtime.ProjectRoot, runtime.DataRoot, runtime.NetworkMode));
                services.AddSingleton<IWorkbenchBackendClient>(sp => new NamedPipeBackendClient(sp.GetRequiredService<BackendProcessHost>().Options));
                services.AddSingleton<IPrivilegedInstallerInvoker>(_ => new PrivilegedInstallerInvoker(runtime.ProjectRoot));
                services.AddSingleton<WorkbenchCoordinator>();
                services.AddSingleton<IKnowledgeWorkbenchService>(_ =>
                    KnowledgeServiceFactory.Create(runtime.DataRoot, Environment.GetEnvironmentVariable));
                services.AddSingleton<IEvidenceLauncher, ShellEvidenceLauncher>();
                services.AddSingleton<DashboardPageViewModel>();
                services.AddSingleton<DoctorPageViewModel>();
                services.AddSingleton<InstallationPageViewModel>();
                services.AddSingleton<KnowledgePageViewModel>();
                services.AddSingleton<MainWindowViewModel>();
                services.AddSingleton<MainWindow>();
            })
            .Build();

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
