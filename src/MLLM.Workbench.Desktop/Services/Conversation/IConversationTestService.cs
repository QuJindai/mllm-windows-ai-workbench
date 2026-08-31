namespace MLLM.Workbench.Desktop.Services.Conversation;

public interface IConversationTestService
{
    Task<ConversationRuntimeSnapshot> RefreshRuntimeAsync(CancellationToken cancellationToken);

    Task<ConversationRunResult> RunAsync(
        ConversationRequest request,
        IProgress<ConversationDelta>? progress,
        CancellationToken cancellationToken);
}
