namespace MLLM.Workbench.Contracts.Services;

public sealed record ServiceLogTail(
    string ServiceId,
    string? StdoutPath,
    string? StderrPath,
    IReadOnlyList<string> StdoutLines,
    IReadOnlyList<string> StderrLines);
