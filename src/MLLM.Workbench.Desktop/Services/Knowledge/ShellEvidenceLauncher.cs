using System.Diagnostics;
using System.IO;

namespace MLLM.Workbench.Desktop.Services.Knowledge;

public sealed class ShellEvidenceLauncher : IEvidenceLauncher
{
    public Task OpenAsync(string sourceUri, CancellationToken cancellationToken) =>
        OpenAsync(sourceUri, locator: null, cancellationToken);

    public Task OpenAsync(string sourceUri, string? locator, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var target = EvidenceLaunchTargetBuilder.Build(sourceUri, locator);

        if (!File.Exists(target.ResolvedPath))
            throw new FileNotFoundException("Evidence source file was not found.", target.ResolvedPath);

        var process = Process.Start(new ProcessStartInfo(target.ShellTarget)
        {
            UseShellExecute = true
        });
        if (process is null)
            throw new InvalidOperationException("Windows could not open the evidence source with its registered application.");

        return Task.CompletedTask;
    }
}
