namespace MLLM.Workbench.Desktop.Services.Conversation;

public interface ILocalConversationClient
{
    Task<ConversationRunResult> StreamAsync(
        LocalConversationEndpoint endpoint,
        ConversationRequest request,
        IProgress<ConversationDelta>? progress,
        CancellationToken cancellationToken);
}
