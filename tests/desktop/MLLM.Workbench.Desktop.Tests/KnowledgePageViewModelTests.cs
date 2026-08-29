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
        Assert.Equal("未配置", vm.EmbeddingIndexStatus);
        Assert.Equal("不可用", vm.HybridStatus);
        Assert.Equal(@"C:\Data\knowledge\knowledge.db", vm.DatabasePath);
        Assert.False(vm.CanHybridSearch);
        Assert.False(vm.CanBuildEmbeddingIndex);
        Assert.Null(vm.LastError);
    }

    [Fact]
    public async Task Refresh_surfaces_invalid_embedding_configuration_without_breaking_fts_state()
    {
        var service = new FakeKnowledgeService
        {
            Snapshot = new KnowledgeWorkspaceSnapshot(
                "knowledge.db",
                Fts5Ready: true,
                EmbeddingConfigured: false,
                EmbeddingProvider: null,
                EmbeddingModel: null,
                EmbeddingConfigurationError: "Missing MLLM_EMBEDDING_DIMENSION")
        };
        var vm = new KnowledgePageViewModel(service, new FakeEvidenceLauncher());

        await vm.RefreshAsync(CancellationToken.None);

        Assert.Equal("可用", vm.Fts5Status);
        Assert.Contains("配置错误", vm.EmbeddingStatus, StringComparison.Ordinal);
        Assert.Contains("MLLM_EMBEDDING_DIMENSION", vm.EmbeddingStatus, StringComparison.Ordinal);
        Assert.Contains("配置错误", vm.EmbeddingIndexStatus, StringComparison.Ordinal);
        Assert.False(vm.CanHybridSearch);
        Assert.False(vm.CanBuildEmbeddingIndex);
    }

    [Fact]
    public async Task Configured_but_partially_indexed_provider_does_not_claim_hybrid_ready()
    {
        var service = new FakeKnowledgeService
        {
            Snapshot = new KnowledgeWorkspaceSnapshot(
                "knowledge.db",
                Fts5Ready: true,
                EmbeddingConfigured: true,
                EmbeddingProvider: "local-embedding",
                EmbeddingModel: "bge-small-zh-v1.5",
                EmbeddingConfigurationError: null,
                EmbeddingIndexedChunks: 0,
                EmbeddingTotalChunks: 12)
        };
        var vm = new KnowledgePageViewModel(service, new FakeEvidenceLauncher());

        await vm.RefreshAsync(CancellationToken.None);

        Assert.Contains("local-embedding", vm.EmbeddingStatus, StringComparison.Ordinal);
        Assert.Equal("已配置 · 0/12 已索引", vm.EmbeddingIndexStatus);
        Assert.Equal("待补齐向量索引", vm.HybridStatus);
        Assert.False(vm.CanHybridSearch);
        Assert.True(vm.CanBuildEmbeddingIndex);
        Assert.Equal(0d, vm.EmbeddingProgressPercent);
    }

    [Fact]
    public async Task Build_embedding_index_surfaces_live_chunk_progress_and_refreshes_hybrid_readiness()
    {
        var service = new FakeKnowledgeService
        {
            Snapshot = new KnowledgeWorkspaceSnapshot(
                "knowledge.db", true, true, "local-embedding", "bge-small-zh-v1.5",
                null, 0, 2),
            BuildSnapshot = new KnowledgeWorkspaceSnapshot(
                "knowledge.db", true, true, "local-embedding", "bge-small-zh-v1.5",
                null, 2, 2),
            BuildProgress =
            [
                new KnowledgeEmbeddingProgress(1, 2, "chunk-a"),
                new KnowledgeEmbeddingProgress(2, 2, "chunk-b")
            ]
        };
        var vm = new KnowledgePageViewModel(service, new FakeEvidenceLauncher());
        var progressTexts = new List<string>();
        vm.PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(vm.EmbeddingProgressText))
                progressTexts.Add(vm.EmbeddingProgressText);
        };

        await vm.RefreshAsync(CancellationToken.None);
        await vm.BuildEmbeddingIndexAsync(CancellationToken.None);

        Assert.Equal(1, service.BuildEmbeddingIndexCalls);
        Assert.Equal("已配置 · 2/2 已索引", vm.EmbeddingIndexStatus);
        Assert.Equal("可用", vm.HybridStatus);
        Assert.True(vm.CanHybridSearch);
        Assert.False(vm.CanBuildEmbeddingIndex);
        Assert.Equal(100d, vm.EmbeddingProgressPercent);
        Assert.Contains(progressTexts, text => text.Contains("chunk-a", StringComparison.Ordinal));
        Assert.Contains(progressTexts, text => text.Contains("chunk-b", StringComparison.Ordinal));
        Assert.Null(vm.LastError);
    }

    [Fact]
    public async Task Import_refreshes_vector_coverage_after_service_indexes_new_document()
    {
        var service = new FakeKnowledgeService
        {
            Snapshot = new KnowledgeWorkspaceSnapshot(
                "knowledge.db", true, true, "local-embedding", "bge-small-zh-v1.5",
                null, 0, 0),
            ImportSnapshot = new KnowledgeWorkspaceSnapshot(
                "knowledge.db", true, true, "local-embedding", "bge-small-zh-v1.5",
                null, 1, 1)
        };
        var vm = new KnowledgePageViewModel(service, new FakeEvidenceLauncher())
        {
            ImportPath = @"C:\Knowledge\new.md"
        };

        await vm.RefreshAsync(CancellationToken.None);
        await vm.ImportAsync(CancellationToken.None);

        Assert.Equal("已配置 · 1/1 已索引", vm.EmbeddingIndexStatus);
        Assert.Equal("可用", vm.HybridStatus);
        Assert.True(vm.CanHybridSearch);
        Assert.Equal(100d, vm.EmbeddingProgressPercent);
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
    public async Task Hybrid_becomes_available_only_when_embedding_provider_is_configured_and_index_complete()
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
        Assert.Equal("已配置 · 0/0 已索引", vm.EmbeddingIndexStatus);
        Assert.Equal("可用", vm.HybridStatus);
    }

    private static KnowledgeWorkspaceSnapshot ReadyFtsOnly() =>
        new("knowledge.db", true, false, null, null);

    private sealed class FakeKnowledgeService : IKnowledgeWorkbenchService
    {
        public KnowledgeWorkspaceSnapshot Snapshot { get; set; } = ReadyFtsOnly();
        public KnowledgeWorkspaceSnapshot? BuildSnapshot { get; set; }
        public KnowledgeWorkspaceSnapshot? ImportSnapshot { get; set; }
        public IReadOnlyList<KnowledgeEmbeddingProgress> BuildProgress { get; set; } = [];
        public IReadOnlyList<KnowledgeSearchHit> SearchResults { get; set; } = [];
        public List<string> ImportedPaths { get; } = [];
        public List<KnowledgeSearchMode> SearchModes { get; } = [];
        public int BuildEmbeddingIndexCalls { get; private set; }

        public Task<KnowledgeWorkspaceSnapshot> GetSnapshotAsync(CancellationToken cancellationToken) =>
            Task.FromResult(Snapshot);

        public Task ImportFileAsync(string path, CancellationToken cancellationToken)
        {
            ImportedPaths.Add(path);
            if (ImportSnapshot is not null) Snapshot = ImportSnapshot;
            return Task.CompletedTask;
        }

        public Task<KnowledgeWorkspaceSnapshot> BuildEmbeddingIndexAsync(
            IProgress<KnowledgeEmbeddingProgress>? progress,
            CancellationToken cancellationToken)
        {
            BuildEmbeddingIndexCalls++;
            foreach (var item in BuildProgress) progress?.Report(item);
            if (BuildSnapshot is not null) Snapshot = BuildSnapshot;
            return Task.FromResult(Snapshot);
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
