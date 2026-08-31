using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Input;
using System.Windows.Threading;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using MLLM.Workbench.Desktop.Pages.Dashboard;
using MLLM.Workbench.Desktop.Pages.Conversation;
using MLLM.Workbench.Desktop.Pages.Doctor;
using MLLM.Workbench.Desktop.Pages.Installation;
using MLLM.Workbench.Desktop.Pages.Knowledge;
using MLLM.Workbench.Desktop.Pages.Models;
using MLLM.Workbench.Desktop.Pages.Services;
using MLLM.Workbench.Desktop.Services;
using MLLM.Workbench.Desktop.Services.Conversation;
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
        var smokeKnowledge = e.Args.Any(x => string.Equals(x, "--smoke-knowledge", StringComparison.OrdinalIgnoreCase));
        var smokeD1Navigation = e.Args.Any(x => string.Equals(x, "--smoke-d1-navigation", StringComparison.OrdinalIgnoreCase));
        try
        {
            var runtime = WorkbenchRuntimeOptions.Resolve();
            _host = BuildHost(runtime);
            await _host.StartAsync().ConfigureAwait(true);

            var coordinator = _host.Services.GetRequiredService<WorkbenchCoordinator>();
            await coordinator.StartAsync(CancellationToken.None).ConfigureAwait(true);

            if (smoke)
            {
                await VerifyBackendPingAsync(_host.Services.GetRequiredService<IWorkbenchBackendClient>()).ConfigureAwait(true);
                WriteSmokeDiagnostic("DESKTOP_SMOKE=PASS");
                Shutdown(0);
                return;
            }

            var viewModel = _host.Services.GetRequiredService<MainWindowViewModel>();
            viewModel.SetBackendStatus("Safe Core backend: connected");

            if (smokeKnowledge)
            {
                await VerifyKnowledgeNavigationAsync(viewModel, _host.Services.GetRequiredService<MainWindow>()).ConfigureAwait(true);
                WriteSmokeDiagnostic("KNOWLEDGE_NAVIGATION_SMOKE=PASS fts5=" + viewModel.Knowledge.Fts5Status);
                Shutdown(0);
                return;
            }

            if (smokeD1Navigation)
            {
                await VerifyD1NavigationAsync(viewModel, _host.Services.GetRequiredService<MainWindow>()).ConfigureAwait(true);
                WriteSmokeDiagnostic("D1_NAVIGATION_SMOKE=PASS");
                Shutdown(0);
                return;
            }

            await viewModel.Dashboard.RefreshAsync(CancellationToken.None).ConfigureAwait(true);

            var window = _host.Services.GetRequiredService<MainWindow>();
            MainWindow = window;
            window.Show();
        }
        catch (Exception ex)
        {
            if (smoke || smokeKnowledge || smokeD1Navigation)
            {
                var prefix = smokeD1Navigation
                    ? "D1_NAVIGATION_SMOKE=FAIL"
                    : smokeKnowledge
                        ? "KNOWLEDGE_NAVIGATION_SMOKE=FAIL"
                        : "DESKTOP_SMOKE=FAIL";
                WriteSmokeDiagnostic(prefix + Environment.NewLine + ex);
                try { Console.Error.WriteLine(prefix + " " + ex); } catch { }
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

    private static void WriteSmokeDiagnostic(string text)
    {
        try
        {
            var path = Environment.GetEnvironmentVariable("MLLM_SMOKE_DIAGNOSTIC_PATH");
            if (string.IsNullOrWhiteSpace(path)) return;
            var full = Path.GetFullPath(path);
            var parent = Path.GetDirectoryName(full);
            if (!string.IsNullOrWhiteSpace(parent)) Directory.CreateDirectory(parent);
            File.WriteAllText(full, text);
        }
        catch
        {
        }
    }

    private static async Task VerifyBackendPingAsync(IWorkbenchBackendClient client)
    {
        var ping = await client.InvokeAsync<JsonElement>("system.ping", null, CancellationToken.None).ConfigureAwait(true);
        if (!ping.TryGetProperty("status", out var status) || !string.Equals(status.GetString(), "PASS", StringComparison.Ordinal))
            throw new BackendRpcException("SMOKE_PING_FAILED", "Safe Core backend ping did not return PASS.");
    }

    private async Task VerifyKnowledgeNavigationAsync(MainWindowViewModel viewModel, MainWindow window)
    {
        Exception? dispatcherFailure = null;
        DispatcherUnhandledExceptionEventHandler handler = (_, args) =>
        {
            dispatcherFailure = args.Exception;
            args.Handled = true;
        };

        DispatcherUnhandledException += handler;
        try
        {
            await VerifyBackendPingAsync(_host!.Services.GetRequiredService<IWorkbenchBackendClient>()).ConfigureAwait(true);
            MainWindow = window;
            window.Show();
            viewModel.NavigateKnowledgeCommand.Execute(null);

            var deadline = DateTime.UtcNow.AddSeconds(10);
            while (viewModel.Knowledge.IsBusy && DateTime.UtcNow < deadline)
            {
                await Task.Delay(40).ConfigureAwait(true);
                await Dispatcher.InvokeAsync(static () => { }, DispatcherPriority.Background);
            }

            await Dispatcher.InvokeAsync(window.UpdateLayout, DispatcherPriority.ApplicationIdle);
            if (dispatcherFailure is not null)
                throw new InvalidOperationException("Knowledge navigation raised an unhandled dispatcher exception.", dispatcherFailure);
            if (!ReferenceEquals(viewModel.CurrentPage, viewModel.Knowledge))
                throw new InvalidOperationException("Knowledge navigation did not keep KnowledgePageViewModel active.");
            if (viewModel.Knowledge.IsBusy)
                throw new TimeoutException("Knowledge workspace refresh did not complete within 10 seconds.");
            if (!string.IsNullOrWhiteSpace(viewModel.Knowledge.LastError))
                throw new InvalidOperationException("Knowledge workspace refresh failed: " + viewModel.Knowledge.LastError);

            window.Close();
        }
        finally
        {
            DispatcherUnhandledException -= handler;
        }
    }

    private async Task VerifyD1NavigationAsync(MainWindowViewModel viewModel, MainWindow window)
    {
        Exception? dispatcherFailure = null;
        DispatcherUnhandledExceptionEventHandler handler = (_, args) =>
        {
            dispatcherFailure = args.Exception;
            args.Handled = true;
        };

        DispatcherUnhandledException += handler;
        try
        {
            await VerifyBackendPingAsync(_host!.Services.GetRequiredService<IWorkbenchBackendClient>()).ConfigureAwait(true);
            MainWindow = window;
            window.Show();

            await VerifyNavigationStepAsync(
                window,
                "models",
                viewModel.NavigateModelsCommand,
                () => ReferenceEquals(viewModel.CurrentPage, viewModel.Models),
                () => viewModel.Models.IsBusy,
                () => viewModel.Models.BackendError).ConfigureAwait(true);
            if (dispatcherFailure is not null)
                throw new InvalidOperationException("Model Management navigation raised an unhandled dispatcher exception.", dispatcherFailure);

            await VerifyNavigationStepAsync(
                window,
                "services",
                viewModel.NavigateServicesCommand,
                () => ReferenceEquals(viewModel.CurrentPage, viewModel.Services),
                () => viewModel.Services.IsBusy,
                () => viewModel.Services.LastError).ConfigureAwait(true);
            if (dispatcherFailure is not null)
                throw new InvalidOperationException("Local Services navigation raised an unhandled dispatcher exception.", dispatcherFailure);

            await VerifyNavigationStepAsync(
                window,
                "knowledge",
                viewModel.NavigateKnowledgeCommand,
                () => ReferenceEquals(viewModel.CurrentPage, viewModel.Knowledge),
                () => viewModel.Knowledge.IsBusy,
                () => viewModel.Knowledge.LastError).ConfigureAwait(true);
            if (dispatcherFailure is not null)
                throw new InvalidOperationException("Knowledge navigation raised an unhandled dispatcher exception during D1 smoke.", dispatcherFailure);

            window.Close();
        }
        finally
        {
            DispatcherUnhandledException -= handler;
        }
    }

    private async Task VerifyNavigationStepAsync(
        MainWindow window,
        string route,
        ICommand command,
        Func<bool> isActive,
        Func<bool> isBusy,
        Func<string?> getError)
    {
        command.Execute(null);
        await Dispatcher.InvokeAsync(static () => { }, DispatcherPriority.Background);

        var deadline = DateTime.UtcNow.AddSeconds(10);
        while (isBusy() && DateTime.UtcNow < deadline)
        {
            await Task.Delay(40).ConfigureAwait(true);
            await Dispatcher.InvokeAsync(static () => { }, DispatcherPriority.Background);
        }

        await Dispatcher.InvokeAsync(window.UpdateLayout, DispatcherPriority.ApplicationIdle);
        if (!isActive())
            throw new InvalidOperationException($"D1 navigation did not keep route '{route}' active.");
        if (isBusy())
            throw new TimeoutException($"D1 route '{route}' refresh did not complete within 10 seconds.");
        var error = getError();
        if (!string.IsNullOrWhiteSpace(error))
            throw new InvalidOperationException($"D1 route '{route}' refresh failed: {error}");
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
                services.AddSingleton<WorkbenchMutationGate>();
                services.AddSingleton<IClipboardService, WpfClipboardService>();
                services.AddSingleton<IKnowledgeWorkbenchService>(_ =>
                    KnowledgeServiceFactory.Create(runtime.DataRoot, Environment.GetEnvironmentVariable));
                services.AddSingleton<IEvidenceLauncher, ShellEvidenceLauncher>();
                services.AddSingleton<ILocalConversationClient, LocalOpenAiConversationClient>();
                services.AddSingleton<IConversationTestService, ConversationTestService>();
                services.AddSingleton<IGoldenTestCatalog>(_ => new JsonGoldenTestCatalog(runtime.DataRoot));
                services.AddSingleton<GoldenTestEvaluator>();
                services.AddSingleton<DashboardPageViewModel>();
                services.AddSingleton<DoctorPageViewModel>();
                services.AddSingleton<InstallationPageViewModel>();
                services.AddSingleton<ModelManagementPageViewModel>();
                services.AddSingleton<LocalServicesPageViewModel>();
                services.AddSingleton<KnowledgePageViewModel>();
                services.AddSingleton<ConversationPageViewModel>();
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
