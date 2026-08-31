namespace MLLM.Workbench.Desktop.Services.Conversation;

public sealed class GoldenTestEvaluator
{
    private static readonly ConversationMetrics EmptyMetrics = new(null, TimeSpan.Zero, null, null);
    private readonly IConversationTestService _service;

    public GoldenTestEvaluator(IConversationTestService service)
    {
        _service = service ?? throw new ArgumentNullException(nameof(service));
    }

    public async Task<IReadOnlyList<GoldenTestResult>> RunAsync(
        IReadOnlyList<GoldenTestCase> cases,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(cases);
        var results = new List<GoldenTestResult>(cases.Count);
        foreach (var testCase in cases)
        {
            cancellationToken.ThrowIfCancellationRequested();
            results.Add(await RunCaseAsync(testCase, cancellationToken).ConfigureAwait(false));
        }
        return results;
    }

    private async Task<GoldenTestResult> RunCaseAsync(
        GoldenTestCase testCase,
        CancellationToken cancellationToken)
    {
        try
        {
            var result = await _service.RunAsync(
                new ConversationRequest(
                    testCase.SystemPrompt,
                    testCase.UserPrompt,
                    [],
                    testCase.Temperature,
                    testCase.MaxOutputTokens,
                    testCase.UseKnowledge),
                null,
                cancellationToken).ConfigureAwait(false);

            if (result.State == ConversationRunState.Cancelled)
                return Failed(testCase, result, result.ErrorCode ?? "RUN_CANCELLED", result.ErrorMessage);
            if (result.State == ConversationRunState.Failed)
                return Failed(testCase, result, result.ErrorCode ?? "RUN_FAILED", result.ErrorMessage);
            if (string.IsNullOrWhiteSpace(result.ResponseText))
                return Failed(testCase, result, "RESPONSE_EMPTY", "Conversation response was empty.");

            var missing = testCase.MustContain.FirstOrDefault(
                fragment => !result.ResponseText.Contains(fragment, StringComparison.OrdinalIgnoreCase));
            if (missing is not null)
                return Failed(testCase, result, "REQUIRED_TEXT_MISSING", $"Required text was missing: {missing}");

            var forbidden = testCase.MustNotContain.FirstOrDefault(
                fragment => result.ResponseText.Contains(fragment, StringComparison.OrdinalIgnoreCase));
            if (forbidden is not null)
                return Failed(testCase, result, "FORBIDDEN_TEXT_PRESENT", $"Forbidden text was present: {forbidden}");

            if (testCase.MaximumTotalLatencyMilliseconds is long maximum &&
                result.Metrics.TotalLatency.TotalMilliseconds > maximum)
            {
                return Failed(
                    testCase,
                    result,
                    "LATENCY_LIMIT_EXCEEDED",
                    $"Total latency exceeded {maximum} ms.");
            }

            return ToResult(testCase, result, true, null, null);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (ConversationException ex)
        {
            return new GoldenTestResult(
                testCase.Id,
                testCase.Name,
                false,
                ex.Code,
                ex.Message,
                string.Empty,
                [],
                EmptyMetrics);
        }
        catch (Exception ex)
        {
            return new GoldenTestResult(
                testCase.Id,
                testCase.Name,
                false,
                "RUN_FAILED",
                ex.Message,
                string.Empty,
                [],
                EmptyMetrics);
        }
    }

    private static GoldenTestResult Failed(
        GoldenTestCase testCase,
        ConversationRunResult result,
        string code,
        string? message) => ToResult(testCase, result, false, code, message);

    private static GoldenTestResult ToResult(
        GoldenTestCase testCase,
        ConversationRunResult result,
        bool passed,
        string? failureCode,
        string? failureMessage) =>
        new(
            testCase.Id,
            testCase.Name,
            passed,
            failureCode,
            failureMessage,
            result.ResponseText,
            result.Evidence.Select(item => item.CitationId).ToArray(),
            result.Metrics);
}
