namespace MLLM.Workbench.Contracts.Services;

public enum ManagedServiceState
{
    Stopped,
    Starting,
    Running,
    Stopping,
    Degraded,
    Blocked,
    Failed
}
