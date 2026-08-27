using System.Diagnostics;

namespace MLLM.Workbench.Infrastructure.Installer;

public sealed class PrivilegedInstallerInvoker : IPrivilegedInstallerInvoker
{
    private readonly string _projectRoot;
    private readonly string _powerShellPath;

    public PrivilegedInstallerInvoker(string projectRoot, string? powerShellPath = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(projectRoot);
        _projectRoot = Path.GetFullPath(projectRoot);
        _powerShellPath = powerShellPath ?? ResolveWindowsPowerShell();
    }

    public ProcessStartInfo BuildStartInfo(InstallerProcessRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        if (request.Action == InstallerAction.ImportOffline && string.IsNullOrWhiteSpace(request.OfflinePackagePath))
        {
            throw new ArgumentException("OfflinePackagePath is required for ImportOffline.", nameof(request));
        }

        var script = Path.Combine(_projectRoot, "installer", "Start-UniversalInstaller.ps1");
        if (!File.Exists(script))
        {
            throw new FileNotFoundException("Universal Installer entrypoint is missing.", script);
        }

        var start = new ProcessStartInfo
        {
            FileName = _powerShellPath,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden
        };
        foreach (var value in new[]
        {
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script,
            "-NoGui", "-Action", request.Action.ToString()
        })
        {
            start.ArgumentList.Add(value);
        }
        if (request.Action == InstallerAction.ImportOffline)
        {
            start.ArgumentList.Add("-OfflinePackagePath");
            start.ArgumentList.Add(Path.GetFullPath(request.OfflinePackagePath!));
        }
        return start;
    }

    public async Task<InstallerProcessResult> RunAsync(InstallerProcessRequest request, CancellationToken cancellationToken)
    {
        var start = BuildStartInfo(request);
        using var process = new Process { StartInfo = start };
        if (!process.Start())
        {
            throw new InvalidOperationException("Universal Installer process failed to start.");
        }

        var stdoutTask = process.StandardOutput.ReadToEndAsync(cancellationToken);
        var stderrTask = process.StandardError.ReadToEndAsync(cancellationToken);
        try
        {
            await process.WaitForExitAsync(cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            try { if (!process.HasExited) process.Kill(entireProcessTree: true); } catch (InvalidOperationException) { }
            throw;
        }
        var stdout = await stdoutTask.ConfigureAwait(false);
        var stderr = await stderrTask.ConfigureAwait(false);
        return new InstallerProcessResult(process.ExitCode, stdout, stderr);
    }

    private static string ResolveWindowsPowerShell()
    {
        var candidate = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
        return File.Exists(candidate) ? candidate : "powershell.exe";
    }
}
