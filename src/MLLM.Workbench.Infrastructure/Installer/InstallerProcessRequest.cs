namespace MLLM.Workbench.Infrastructure.Installer;

public enum InstallerAction
{
    InstallResume,
    RetryAcquisition,
    ImportOffline,
    Rollback
}

public sealed record InstallerProcessRequest(
    InstallerAction Action,
    string? OfflinePackagePath = null,
    string? RunId = null,
    string? VersionId = null);

public sealed record InstallerProcessResult(
    int ExitCode,
    string StandardOutput,
    string StandardError)
{
    public bool Succeeded => ExitCode == 0;
    public bool ElevationRequested => StandardOutput.Contains("UNIVERSAL_INSTALLER_ELEVATION=REQUESTED", StringComparison.OrdinalIgnoreCase);
}
