using System.Text.Json;

namespace MLLM.Workbench.Contracts.Operations;

public sealed record OperationProgress(
    string OperationId,
    string StageId,
    double? Percentage,
    string Message,
    JsonElement? Details,
    string? EvidenceRunId);
