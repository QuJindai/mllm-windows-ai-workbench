using System.Windows;
using System.Windows.Controls;
using Microsoft.Win32;

namespace MLLM.Workbench.Desktop.Pages.Knowledge;

public partial class KnowledgePage : UserControl
{
    public KnowledgePage()
    {
        InitializeComponent();
    }

    private void BrowseKnowledgeFile_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog
        {
            Title = "选择知识文件",
            CheckFileExists = true,
            Multiselect = false,
            Filter = "Markdown / Text (*.md;*.markdown;*.txt)|*.md;*.markdown;*.txt|All files (*.*)|*.*"
        };

        if (dialog.ShowDialog() == true && DataContext is KnowledgePageViewModel viewModel)
            viewModel.ImportPath = dialog.FileName;
    }
}
