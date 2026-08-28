namespace MLLM.Workbench.Contracts.Status;

public enum ComponentHealth
{
    Unknown,
    Pass,
    Running,
    ReadyToInstall,
    RepairAvailable,
    Blocked,
    NotFound,
    DetectionError,
    OperationFailed
}
