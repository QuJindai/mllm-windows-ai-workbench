using System.Windows.Input;
using MLLM.Workbench.Desktop.Pages.Conversation;
using MLLM.Workbench.Desktop.Services.Conversation;
using MLLM.Workbench.Desktop.Services.Knowledge;
using MLLM.Workbench.Knowledge;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class ConversationPageViewModelTests
{
    [Fact]
    public async Task Refresh_maps_runtime_readiness_and_loads_persisted_golden_cases()
    {
        var service = new FakeConversationService();
        var catalog = new FakeGoldenCatalog([Case("case-1", "Golden one")]);
        var vm = CreateViewModel(service, catalog);

        await vm.RefreshAsync(CancellationToken.None);

        Assert.True(vm.IsRuntimeReady);
        Assert.Equal("http://127.0.0.1:8080", vm.Endpoint);
        Assert.Equal("active-model", vm.ActiveModel);
        Assert.Equal("service-model", vm.ServiceModel);
        Assert.Equal("Ready", vm.RuntimeStatus);
        Assert.Equal("case-1", Assert.Single(vm.GoldenCases).Id);
        Assert.Null(vm.LastError);
    }

    [Fact]
    public async Task Refresh_preserves_runtime_block_reason_and_disables_send_when_not_ready()
    {
        var service = new FakeConversationService
        {
            Runtime = new(
                false,
                "local-model-api",
                "Stopped",
                null,
                null,
                null,
                "本机模型服务尚未运行。")
        };
        var vm = CreateViewModel(service);
        vm.UserPrompt = "hello";

        await vm.RefreshAsync(CancellationToken.None);

        Assert.False(vm.IsRuntimeReady);
        Assert.Equal("Not ready", vm.RuntimeStatus);
        Assert.Equal("RUNTIME_NOT_READY", vm.LastErrorCode);
        Assert.Equal("本机模型服务尚未运行。", vm.LastError);
        Assert.False(vm.SendCommand.CanExecute(null));
    }

    [Fact]
    public async Task Blank_prompt_is_rejected_without_calling_conversation_service()
    {
        var service = new FakeConversationService();
        var vm = CreateViewModel(service);
        vm.UserPrompt = "   ";

        await vm.SendAsync(CancellationToken.None);

        Assert.Equal(0, service.RunCallCount);
        Assert.Equal("PROMPT_REQUIRED", vm.LastErrorCode);
        Assert.Empty(vm.Transcript);
    }

    [Fact]
    public async Task Streaming_run_updates_one_assistant_entry_metrics_and_trusted_evidence()
    {
        var service = new FakeConversationService
        {
            RunHandler = (request, progress, cancellationToken) =>
            {
                progress?.Report(new ConversationDelta("你"));
                progress?.Report(new ConversationDelta("好"));
                return Task.FromResult(Completed(
                    "你好",
                    new ConversationMetrics(TimeSpan.FromMilliseconds(10), TimeSpan.FromMilliseconds(25), 2, 80),
                    [Evidence()]));
            }
        };
        var launcher = new FakeEvidenceLauncher();
        var vm = CreateViewModel(service, launcher: launcher);
        vm.SystemPrompt = "system";
        vm.UserPrompt = "hello";
        vm.UseKnowledge = true;

        await vm.SendAsync(CancellationToken.None);

        Assert.Equal(2, vm.Transcript.Count);
        Assert.Equal(ConversationTranscriptRole.User, vm.Transcript[0].Role);
        Assert.Equal("hello", vm.Transcript[0].Content);
        Assert.Equal(ConversationTranscriptRole.Assistant, vm.Transcript[1].Role);
        Assert.Equal("你好", vm.Transcript[1].Content);
        Assert.Equal("10 ms", vm.TimeToFirstTokenText);
        Assert.Equal("25 ms", vm.TotalLatencyText);
        Assert.Equal("2", vm.CompletionTokensText);
        Assert.Equal("80.00", vm.TokensPerSecondText);
        Assert.Equal("K1", Assert.Single(vm.Evidence).CitationId);
        Assert.Equal(1, service.RunCallCount);
        Assert.True(service.LastRequest!.UseKnowledge);

        vm.SelectedEvidence = vm.Evidence[0];
        await vm.OpenSelectedEvidenceAsync(CancellationToken.None);
        Assert.Equal((@"C:\Docs\vehicle.pdf", "page=2"), Assert.Single(launcher.Opened));
    }

    [Fact]
    public async Task Missing_server_usage_is_displayed_as_unavailable_not_estimated()
    {
        var service = new FakeConversationService
        {
            RunHandler = (request, progress, cancellationToken) => Task.FromResult(Completed(
                "answer",
                new ConversationMetrics(TimeSpan.FromMilliseconds(5), TimeSpan.FromMilliseconds(20), null, null),
                []))
        };
        var vm = CreateViewModel(service);
        vm.UserPrompt = "prompt";

        await vm.SendAsync(CancellationToken.None);

        Assert.Equal("Unavailable", vm.CompletionTokensText);
        Assert.Equal("Unavailable", vm.TokensPerSecondText);
    }

    [Fact]
    public async Task Failed_transport_result_keeps_partial_text_metrics_and_structured_error()
    {
        var service = new FakeConversationService
        {
            RunHandler = (request, progress, cancellationToken) =>
            {
                progress?.Report(new ConversationDelta("partial"));
                return Task.FromResult(new ConversationRunResult(
                    ConversationRunState.Failed,
                    "partial",
                    new ConversationMetrics(TimeSpan.FromMilliseconds(7), TimeSpan.FromMilliseconds(30), null, null),
                    [],
                    "STREAM_PROTOCOL_ERROR",
                    "Malformed stream."));
            }
        };
        var vm = CreateViewModel(service);
        vm.UserPrompt = "prompt";

        await vm.SendAsync(CancellationToken.None);

        Assert.Equal("partial", vm.Transcript.Single(item => item.Role == ConversationTranscriptRole.Assistant).Content);
        Assert.Equal("7 ms", vm.TimeToFirstTokenText);
        Assert.Equal("30 ms", vm.TotalLatencyText);
        Assert.Equal("STREAM_PROTOCOL_ERROR", vm.LastErrorCode);
        Assert.Contains(vm.Transcript, item => item.Role == ConversationTranscriptRole.Status && item.Code == "STREAM_PROTOCOL_ERROR");
    }

    [Fact]
    public async Task Cancel_keeps_partial_assistant_text_and_disables_competing_runs_while_active()
    {
        var started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var service = new FakeConversationService
        {
            RunHandler = async (request, progress, cancellationToken) =>
            {
                progress?.Report(new ConversationDelta("partial"));
                started.TrySetResult();
                try
                {
                    await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken);
                    throw new InvalidOperationException("Cancellation was not observed.");
                }
                catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
                {
                    return new ConversationRunResult(
                        ConversationRunState.Cancelled,
                        "partial",
                        new ConversationMetrics(TimeSpan.FromMilliseconds(1), TimeSpan.FromMilliseconds(5), null, null),
                        [],
                        "RUN_CANCELLED",
                        "Cancelled");
                }
            }
        };
        var vm = CreateViewModel(service, new FakeGoldenCatalog([Case("case-1", "One")]));
        vm.UserPrompt = "cancel";

        var run = vm.SendAsync(CancellationToken.None);
        await started.Task.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.True(vm.IsRunActive);
        Assert.False(vm.SendCommand.CanExecute(null));
        Assert.False(vm.RunAllGoldenCommand.CanExecute(null));
        Assert.True(vm.CancelCommand.CanExecute(null));

        vm.CancelCommand.Execute(null);
        await run.WaitAsync(TimeSpan.FromSeconds(5));

        Assert.False(vm.IsRunActive);
        Assert.Equal("partial", vm.Transcript.Single(item => item.Role == ConversationTranscriptRole.Assistant).Content);
        Assert.Contains(vm.Transcript, item => item.Role == ConversationTranscriptRole.Status && item.Code == "RUN_CANCELLED");
    }

    [Fact]
    public async Task Clear_removes_run_state_but_keeps_golden_catalog()
    {
        var service = new FakeConversationService();
        var vm = CreateViewModel(service, new FakeGoldenCatalog([Case("case-1", "One")]));
        await vm.RefreshAsync(CancellationToken.None);
        vm.UserPrompt = "prompt";
        await vm.SendAsync(CancellationToken.None);

        vm.ClearCommand.Execute(null);

        Assert.Empty(vm.Transcript);
        Assert.Empty(vm.Evidence);
        Assert.Equal("-", vm.TotalLatencyText);
        Assert.Equal("case-1", Assert.Single(vm.GoldenCases).Id);
    }

    [Fact]
    public async Task History_contains_only_recent_successful_pairs_within_explicit_budgets()
    {
        var invocation = 0;
        var service = new FakeConversationService
        {
            RunHandler = (request, progress, cancellationToken) =>
            {
                invocation++;
                if (invocation == 1)
                {
                    progress?.Report(new ConversationDelta("partial"));
                    return Task.FromResult(new ConversationRunResult(
                        ConversationRunState.Cancelled,
                        "partial",
                        new ConversationMetrics(TimeSpan.FromMilliseconds(1), TimeSpan.FromMilliseconds(2), null, null),
                        [],
                        "RUN_CANCELLED",
                        "Cancelled"));
                }

                return Task.FromResult(Completed(
                    new string('x', 1_500) + invocation,
                    new ConversationMetrics(TimeSpan.FromMilliseconds(1), TimeSpan.FromMilliseconds(2), 2, 100),
                    []));
            }
        };
        var vm = CreateViewModel(service);

        vm.UserPrompt = "cancelled prompt";
        await vm.SendAsync(CancellationToken.None);
        for (var index = 0; index < 13; index++)
        {
            vm.UserPrompt = "successful prompt " + index;
            await vm.SendAsync(CancellationToken.None);
        }
        vm.UserPrompt = "final prompt";
        await vm.SendAsync(CancellationToken.None);

        var finalHistory = service.Requests[^1].History;
        Assert.DoesNotContain(finalHistory, item => item.Content.Contains("cancelled prompt", StringComparison.Ordinal));
        Assert.DoesNotContain(finalHistory, item => item.Content.Contains("partial", StringComparison.Ordinal));
        Assert.True(finalHistory.Count <= 20);
        Assert.True(finalHistory.Sum(item => item.Content.Length) <= 12_000);
        Assert.Equal(0, finalHistory.Count % 2);
        Assert.Equal("successful prompt 12", finalHistory[^2].Content);
    }

    [Fact]
    public async Task Golden_run_uses_shared_cancel_command_and_releases_active_state()
    {
        var started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var service = new FakeConversationService
        {
            RunHandler = async (request, progress, cancellationToken) =>
            {
                started.TrySetResult();
                try
                {
                    await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken);
                    throw new InvalidOperationException("Cancellation was not observed.");
                }
                catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
                {
                    return new ConversationRunResult(
                        ConversationRunState.Cancelled,
                        "partial",
                        new ConversationMetrics(null, TimeSpan.FromMilliseconds(10), null, null),
                        [],
                        "RUN_CANCELLED",
                        "Cancelled");
                }
            }
        };
        var vm = CreateViewModel(service, new FakeGoldenCatalog([Case("case-1", "One")]));
        await vm.RefreshAsync(CancellationToken.None);

        var run = vm.RunAllGoldenAsync(CancellationToken.None);
        await started.Task.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.True(vm.IsRunActive);
        Assert.True(vm.CancelCommand.CanExecute(null));
        Assert.False(vm.SendCommand.CanExecute(null));

        vm.CancelCommand.Execute(null);
        await run.WaitAsync(TimeSpan.FromSeconds(5));

        Assert.False(vm.IsRunActive);
        Assert.False(vm.IsBusy);
        Assert.Equal("RUN_CANCELLED", vm.LastErrorCode);
        var cancelled = Assert.Single(vm.GoldenResults);
        Assert.Equal("RUN_CANCELLED", cancelled.FailureCode);
        Assert.Equal("partial", cancelled.ResponseText);
    }

    [Fact]
    public async Task Save_as_new_update_delete_and_run_golden_cases_preserve_stable_selection()
    {
        var service = new FakeConversationService();
        var catalog = new FakeGoldenCatalog([Case("case-1", "One"), Case("case-2", "Two")]);
        var vm = CreateViewModel(service, catalog);
        await vm.RefreshAsync(CancellationToken.None);
        vm.UserPrompt = "new prompt";
        vm.GoldenName = "New case";
        vm.GoldenMustContain = "answer\nrequired";
        vm.GoldenMustNotContain = "forbidden";
        vm.GoldenMaximumLatencyMilliseconds = 500;

        await vm.SaveGoldenAsNewAsync(CancellationToken.None);
        var created = catalog.Upserts.Last();
        Assert.False(string.IsNullOrWhiteSpace(created.Id));
        Assert.DoesNotContain(created.Id, new[] { "case-1", "case-2" });
        Assert.Equal(["answer", "required"], created.MustContain);
        Assert.Equal(["forbidden"], created.MustNotContain);

        vm.SelectedGoldenCase = vm.GoldenCases.Single(item => item.Id == "case-1");
        vm.GoldenName = "One updated";
        await vm.UpdateSelectedGoldenAsync(CancellationToken.None);
        Assert.Equal("case-1", catalog.Upserts.Last().Id);
        Assert.Equal("One updated", catalog.Upserts.Last().Name);

        await vm.RunSelectedGoldenAsync(CancellationToken.None);
        Assert.Single(vm.GoldenResults);
        Assert.Equal("case-1", vm.GoldenResults[0].CaseId);

        await vm.RunAllGoldenAsync(CancellationToken.None);
        Assert.Equal(vm.GoldenCases.Count, vm.GoldenResults.Count);

        var deletedId = vm.SelectedGoldenCase!.Id;
        await vm.DeleteGoldenAsync(CancellationToken.None);
        Assert.Contains(deletedId, catalog.Deletes);
        Assert.DoesNotContain(vm.GoldenCases, item => item.Id == deletedId);
    }

    private static ConversationPageViewModel CreateViewModel(
        FakeConversationService service,
        FakeGoldenCatalog? catalog = null,
        FakeEvidenceLauncher? launcher = null)
    {
        catalog ??= new FakeGoldenCatalog([]);
        return new ConversationPageViewModel(
            service,
            catalog,
            new GoldenTestEvaluator(service),
            launcher ?? new FakeEvidenceLauncher());
    }

    private static ConversationRunResult Completed(
        string response,
        ConversationMetrics metrics,
        IReadOnlyList<RagEvidence> evidence) =>
        new(ConversationRunState.Completed, response, metrics, evidence);

    private static RagEvidence Evidence() =>
        new(
            "K1",
            "doc",
            KnowledgeChunkLocator.CreateChunkId("doc", "page=2", 0),
            @"C:\Docs\vehicle.pdf",
            "Vehicle",
            0,
            "excerpt",
            1);

    private static GoldenTestCase Case(string id, string name) =>
        new(
            id,
            name,
            "system",
            "answer required",
            0.2,
            64,
            false,
            ["answer"],
            ["forbidden"],
            null,
            DateTimeOffset.Parse("2026-09-01T00:00:00+08:00"),
            DateTimeOffset.Parse("2026-09-01T00:00:00+08:00"));

    private sealed class FakeConversationService : IConversationTestService
    {
        public ConversationRuntimeSnapshot Runtime { get; set; } =
            new(true, "local-model-api", "Running", "http://127.0.0.1:8080", "active-model", "service-model", null);
        public Func<ConversationRequest, IProgress<ConversationDelta>?, CancellationToken, Task<ConversationRunResult>> RunHandler { get; set; } =
            (request, progress, cancellationToken) => Task.FromResult(Completed(
                "answer required",
                new ConversationMetrics(TimeSpan.FromMilliseconds(5), TimeSpan.FromMilliseconds(10), 2, 200),
                []));
        public int RunCallCount { get; private set; }
        public ConversationRequest? LastRequest { get; private set; }
        public List<ConversationRequest> Requests { get; } = [];

        public Task<ConversationRuntimeSnapshot> RefreshRuntimeAsync(CancellationToken cancellationToken) =>
            Task.FromResult(Runtime);

        public Task<ConversationRunResult> RunAsync(
            ConversationRequest request,
            IProgress<ConversationDelta>? progress,
            CancellationToken cancellationToken)
        {
            RunCallCount++;
            LastRequest = request;
            Requests.Add(request);
            return RunHandler(request, progress, cancellationToken);
        }
    }

    private sealed class FakeGoldenCatalog(IEnumerable<GoldenTestCase> initial) : IGoldenTestCatalog
    {
        private readonly List<GoldenTestCase> _cases = initial.ToList();
        public List<GoldenTestCase> Upserts { get; } = [];
        public List<string> Deletes { get; } = [];

        public Task<IReadOnlyList<GoldenTestCase>> LoadAsync(CancellationToken cancellationToken) =>
            Task.FromResult<IReadOnlyList<GoldenTestCase>>(_cases.ToArray());

        public Task<GoldenTestCase> UpsertAsync(GoldenTestCase testCase, CancellationToken cancellationToken)
        {
            var now = DateTimeOffset.Parse("2026-09-01T01:00:00+08:00");
            var saved = testCase with
            {
                CreatedAt = testCase.CreatedAt == default ? now : testCase.CreatedAt,
                UpdatedAt = now
            };
            Upserts.Add(saved);
            var index = _cases.FindIndex(item => item.Id == saved.Id);
            if (index >= 0) _cases[index] = saved;
            else _cases.Add(saved);
            return Task.FromResult(saved);
        }

        public Task DeleteAsync(string id, CancellationToken cancellationToken)
        {
            Deletes.Add(id);
            _cases.RemoveAll(item => item.Id == id);
            return Task.CompletedTask;
        }
    }

    private sealed class FakeEvidenceLauncher : IEvidenceLauncher
    {
        public List<(string Source, string? Locator)> Opened { get; } = [];

        public Task OpenAsync(string sourceUri, CancellationToken cancellationToken)
        {
            Opened.Add((sourceUri, null));
            return Task.CompletedTask;
        }

        public Task OpenAsync(string sourceUri, string? locator, CancellationToken cancellationToken)
        {
            Opened.Add((sourceUri, locator));
            return Task.CompletedTask;
        }
    }
}
