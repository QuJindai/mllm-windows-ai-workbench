namespace MLLM.Workbench.Contracts.Services;

public sealed record ServiceActionRequest(
    string ServiceId,
    string OperationId);

public sealed record ServiceLogRequest(
    string ServiceId,
    int TailLines);
