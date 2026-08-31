using System.IO;
using System.Xml.Linq;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class D2ConversationPageRuntimeLoadTests
{
    private static readonly string[] RequiredAutomationIds =
    [
        "ConversationPageRoot",
        "ConversationRefreshButton",
        "ConversationSystemPrompt",
        "ConversationUserPrompt",
        "ConversationSendButton",
        "ConversationCancelButton",
        "ConversationTranscript",
        "ConversationEvidenceList",
        "GoldenCaseList",
        "GoldenRunSelectedButton",
        "GoldenRunAllButton",
        "GoldenResultList"
    ];

    [Fact]
    public void Conversation_page_is_parseable_wpf_xaml_with_required_controls()
    {
        var root = FindRepositoryRoot();
        var path = Path.Combine(root, "src", "MLLM.Workbench.Desktop", "Pages", "Conversation", "ConversationPage.xaml");
        Assert.True(File.Exists(path), $"Conversation page missing: {path}");

        var text = File.ReadAllText(path);
        foreach (var automationId in RequiredAutomationIds)
            Assert.Contains($"AutomationProperties.AutomationId=\"{automationId}\"", text, StringComparison.Ordinal);

        Assert.Contains("CardStyle", text, StringComparison.Ordinal);
        Assert.Contains("ActionButtonStyle", text, StringComparison.Ordinal);
        Assert.Contains("PrimaryTextBrush", text, StringComparison.Ordinal);
        Assert.Contains("MutedTextBrush", text, StringComparison.Ordinal);
        Assert.Contains("ItemsSource=\"{Binding Evidence}\"", text, StringComparison.Ordinal);
        Assert.Contains("Command=\"{Binding OpenSelectedEvidenceCommand}\"", text, StringComparison.Ordinal);

        var document = XDocument.Load(path);
        XNamespace x = "http://schemas.microsoft.com/winfx/2006/xaml";
        Assert.Equal("UserControl", document.Root?.Name.LocalName);
        Assert.Equal(
            "MLLM.Workbench.Desktop.Pages.Conversation.ConversationPage",
            (string?)document.Root?.Attribute(x + "Class"));
    }

    [Fact]
    public void Conversation_code_behind_is_constructor_only()
    {
        var root = FindRepositoryRoot();
        var path = Path.Combine(root, "src", "MLLM.Workbench.Desktop", "Pages", "Conversation", "ConversationPage.xaml.cs");
        Assert.True(File.Exists(path), $"Conversation code-behind missing: {path}");

        var source = File.ReadAllText(path);
        Assert.Contains("public ConversationPage()", source, StringComparison.Ordinal);
        Assert.Contains("InitializeComponent();", source, StringComparison.Ordinal);
        Assert.DoesNotContain("Click=", source, StringComparison.Ordinal);
        Assert.DoesNotContain("RunAsync(", source, StringComparison.Ordinal);
        Assert.DoesNotContain("UpsertAsync(", source, StringComparison.Ordinal);
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
