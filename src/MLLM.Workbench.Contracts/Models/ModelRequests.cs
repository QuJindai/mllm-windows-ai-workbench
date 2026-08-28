namespace MLLM.Workbench.Contracts.Models;

public sealed record ModelVerifyRequest(
    string ModelId,
    string OperationId);

public sealed record ModelImportRequest(
    string SourcePath,
    string? DisplayName,
    string OperationId);

public sealed record ModelActivateRequest(
    string ModelId,
    string OperationId);
