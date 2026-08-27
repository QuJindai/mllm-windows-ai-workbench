using System.Text.Json;
using MLLM.Workbench.Contracts.Operations;

namespace MLLM.Workbench.Contracts.Protocol;

public sealed record RpcRequest(
    string Protocol,
    string Type,
    string Id,
    string Method,
    string SessionToken,
    JsonElement? Payload);

public sealed record RpcResponse(
    string Protocol,
    string Type,
    string Id,
    bool Success,
    JsonElement? Payload,
    OperationError? Error);
