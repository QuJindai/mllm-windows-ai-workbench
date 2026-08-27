namespace MLLM.Workbench.Desktop.Services;

public sealed record WorkbenchRuntimeOptions(string ProjectRoot, string DataRoot, string NetworkMode)
{
    public static WorkbenchRuntimeOptions Resolve()
    {
        var projectRoot = FindProjectRoot();
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrWhiteSpace(local)) local = Path.GetTempPath();
        var dataRoot = Path.Combine(local, "M-LLM", "Workbench", "Data");
        return new WorkbenchRuntimeOptions(projectRoot, dataRoot, "OFFLINE_CACHE");
    }

    private static string FindProjectRoot()
    {
        var cursor = new DirectoryInfo(AppContext.BaseDirectory);
        while (cursor is not null)
        {
            if (File.Exists(Path.Combine(cursor.FullName, "Bootstrap_SafeCore.ps1")) &&
                File.Exists(Path.Combine(cursor.FullName, "runtime", "WorkbenchBackend.ps1")))
            {
                return cursor.FullName;
            }
            cursor = cursor.Parent;
        }
        throw new DirectoryNotFoundException("M-LLM runtime root could not be resolved from the desktop executable.");
    }
}
