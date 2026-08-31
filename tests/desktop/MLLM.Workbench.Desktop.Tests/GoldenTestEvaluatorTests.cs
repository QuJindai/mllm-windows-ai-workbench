using MLLM.Workbench.Desktop.Services.Conversation;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class GoldenTestEvaluatorTests
{
    [Fact]
    public async Task Cases_run_sequentially_and_return_literal_failure_codes_without_stopping_the_batch()
    {
        var service = new FakeConversationService();
        var evaluator = new GoldenTestEvaluator(service);
        var cases = new[]
        {
            Case("pass", ["required"], ["forbidden"]),
            Case("missing", ["absent"], []),
            Case("forbidden", [], ["forbidden"]),
            Case("empty", [], []),
            Case("slow", [], [], maximumLatency: 50),
            Case("no-evidence", [], [], useKnowledge: true),
            Case("failed", [], []),
            Case("cancelled", [], [])
        };

        var results = await evaluator.RunAsync(cases, CancellationToken.None);

        Assert.Equal(1, service.MaximumConcurrency);
        Assert.Equal(cases.Select(item => item.Id), results.Select(item => item.CaseId));
        Assert.True(results[0].Passed);
        Assert.Null(results[0].FailureCode);
        Assert.Equal("REQUIRED_TEXT_MISSING", results[1].FailureCode);
        Assert.Equal("FORBIDDEN_TEXT_PRESENT", results[2].FailureCode);
        Assert.Equal("RESPONSE_EMPTY", results[3].FailureCode);
        Assert.Equal("LATENCY_LIMIT_EXCEEDED", results[4].FailureCode);
        Assert.Equal("NO_EVIDENCE", results[5].FailureCode);
        Assert.Equal("RUN_FAILED", results[6].FailureCode);
        Assert.Equal(TimeSpan.FromMilliseconds(10), results[6].Metrics.TotalLatency);
        Assert.Equal("RUN_CANCELLED", results[7].FailureCode);
        Assert.Equal("answer required [K1]", results[0].ResponseText);
        Assert.Equal(["K1"], results[0].EvidenceIds);
    }

    [Fact]
    public async Task Cancellation_preserves_completed_rows_and_cancelled_partial_result_then_stops()
    {
        using var cancellation = new CancellationTokenSource();
        var service = new CancellingConversationService(cancellation);
        var evaluator = new GoldenTestEvaluator(service);

        var results = await evaluator.RunAsync(
            [Case("before", [], []), Case("cancel-now", [], []), Case("after", [], [])],
            cancellation.Token);

        Assert.Equal(["before", "cancel-now"], results.Select(item => item.CaseId));
        Assert.True(results[0].Passed);
        Assert.Equal("RUN_CANCELLED", results[1].FailureCode);
        Assert.Equal("partial", results[1].ResponseText);
        Assert.Equal(TimeSpan.FromMilliseconds(25), results[1].Metrics.TotalLatency);
        Assert.Equal(2, service.CallCount);
    }

    private static GoldenTestCase Case(
        string id,
        IReadOnlyList<string> mustContain,
        IReadOnlyList<string> mustNotContain,
        long? maximumLatency = null,
        bool useKnowledge = false) =>
        new(
            id,
            id,
            "system",
            id,
            0,
            64,
            useKnowledge,
            mustContain,
            mustNotContain,
            maximumLatency,
            DateTimeOffset.Parse("2026-09-01T00:00:00+08:00"),
            DateTimeOffset.Parse("2026-09-01T00:00:00+08:00"));

    private sealed class FakeConversationService : IConversationTestService
    {
        private int _currentConcurrency;
        private int _maximumConcurrency;

        public int MaximumConcurrency => Volatile.Read(ref _maximumConcurrency);

        public Task<ConversationRuntimeSnapshot> RefreshRuntimeAsync(CancellationToken cancellationToken) =>
            throw new NotSupportedException();

        public async Task<ConversationRunResult> RunAsync(
            ConversationRequest request,
            IProgress<ConversationDelta>? progress,
            CancellationToken cancellationToken)
        {
            var current = Interlocked.Increment(ref _currentConcurrency);
            UpdateMaximum(current);
            try
            {
                await Task.Delay(10, cancellationToken);
                if (request.UserPrompt == "no-evidence")
                    throw new ConversationRunException("NO_EVIDENCE", "No evidence.");
                if (request.UserPrompt == "failed")
                    return Result(ConversationRunState.Failed, "", 10, "RUN_FAILED");
                if (request.UserPrompt == "cancelled")
                    return Result(ConversationRunState.Cancelled, "partial", 10, "RUN_CANCELLED");
                if (request.UserPrompt == "empty")
                    return Result(ConversationRunState.Completed, "", 10);
                if (request.UserPrompt == "slow")
                    return Result(ConversationRunState.Completed, "answer", 100);
                if (request.UserPrompt == "forbidden")
                    return Result(ConversationRunState.Completed, "answer forbidden", 10);
                return Result(ConversationRunState.Completed, "answer required [K1]", 10);
            }
            finally
            {
                Interlocked.Decrement(ref _currentConcurrency);
            }
        }

        private void UpdateMaximum(int value)
        {
            while (true)
            {
                var current = Volatile.Read(ref _maximumConcurrency);
                if (value <= current || Interlocked.CompareExchange(ref _maximumConcurrency, value, current) == current) return;
            }
        }

        private static ConversationRunResult Result(
            ConversationRunState state,
            string response,
            long latencyMilliseconds,
            string? errorCode = null) =>
            new(
                state,
                response,
                new ConversationMetrics(
                    TimeSpan.FromMilliseconds(1),
                    TimeSpan.FromMilliseconds(latencyMilliseconds),
                    2,
                    100),
                [new MLLM.Workbench.Knowledge.RagEvidence(
                    "K1", "doc", "chunk", @"C:\doc.md", "Doc", 0, "excerpt", 1)],
                errorCode,
                errorCode);
    }

    private sealed class CancellingConversationService(CancellationTokenSource cancellation) : IConversationTestService
    {
        public int CallCount { get; private set; }
        public Task<ConversationRuntimeSnapshot> RefreshRuntimeAsync(CancellationToken cancellationToken) =>
            throw new NotSupportedException();

        public Task<ConversationRunResult> RunAsync(
            ConversationRequest request,
            IProgress<ConversationDelta>? progress,
            CancellationToken cancellationToken)
        {
            CallCount++;
            if (request.UserPrompt == "cancel-now")
            {
                progress?.Report(new ConversationDelta("partial"));
                cancellation.Cancel();
                return Task.FromResult(new ConversationRunResult(
                    ConversationRunState.Cancelled,
                    "partial",
                    new ConversationMetrics(TimeSpan.FromMilliseconds(5), TimeSpan.FromMilliseconds(25), null, null),
                    [],
                    "RUN_CANCELLED",
                    "Cancelled"));
            }

            return Task.FromResult(new ConversationRunResult(
                ConversationRunState.Completed,
                "answer",
                new ConversationMetrics(TimeSpan.FromMilliseconds(1), TimeSpan.FromMilliseconds(10), 1, 100),
                []));
        }
    }
}
