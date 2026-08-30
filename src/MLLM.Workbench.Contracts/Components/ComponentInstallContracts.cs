namespace MLLM.Workbench.Contracts.Components;

public sealed record ComponentPresetInstallRequest(
    string Preset,
    string NetworkMode,
    string OperationId);

public sealed record ComponentTaskInstallRequest(
    string TaskId,
    string NetworkMode,
    string OperationId);

public sealed record ComponentInstallItemResult(
    string Id,
    string Status,
    string Summary);

public sealed record ComponentInstallResult(
    string? Preset,
    string? TaskId,
    string NetworkMode,
    string Status,
    string RunDirectory,
    IReadOnlyList<ComponentInstallItemResult> Items);
