using MLLM.Workbench.Infrastructure.Installer;

namespace MLLM.Workbench.Infrastructure.Tests;

public sealed class PrivilegedInstallerInvokerTests
{
    [Fact]
    public void BuildStartInfo_uses_argument_list_and_never_directly_requests_runas()
    {
        var root = FindRepositoryRoot();
        var invoker = new PrivilegedInstallerInvoker(root);
        var offline = @"C:\Users\Test User\Downloads\M LLM offline.zip";
        var request = new InstallerProcessRequest(InstallerAction.ImportOffline, offline);

        var start = invoker.BuildStartInfo(request);

        Assert.False(start.UseShellExecute);
        Assert.True(string.IsNullOrEmpty(start.Verb));
        Assert.Contains("-Action", start.ArgumentList);
        Assert.Contains("ImportOffline", start.ArgumentList);
        Assert.Contains("-OfflinePackagePath", start.ArgumentList);
        Assert.Contains(offline, start.ArgumentList);
        Assert.DoesNotContain(start.ArgumentList, x => x.Contains("runas", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void BuildStartInfo_omits_offline_path_for_non_import_actions()
    {
        var root = FindRepositoryRoot();
        var invoker = new PrivilegedInstallerInvoker(root);
        var start = invoker.BuildStartInfo(new InstallerProcessRequest(InstallerAction.InstallResume));

        Assert.Contains("InstallResume", start.ArgumentList);
        Assert.DoesNotContain("-OfflinePackagePath", start.ArgumentList);
    }

    private static string FindRepositoryRoot()
    {
        var cursor = new DirectoryInfo(AppContext.BaseDirectory);
        while (cursor is not null)
        {
            if (File.Exists(Path.Combine(cursor.FullName, "installer", "Start-UniversalInstaller.ps1"))) return cursor.FullName;
            cursor = cursor.Parent;
        }
        throw new DirectoryNotFoundException("Repository root was not found.");
    }
}
