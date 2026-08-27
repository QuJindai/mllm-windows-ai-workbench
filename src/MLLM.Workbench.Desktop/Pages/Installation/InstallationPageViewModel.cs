using MLLM.Workbench.Desktop.Shell;

namespace MLLM.Workbench.Desktop.Pages.Installation;

public sealed class InstallationPageViewModel : ObservableObject
{
    public string Title => "安装中心";
    public string Subtitle => "安装、恢复与回滚继续由 Universal Installer 事务引擎负责";
}
