using System.Text;

namespace MLLM.Workbench.Knowledge;

public sealed record RagEvidence(
    string CitationId,
    string DocumentId,
    string ChunkId,
    string SourceUri,
    string Title,
    int Ordinal,
    string Excerpt,
    double Score);

public sealed record RagContext(
    string ContextText,
    IReadOnlyList<RagEvidence> Evidence);

public static class RagContextBuilder
{
    public static RagContext Build(
        IReadOnlyList<KnowledgeSearchHit> hits,
        int maxEvidence = 8,
        int maxCharacters = 12_000)
    {
        ArgumentNullException.ThrowIfNull(hits);
        if (maxEvidence < 1 || maxEvidence > 100)
            throw new ArgumentOutOfRangeException(nameof(maxEvidence));
        if (maxCharacters < 1)
            throw new ArgumentOutOfRangeException(nameof(maxCharacters));

        foreach (var hit in hits) ValidateHit(hit);

        var evidence = new List<RagEvidence>(Math.Min(maxEvidence, hits.Count));
        var seen = new HashSet<EvidenceKey>();
        var context = new StringBuilder(Math.Min(maxCharacters, 4096));

        foreach (var hit in hits)
        {
            if (evidence.Count >= maxEvidence) break;

            var key = new EvidenceKey(hit.DocumentId, hit.ChunkId);
            if (!seen.Add(key)) continue;

            var citationId = $"K{evidence.Count + 1}";
            var block = BuildBlock(citationId, hit);
            if (context.Length + block.Length > maxCharacters) continue;

            context.Append(block);
            evidence.Add(new RagEvidence(
                CitationId: citationId,
                DocumentId: hit.DocumentId,
                ChunkId: hit.ChunkId,
                SourceUri: hit.SourceUri,
                Title: hit.Title,
                Ordinal: hit.Ordinal,
                Excerpt: hit.Excerpt,
                Score: hit.Score));
        }

        return new RagContext(context.ToString(), evidence);
    }

    private static string BuildBlock(string citationId, KnowledgeSearchHit hit)
    {
        var builder = new StringBuilder();
        builder.Append('[').Append(citationId).Append("] ")
            .Append(hit.Title)
            .Append(" | source=").Append(hit.SourceUri)
            .Append(" | chunk=").Append(hit.ChunkId)
            .Append(" | ordinal=").Append(hit.Ordinal)
            .AppendLine();
        builder.AppendLine(hit.Excerpt);
        builder.AppendLine();
        return builder.ToString();
    }

    private static void ValidateHit(KnowledgeSearchHit hit)
    {
        ArgumentNullException.ThrowIfNull(hit);
        if (string.IsNullOrWhiteSpace(hit.DocumentId))
            throw new ArgumentException("RAG evidence document id is required.", nameof(hit));
        if (string.IsNullOrWhiteSpace(hit.ChunkId))
            throw new ArgumentException("RAG evidence chunk id is required.", nameof(hit));
        if (string.IsNullOrWhiteSpace(hit.SourceUri))
            throw new ArgumentException("RAG evidence source URI is required.", nameof(hit));
        if (string.IsNullOrWhiteSpace(hit.Excerpt))
            throw new ArgumentException("RAG evidence excerpt is required.", nameof(hit));
    }

    private readonly record struct EvidenceKey(string DocumentId, string ChunkId);
}
