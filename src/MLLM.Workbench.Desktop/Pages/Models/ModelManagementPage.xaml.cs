using System.Windows;
using System.Windows.Controls;
using Microsoft.Win32;

namespace MLLM.Workbench.Desktop.Pages.Models;

public partial class ModelManagementPage : UserControl
{
    public ModelManagementPage()
    {
        InitializeComponent();
    }

    private async void ImportModelButton_OnClick(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ModelManagementPageViewModel viewModel || !viewModel.CanImport) return;
        var dialog = new OpenFileDialog
        {
            Title = "选择本地 GGUF 模型",
            Filter = "GGUF model (*.gguf)|*.gguf",
            CheckFileExists = true,
            Multiselect = false
        };
        if (dialog.ShowDialog() != true) return;
        try
        {
            await viewModel.ImportAsync(dialog.FileName, CancellationToken.None).ConfigureAwait(true);
        }
        catch
        {
            // ViewModel preserves the structured backend error for the page.
        }
    }
}
