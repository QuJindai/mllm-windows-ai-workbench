using System.IO;
using System.Xml.Linq;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class KnowledgeShellIntegrationTests
{
    [Fact]
    public void Shell_exposes_native_knowledge_navigation_and_page_template()
    {
        var root = FindRepositoryRoot();
        var shellPath = Path.Combine(root, "src", "MLLM.Workbench.Desktop", "Shell", "MainWindow.xaml");
        var xml = File.ReadAllText(shellPath);
        var document = XDocument.Load(shellPath);
        XNamespace x = "http://schemas.microsoft.com/winfx/2006/xaml";

        var names = document.Descendants()
            .Select(e => (string?)e.Attribute(x + "Name"))
            .Where(v => !string.IsNullOrWhiteSpace(v))
            .ToHashSet(StringComparer.Ordinal);

        Assert.Contains("KnowledgeNavigation", names);
        Assert.Contains("clr-namespace:MLLM.Workbench.Desktop.Pages.Knowledge", xml, StringComparison.Ordinal);
        Assert.Contains("knowledge:KnowledgePageViewModel", xml, StringComparison.Ordinal);
        Assert.Contains("knowledge:KnowledgePage", xml, StringComparison.Ordinal);
        Assert.Contains("NavigateKnowledgeCommand", xml, StringComparison.Ordinal);
    }

    [Fact]
    public void Knowledge_page_has_import_search_evidence_and_rag_automation_contracts()
    {
        var root = FindRepositoryRoot();
        var pagePath = Path.Combine(root, "src", "MLLM.Workbench.Desktop", "Pages", "Knowledge", "KnowledgePage.xaml");
        Assert.True(File.Exists(pagePath), $"KnowledgePage.xaml missing: {pagePath}");

        var document = XDocument.Load(pagePath);
        var automationIds = document.Descendants()
            .SelectMany(e => e.Attributes())
            .Where(a => a.Name.LocalName == "AutomationId")
            .Select(a => a.Value)
            .ToHashSet(StringComparer.Ordinal);

        foreach (var required in new[]
        {
            "KnowledgeFtsStatus",
            "KnowledgeEmbeddingStatus",
            "KnowledgeHybridStatus",
            "KnowledgeImportPath",
            "KnowledgeBrowseButton",
            "KnowledgeImportButton",
            "KnowledgeQueryBox",
            "KnowledgeSearchMode",
            "KnowledgeSearchButton",
            "KnowledgeResults",
            "KnowledgeOpenEvidence",
            "KnowledgeRagContext"
        })
        {
            Assert.Contains(required, automationIds);
        }
    }

    [Fact]
    public void Desktop_composition_wires_real_knowledge_service_launcher_and_view_model()
    {
        var root = FindRepositoryRoot();
        var app = File.ReadAllText(Path.Combine(root, "src", "MLLM.Workbench.Desktop", "App.xaml.cs"));
        var mainVm = File.ReadAllText(Path.Combine(root, "src", "MLLM.Workbench.Desktop", "Shell", "MainWindowViewModel.cs"));

        Assert.Contains("IKnowledgeWorkbenchService", app, StringComparison.Ordinal);
        Assert.Contains("KnowledgeWorkbenchService", app, StringComparison.Ordinal);
        Assert.Contains("IEvidenceLauncher", app, StringComparison.Ordinal);
        Assert.Contains("ShellEvidenceLauncher", app, StringComparison.Ordinal);
        Assert.Contains("KnowledgePageViewModel", app, StringComparison.Ordinal);

        Assert.Contains("KnowledgePageViewModel", mainVm, StringComparison.Ordinal);
        Assert.Contains("NavigateKnowledgeCommand", mainVm, StringComparison.Ordinal);
        Assert.Contains("\"knowledge\" => Knowledge", mainVm, StringComparison.Ordinal);
    }

    [Fact]
    public void File_picker_contract_does_not_claim_unsupported_pdf_import()
    {
        var root = FindRepositoryRoot();
        var codeBehindPath = Path.Combine(root, "src", "MLLM.Workbench.Desktop", "Pages", "Knowledge", "KnowledgePage.xaml.cs");
        Assert.True(File.Exists(codeBehindPath), $"KnowledgePage.xaml.cs missing: {codeBehindPath}");
        var source = File.ReadAllText(codeBehindPath);

        Assert.Contains("*.md;*.markdown;*.txt", source, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("*.pdf", source, StringComparison.OrdinalIgnoreCase);
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
