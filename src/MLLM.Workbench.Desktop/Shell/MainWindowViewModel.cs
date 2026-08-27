using System.Collections.ObjectModel;
using System.Windows.Input;
using MLLM.Workbench.Desktop.Pages.Dashboard;
using MLLM.Workbench.Desktop.Pages.Doctor;
using MLLM.Workbench.Desktop.Pages.Installation;
using MLLM.Workbench.Desktop.Services;

namespace MLLM.Workbench.Desktop.Shell;

public sealed class MainWindowViewModel : ObservableObject
{
    private object _currentPage;
    private string _backendStatus = "Safe Core backend: starting";

    public MainWindowViewModel(
        DashboardPageViewModel dashboard,
        DoctorPageViewModel doctor,
        InstallationPageViewModel installation,
        WorkbenchRuntimeOptions runtime)
    {
        Dashboard = dashboard;
        Doctor = doctor;
        Installation = installation;
        _currentPage = dashboard;
        NetworkMode = runtime.NetworkMode;
        NavigateDashboardCommand = new RelayCommand(() => CurrentPage = Dashboard);
        NavigateDoctorCommand = new RelayCommand(() => CurrentPage = Doctor);
        NavigateInstallationCommand = new RelayCommand(() => CurrentPage = Installation);
        NavigationItems = new ObservableCollection<NavigationItem>
        {
            new("dashboard", "工作台", NavigateDashboardCommand),
            new("doctor", "系统体检", NavigateDoctorCommand),
            new("installation", "安装中心", NavigateInstallationCommand)
        };
    }

    public DashboardPageViewModel Dashboard { get; }
    public DoctorPageViewModel Doctor { get; }
    public InstallationPageViewModel Installation { get; }
    public ObservableCollection<NavigationItem> NavigationItems { get; }
    public string NetworkMode { get; }
    public ICommand NavigateDashboardCommand { get; }
    public ICommand NavigateDoctorCommand { get; }
    public ICommand NavigateInstallationCommand { get; }

    public object CurrentPage
    {
        get => _currentPage;
        private set => SetProperty(ref _currentPage, value);
    }

    public string BackendStatus
    {
        get => _backendStatus;
        private set => SetProperty(ref _backendStatus, value);
    }

    public void SetBackendStatus(string value) => BackendStatus = value;
}
