using System.IO;
using MLLM.Workbench.Desktop.Pages.Knowledge;
using MLLM.Workbench.Desktop.Services.Knowledge;
using MLLM.Workbench.Knowledge;
using Xunit;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class EvidenceLaunchTargetTests
{
    [Fact]
    public void Pdf_page_locator_builds_local_file_fragment_target()
    {
        var root = NewTempRoot();
        var source = Path.Combine(root, "manual.pdf");
        File.WriteAllText(source, "pdf placeholder");
        try
        {
            var target = EvidenceLaunchTargetBuilder.Build(source, "page=3");

            Assert.Equal(Path.GetFullPath(source), target.ResolvedPath);
            Assert.True(target.IsDeepLink);
            Assert.Equal("page=3", target.AppliedLocator);
            Assert.StartsWith("file:", target.ShellTarget, StringComparison.OrdinalIgnoreCase);
            Assert.EndsWith("#page=3", target.ShellTarget, StringComparison.Ordinal);
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    [Fact]
    public void Docx_paragraph_locator_remains_plain_local_open_without_fake_deep_link()
    {
        var root = NewTempRoot();
        var source = Path.Combine(root, "procedure.docx");
        File.WriteAllText(source, "docx placeholder");
        try
        {
            var target = EvidenceLaunchTargetBuilder.Build(source, "paragraph=7");

            Assert.Equal(Path.GetFullPath(source), target.ResolvedPath);
            Assert.Equal(Path.GetFullPath(source), target.ShellTarget);
            Assert.False(target.IsDeepLink);
            Assert.Null(target.AppliedLocator);
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    [Fact]
    public void Remote_evidence_url_is_rejected_by_launch_target_builder()
    {
        Assert.Throws<NotSupportedException>(() =>
            EvidenceLaunchTargetBuilder.Build("https://example.com/evidence.pdf", "page=1"));
    }

    [Fact]
    public async Task View_model_passes_selected_locator_to_locator_aware_launcher()
    {
        var launcher = new LocatorAwareEvidenceLauncher();
        var vm = new KnowledgePageViewModel(new NoopKnowledgeService(), launcher);
        var chunkId = KnowledgeChunkLocator.CreateChunkId("doc-a", "page=5", 0);
        vm.SelectedResult = new KnowledgeSearchHit(
            "doc-a",
            chunkId,
            @"C:\Knowledge\manual.pdf",
            "manual",
            0,
            "evidence",
            0.9);

        await vm.OpenSelectedEvidenceAsync(CancellationToken.None);

        Assert.Equal(@"C:\Knowledge\manual.pdf", launcher.OpenedSource);
        Assert.Equal("page=5", launcher.OpenedLocator);
        Assert.True(launcher.LocatorAwareOverloadUsed);
    }

    private static string NewTempRoot()
    {
        var root = Path.Combine(Path.GetTempPath(), "mllm-evidence-launch", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        return root;
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

    private sealed class LocatorAwareEvidenceLauncher : IEvidenceLauncher
    {
        public string? OpenedSource { get; private set; }
        public string? OpenedLocator { get; private set; }
        public bool LocatorAwareOverloadUsed { get; private set; }

        public Task OpenAsync(string sourceUri, CancellationToken cancellationToken)
        {
            OpenedSource = sourceUri;
            OpenedLocator = null;
            LocatorAwareOverloadUsed = false;
            return Task.CompletedTask;
        }

        public Task OpenAsync(string sourceUri, string? locator, CancellationToken cancellationToken)
        {
            OpenedSource = sourceUri;
            OpenedLocator = locator;
            LocatorAwareOverloadUsed = true;
            return Task.CompletedTask;
        }
    }
}
