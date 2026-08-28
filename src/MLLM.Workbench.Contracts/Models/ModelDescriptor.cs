namespace MLLM.Workbench.Contracts.Models;

public sealed record ModelDescriptor(
    string Id,
    string Role,
    string DisplayName,
    ModelSourceKind SourceKind,
    string? FilePath,
    string FileName,
    string Format,
    string? Quantization,
    long SizeBytes,
    long MinimumBytes,
    string? ExpectedSha256,
    string? ActualSha256,
    ModelIntegrityState IntegrityState,
    bool IsActive,
    string? ActivationBlockedReason);
