using System.Collections.ObjectModel;
using System.Windows.Input;
using MLLM.Workbench.Desktop.Pages.Dashboard;
using MLLM.Workbench.Desktop.Pages.Doctor;
using MLLM.Workbench.Desktop.Pages.Installation;
using MLLM.Workbench.Desktop.Pages.Knowledge;
using MLLM.Workbench.Desktop.Pages.Models;
using MLLM.Workbench.Desktop.Pages.Services;
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
        ModelManagementPageViewModel models,
        LocalServicesPageViewModel services,
        KnowledgePageViewModel knowledge,
        WorkbenchRuntimeOptions runtime)
    {
        Dashboard = dashboard;
        Doctor = doctor;
        Installation = installation;
        Models = models;
        Services = services;
        Knowledge = knowledge;
        _currentPage = dashboard;
        NetworkMode = runtime.NetworkMode;
        NavigateDashboardCommand = new RelayCommand(() => Navigate("dashboard"));
        NavigateDoctorCommand = new RelayCommand(() => Navigate("doctor"));
        NavigateInstallationCommand = new RelayCommand(() => Navigate("installation"));
        NavigateModelsCommand = new RelayCommand(() => Navigate("models"));
        NavigateServicesCommand = new RelayCommand(() => Navigate("services"));
        NavigateKnowledgeCommand = new RelayCommand(() => Navigate("knowledge"));
        Dashboard.NavigationRequested += Navigate;
        NavigationItems = new ObservableCollection<NavigationItem>
        {
            new("dashboard", "工作台", NavigateDashboardCommand),
            new("doctor", "系统体检", NavigateDoctorCommand),
            new("installation", "安装中心", NavigateInstallationCommand),
            new("models", "模型管理", NavigateModelsCommand),
            new("services", "本地服务", NavigateServicesCommand),
            new("knowledge", "知识工作台", NavigateKnowledgeCommand)
        };
    }

    public DashboardPageViewModel Dashboard { get; }
    public DoctorPageViewModel Doctor { get; }
    public InstallationPageViewModel Installation { get; }
    public ModelManagementPageViewModel Models { get; }
    public LocalServicesPageViewModel Services { get; }
    public KnowledgePageViewModel Knowledge { get; }
    public ObservableCollection<NavigationItem> NavigationItems { get; }
    public string NetworkMode { get; }
    public ICommand NavigateDashboardCommand { get; }
    public ICommand NavigateDoctorCommand { get; }
    public ICommand NavigateInstallationCommand { get; }
    public ICommand NavigateModelsCommand { get; }
    public ICommand NavigateServicesCommand { get; }
    public ICommand NavigateKnowledgeCommand { get; }
    public object CurrentPage { get => _currentPage; private set => SetProperty(ref _currentPage, value); }
    public string BackendStatus { get => _backendStatus; private set => SetProperty(ref _backendStatus, value); }
    public void SetBackendStatus(string value) => BackendStatus = value;

    private void Navigate(string route)
    {
        CurrentPage = route switch
        {
            "doctor" => Doctor,
            "installation" => Installation,
            "models" => Models,
            "services" => Services,
            "knowledge" => Knowledge,
            _ => Dashboard
        };
        if (route == "doctor") Doctor.RefreshCommand.Execute(null);
        if (route == "installation") Installation.RefreshCommand.Execute(null);
        if (route == "models") Models.RefreshCommand.Execute(null);
        if (route == "services") Services.RefreshCommand.Execute(null);
        if (route == "knowledge") Knowledge.RefreshCommand.Execute(null);
    }
}
