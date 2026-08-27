using MLLM.Workbench.Desktop.Shell;

namespace MLLM.Workbench.Desktop.Pages.Dashboard;

public sealed class DashboardPageViewModel : ObservableObject
{
    public string Title => "工作台";
    public string Subtitle => "系统、组件和 Safe Core 后端总览";
}
