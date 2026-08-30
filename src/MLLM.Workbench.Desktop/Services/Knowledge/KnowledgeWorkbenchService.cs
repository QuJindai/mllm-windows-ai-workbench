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
    private readonly string? _embeddingConfigurationError;
    private readonly string _databasePath;
    private readonly SemaphoreSlim _initializeGate = new(1, 1);
    private bool _initialized;
    private bool _disposed;

    public KnowledgeWorkbenchService(
        string dataRoot,
        IEmbeddingProvider? embeddingProvider = null,
        string? embeddingConfigurationError = null)
    {
        if (string.IsNullOrWhiteSpace(dataRoot))
            throw new ArgumentException("Knowledge data root is required.", nameof(dataRoot));

        var fullRoot = Path.GetFullPath(dataRoot);
        _databasePath = Path.Combine(fullRoot, "knowledge", "knowledge.db");
        _embeddingProvider = embeddingProvider;
        _embeddingConfigurationError = string.IsNullOrWhiteSpace(embeddingConfigurationError)
            ? null
            : embeddingConfigurationError.Trim();
        _store = new KnowledgeStore(new KnowledgeStoreOptions(_databasePath));
    }

    public async Task<KnowledgeWorkspaceSnapshot> GetSnapshotAsync(CancellationToken cancellationToken)
    {
        await EnsureInitializedAsync(cancellationToken).ConfigureAwait(false);
        return await ReadSnapshotAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task ImportFileAsync(string path, CancellationToken cancellationToken)
    {
        await EnsureInitializedAsync(cancellationToken).ConfigureAwait(false);
        if (string.IsNullOrWhiteSpace(path))
            throw new ArgumentException("Knowledge source path is required.", nameof(path));

        var fullPath = Path.GetFullPath(path);
        if (!File.Exists(fullPath))
            throw new FileNotFoundException("Knowledge source file was not found.", fullPath);

        var sections = await KnowledgeSourceExtractor
            .ExtractAsync(fullPath, cancellationToken)
            .ConfigureAwait(false);

        var documentId = CreateDocumentId(fullPath);
        var chunks = CreateChunks(documentId, sections);
        var document = new KnowledgeDocument(
            DocumentId: documentId,
            SourceUri: fullPath,
            Title: Path.GetFileNameWithoutExtension(fullPath),
            Chunks: chunks);

        await _store.UpsertDocumentAsync(document, cancellationToken).ConfigureAwait(false);
        if (_embeddingProvider is not null)
            await _store.IndexEmbeddingsAsync(documentId, _embeddingProvider, cancellationToken).ConfigureAwait(false);
    }

    public async Task<KnowledgeWorkspaceSnapshot> BuildEmbeddingIndexAsync(
        IProgress<KnowledgeEmbeddingProgress>? progress,
        CancellationToken cancellationToken)
    {
        await EnsureInitializedAsync(cancellationToken).ConfigureAwait(false);
        if (_embeddingProvider is null)
            throw new InvalidOperationException(GetEmbeddingUnavailableMessage());

        var before = await _store
            .GetEmbeddingIndexStatusAsync(_embeddingProvider, cancellationToken)
            .ConfigureAwait(false);

        IProgress<EmbeddingIndexProgress>? storeProgress = null;
        if (progress is not null)
        {
            storeProgress = new InlineProgress<EmbeddingIndexProgress>(item =>
            {
                var completed = Math.Min(before.TotalChunks, before.IndexedChunks + item.CompletedChunks);
                progress.Report(new KnowledgeEmbeddingProgress(
                    Completed: completed,
                    Total: before.TotalChunks,
                    CurrentChunkId: item.ChunkId));
            });
        }

        await _store
            .IndexMissingEmbeddingsAsync(_embeddingProvider, storeProgress, cancellationToken)
            .ConfigureAwait(false);

        return await ReadSnapshotAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<KnowledgeSearchHit>> SearchAsync(
        string query,
        KnowledgeSearchMode mode,
        int limit,
        CancellationToken cancellationToken)
    {
        await EnsureInitializedAsync(cancellationToken).ConfigureAwait(false);

        switch (mode)
        {
            case KnowledgeSearchMode.Fts5:
                return await _store.SearchFtsAsync(query, limit, cancellationToken).ConfigureAwait(false);

            case KnowledgeSearchMode.Embedding:
                if (_embeddingProvider is null)
                    throw new InvalidOperationException(GetEmbeddingUnavailableMessage());
                return await _store
                    .SearchVectorAsync(query, _embeddingProvider, limit, cancellationToken)
                    .ConfigureAwait(false);

            case KnowledgeSearchMode.Hybrid:
                if (_embeddingProvider is null)
                    throw new InvalidOperationException(GetEmbeddingUnavailableMessage() + " Hybrid search is unavailable.");

                var status = await _store
                    .GetEmbeddingIndexStatusAsync(_embeddingProvider, cancellationToken)
                    .ConfigureAwait(false);
                if (status.PendingChunks > 0)
                {
                    throw new InvalidOperationException(
                        $"Embedding index is incomplete ({status.IndexedChunks}/{status.TotalChunks}); build or resume the vector index before Hybrid search.");
                }

                return await _store
                    .SearchHybridAsync(query, _embeddingProvider, limit, cancellationToken)
                    .ConfigureAwait(false);

            default:
                throw new ArgumentOutOfRangeException(nameof(mode), mode, "Unsupported knowledge search mode.");
        }
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _store.DisposeAsync().AsTask().GetAwaiter().GetResult();
        _initializeGate.Dispose();
    }

    private async Task<KnowledgeWorkspaceSnapshot> ReadSnapshotAsync(CancellationToken cancellationToken)
    {
        var health = await _store.GetHealthAsync(cancellationToken).ConfigureAwait(false);
        var indexStatus = _embeddingProvider is null
            ? new EmbeddingIndexStatus(0, 0)
            : await _store
                .GetEmbeddingIndexStatusAsync(_embeddingProvider, cancellationToken)
                .ConfigureAwait(false);

        return new KnowledgeWorkspaceSnapshot(
            DatabasePath: _databasePath,
            Fts5Ready: health.Fts5Ready,
            EmbeddingConfigured: _embeddingProvider is not null,
            EmbeddingProvider: _embeddingProvider?.ProviderId,
            EmbeddingModel: _embeddingProvider?.ModelId,
            EmbeddingConfigurationError: _embeddingConfigurationError,
            EmbeddingIndexedChunks: indexStatus.IndexedChunks,
            EmbeddingTotalChunks: indexStatus.TotalChunks);
    }

    private string GetEmbeddingUnavailableMessage() =>
        _embeddingConfigurationError is null
            ? "Embedding provider is not configured."
            : $"Embedding provider configuration is invalid: {_embeddingConfigurationError}";

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

    private static IReadOnlyList<KnowledgeChunk> CreateChunks(
        string documentId,
        IReadOnlyList<KnowledgeSourceSection> sections)
    {
        var chunks = new List<KnowledgeChunk>();

        foreach (var section in sections)
        {
            foreach (var content in CreateRawChunks(section.Text))
            {
                var ordinal = chunks.Count;
                var chunkId = string.IsNullOrWhiteSpace(section.Locator)
                    ? $"{documentId}:{ordinal:D6}"
                    : KnowledgeChunkLocator.CreateChunkId(documentId, section.Locator, ordinal);
                chunks.Add(new KnowledgeChunk(chunkId, ordinal, content));
            }
        }

        if (chunks.Count == 0)
            throw new InvalidDataException("Knowledge source produced no indexable text chunks.");

        return chunks;
    }

    private static IReadOnlyList<string> CreateRawChunks(string text)
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
        return rawChunks;
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

    private sealed class InlineProgress<T>(Action<T> report) : IProgress<T>
    {
        public void Report(T value) => report(value);
    }
}
