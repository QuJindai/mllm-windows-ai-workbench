using MLLM.Workbench.Desktop.Services;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class WorkbenchRuntimeOptionsTests
{
    private static readonly object EnvironmentGate = new();

    [Fact]
    public void Resolve_uses_configured_default_network_mode_instead_of_forcing_offline_cache()
    {
        lock (EnvironmentGate)
        {
            var previous = Environment.GetEnvironmentVariable("MLLM_NETWORK_MODE");
            try
            {
                Environment.SetEnvironmentVariable("MLLM_NETWORK_MODE", null);
                var runtime = WorkbenchRuntimeOptions.Resolve();
                Assert.Equal("AUTO_CN_FIRST", runtime.NetworkMode);
            }
            finally
            {
                Environment.SetEnvironmentVariable("MLLM_NETWORK_MODE", previous);
            }
        }
    }

    [Fact]
    public void Resolve_allows_ci_or_user_to_explicitly_force_offline_cache()
    {
        lock (EnvironmentGate)
        {
            var previous = Environment.GetEnvironmentVariable("MLLM_NETWORK_MODE");
            try
            {
                Environment.SetEnvironmentVariable("MLLM_NETWORK_MODE", "OFFLINE_CACHE");
                var runtime = WorkbenchRuntimeOptions.Resolve();
                Assert.Equal("OFFLINE_CACHE", runtime.NetworkMode);
            }
            finally
            {
                Environment.SetEnvironmentVariable("MLLM_NETWORK_MODE", previous);
            }
        }
    }
}
