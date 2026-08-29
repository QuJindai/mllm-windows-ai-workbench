using System.Diagnostics;
using System.IO;

namespace MLLM.Workbench.Desktop.Services.Knowledge;

public sealed class ShellEvidenceLauncher : IEvidenceLauncher
{
    public Task OpenAsync(string sourceUri, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (string.IsNullOrWhiteSpace(sourceUri))
            throw new ArgumentException("Evidence source is required.", nameof(sourceUri));

        string path;
        if (Path.IsPathRooted(sourceUri))
        {
            path = Path.GetFullPath(sourceUri);
        }
        else if (Uri.TryCreate(sourceUri, UriKind.Absolute, out var uri))
        {
            if (!uri.IsFile)
                throw new NotSupportedException("Only local file evidence can be opened from the knowledge workbench.");
            path = Path.GetFullPath(uri.LocalPath);
        }
        else
        {
            path = Path.GetFullPath(sourceUri);
        }

        if (!File.Exists(path))
            throw new FileNotFoundException("Evidence source file was not found.", path);

        var process = Process.Start(new ProcessStartInfo(path)
        {
            UseShellExecute = true
        });
        if (process is null)
            throw new InvalidOperationException("Windows could not open the evidence source with its registered application.");

        return Task.CompletedTask;
    }
}
