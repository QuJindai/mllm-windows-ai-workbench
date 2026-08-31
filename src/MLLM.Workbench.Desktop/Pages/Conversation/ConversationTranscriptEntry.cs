namespace MLLM.Workbench.Desktop.Pages.Conversation;

public enum ConversationTranscriptRole
{
    User,
    Assistant,
    Status
}

public sealed record ConversationTranscriptEntry(
    ConversationTranscriptRole Role,
    string Content,
    string? Code = null);
