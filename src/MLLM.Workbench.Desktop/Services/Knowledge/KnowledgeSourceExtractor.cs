using System.IO;
using System.IO.Compression;
using System.Text;
using System.Xml.Linq;
using UglyToad.PdfPig;
using UglyToad.PdfPig.DocumentLayoutAnalysis.TextExtractor;

namespace MLLM.Workbench.Desktop.Services.Knowledge;

internal sealed record KnowledgeSourceSection(string? Locator, string Text);

internal static class KnowledgeSourceExtractor
{
    public static async Task<IReadOnlyList<KnowledgeSourceSection>> ExtractAsync(
        string fullPath,
        CancellationToken cancellationToken)
    {
        var extension = Path.GetExtension(fullPath).ToLowerInvariant();
        return extension switch
        {
            ".md" or ".markdown" or ".txt" =>
                await ExtractTextAsync(fullPath, cancellationToken).ConfigureAwait(false),
            ".pdf" => ExtractPdf(fullPath, cancellationToken),
            ".docx" => await ExtractDocxAsync(fullPath, cancellationToken).ConfigureAwait(false),
            _ => throw new NotSupportedException(
                $"Knowledge import does not support '{extension}'. Supported formats: .md, .markdown, .txt, .pdf, .docx.")
        };
    }

    private static async Task<IReadOnlyList<KnowledgeSourceSection>> ExtractTextAsync(
        string fullPath,
        CancellationToken cancellationToken)
    {
        var text = await File.ReadAllTextAsync(fullPath, Encoding.UTF8, cancellationToken).ConfigureAwait(false);
        if (string.IsNullOrWhiteSpace(text))
            throw new InvalidDataException("Knowledge source file is empty.");
        return [new KnowledgeSourceSection(null, text)];
    }

    private static IReadOnlyList<KnowledgeSourceSection> ExtractPdf(
        string fullPath,
        CancellationToken cancellationToken)
    {
        var sections = new List<KnowledgeSourceSection>();
        using var document = PdfDocument.Open(fullPath);
        foreach (var page in document.GetPages())
        {
            cancellationToken.ThrowIfCancellationRequested();
            var text = ContentOrderTextExtractor.GetText(page).Trim();
            if (text.Length == 0) continue;
            sections.Add(new KnowledgeSourceSection($"page={page.Number}", text));
        }

        if (sections.Count == 0)
        {
            throw new InvalidDataException(
                "PDF contains no extractable text. Image-only or scanned PDF requires OCR, which is not enabled.");
        }

        return sections;
    }

    private static async Task<IReadOnlyList<KnowledgeSourceSection>> ExtractDocxAsync(
        string fullPath,
        CancellationToken cancellationToken)
    {
        using var archive = ZipFile.OpenRead(fullPath);
        var documentEntry = archive.GetEntry("word/document.xml")
            ?? throw new InvalidDataException("DOCX is missing word/document.xml.");

        await using var stream = documentEntry.Open();
        var document = await XDocument.LoadAsync(stream, LoadOptions.None, cancellationToken).ConfigureAwait(false);
        XNamespace w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";

        var sections = new List<KnowledgeSourceSection>();
        var paragraphNumber = 0;
        foreach (var paragraph in document.Descendants(w + "p"))
        {
            cancellationToken.ThrowIfCancellationRequested();
            paragraphNumber++;
            var text = string.Concat(paragraph.Descendants(w + "t").Select(static node => node.Value)).Trim();
            if (text.Length == 0) continue;
            sections.Add(new KnowledgeSourceSection($"paragraph={paragraphNumber}", text));
        }

        if (sections.Count == 0)
            throw new InvalidDataException("DOCX contains no extractable paragraph text.");

        return sections;
    }
}
