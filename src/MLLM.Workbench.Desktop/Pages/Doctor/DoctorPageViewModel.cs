using MLLM.Workbench.Desktop.Shell;

namespace MLLM.Workbench.Desktop.Pages.Doctor;

public sealed class DoctorPageViewModel : ObservableObject
{
    public string Title => "系统体检 (Doctor)";
    public string Subtitle => "区分正常、可安装、受阻和产品故障";
}
