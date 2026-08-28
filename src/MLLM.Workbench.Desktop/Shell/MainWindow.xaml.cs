using System.Windows;

namespace MLLM.Workbench.Desktop.Shell;

public partial class MainWindow : Window
{
    public MainWindow(MainWindowViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
    }
}
