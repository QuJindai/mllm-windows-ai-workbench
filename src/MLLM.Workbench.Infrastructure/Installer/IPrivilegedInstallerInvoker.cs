namespace MLLM.Workbench.Infrastructure.Installer;

public interface IPrivilegedInstallerInvoker
{
    Task<InstallerProcessResult> RunAsync(InstallerProcessRequest request, CancellationToken cancellationToken);
}
