using System.IO;
using System.Xml.Linq;
using Xunit;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class KnowledgeEvidenceMicroscopeShellTests
{
    [Fact]
    public void Knowledge_page_exposes_bound_evidence_microscope_panel()
    {
        var root = FindRepositoryRoot();
        var pagePath = Path.Combine(root, "src", "MLLM.Workbench.Desktop", "Pages", "Knowledge", "KnowledgePage.xaml");
        Assert.True(File.Exists(pagePath), $"KnowledgePage.xaml missing: {pagePath}");

        var document = XDocument.Load(pagePath);
        var automationIds = document.Descendants()
            .SelectMany(e => e.Attributes())
            .Where(a => a.Name.LocalName.EndsWith("AutomationId", StringComparison.Ordinal))
            .Select(a => a.Value)
            .ToHashSet(StringComparer.Ordinal);

        Assert.Contains("KnowledgeEvidenceMicroscope", automationIds);

        var xml = File.ReadAllText(pagePath);
        Assert.Contains("EvidenceMicroscopeText", xml, StringComparison.Ordinal);
        Assert.Contains("证据显微镜", xml, StringComparison.Ordinal);
        Assert.Contains("FTS", xml, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("Embedding", xml, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("RRF", xml, StringComparison.OrdinalIgnoreCase);
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
