using MLLM.Workbench.Desktop.Pages.Knowledge;
using MLLM.Workbench.Desktop.Services.Knowledge;
using MLLM.Workbench.Knowledge;
using Xunit;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class KnowledgeEvidenceMicroscopeTests
{
    [Fact]
    public void Selecting_hybrid_result_builds_explainable_microscope_text()
    {
        var chunkId = KnowledgeChunkLocator.CreateChunkId("doc-a", "page=2", 0);
        var hit = new KnowledgeSearchHit(
            "doc-a",
            chunkId,
            @"C:\Knowledge\manual.pdf",
            "manual",
            0,
            "vehicle software traceability evidence",
            (1d / 61d) + (1d / 62d))
        {
            Diagnostics = new KnowledgeSearchDiagnostics(
                Method: "Hybrid/RRF",
                LexicalRank: 1,
                LexicalScore: 0.91,
                SemanticRank: 2,
                SemanticScore: 0.84,
                LexicalRrfContribution: 1d / 61d,
                SemanticRrfContribution: 1d / 62d,
                RrfK: 60)
        };

        var vm = new KnowledgePageViewModel(new NoopKnowledgeService(), new NoopEvidenceLauncher());
        vm.SelectedResult = hit;

        Assert.Contains("Hybrid/RRF", vm.EvidenceMicroscopeText, StringComparison.Ordinal);
        Assert.Contains(@"C:\Knowledge\manual.pdf", vm.EvidenceMicroscopeText, StringComparison.Ordinal);
        Assert.Contains("page=2", vm.EvidenceMicroscopeText, StringComparison.Ordinal);
        Assert.Contains(chunkId, vm.EvidenceMicroscopeText, StringComparison.Ordinal);
        Assert.Contains("FTS: rank #1", vm.EvidenceMicroscopeText, StringComparison.Ordinal);
        Assert.Contains("score=0.910000", vm.EvidenceMicroscopeText, StringComparison.Ordinal);
        Assert.Contains("Embedding: rank #2", vm.EvidenceMicroscopeText, StringComparison.Ordinal);
        Assert.Contains("cosine=0.840000", vm.EvidenceMicroscopeText, StringComparison.Ordinal);
        Assert.Contains("RRF: k=60", vm.EvidenceMicroscopeText, StringComparison.Ordinal);
        Assert.Contains("lexical=0.016393", vm.EvidenceMicroscopeText, StringComparison.Ordinal);
        Assert.Contains("semantic=0.016129", vm.EvidenceMicroscopeText, StringComparison.Ordinal);
    }

    [Fact]
    public void Selecting_result_without_diagnostics_does_not_invent_channel_scores()
    {
        var hit = new KnowledgeSearchHit(
            "doc-legacy",
            "legacy:000000",
            @"C:\Knowledge\legacy.txt",
            "legacy",
            0,
            "legacy evidence",
            0.75);

        var vm = new KnowledgePageViewModel(new NoopKnowledgeService(), new NoopEvidenceLauncher());
        vm.SelectedResult = hit;

        Assert.Contains("未携带检索诊断数据", vm.EvidenceMicroscopeText, StringComparison.Ordinal);
        Assert.Contains(@"C:\Knowledge\legacy.txt", vm.EvidenceMicroscopeText, StringComparison.Ordinal);
        Assert.DoesNotContain("rank #", vm.EvidenceMicroscopeText, StringComparison.Ordinal);
        Assert.DoesNotContain("RRF: k=", vm.EvidenceMicroscopeText, StringComparison.Ordinal);
    }

    private sealed class NoopKnowledgeService : IKnowledgeWorkbenchService
    {
        public Task<KnowledgeWorkspaceSnapshot> GetSnapshotAsync(CancellationToken cancellationToken) =>
            Task.FromResult(new KnowledgeWorkspaceSnapshot("knowledge.db", true, false, null, null));

        public Task ImportFileAsync(string path, CancellationToken cancellationToken) => Task.CompletedTask;

        public Task<KnowledgeWorkspaceSnapshot> BuildEmbeddingIndexAsync(
            IProgress<KnowledgeEmbeddingProgress>? progress,
            CancellationToken cancellationToken) => GetSnapshotAsync(cancellationToken);

        public Task<IReadOnlyList<KnowledgeSearchHit>> SearchAsync(
            string query,
            KnowledgeSearchMode mode,
            int limit,
            CancellationToken cancellationToken) =>
            Task.FromResult<IReadOnlyList<KnowledgeSearchHit>>([]);
    }

    private sealed class NoopEvidenceLauncher : IEvidenceLauncher
    {
        public Task OpenAsync(string sourceUri, CancellationToken cancellationToken) => Task.CompletedTask;
    }
}
