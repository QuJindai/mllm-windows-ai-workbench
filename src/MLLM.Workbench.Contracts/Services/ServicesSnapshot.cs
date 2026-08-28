namespace MLLM.Workbench.Contracts.Services;

public sealed record ServicesSnapshot(
    IReadOnlyList<ServiceDescriptor> Services,
    string NetworkMode);
