using System.Windows;
using System.Windows.Controls;
using Microsoft.Win32;

namespace MLLM.Workbench.Desktop.Pages.Installation;

public partial class InstallationPage : UserControl
{
    public InstallationPage() => InitializeComponent();

    private async void ImportOfflineButton_OnClick(object sender, RoutedEventArgs e)
    {
        if (DataContext is not InstallationPageViewModel viewModel) return;
        var dialog = new OpenFileDialog
        {
            Title = "选择 M-LLM 离线安装包",
            Filter = "ZIP packages (*.zip)|*.zip|All files (*.*)|*.*",
            CheckFileExists = true,
            Multiselect = false
        };
        if (dialog.ShowDialog() == true)
        {
            await viewModel.ImportOfflineAsync(dialog.FileName, CancellationToken.None).ConfigureAwait(true);
        }
    }
}
