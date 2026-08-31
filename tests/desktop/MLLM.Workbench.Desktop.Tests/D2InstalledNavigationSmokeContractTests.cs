using System.IO;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class D2InstalledNavigationSmokeContractTests
{
    [Fact]
    public void Installed_release_requires_read_only_D2_conversation_navigation_smoke()
    {
        var root = FindRepositoryRoot();
        var app = File.ReadAllText(Path.Combine(root, "src", "MLLM.Workbench.Desktop", "App.xaml.cs"));

        Assert.Contains("--smoke-d2-navigation", app, StringComparison.Ordinal);
        Assert.Contains("VerifyD2NavigationAsync", app, StringComparison.Ordinal);
        Assert.Contains("D2_NAVIGATION_SMOKE=PASS", app, StringComparison.Ordinal);
        Assert.Contains("viewModel.NavigateConversationCommand", app, StringComparison.Ordinal);
        Assert.Contains("ReferenceEquals(viewModel.CurrentPage, viewModel.Conversation)", app, StringComparison.Ordinal);
        Assert.Contains("viewModel.Conversation.IsBusy", app, StringComparison.Ordinal);
        Assert.Contains("DispatcherPriority.ApplicationIdle", app, StringComparison.Ordinal);
        Assert.DoesNotContain("viewModel.Conversation.SendCommand", app, StringComparison.Ordinal);
        Assert.DoesNotContain("viewModel.Services.StartCommand", app, StringComparison.Ordinal);
        Assert.DoesNotContain("viewModel.Models.ActivateCommand", app, StringComparison.Ordinal);

        var releaseSmoke = File.ReadAllText(Path.Combine(root, "tests", "ci", "Invoke-C7ReleasePackageSmoke.ps1"));
        Assert.Contains("$oldNetworkMode=$env:MLLM_NETWORK_MODE", releaseSmoke, StringComparison.Ordinal);
        Assert.Contains("[IO.Path]::GetTempPath()", releaseSmoke, StringComparison.Ordinal);
        Assert.Contains("git -C $root rev-parse HEAD", releaseSmoke, StringComparison.Ordinal);
        Assert.Contains("$oldProgramW6432=$env:ProgramW6432", releaseSmoke, StringComparison.Ordinal);
        Assert.Contains("${env:ProgramFiles(x86)}=$env:ProgramFiles", releaseSmoke, StringComparison.Ordinal);
        Assert.Contains("$env:ProgramW6432=$oldProgramW6432", releaseSmoke, StringComparison.Ordinal);
        Assert.Contains("$env:MLLM_NETWORK_MODE='OFFLINE_CACHE'", releaseSmoke, StringComparison.Ordinal);
        Assert.Contains("@('--smoke-d2-navigation')", releaseSmoke, StringComparison.Ordinal);
        Assert.Contains("-TimeoutMs 30000", releaseSmoke, StringComparison.Ordinal);
        Assert.Contains("d2_navigation_smoke=PASS", releaseSmoke, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("$env:MLLM_NETWORK_MODE=$oldNetworkMode", releaseSmoke, StringComparison.Ordinal);
    }

    [Fact]
    public void Knowledge_workflow_runs_D2_gate_before_full_desktop_regression()
    {
        var root = FindRepositoryRoot();
        var workflow = File.ReadAllText(Path.Combine(root, ".github", "workflows", "knowledge-phase-c.yml"));
        const string gate = "- name: D2 conversation and golden tests";
        const string full = "- name: Full desktop regression";

        var gateIndex = workflow.IndexOf(gate, StringComparison.Ordinal);
        var fullIndex = workflow.IndexOf(full, StringComparison.Ordinal);
        Assert.True(gateIndex >= 0, "D2 conversation CI gate is missing.");
        Assert.True(fullIndex > gateIndex, "D2 conversation CI gate must run before the full Desktop regression.");
        foreach (var required in new[]
        {
            "LocalConversation",
            "OpenAiSseReader",
            "ConversationTestService",
            "JsonGoldenTestCatalog",
            "GoldenTestEvaluator",
            "ConversationPageViewModel",
            "D2Conversation",
            "D2InstalledNavigation"
        })
            Assert.Contains(required, workflow, StringComparison.Ordinal);
    }

    private static string FindRepositoryRoot()
    {
        var cursor = new DirectoryInfo(AppContext.BaseDirectory);
        while (cursor is not null)
        {
            if (File.Exists(Path.Combine(cursor.FullName, "Bootstrap_SafeCore.ps1"))) return cursor.FullName;
            cursor = cursor.Parent;
        }
        throw new DirectoryNotFoundException("Repository root was not found.");
    }
}
