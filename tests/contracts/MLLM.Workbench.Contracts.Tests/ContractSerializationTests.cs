using System.Text.Json;
using MLLM.Workbench.Contracts.Protocol;
using MLLM.Workbench.Contracts.Snapshots;
using MLLM.Workbench.Contracts.Status;

namespace MLLM.Workbench.Contracts.Tests;

public sealed class ContractSerializationTests
{
    [Fact]
    public void DashboardSnapshot_round_trips_with_stable_enum_names()
    {
        var input = new DashboardSnapshot(
            new MachineSnapshot("Windows 11", "x64", "CPU", 32.0, ["GPU"], 100.0),
            "OFFLINE_CACHE",
            [new ComponentSnapshot("python", ComponentHealth.ReadyToInstall, "Python not installed", true, "python")],
            null);

        var json = JsonSerializer.Serialize(input, WorkbenchJson.Options);
        var output = JsonSerializer.Deserialize<DashboardSnapshot>(json, WorkbenchJson.Options)!;

        Assert.Equal(ComponentHealth.ReadyToInstall, output.Components[0].Health);
        Assert.Contains("ReadyToInstall", json, StringComparison.Ordinal);
    }

    [Fact]
    public void Protocol_version_is_fixed_for_phase_a()
    {
        Assert.Equal("1.0", RpcProtocol.Version);
    }
}
