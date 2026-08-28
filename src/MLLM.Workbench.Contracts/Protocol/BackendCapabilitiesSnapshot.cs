namespace MLLM.Workbench.Contracts.Protocol;

public sealed record BackendCapabilitiesSnapshot(
    string BackendVersion,
    IReadOnlyList<string> Methods);
