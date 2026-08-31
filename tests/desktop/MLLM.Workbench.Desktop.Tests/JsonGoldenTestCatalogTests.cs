using System.IO;
using System.Text;
using MLLM.Workbench.Desktop.Services.Conversation;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class JsonGoldenTestCatalogTests
{
    [Fact]
    public async Task Missing_catalog_loads_empty_then_upsert_round_trips_every_field_after_reopen()
    {
        var root = CreateRoot();
        var time = new MutableTimeProvider(DateTimeOffset.Parse("2026-09-01T01:00:00+08:00"));
        try
        {
            var catalog = new JsonGoldenTestCatalog(root, time);
            Assert.Empty(await catalog.LoadAsync(CancellationToken.None));

            var saved = await catalog.UpsertAsync(Case("case-1", "Beta"), CancellationToken.None);
            var reopened = new JsonGoldenTestCatalog(root, time);
            var loaded = Assert.Single(await reopened.LoadAsync(CancellationToken.None));

            Assert.Equal(saved.Id, loaded.Id);
            Assert.Equal(saved.Name, loaded.Name);
            Assert.Equal(saved.SystemPrompt, loaded.SystemPrompt);
            Assert.Equal(saved.UserPrompt, loaded.UserPrompt);
            Assert.Equal(saved.Temperature, loaded.Temperature);
            Assert.Equal(saved.MaxOutputTokens, loaded.MaxOutputTokens);
            Assert.Equal(saved.UseKnowledge, loaded.UseKnowledge);
            Assert.Equal(saved.MustContain, loaded.MustContain);
            Assert.Equal(saved.MustNotContain, loaded.MustNotContain);
            Assert.Equal(saved.MaximumTotalLatencyMilliseconds, loaded.MaximumTotalLatencyMilliseconds);
            Assert.Equal(saved.CreatedAt, loaded.CreatedAt);
            Assert.Equal(saved.UpdatedAt, loaded.UpdatedAt);
            Assert.Equal("case-1", loaded.Id);
            Assert.Equal("Base system", loaded.SystemPrompt);
            Assert.Equal("User prompt case-1", loaded.UserPrompt);
            Assert.Equal(0.2, loaded.Temperature, 3);
            Assert.Equal(512, loaded.MaxOutputTokens);
            Assert.True(loaded.UseKnowledge);
            Assert.Equal(["required"], loaded.MustContain);
            Assert.Equal(["forbidden"], loaded.MustNotContain);
            Assert.Equal(2500, loaded.MaximumTotalLatencyMilliseconds);
            Assert.Equal(time.GetUtcNow(), loaded.CreatedAt);
            Assert.Equal(time.GetUtcNow(), loaded.UpdatedAt);
        }
        finally
        {
            TryDelete(root);
        }
    }

    [Fact]
    public async Task Update_preserves_created_time_delete_is_exact_and_load_order_is_name_then_id()
    {
        var root = CreateRoot();
        var time = new MutableTimeProvider(DateTimeOffset.Parse("2026-09-01T01:00:00+08:00"));
        try
        {
            var catalog = new JsonGoldenTestCatalog(root, time);
            var beta = await catalog.UpsertAsync(Case("case-b", "Beta"), CancellationToken.None);
            await catalog.UpsertAsync(Case("case-z", "Alpha"), CancellationToken.None);
            await catalog.UpsertAsync(Case("case-a", "Alpha"), CancellationToken.None);
            time.UtcNow = time.UtcNow.AddMinutes(5);

            var updated = await catalog.UpsertAsync(Case("case-b", "Beta updated"), CancellationToken.None);
            var ordered = await catalog.LoadAsync(CancellationToken.None);

            Assert.Equal(beta.CreatedAt, updated.CreatedAt);
            Assert.Equal(time.GetUtcNow(), updated.UpdatedAt);
            Assert.Equal(["case-a", "case-z", "case-b"], ordered.Select(item => item.Id).ToArray());

            await catalog.DeleteAsync("case-z", CancellationToken.None);
            Assert.Equal(["case-a", "case-b"], (await catalog.LoadAsync(CancellationToken.None)).Select(item => item.Id).ToArray());
        }
        finally
        {
            TryDelete(root);
        }
    }

    [Fact]
    public async Task Corrupt_catalog_is_preserved_and_reported_instead_of_replaced()
    {
        var root = CreateRoot();
        try
        {
            var path = CatalogPath(root);
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            var corrupt = Encoding.UTF8.GetBytes("{this is not json");
            await File.WriteAllBytesAsync(path, corrupt);
            var catalog = new JsonGoldenTestCatalog(root);

            var error = await Assert.ThrowsAsync<GoldenCatalogException>(
                () => catalog.LoadAsync(CancellationToken.None));

            Assert.Equal("GOLDEN_CATALOG_CORRUPT", error.Code);
            Assert.Contains(path, error.Message, StringComparison.OrdinalIgnoreCase);
            Assert.Equal(corrupt, await File.ReadAllBytesAsync(path));
        }
        finally
        {
            TryDelete(root);
        }
    }

    [Fact]
    public async Task Failed_atomic_replace_keeps_prior_catalog_and_removes_temporary_sibling()
    {
        var root = CreateRoot();
        try
        {
            var catalog = new JsonGoldenTestCatalog(root);
            await catalog.UpsertAsync(Case("case-1", "Original"), CancellationToken.None);
            var path = CatalogPath(root);
            var before = await File.ReadAllBytesAsync(path);

            await using (var locked = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                var error = await Record.ExceptionAsync(
                    () => catalog.UpsertAsync(Case("case-2", "New"), CancellationToken.None));
                Assert.True(
                    error is IOException or UnauthorizedAccessException,
                    $"Expected a file-lock failure, got {error?.GetType().FullName ?? "no exception"}.");
            }

            Assert.Equal(before, await File.ReadAllBytesAsync(path));
            Assert.False(File.Exists(path + ".tmp"));
            Assert.Equal("case-1", Assert.Single(await catalog.LoadAsync(CancellationToken.None)).Id);
        }
        finally
        {
            TryDelete(root);
        }
    }

    private static GoldenTestCase Case(string id, string name) =>
        new(
            id,
            name,
            "Base system",
            "User prompt " + id,
            0.2,
            512,
            true,
            ["required"],
            ["forbidden"],
            2500,
            default,
            default);

    private static string CreateRoot()
    {
        var path = Path.Combine(Path.GetTempPath(), "mllm-golden-tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(path);
        return path;
    }

    private static string CatalogPath(string root) => Path.Combine(root, "conversation", "golden-tests.json");

    private static void TryDelete(string root)
    {
        try { Directory.Delete(root, recursive: true); } catch { }
    }

    private sealed class MutableTimeProvider(DateTimeOffset utcNow) : TimeProvider
    {
        public DateTimeOffset UtcNow { get; set; } = utcNow;
        public override DateTimeOffset GetUtcNow() => UtcNow;
    }
}
