using System.IO;
using System.Text.Json;

namespace MLLM.Workbench.Desktop.Services;

public sealed record WorkbenchRuntimeOptions(string ProjectRoot, string DataRoot, string NetworkMode)
{
    private static readonly HashSet<string> AllowedNetworkModes = new(StringComparer.OrdinalIgnoreCase)
    {
        "AUTO_CN_FIRST",
        "CHINA_ONLY",
        "GLOBAL_FIRST",
        "OFFLINE_CACHE",
        "CUSTOM_PROXY"
    };

    public static WorkbenchRuntimeOptions Resolve()
    {
        var projectRoot = FindProjectRoot();
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrWhiteSpace(local)) local = Path.GetTempPath();
        var dataRoot = Path.Combine(local, "M-LLM", "Workbench", "Data");
        var networkMode = ResolveNetworkMode(projectRoot);
        return new WorkbenchRuntimeOptions(projectRoot, dataRoot, networkMode);
    }

    private static string ResolveNetworkMode(string projectRoot)
    {
        var explicitMode = Environment.GetEnvironmentVariable("MLLM_NETWORK_MODE");
        if (!string.IsNullOrWhiteSpace(explicitMode))
            return ValidateNetworkMode(explicitMode);

        var defaultsPath = Path.Combine(projectRoot, "config", "defaults.json");
        if (!File.Exists(defaultsPath))
            throw new FileNotFoundException("M-LLM runtime defaults are missing.", defaultsPath);

        using var document = JsonDocument.Parse(File.ReadAllText(defaultsPath));
        if (!document.RootElement.TryGetProperty("network_mode", out var networkModeElement))
            throw new InvalidDataException("config/defaults.json does not define network_mode.");

        var configured = networkModeElement.GetString();
        if (string.IsNullOrWhiteSpace(configured))
            throw new InvalidDataException("config/defaults.json network_mode is empty.");

        return ValidateNetworkMode(configured);
    }

    private static string ValidateNetworkMode(string mode)
    {
        var normalized = mode.Trim().ToUpperInvariant();
        if (!AllowedNetworkModes.Contains(normalized))
            throw new InvalidDataException("Unsupported M-LLM network mode: " + mode);
        return normalized;
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
