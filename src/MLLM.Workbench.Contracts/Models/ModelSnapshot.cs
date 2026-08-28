namespace MLLM.Workbench.Contracts.Models;

public sealed record ModelSnapshot(
    IReadOnlyList<ModelDescriptor> Models,
    string? ActiveModelId,
    string NetworkMode);
