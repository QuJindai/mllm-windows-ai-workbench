namespace MLLM.Workbench.Contracts.Snapshots;

public sealed record MachineSnapshot(
    string Os,
    string Architecture,
    string Cpu,
    double RamGb,
    IReadOnlyList<string> Gpus,
    double FixedDiskFreeGb);
