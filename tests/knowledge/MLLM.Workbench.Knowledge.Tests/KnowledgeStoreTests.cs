using MLLM.Workbench.Knowledge;
using Xunit;

namespace MLLM.Workbench.Knowledge.Tests;

public sealed class KnowledgeStoreTests
{
    [Fact]
    public async Task Initialize_reports_real_fts5_health()
    {
        await using var fixture = new TempKnowledgeStore();
        await fixture.Store.InitializeAsync(CancellationToken.None);

        var health = await fixture.Store.GetHealthAsync(CancellationToken.None);

        Assert.True(health.DatabaseReady);
        Assert.True(health.Fts5Ready);
        Assert.False(string.IsNullOrWhiteSpace(health.SQLiteVersion));
        Assert.Equal(fixture.DatabasePath, health.DatabasePath);
        Assert.True(File.Exists(fixture.DatabasePath));
    }

    [Fact]
    public async Task Fts_search_returns_chinese_and_english_hits_with_exact_evidence()
    {
        await using var fixture = new TempKnowledgeStore();
        await fixture.Store.InitializeAsync(CancellationToken.None);
        await fixture.Store.UpsertDocumentAsync(
            new KnowledgeDocument(
                "doc-standard",
                @"C:\Knowledge\整车软件制造管控.md",
                "整车软件制造管控",
                [
                    new KnowledgeChunk("chunk-cn", 0, "整车软件制造管控要求生产过程中的软件版本可追溯，并保留完整证据链。"),
                    new KnowledgeChunk("chunk-en", 1, "Hybrid retrieval combines lexical FTS5 evidence with semantic vector recall.")
                ]),
            CancellationToken.None);

        var cn = await fixture.Store.SearchFtsAsync("软件制造管控", 10, CancellationToken.None);
        var en = await fixture.Store.SearchFtsAsync("semantic vector", 10, CancellationToken.None);

        var cnHit = Assert.Single(cn);
        Assert.Equal("doc-standard", cnHit.DocumentId);
        Assert.Equal("chunk-cn", cnHit.ChunkId);
        Assert.Equal(@"C:\Knowledge\整车软件制造管控.md", cnHit.SourceUri);
        Assert.Equal("整车软件制造管控", cnHit.Title);
        Assert.Equal(0, cnHit.Ordinal);
        Assert.Contains("软件制造管控", cnHit.Excerpt, StringComparison.Ordinal);
        Assert.True(cnHit.Score > 0);

        var enHit = Assert.Single(en);
        Assert.Equal("chunk-en", enHit.ChunkId);
        Assert.Contains("semantic vector", enHit.Excerpt, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Reimport_replaces_only_target_document_index_rows()
    {
        await using var fixture = new TempKnowledgeStore();
        await fixture.Store.InitializeAsync(CancellationToken.None);
        await fixture.Store.UpsertDocumentAsync(Doc("doc-a", "a.md", "旧版工艺内容需要被替换"), CancellationToken.None);
        await fixture.Store.UpsertDocumentAsync(Doc("doc-b", "b.md", "稳定基线内容必须保留"), CancellationToken.None);

        await fixture.Store.UpsertDocumentAsync(Doc("doc-a", "a.md", "新版工艺内容已经生效"), CancellationToken.None);

        Assert.Empty(await fixture.Store.SearchFtsAsync("旧版工艺内容", 10, CancellationToken.None));
        Assert.Single(await fixture.Store.SearchFtsAsync("新版工艺内容", 10, CancellationToken.None));
        var untouched = Assert.Single(await fixture.Store.SearchFtsAsync("稳定基线内容", 10, CancellationToken.None));
        Assert.Equal("doc-b", untouched.DocumentId);
    }

    [Fact]
    public async Task Reopen_preserves_index_and_evidence()
    {
        var root = Path.Combine(Path.GetTempPath(), "mllm-knowledge-tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var databasePath = Path.Combine(root, "knowledge.db");
        try
        {
            await using (var first = new KnowledgeStore(new KnowledgeStoreOptions(databasePath)))
            {
                await first.InitializeAsync(CancellationToken.None);
                await first.UpsertDocumentAsync(
                    Doc("doc-persist", @"C:\Knowledge\persist.md", "重启持久化检索证据仍然存在"),
                    CancellationToken.None);
            }

            await using (var reopened = new KnowledgeStore(new KnowledgeStoreOptions(databasePath)))
            {
                await reopened.InitializeAsync(CancellationToken.None);
                var hits = await reopened.SearchFtsAsync("持久化检索证据", 10, CancellationToken.None);
                var hit = Assert.Single(hits);
                Assert.Equal("doc-persist", hit.DocumentId);
                Assert.Equal("doc-persist-chunk", hit.ChunkId);
                Assert.Equal(@"C:\Knowledge\persist.md", hit.SourceUri);
            }
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    private static KnowledgeDocument Doc(string id, string source, string content) =>
        new(id, source, id, [new KnowledgeChunk(id + "-chunk", 0, content)]);

    private sealed class TempKnowledgeStore : IAsyncDisposable
    {
        private readonly string _root;

        public TempKnowledgeStore()
        {
            _root = Path.Combine(Path.GetTempPath(), "mllm-knowledge-tests", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_root);
            DatabasePath = Path.Combine(_root, "knowledge.db");
            Store = new KnowledgeStore(new KnowledgeStoreOptions(DatabasePath));
        }

        public string DatabasePath { get; }
        public KnowledgeStore Store { get; }

        public async ValueTask DisposeAsync()
        {
            await Store.DisposeAsync();
            try { Directory.Delete(_root, true); } catch { }
        }
    }
}
