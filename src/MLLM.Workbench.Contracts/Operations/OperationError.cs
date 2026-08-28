using System.Text.Json;

namespace MLLM.Workbench.Contracts.Operations;

public sealed record OperationError(
    string Code,
    string Message,
    string? Stage,
    bool Recoverable,
    JsonElement? Details);
