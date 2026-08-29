using System.IO;
using System.Security.Cryptography;
using System.Text;
using MLLM.Workbench.Knowledge;
using MLLM.Workbench.Knowledge.Embeddings;

namespace MLLM.Workbench.Desktop.Services.Knowledge;

public sealed class KnowledgeWorkbenchService : IKnowledgeWorkbenchService, IDisposable
{
    private const int TargetChunkCharacters = 1200;
    private const int ChunkOverlapCharacters = 120;

    private readonly KnowledgeStore _store;
    private readonly IEmbeddingProvider? _embeddingProvider;
    private readonly string _databasePath;
    private readonly SemaphoreSlim _initializeGate = new(1, 1);
    private bool _initialized;
    private bool _disposed;

    public KnowledgeWorkbenchService(string dataRoot, IEmbeddingProvider? embeddingProvider = null)
    {
        if (string.IsNullOrWhiteSpace(dataRoot))
            throw new ArgumentException("Knowledge data root is required.", nameof(dataRoot));

        var fullRoot = Path.GetFullPath(dataRoot);
        _databasePath = Path.Combine(fullRoot, "knowledge", "knowledge.db");
        _embeddingProvider = embeddingProvider;
        _store = new KnowledgeStore(new KnowledgeStoreOptions(_databasePath));
    }

    public async Task<KnowledgeWorkspaceSnapshot> GetSnapshotAsync(CancellationToken cancellationToken)
    {
        await EnsureInitializedAsync(cancellationToken).ConfigureAwait(false);
        var health = await _store.GetHealthAsync(cancellationToken).ConfigureAwait(false);

        return new KnowledgeWorkspaceSnapshot(
            DatabasePath: _databasePath,
            Fts5Ready: health.Fts5Ready,
            EmbeddingConfigured: _embeddingProvider is not null,
            EmbeddingProvider: _embeddingProvider?.ProviderId,
            EmbeddingModel: _embeddingProvider?.ModelId);
    }

    public async Task ImportFileAsync(string path, CancellationToken cancellationToken)
    {
        await EnsureInitializedAsync(cancellationToken).ConfigureAwait(false);
        if (string.IsNullOrWhiteSpace(path))
            throw new ArgumentException("Knowledge source path is required.", nameof(path));

        var fullPath = Path.GetFullPath(path);
        if (!File.Exists(fullPath))
            throw new FileNotFoundException("Knowledge source file was not found.", fullPath);

        var extension = Path.GetExtension(fullPath).ToLowerInvariant();
        if (extension is not ".md" and not ".markdown" and not ".txt")
            throw new NotSupportedException($"Knowledge import does not support '{extension}' yet. Supported formats: .md, .markdown, .txt.");

        var text = await File.ReadAllTextAsync(fullPath, Encoding.UTF8, cancellationToken).ConfigureAwait(false);
        if (string.IsNullOrWhiteSpace(text))
            throw new InvalidDataException("Knowledge source file is empty.");

        var documentId = CreateDocumentId(fullPath);
        var chunks = CreateChunks(documentId, text);
        var document = new KnowledgeDocument(
            DocumentId: documentId,
            SourceUri: fullPath,
            Title: Path.GetFileNameWithoutExtension(fullPath),
            Chunks: chunks);

        await _store.UpsertDocumentAsync(document, cancellationToken).ConfigureAwait(false);
        if (_embeddingProvider is not null)
            await _store.IndexEmbeddingsAsync(documentId, _embeddingProvider, cancellationToken).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<KnowledgeSearchHit>> SearchAsync(
        string query,
        KnowledgeSearchMode mode,
        int limit,
        CancellationToken cancellationToken)
    {
        await EnsureInitializedAsync(cancellationToken).ConfigureAwait(false);

        return mode switch
        {
            KnowledgeSearchMode.Fts5 =>
                await _store.SearchFtsAsync(query, limit, cancellationToken).ConfigureAwait(false),
            KnowledgeSearchMode.Embedding when _embeddingProvider is null =>
                throw new InvalidOperationException("Embedding provider is not configured."),
            KnowledgeSearchMode.Embedding =>
                await _store.SearchVectorAsync(query, _embeddingProvider!, limit, cancellationToken).ConfigureAwait(false),
            KnowledgeSearchMode.Hybrid when _embeddingProvider is null =>
                throw new InvalidOperationException("Embedding provider is not configured; Hybrid search is unavailable."),
            KnowledgeSearchMode.Hybrid =>
                await _store.SearchHybridAsync(query, _embeddingProvider!, limit, cancellationToken).ConfigureAwait(false),
            _ => throw new ArgumentOutOfRangeException(nameof(mode), mode, "Unsupported knowledge search mode.")
        };
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _store.DisposeAsync().AsTask().GetAwaiter().GetResult();
        _initializeGate.Dispose();
    }

    private async Task EnsureInitializedAsync(CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        if (_initialized) return;

        await _initializeGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            ThrowIfDisposed();
            if (_initialized) return;
            await _store.InitializeAsync(cancellationToken).ConfigureAwait(false);
            _initialized = true;
        }
        finally
        {
            _initializeGate.Release();
        }
    }

    private static string CreateDocumentId(string fullPath)
    {
        var normalized = Path.GetFullPath(fullPath).ToUpperInvariant();
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(normalized));
        return "doc-" + Convert.ToHexString(hash).ToLowerInvariant()[..32];
    }

    private static IReadOnlyList<KnowledgeChunk> CreateChunks(string documentId, string text)
    {
        var normalized = text.Replace("\r\n", "\n", StringComparison.Ordinal).Replace('\r', '\n');
        var paragraphs = normalized
            .Split(["\n\n"], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Where(static x => !string.IsNullOrWhiteSpace(x))
            .ToArray();

        var rawChunks = new List<string>();
        var current = new StringBuilder();

        foreach (var paragraph in paragraphs)
        {
            if (paragraph.Length > TargetChunkCharacters)
            {
                FlushCurrent(current, rawChunks);
                AddLongParagraph(paragraph, rawChunks);
                continue;
            }

            var separatorLength = current.Length == 0 ? 0 : 2;
            if (current.Length + separatorLength + paragraph.Length > TargetChunkCharacters)
                FlushCurrent(current, rawChunks);

            if (current.Length > 0) current.AppendLine().AppendLine();
            current.Append(paragraph);
        }

        FlushCurrent(current, rawChunks);
        if (rawChunks.Count == 0)
            throw new InvalidDataException("Knowledge source produced no indexable text chunks.");

        return rawChunks
            .Select((content, ordinal) => new KnowledgeChunk(
                ChunkId: $"{documentId}:{ordinal:D6}",
                Ordinal: ordinal,
                Content: content))
            .ToArray();
    }

    private static void AddLongParagraph(string paragraph, List<string> chunks)
    {
        var start = 0;
        while (start < paragraph.Length)
        {
            var length = Math.Min(TargetChunkCharacters, paragraph.Length - start);
            var chunk = paragraph.Substring(start, length).Trim();
            if (chunk.Length > 0) chunks.Add(chunk);
            if (start + length >= paragraph.Length) break;
            start += Math.Max(1, length - ChunkOverlapCharacters);
        }
    }

    private static void FlushCurrent(StringBuilder current, List<string> chunks)
    {
        if (current.Length == 0) return;
        var content = current.ToString().Trim();
        if (content.Length > 0) chunks.Add(content);
        current.Clear();
    }

    private void ThrowIfDisposed()
    {
        if (_disposed) throw new ObjectDisposedException(nameof(KnowledgeWorkbenchService));
    }
}
