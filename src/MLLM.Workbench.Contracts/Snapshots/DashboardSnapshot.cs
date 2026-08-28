namespace MLLM.Workbench.Contracts.Snapshots;

public sealed record DashboardSnapshot(
    MachineSnapshot Machine,
    string NetworkMode,
    IReadOnlyList<ComponentSnapshot> Components,
    string? CurrentModel);
