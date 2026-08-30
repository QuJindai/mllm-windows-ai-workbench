using System.IO.Compression;
using System.Text;
using System.Xml.Linq;
using MLLM.Workbench.Desktop.Services.Knowledge;
using MLLM.Workbench.Knowledge;
using Xunit;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class KnowledgeDocumentImportTests
{
    [Fact]
    public async Task Pdf_import_is_searchable_with_page_locator()
    {
        var root = NewTempRoot();
        var source = Path.Combine(root, "manual.pdf");
        await File.WriteAllBytesAsync(
            source,
            BuildPdf(["overview placeholder", "vehicle software traceability evidence on second page"]),
            CancellationToken.None);

        try
        {
            using var service = new KnowledgeWorkbenchService(root);
            await service.ImportFileAsync(source, CancellationToken.None);

            var hits = await service.SearchAsync(
                "software traceability evidence",
                KnowledgeSearchMode.Fts5,
                10,
                CancellationToken.None);

            var hit = Assert.Single(hits);
            Assert.Equal(Path.GetFullPath(source), hit.SourceUri);
            Assert.Equal("page=2", hit.Locator);
            Assert.Contains("second page", hit.Excerpt, StringComparison.OrdinalIgnoreCase);

            var rag = RagContextBuilder.Build(hits);
            Assert.Contains("locator=page=2", rag.ContextText, StringComparison.Ordinal);
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    [Fact]
    public async Task Docx_import_is_searchable_with_paragraph_locator()
    {
        var root = NewTempRoot();
        var source = Path.Combine(root, "procedure.docx");
        WriteDocx(source, ["Overview paragraph", "supplier software evidence paragraph"]);

        try
        {
            using var service = new KnowledgeWorkbenchService(root);
            await service.ImportFileAsync(source, CancellationToken.None);

            var hits = await service.SearchAsync(
                "supplier software evidence",
                KnowledgeSearchMode.Fts5,
                10,
                CancellationToken.None);

            var hit = Assert.Single(hits);
            Assert.Equal(Path.GetFullPath(source), hit.SourceUri);
            Assert.Equal("paragraph=2", hit.Locator);
            Assert.Contains("supplier software evidence", hit.Excerpt, StringComparison.OrdinalIgnoreCase);
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    [Fact]
    public async Task Image_only_pdf_is_rejected_without_fake_ocr()
    {
        var root = NewTempRoot();
        var source = Path.Combine(root, "scan.pdf");
        await File.WriteAllBytesAsync(source, BuildPdf([string.Empty]), CancellationToken.None);

        try
        {
            using var service = new KnowledgeWorkbenchService(root);
            var error = await Assert.ThrowsAsync<InvalidDataException>(() =>
                service.ImportFileAsync(source, CancellationToken.None));

            Assert.Contains("OCR", error.Message, StringComparison.OrdinalIgnoreCase);
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    private static byte[] BuildPdf(IReadOnlyList<string> pageTexts)
    {
        if (pageTexts.Count == 0) throw new ArgumentException("At least one page is required.", nameof(pageTexts));

        var pageObjectStart = 3;
        var fontObject = pageObjectStart + pageTexts.Count;
        var contentObjectStart = fontObject + 1;
        var maxObject = contentObjectStart + pageTexts.Count - 1;
        var objects = new Dictionary<int, string>();

        objects[1] = "<< /Type /Catalog /Pages 2 0 R >>";
        var kids = string.Join(' ', Enumerable.Range(0, pageTexts.Count).Select(i => $"{pageObjectStart + i} 0 R"));
        objects[2] = $"<< /Type /Pages /Kids [{kids}] /Count {pageTexts.Count} >>";
        objects[fontObject] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>";

        for (var i = 0; i < pageTexts.Count; i++)
        {
            var pageObject = pageObjectStart + i;
            var contentObject = contentObjectStart + i;
            objects[pageObject] =
                $"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {fontObject} 0 R >> >> /Contents {contentObject} 0 R >>";

            var escaped = pageTexts[i]
                .Replace("\\", "\\\\", StringComparison.Ordinal)
                .Replace("(", "\\(", StringComparison.Ordinal)
                .Replace(")", "\\)", StringComparison.Ordinal);
            var stream = $"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET";
            objects[contentObject] = $"<< /Length {Encoding.ASCII.GetByteCount(stream)} >>\nstream\n{stream}\nendstream";
        }

        using var output = new MemoryStream();
        WriteAscii(output, "%PDF-1.4\n");
        var offsets = new long[maxObject + 1];
        for (var objectNumber = 1; objectNumber <= maxObject; objectNumber++)
        {
            offsets[objectNumber] = output.Position;
            WriteAscii(output, $"{objectNumber} 0 obj\n{objects[objectNumber]}\nendobj\n");
        }

        var xrefOffset = output.Position;
        WriteAscii(output, $"xref\n0 {maxObject + 1}\n");
        WriteAscii(output, "0000000000 65535 f \n");
        for (var objectNumber = 1; objectNumber <= maxObject; objectNumber++)
            WriteAscii(output, $"{offsets[objectNumber]:D10} 00000 n \n");
        WriteAscii(output, $"trailer\n<< /Size {maxObject + 1} /Root 1 0 R >>\nstartxref\n{xrefOffset}\n%%EOF\n");
        return output.ToArray();
    }

    private static void WriteDocx(string path, IReadOnlyList<string> paragraphs)
    {
        using var archive = ZipFile.Open(path, ZipArchiveMode.Create);
        WriteZipText(archive, "[Content_Types].xml", """
            <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
              <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
              <Default Extension="xml" ContentType="application/xml"/>
              <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
            </Types>
            """);
        WriteZipText(archive, "_rels/.rels", """
            <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
            </Relationships>
            """);

        XNamespace w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
        var body = new XElement(w + "body",
            paragraphs.Select(text =>
                new XElement(w + "p",
                    new XElement(w + "r",
                        new XElement(w + "t", text)))));
        var document = new XDocument(
            new XDeclaration("1.0", "UTF-8", "yes"),
            new XElement(w + "document", body));
        WriteZipText(archive, "word/document.xml", document.ToString(SaveOptions.DisableFormatting));
    }

    private static void WriteZipText(ZipArchive archive, string name, string text)
    {
        var entry = archive.CreateEntry(name, CompressionLevel.Fastest);
        using var writer = new StreamWriter(entry.Open(), new UTF8Encoding(false));
        writer.Write(text.Trim());
    }

    private static void WriteAscii(Stream stream, string text)
    {
        var bytes = Encoding.ASCII.GetBytes(text);
        stream.Write(bytes, 0, bytes.Length);
    }

    private static string NewTempRoot()
    {
        var root = Path.Combine(Path.GetTempPath(), "mllm-document-import", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        return root;
    }
}
