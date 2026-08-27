using MLLM.Workbench.Contracts.Operations;

namespace MLLM.Workbench.Contracts.Snapshots;

public sealed record DoctorSnapshot(
    IReadOnlyList<ComponentSnapshot> Components,
    IReadOnlyList<OperationError> Errors);
