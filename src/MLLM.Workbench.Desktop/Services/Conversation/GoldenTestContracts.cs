namespace MLLM.Workbench.Desktop.Services.Conversation;

public sealed record GoldenTestCase(
    string Id,
    string Name,
    string SystemPrompt,
    string UserPrompt,
    double Temperature,
    int MaxOutputTokens,
    bool UseKnowledge,
    IReadOnlyList<string> MustContain,
    IReadOnlyList<string> MustNotContain,
    long? MaximumTotalLatencyMilliseconds,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt);

public sealed record GoldenTestResult(
    string CaseId,
    string CaseName,
    bool Passed,
    string? FailureCode,
    string? FailureMessage,
    string ResponseText,
    IReadOnlyList<string> EvidenceIds,
    ConversationMetrics Metrics)
{
    public string EvidenceSummary => string.Join(", ", EvidenceIds);
    public string TotalLatencyText =>
        Math.Round(Metrics.TotalLatency.TotalMilliseconds, MidpointRounding.AwayFromZero)
            .ToString("0", System.Globalization.CultureInfo.InvariantCulture) + " ms";
    public string CompletionTokensText =>
        Metrics.CompletionTokens?.ToString(System.Globalization.CultureInfo.InvariantCulture) ?? "Unavailable";
}

public sealed class GoldenCatalogException : ConversationException
{
    public GoldenCatalogException(string code, string message, Exception? innerException = null)
        : base(code, message, innerException)
    {
    }
}
