namespace MLLM.Workbench.Contracts.Services;

public sealed record ServiceDescriptor(
    string ServiceId,
    string DisplayName,
    ManagedServiceState State,
    int? Pid,
    int? Port,
    string? BaseUrl,
    DateTimeOffset? StartedAt,
    long? UptimeSeconds,
    string? ModelId,
    string? ModelPath,
    string HealthSummary,
    string? StdoutLog,
    string? StderrLog,
    bool CanStart,
    bool CanStop,
    bool CanRestart,
    string? BlockedReason);
