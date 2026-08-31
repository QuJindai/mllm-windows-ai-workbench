using MLLM.Workbench.Knowledge;

namespace MLLM.Workbench.Desktop.Services.Conversation;

public enum ConversationRunState
{
    Completed,
    Cancelled,
    Failed
}

public sealed record ConversationMessage(string Role, string Content);

public sealed record ConversationDelta(string Content);

public sealed record ConversationMetrics(
    TimeSpan? TimeToFirstToken,
    TimeSpan TotalLatency,
    int? CompletionTokens,
    double? TokensPerSecond);

public sealed record ConversationRequest(
    string SystemPrompt,
    string UserPrompt,
    IReadOnlyList<ConversationMessage> History,
    double Temperature,
    int MaxOutputTokens,
    bool UseKnowledge);

public sealed record ConversationRunResult(
    ConversationRunState State,
    string ResponseText,
    ConversationMetrics Metrics,
    IReadOnlyList<RagEvidence> Evidence,
    string? ErrorCode = null,
    string? ErrorMessage = null);

public sealed record ConversationRuntimeSnapshot(
    bool IsReady,
    string ServiceId,
    string ServiceState,
    string? BaseUrl,
    string? ActiveModelId,
    string? ServiceModelId,
    string? BlockedReason);

public class ConversationException : Exception
{
    public ConversationException(string code, string message, Exception? innerException = null)
        : base(message, innerException)
    {
        if (string.IsNullOrWhiteSpace(code))
            throw new ArgumentException("Conversation error code is required.", nameof(code));

        Code = code;
    }

    public string Code { get; }
}

public sealed class ConversationEndpointException : ConversationException
{
    public ConversationEndpointException(string code, string message)
        : base(code, message)
    {
    }
}

public sealed class ConversationProtocolException : ConversationException
{
    public ConversationProtocolException(string code, string message, Exception? innerException = null)
        : base(code, message, innerException)
    {
    }
}

public sealed class ConversationClientException : ConversationException
{
    public ConversationClientException(string code, string message, Exception? innerException = null)
        : base(code, message, innerException)
    {
    }
}
