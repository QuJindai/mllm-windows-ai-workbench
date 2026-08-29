using System.Security.Cryptography;
using System.Text;
using Microsoft.Data.Sqlite;

namespace MLLM.Workbench.Knowledge;

public sealed class KnowledgeStore : IAsyncDisposable
{
    private readonly string _databasePath;
    private readonly string _connectionString;
    private readonly SemaphoreSlim _writeGate = new(1, 1);
    private bool _initialized;
    private bool _disposed;

    public KnowledgeStore(KnowledgeStoreOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);
        if (string.IsNullOrWhiteSpace(options.DatabasePath))
            throw new ArgumentException("Knowledge database path is required.", nameof(options));

        _databasePath = Path.GetFullPath(options.DatabasePath);
        _connectionString = new SqliteConnectionStringBuilder
        {
            DataSource = _databasePath,
            Mode = SqliteOpenMode.ReadWriteCreate,
            Cache = SqliteCacheMode.Shared,
            Pooling = false
        }.ToString();
    }

    public async Task InitializeAsync(CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        var directory = Path.GetDirectoryName(_databasePath);
        if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);

        await using var connection = await OpenConnectionAsync(cancellationToken).ConfigureAwait(false);
        await ExecuteAsync(connection, null, "PRAGMA journal_mode=WAL;", cancellationToken).ConfigureAwait(false);
        await ExecuteAsync(connection, null, "PRAGMA synchronous=NORMAL;", cancellationToken).ConfigureAwait(false);

        const string schema = """
            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY NOT NULL,
                source_uri TEXT NOT NULL,
                title TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY NOT NULL,
                document_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                content TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                FOREIGN KEY(document_id) REFERENCES documents(document_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS ix_chunks_document_ordinal
                ON chunks(document_id, ordinal);

            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
                USING fts5(chunk_id UNINDEXED, content, tokenize='trigram');
            """;

        await ExecuteAsync(connection, null, schema, cancellationToken).ConfigureAwait(false);
        _initialized = true;
    }

    public async Task<KnowledgeStoreHealth> GetHealthAsync(CancellationToken cancellationToken)
    {
        EnsureReady();
        await using var connection = await OpenConnectionAsync(cancellationToken).ConfigureAwait(false);

        await using var versionCommand = connection.CreateCommand();
        versionCommand.CommandText = "SELECT sqlite_version();";
        var version = Convert.ToString(await versionCommand.ExecuteScalarAsync(cancellationToken).ConfigureAwait(false)) ?? string.Empty;

        await using var ftsCommand = connection.CreateCommand();
        ftsCommand.CommandText = "SELECT sql FROM sqlite_master WHERE type='table' AND name='chunks_fts';";
        var ftsSql = Convert.ToString(await ftsCommand.ExecuteScalarAsync(cancellationToken).ConfigureAwait(false));
        var ftsReady = !string.IsNullOrWhiteSpace(ftsSql) && ftsSql.Contains("fts5", StringComparison.OrdinalIgnoreCase);

        return new KnowledgeStoreHealth(
            DatabaseReady: File.Exists(_databasePath),
            Fts5Ready: ftsReady,
            SQLiteVersion: version,
            DatabasePath: _databasePath);
    }

    public async Task UpsertDocumentAsync(KnowledgeDocument document, CancellationToken cancellationToken)
    {
        EnsureReady();
        ValidateDocument(document);

        await _writeGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await using var connection = await OpenConnectionAsync(cancellationToken).ConfigureAwait(false);
            using var transaction = connection.BeginTransaction();

            await using (var removeFts = connection.CreateCommand())
            {
                removeFts.Transaction = transaction;
                removeFts.CommandText = """
                    DELETE FROM chunks_fts
                    WHERE chunk_id IN (SELECT chunk_id FROM chunks WHERE document_id = $documentId);
                    """;
                removeFts.Parameters.AddWithValue("$documentId", document.DocumentId);
                await removeFts.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
            }

            await using (var removeChunks = connection.CreateCommand())
            {
                removeChunks.Transaction = transaction;
                removeChunks.CommandText = "DELETE FROM chunks WHERE document_id = $documentId;";
                removeChunks.Parameters.AddWithValue("$documentId", document.DocumentId);
                await removeChunks.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
            }

            await using (var upsertDocument = connection.CreateCommand())
            {
                upsertDocument.Transaction = transaction;
                upsertDocument.CommandText = """
                    INSERT INTO documents(document_id, source_uri, title, content_sha256, updated_at_utc)
                    VALUES($documentId, $sourceUri, $title, $contentSha256, $updatedAtUtc)
                    ON CONFLICT(document_id) DO UPDATE SET
                        source_uri=excluded.source_uri,
                        title=excluded.title,
                        content_sha256=excluded.content_sha256,
                        updated_at_utc=excluded.updated_at_utc;
                    """;
                upsertDocument.Parameters.AddWithValue("$documentId", document.DocumentId);
                upsertDocument.Parameters.AddWithValue("$sourceUri", document.SourceUri);
                upsertDocument.Parameters.AddWithValue("$title", document.Title);
                upsertDocument.Parameters.AddWithValue("$contentSha256", HashDocument(document));
                upsertDocument.Parameters.AddWithValue("$updatedAtUtc", DateTimeOffset.UtcNow.ToString("O"));
                await upsertDocument.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
            }

            foreach (var chunk in document.Chunks.OrderBy(x => x.Ordinal))
            {
                await using (var insertChunk = connection.CreateCommand())
                {
                    insertChunk.Transaction = transaction;
                    insertChunk.CommandText = """
                        INSERT INTO chunks(chunk_id, document_id, ordinal, content, content_sha256)
                        VALUES($chunkId, $documentId, $ordinal, $content, $contentSha256);
                        """;
                    insertChunk.Parameters.AddWithValue("$chunkId", chunk.ChunkId);
                    insertChunk.Parameters.AddWithValue("$documentId", document.DocumentId);
                    insertChunk.Parameters.AddWithValue("$ordinal", chunk.Ordinal);
                    insertChunk.Parameters.AddWithValue("$content", chunk.Content);
                    insertChunk.Parameters.AddWithValue("$contentSha256", HashText(chunk.Content));
                    await insertChunk.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
                }

                await using var insertFts = connection.CreateCommand();
                insertFts.Transaction = transaction;
                insertFts.CommandText = "INSERT INTO chunks_fts(chunk_id, content) VALUES($chunkId, $content);";
                insertFts.Parameters.AddWithValue("$chunkId", chunk.ChunkId);
                insertFts.Parameters.AddWithValue("$content", chunk.Content);
                await insertFts.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
            }

            transaction.Commit();
        }
        finally
        {
            _writeGate.Release();
        }
    }

    public async Task<IReadOnlyList<KnowledgeSearchHit>> SearchFtsAsync(
        string query,
        int limit,
        CancellationToken cancellationToken)
    {
        EnsureReady();
        if (string.IsNullOrWhiteSpace(query)) return Array.Empty<KnowledgeSearchHit>();
        if (limit < 1 || limit > 100) throw new ArgumentOutOfRangeException(nameof(limit));

        await using var connection = await OpenConnectionAsync(cancellationToken).ConfigureAwait(false);
        await using var command = connection.CreateCommand();
        command.CommandText = """
            SELECT d.document_id,
                   c.chunk_id,
                   d.source_uri,
                   d.title,
                   c.ordinal,
                   c.content,
                   bm25(chunks_fts) AS lexical_rank
            FROM chunks_fts
            JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id
            JOIN documents d ON d.document_id = c.document_id
            WHERE chunks_fts MATCH $query
            ORDER BY lexical_rank ASC, c.ordinal ASC, c.chunk_id ASC
            LIMIT $limit;
            """;
        command.Parameters.AddWithValue("$query", ToMatchPhrase(query));
        command.Parameters.AddWithValue("$limit", limit);

        var hits = new List<KnowledgeSearchHit>();
        await using var reader = await command.ExecuteReaderAsync(cancellationToken).ConfigureAwait(false);
        while (await reader.ReadAsync(cancellationToken).ConfigureAwait(false))
        {
            var rank = reader.GetDouble(6);
            hits.Add(new KnowledgeSearchHit(
                DocumentId: reader.GetString(0),
                ChunkId: reader.GetString(1),
                SourceUri: reader.GetString(2),
                Title: reader.GetString(3),
                Ordinal: reader.GetInt32(4),
                Excerpt: reader.GetString(5),
                Score: 1d / (1d + Math.Abs(rank))));
        }

        return hits;
    }

    public ValueTask DisposeAsync()
    {
        if (_disposed) return ValueTask.CompletedTask;
        _disposed = true;
        _writeGate.Dispose();
        return ValueTask.CompletedTask;
    }

    private async Task<SqliteConnection> OpenConnectionAsync(CancellationToken cancellationToken)
    {
        var connection = new SqliteConnection(_connectionString);
        try
        {
            await connection.OpenAsync(cancellationToken).ConfigureAwait(false);
            await ExecuteAsync(connection, null, "PRAGMA foreign_keys=ON;", cancellationToken).ConfigureAwait(false);
            return connection;
        }
        catch
        {
            await connection.DisposeAsync().ConfigureAwait(false);
            throw;
        }
    }

    private static async Task ExecuteAsync(
        SqliteConnection connection,
        SqliteTransaction? transaction,
        string sql,
        CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = sql;
        await command.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
    }

    private static void ValidateDocument(KnowledgeDocument document)
    {
        ArgumentNullException.ThrowIfNull(document);
        if (string.IsNullOrWhiteSpace(document.DocumentId)) throw new ArgumentException("Document id is required.", nameof(document));
        if (string.IsNullOrWhiteSpace(document.SourceUri)) throw new ArgumentException("Source URI is required.", nameof(document));
        if (string.IsNullOrWhiteSpace(document.Title)) throw new ArgumentException("Document title is required.", nameof(document));
        if (document.Chunks is null || document.Chunks.Count == 0) throw new ArgumentException("At least one chunk is required.", nameof(document));

        var chunkIds = new HashSet<string>(StringComparer.Ordinal);
        foreach (var chunk in document.Chunks)
        {
            if (string.IsNullOrWhiteSpace(chunk.ChunkId)) throw new ArgumentException("Chunk id is required.", nameof(document));
            if (chunk.Ordinal < 0) throw new ArgumentException("Chunk ordinal cannot be negative.", nameof(document));
            if (string.IsNullOrWhiteSpace(chunk.Content)) throw new ArgumentException("Chunk content is required.", nameof(document));
            if (!chunkIds.Add(chunk.ChunkId)) throw new ArgumentException("Chunk ids must be unique within a document.", nameof(document));
        }
    }

    private static string HashDocument(KnowledgeDocument document)
    {
        var builder = new StringBuilder();
        builder.Append(document.SourceUri).Append('\n').Append(document.Title).Append('\n');
        foreach (var chunk in document.Chunks.OrderBy(x => x.Ordinal))
            builder.Append(chunk.ChunkId).Append('|').Append(chunk.Ordinal).Append('|').Append(chunk.Content).Append('\n');
        return HashText(builder.ToString());
    }

    private static string HashText(string text) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(text))).ToLowerInvariant();

    private static string ToMatchPhrase(string query) =>
        "\"" + query.Trim().Replace("\"", "\"\"", StringComparison.Ordinal) + "\"";

    private void EnsureReady()
    {
        ThrowIfDisposed();
        if (!_initialized) throw new InvalidOperationException("Knowledge store has not been initialized.");
    }

    private void ThrowIfDisposed()
    {
        if (_disposed) throw new ObjectDisposedException(nameof(KnowledgeStore));
    }
}
