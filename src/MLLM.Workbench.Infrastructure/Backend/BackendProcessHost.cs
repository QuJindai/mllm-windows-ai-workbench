using System.Diagnostics;
using System.Security.Cryptography;

namespace MLLM.Workbench.Infrastructure.Backend;

public sealed class BackendProcessHost : IAsyncDisposable
{
    private readonly string _powerShellPath;
    private Process? _process;

    public BackendProcessHost(string projectRoot, string dataRoot, string networkMode, string? powerShellPath = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(projectRoot);
        ArgumentException.ThrowIfNullOrWhiteSpace(dataRoot);
        ArgumentException.ThrowIfNullOrWhiteSpace(networkMode);

        var nonce = Convert.ToHexString(RandomNumberGenerator.GetBytes(8)).ToLowerInvariant();
        var rawToken = Convert.ToBase64String(RandomNumberGenerator.GetBytes(32));
        var token = rawToken.TrimEnd('=').Replace('+', '-').Replace('/', '_');
        Options = new BackendClientOptions(
            $"mllm-workbench-{Environment.ProcessId}-{nonce}",
            token,
            Path.GetFullPath(projectRoot),
            Path.GetFullPath(dataRoot),
            networkMode);

        _powerShellPath = powerShellPath ?? ResolveWindowsPowerShell();
    }

    public BackendClientOptions Options { get; }
    public event Action<string>? BackendLogReceived;

    public Task StartAsync(CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (_process is not null)
        {
            throw new InvalidOperationException("Backend process is already started.");
        }

        Directory.CreateDirectory(Options.DataRoot);
        var script = Path.Combine(Options.ProjectRoot, "runtime", "WorkbenchBackend.ps1");
        if (!File.Exists(script))
        {
            throw new FileNotFoundException("Workbench backend script is missing.", script);
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
        foreach (var argument in new[]
        {
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script,
            "-PipeName", Options.PipeName,
            "-SessionToken", Options.SessionToken,
            "-ProtocolVersion", Options.ProtocolVersion,
            "-ProjectRoot", Options.ProjectRoot,
            "-DataRoot", Options.DataRoot,
            "-NetworkMode", Options.NetworkMode
        })
        {
            start.ArgumentList.Add(argument);
        }

        _process = new Process { StartInfo = start, EnableRaisingEvents = true };
        _process.OutputDataReceived += (_, args) => PublishLog(args.Data);
        _process.ErrorDataReceived += (_, args) => PublishLog(args.Data);
        if (!_process.Start())
        {
            throw new InvalidOperationException("Windows PowerShell backend failed to start.");
        }
        _process.BeginOutputReadLine();
        _process.BeginErrorReadLine();
        return Task.CompletedTask;
    }

    private void PublishLog(string? line)
    {
        if (string.IsNullOrEmpty(line))
        {
            return;
        }
        BackendLogReceived?.Invoke(line.Replace(Options.SessionToken, "[REDACTED]", StringComparison.Ordinal));
    }

    private static string ResolveWindowsPowerShell()
    {
        var candidate = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
        return File.Exists(candidate) ? candidate : "powershell.exe";
    }

    public async ValueTask DisposeAsync()
    {
        if (_process is null)
        {
            return;
        }
        try
        {
            if (!_process.HasExited)
            {
                _process.Kill(entireProcessTree: true);
                await _process.WaitForExitAsync().ConfigureAwait(false);
            }
        }
        catch (InvalidOperationException)
        {
        }
        finally
        {
            _process.Dispose();
            _process = null;
        }
    }
}
