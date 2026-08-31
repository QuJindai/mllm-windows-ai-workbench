using System.IO;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class D2ConversationShellTests
{
    [Fact]
    public void Shell_exposes_exact_conversation_route_template_and_refresh_navigation()
    {
        var root = FindRepositoryRoot();
        var desktopRoot = Path.Combine(root, "src", "MLLM.Workbench.Desktop");
        var page = Path.Combine(desktopRoot, "Pages", "Conversation", "ConversationPage.xaml");
        var codeBehind = Path.Combine(desktopRoot, "Pages", "Conversation", "ConversationPage.xaml.cs");

        Assert.True(File.Exists(page), $"Conversation page missing: {page}");
        Assert.True(File.Exists(codeBehind), $"Conversation code-behind missing: {codeBehind}");

        var shellXaml = File.ReadAllText(Path.Combine(desktopRoot, "Shell", "MainWindow.xaml"));
        Assert.Contains("xmlns:conversation=\"clr-namespace:MLLM.Workbench.Desktop.Pages.Conversation\"", shellXaml, StringComparison.Ordinal);
        Assert.Contains("conversation:ConversationPageViewModel", shellXaml, StringComparison.Ordinal);
        Assert.Contains("<conversation:ConversationPage", shellXaml, StringComparison.Ordinal);
        Assert.Contains("ConversationNavigation", shellXaml, StringComparison.Ordinal);
        Assert.Contains("对话测试", shellXaml, StringComparison.Ordinal);

        var shellViewModel = File.ReadAllText(Path.Combine(desktopRoot, "Shell", "MainWindowViewModel.cs"));
        Assert.Contains("ConversationPageViewModel conversation", shellViewModel, StringComparison.Ordinal);
        Assert.Contains("public ConversationPageViewModel Conversation", shellViewModel, StringComparison.Ordinal);
        Assert.Contains("NavigateConversationCommand", shellViewModel, StringComparison.Ordinal);
        Assert.Contains("new(\"conversation\", \"对话测试\"", shellViewModel, StringComparison.Ordinal);
        Assert.Contains("\"conversation\" => Conversation", shellViewModel, StringComparison.Ordinal);
        Assert.Contains("Conversation.RefreshCommand.Execute(null)", shellViewModel, StringComparison.Ordinal);
    }

    [Fact]
    public void Desktop_composition_registers_real_conversation_dependencies_and_dashboard_action()
    {
        var root = FindRepositoryRoot();
        var desktopRoot = Path.Combine(root, "src", "MLLM.Workbench.Desktop");
        var app = File.ReadAllText(Path.Combine(desktopRoot, "App.xaml.cs"));
        var dashboard = File.ReadAllText(Path.Combine(desktopRoot, "Pages", "Dashboard", "DashboardPage.xaml"));

        Assert.Contains("ILocalConversationClient", app, StringComparison.Ordinal);
        Assert.Contains("LocalOpenAiConversationClient", app, StringComparison.Ordinal);
        Assert.Contains("IConversationTestService", app, StringComparison.Ordinal);
        Assert.Contains("ConversationTestService", app, StringComparison.Ordinal);
        Assert.Contains("IGoldenTestCatalog", app, StringComparison.Ordinal);
        Assert.Contains("JsonGoldenTestCatalog(runtime.DataRoot", app, StringComparison.Ordinal);
        Assert.Contains("GoldenTestEvaluator", app, StringComparison.Ordinal);
        Assert.Contains("ConversationPageViewModel", app, StringComparison.Ordinal);
        Assert.Contains("OpenConversationButton", dashboard, StringComparison.Ordinal);
        Assert.Contains("OpenConversationCommand", dashboard, StringComparison.Ordinal);
    }

    private static string FindRepositoryRoot()
    {
        var cursor = new DirectoryInfo(AppContext.BaseDirectory);
        while (cursor is not null)
        {
            if (File.Exists(Path.Combine(cursor.FullName, "Bootstrap_SafeCore.ps1"))) return cursor.FullName;
            cursor = cursor.Parent;
        }
        throw new DirectoryNotFoundException("Repository root was not found.");
    }
}
