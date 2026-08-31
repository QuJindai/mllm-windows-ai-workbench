using System.Collections.ObjectModel;
using System.Windows.Input;
using MLLM.Workbench.Contracts.Services;
using MLLM.Workbench.Desktop.Shell;
using MLLM.Workbench.Infrastructure.Backend;

namespace MLLM.Workbench.Desktop.Pages.Services;

public sealed class LocalServicesPageViewModel : ObservableObject
{
    private readonly IWorkbenchBackendClient _backend;

    public LocalServicesPageViewModel(IWorkbenchBackendClient backend)
    {
        _backend = backend ?? throw new ArgumentNullException(nameof(backend));
        RefreshCommand = new AsyncRelayCommand(_ => Task.CompletedTask);
    }

    public string Title => "本地服务";
    public string Subtitle => "Local Model API 与 Web Workbench 运行状态";
    public ObservableCollection<ServiceDescriptor> Services { get; } = [];
    public ICommand RefreshCommand { get; }
}
