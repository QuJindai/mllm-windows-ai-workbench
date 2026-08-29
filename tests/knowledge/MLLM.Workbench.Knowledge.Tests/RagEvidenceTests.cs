using MLLM.Workbench.Knowledge;
using Xunit;

namespace MLLM.Workbench.Knowledge.Tests;

public sealed class RagEvidenceTests
{
    [Fact]
    public void Builder_assigns_stable_citation_ids_and_preserves_exact_evidence()
    {
        var hits = new[]
        {
            Hit("doc-a", "a1", "a.md", "A", 0, "第一条原始证据", 0.9),
            Hit("doc-b", "b1", "b.md", "B", 2, "Second exact evidence", 0.8)
        };

        var context = RagContextBuilder.Build(hits, maxEvidence: 8, maxCharacters: 2000);

        Assert.Equal(2, context.Evidence.Count);
        Assert.Equal("K1", context.Evidence[0].CitationId);
        Assert.Equal("K2", context.Evidence[1].CitationId);
        Assert.Equal("第一条原始证据", context.Evidence[0].Excerpt);
        Assert.Equal("a.md", context.Evidence[0].SourceUri);
        Assert.Equal("a1", context.Evidence[0].ChunkId);
        Assert.Contains("[K1]", context.ContextText, StringComparison.Ordinal);
        Assert.Contains("第一条原始证据", context.ContextText, StringComparison.Ordinal);
        Assert.Contains("[K2]", context.ContextText, StringComparison.Ordinal);
        Assert.Contains("Second exact evidence", context.ContextText, StringComparison.Ordinal);
    }

    [Fact]
    public void Builder_deduplicates_same_document_chunk_without_losing_rank_order()
    {
        var hits = new[]
        {
            Hit("doc-a", "same", "a.md", "A", 0, "same evidence", 0.9),
            Hit("doc-a", "same", "a.md", "A", 0, "same evidence", 0.8),
            Hit("doc-b", "other", "b.md", "B", 0, "other evidence", 0.7)
        };

        var context = RagContextBuilder.Build(hits, 8, 2000);

        Assert.Equal(2, context.Evidence.Count);
        Assert.Equal("same", context.Evidence[0].ChunkId);
        Assert.Equal("other", context.Evidence[1].ChunkId);
        Assert.Equal(["K1", "K2"], context.Evidence.Select(x => x.CitationId).ToArray());
    }

    [Fact]
    public void Builder_respects_character_budget_without_truncating_evidence_text()
    {
        var hits = new[]
        {
            Hit("doc-a", "a1", "a.md", "A", 0, "short evidence", 0.9),
            Hit("doc-b", "b1", "b.md", "B", 0, new string('x', 1000), 0.8)
        };

        var context = RagContextBuilder.Build(hits, 8, 180);

        var evidence = Assert.Single(context.Evidence);
        Assert.Equal("short evidence", evidence.Excerpt);
        Assert.DoesNotContain(new string('x', 50), context.ContextText, StringComparison.Ordinal);
        Assert.True(context.ContextText.Length <= 180);
    }

    [Fact]
    public void Builder_rejects_detached_or_empty_evidence()
    {
        var detached = Hit("doc-a", "a1", "", "A", 0, "evidence", 0.9);
        var empty = Hit("doc-b", "b1", "b.md", "B", 0, "", 0.8);

        Assert.Throws<ArgumentException>(() => RagContextBuilder.Build([detached], 8, 2000));
        Assert.Throws<ArgumentException>(() => RagContextBuilder.Build([empty], 8, 2000));
    }

    private static KnowledgeSearchHit Hit(
        string documentId,
        string chunkId,
        string sourceUri,
        string title,
        int ordinal,
        string excerpt,
        double score) =>
        new(documentId, chunkId, sourceUri, title, ordinal, excerpt, score);
}
