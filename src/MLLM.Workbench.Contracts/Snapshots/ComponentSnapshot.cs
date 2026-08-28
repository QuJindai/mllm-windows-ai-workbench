using MLLM.Workbench.Contracts.Status;

namespace MLLM.Workbench.Contracts.Snapshots;

public sealed record ComponentSnapshot(
    string Id,
    ComponentHealth Health,
    string Summary,
    bool RepairAvailable,
    string? RepairTask);
