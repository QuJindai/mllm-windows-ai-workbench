namespace MLLM.Workbench.Contracts.Components;

public sealed record ComponentPresetDescriptor(
    string Id,
    string DisplayName,
    string Description,
    bool Recommended,
    IReadOnlyList<string> Components);

public sealed record ComponentPresetCatalog(
    IReadOnlyList<ComponentPresetDescriptor> Presets);

public sealed record ComponentPresetInstallRequest(
    string PresetId,
    string OperationId);

public sealed record ComponentPresetTaskResult(
    string Id,
    string Status,
    string Summary);

public sealed record ComponentPresetInstallResult(
    string PresetId,
    string DisplayName,
    IReadOnlyList<ComponentPresetTaskResult> Results);
