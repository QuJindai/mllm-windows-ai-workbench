using MLLM.Workbench.Desktop.Pages.Knowledge;
using MLLM.Workbench.Desktop.Services.Knowledge;
using MLLM.Workbench.Knowledge;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class KnowledgePageViewModelTests
{
    [Fact]
    public async Task Refresh_exposes_real_fts_embedding_and_hybrid_state_without_fake_readiness()
    {
        var service = new FakeKnowledgeService
        {
            Snapshot = new KnowledgeWorkspaceSnapshot(
                @"C:\Data\knowledge\knowledge.db",
                Fts5Ready: true,
                EmbeddingConfigured: false,
                EmbeddingProvider: null,
                EmbeddingModel: null)
        };
        var vm = new KnowledgePageViewModel(service, new FakeEvidenceLauncher());

        await vm.RefreshAsync(CancellationToken.None);

        Assert.Equal("可用", vm.Fts5Status);
        Assert.Equal("未配置", vm.EmbeddingStatus);
        Assert.Equal("不可用", vm.HybridStatus);
        Assert.Equal(@"C:\Data\knowledge\knowledge.db", vm.DatabasePath);
        Assert.False(vm.CanHybridSearch);
        Assert.Null(vm.LastError);
    }

    [Fact]
    public async Task Import_and_fts_search_produce_ranked_results_and_rag_context()
    {
        var service = new FakeKnowledgeService
        {
            Snapshot = ReadyFtsOnly(),
            SearchResults =
            [
                new KnowledgeSearchHit(
                    "doc-a", "chunk-a", @"C:\Knowledge\standard.md", "标准",
                    0, "整车软件制造管控证据链", 0.95)
            ]
        };
        var vm = new KnowledgePageViewModel(service, new FakeEvidenceLauncher())
        {
            ImportPath = @"C:\Knowledge\standard.md",
            Query = "软件制造管控",
            SelectedSearchMode = KnowledgeSearchMode.Fts5
        };

        await vm.RefreshAsync(CancellationToken.None);
        await vm.ImportAsync(CancellationToken.None);
        await vm.SearchAsync(CancellationToken.None);

        Assert.Equal(@"C:\Knowledge\standard.md", Assert.Single(service.ImportedPaths));
        Assert.Equal(KnowledgeSearchMode.Fts5, Assert.Single(service.SearchModes));
        var hit = Assert.Single(vm.Results);
        Assert.Equal("chunk-a", hit.ChunkId);
        Assert.Contains("[K1]", vm.RagContextText, StringComparison.Ordinal);
        Assert.Contains("整车软件制造管控证据链", vm.RagContextText, StringComparison.Ordinal);
        Assert.Equal("1 条证据", vm.ResultSummary);
    }

    [Fact]
    public async Task Open_selected_evidence_delegates_to_safe_launcher()
    {
        var launcher = new FakeEvidenceLauncher();
        var service = new FakeKnowledgeService
        {
            Snapshot = ReadyFtsOnly(),
            SearchResults =
            [
                new KnowledgeSearchHit(
                    "doc-a", "chunk-a", @"C:\Knowledge\evidence.md", "Evidence",
                    0, "exact evidence", 0.9)
            ]
        };
        var vm = new KnowledgePageViewModel(service, launcher)
        {
            Query = "evidence",
            SelectedSearchMode = KnowledgeSearchMode.Fts5
        };

        await vm.RefreshAsync(CancellationToken.None);
        await vm.SearchAsync(CancellationToken.None);
        vm.SelectedResult = Assert.Single(vm.Results);
        await vm.OpenSelectedEvidenceAsync(CancellationToken.None);

        Assert.Equal(@"C:\Knowledge\evidence.md", Assert.Single(launcher.OpenedSources));
    }

    [Fact]
    public async Task Hybrid_becomes_available_only_when_embedding_provider_is_configured()
    {
        var service = new FakeKnowledgeService
        {
            Snapshot = new KnowledgeWorkspaceSnapshot(
                "knowledge.db",
                Fts5Ready: true,
                EmbeddingConfigured: true,
                EmbeddingProvider: "local-embedding",
                EmbeddingModel: "bge-small-zh-v1.5")
        };
        var vm = new KnowledgePageViewModel(service, new FakeEvidenceLauncher());

        await vm.RefreshAsync(CancellationToken.None);

        Assert.True(vm.CanHybridSearch);
        Assert.Contains("local-embedding", vm.EmbeddingStatus, StringComparison.Ordinal);
        Assert.Contains("bge-small-zh-v1.5", vm.EmbeddingStatus, StringComparison.Ordinal);
        Assert.Equal("可用", vm.HybridStatus);
    }

    private static KnowledgeWorkspaceSnapshot ReadyFtsOnly() =>
        new("knowledge.db", true, false, null, null);

    private sealed class FakeKnowledgeService : IKnowledgeWorkbenchService
    {
        public KnowledgeWorkspaceSnapshot Snapshot { get; set; } = ReadyFtsOnly();
        public IReadOnlyList<KnowledgeSearchHit> SearchResults { get; set; } = [];
        public List<string> ImportedPaths { get; } = [];
        public List<KnowledgeSearchMode> SearchModes { get; } = [];

        public Task<KnowledgeWorkspaceSnapshot> GetSnapshotAsync(CancellationToken cancellationToken) =>
            Task.FromResult(Snapshot);

        public Task ImportFileAsync(string path, CancellationToken cancellationToken)
        {
            ImportedPaths.Add(path);
            return Task.CompletedTask;
        }

        public Task<IReadOnlyList<KnowledgeSearchHit>> SearchAsync(
            string query,
            KnowledgeSearchMode mode,
            int limit,
            CancellationToken cancellationToken)
        {
            SearchModes.Add(mode);
            return Task.FromResult(SearchResults);
        }
    }

    private sealed class FakeEvidenceLauncher : IEvidenceLauncher
    {
        public List<string> OpenedSources { get; } = [];

        public Task OpenAsync(string sourceUri, CancellationToken cancellationToken)
        {
            OpenedSources.Add(sourceUri);
            return Task.CompletedTask;
        }
    }
}
