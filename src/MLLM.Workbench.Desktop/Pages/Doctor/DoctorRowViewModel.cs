using MLLM.Workbench.Contracts.Status;

namespace MLLM.Workbench.Desktop.Pages.Doctor;

public sealed record DoctorRowViewModel(
    string Id,
    ComponentHealth Health,
    string DisplayState,
    string Summary,
    string Recommendation,
    bool IsProductFault,
    bool RepairAvailable,
    string? RepairTask);
