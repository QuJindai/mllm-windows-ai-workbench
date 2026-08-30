using Microsoft.Data.Sqlite;
using Xunit;

namespace MLLM.Workbench.Knowledge.Tests;

public sealed class KnowledgeLocatorTests
{
    [Fact]
    public async Task Fts_and_rag_preserve_source_locator_from_stable_chunk_id()
    {
        var root = NewTempRoot();
        var databasePath = Path.Combine(root, "knowledge.db");
        try
        {
            await using var store = new KnowledgeStore(new KnowledgeStoreOptions(databasePath));
            await store.InitializeAsync(CancellationToken.None);
            var chunkId = KnowledgeChunkLocator.CreateChunkId("doc-pdf", "page=2", 0);
            await store.UpsertDocumentAsync(
                new KnowledgeDocument(
                    "doc-pdf",
                    @"C:\evidence\manual.pdf",
                    "manual",
                    [new KnowledgeChunk(chunkId, 0, "vehicle software traceability evidence")]),
                CancellationToken.None);

            var hits = await store.SearchFtsAsync("software traceability", 10, CancellationToken.None);
            var hit = Assert.Single(hits);
            Assert.Equal("page=2", hit.Locator);

            var rag = RagContextBuilder.Build(hits);
            var evidence = Assert.Single(rag.Evidence);
            Assert.Equal("page=2", evidence.Locator);
            Assert.Contains("locator=page=2", rag.ContextText, StringComparison.Ordinal);
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    [Fact]
    public async Task Existing_database_without_locator_schema_remains_compatible_and_keeps_legacy_rows()
    {
        var root = NewTempRoot();
        var databasePath = Path.Combine(root, "knowledge.db");
        try
        {
            await using (var connection = new SqliteConnection($"Data Source={databasePath}"))
            {
                await connection.OpenAsync(CancellationToken.None);
                await using var command = connection.CreateCommand();
                command.CommandText = """
                    CREATE TABLE documents (
                        document_id TEXT PRIMARY KEY NOT NULL,
                        source_uri TEXT NOT NULL,
                        title TEXT NOT NULL,
                        content_sha256 TEXT NOT NULL,
                        updated_at_utc TEXT NOT NULL
                    );
                    CREATE TABLE chunks (
                        chunk_id TEXT PRIMARY KEY NOT NULL,
                        document_id TEXT NOT NULL,
                        ordinal INTEGER NOT NULL,
                        content TEXT NOT NULL,
                        content_sha256 TEXT NOT NULL
                    );
                    INSERT INTO documents(document_id, source_uri, title, content_sha256, updated_at_utc)
                    VALUES('legacy', 'legacy.txt', 'legacy', 'hash', '2026-01-01T00:00:00Z');
                    INSERT INTO chunks(chunk_id, document_id, ordinal, content, content_sha256)
                    VALUES('legacy:000000', 'legacy', 0, 'legacy searchable evidence', 'hash');
                    """;
                await command.ExecuteNonQueryAsync(CancellationToken.None);
            }

            await using var store = new KnowledgeStore(new KnowledgeStoreOptions(databasePath));
            await store.InitializeAsync(CancellationToken.None);
            var chunkId = KnowledgeChunkLocator.CreateChunkId("new", "page=4", 0);
            await store.UpsertDocumentAsync(
                new KnowledgeDocument(
                    "new",
                    "new.pdf",
                    "new",
                    [new KnowledgeChunk(chunkId, 0, "new locator evidence")]),
                CancellationToken.None);

            var hits = await store.SearchFtsAsync("locator evidence", 10, CancellationToken.None);
            Assert.Equal("page=4", Assert.Single(hits).Locator);

            await using var verify = new SqliteConnection($"Data Source={databasePath}");
            await verify.OpenAsync(CancellationToken.None);
            await using var count = verify.CreateCommand();
            count.CommandText = "SELECT COUNT(*) FROM chunks WHERE chunk_id = 'legacy:000000';";
            Assert.Equal(1L, Convert.ToInt64(await count.ExecuteScalarAsync(CancellationToken.None)));
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    private static string NewTempRoot()
    {
        var root = Path.Combine(Path.GetTempPath(), "mllm-knowledge-locator", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        return root;
    }
}
