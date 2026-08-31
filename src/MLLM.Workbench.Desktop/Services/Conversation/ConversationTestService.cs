using MLLM.Workbench.Contracts.Models;
using MLLM.Workbench.Contracts.Services;
using MLLM.Workbench.Desktop.Services.Knowledge;
using MLLM.Workbench.Infrastructure.Backend;
using MLLM.Workbench.Knowledge;

namespace MLLM.Workbench.Desktop.Services.Conversation;

public sealed class ConversationTestService : IConversationTestService
{
    private const string LocalModelServiceId = "local-model-api";
    private readonly IWorkbenchBackendClient _backend;
    private readonly ILocalConversationClient _client;
    private readonly IKnowledgeWorkbenchService _knowledge;

    public ConversationTestService(
        IWorkbenchBackendClient backend,
        ILocalConversationClient client,
        IKnowledgeWorkbenchService knowledge)
    {
        _backend = backend ?? throw new ArgumentNullException(nameof(backend));
        _client = client ?? throw new ArgumentNullException(nameof(client));
        _knowledge = knowledge ?? throw new ArgumentNullException(nameof(knowledge));
    }

    public async Task<ConversationRuntimeSnapshot> RefreshRuntimeAsync(CancellationToken cancellationToken)
    {
        var state = await ReadRuntimeAsync(cancellationToken).ConfigureAwait(false);
        return state.Snapshot;
    }

    public async Task<ConversationRunResult> RunAsync(
        ConversationRequest request,
        IProgress<ConversationDelta>? progress,
        CancellationToken cancellationToken)
    {
        ValidateRequest(request);
        var runtime = await ReadRuntimeAsync(cancellationToken).ConfigureAwait(false);
        if (!runtime.Snapshot.IsReady || runtime.Endpoint is null)
        {
            throw new ConversationRunException(
                runtime.ErrorCode ?? "RUNTIME_NOT_READY",
                runtime.Snapshot.BlockedReason ?? "Local conversation runtime is not ready.");
        }

        var effectiveRequest = request;
        IReadOnlyList<RagEvidence> evidence = [];
        if (request.UseKnowledge)
        {
            var knowledgeSnapshot = await _knowledge.GetSnapshotAsync(cancellationToken).ConfigureAwait(false);
            var mode = knowledgeSnapshot.HybridReady
                ? KnowledgeSearchMode.Hybrid
                : KnowledgeSearchMode.Fts5;
            var hits = await _knowledge
                .SearchAsync(request.UserPrompt.Trim(), mode, 8, cancellationToken)
                .ConfigureAwait(false);
            var rag = RagContextBuilder.Build(hits, maxEvidence: 8, maxCharacters: 12_000);
            if (rag.Evidence.Count == 0)
            {
                throw new ConversationRunException(
                    "NO_EVIDENCE",
                    "Knowledge grounding was requested, but no evidence was found. No answer was generated.");
            }

            evidence = rag.Evidence;
            effectiveRequest = request with
            {
                SystemPrompt = BuildGroundedSystemPrompt(request.SystemPrompt, rag)
            };
        }

        var result = await _client
            .StreamAsync(runtime.Endpoint, effectiveRequest, progress, cancellationToken)
            .ConfigureAwait(false);
        return result with { Evidence = evidence };
    }

    private async Task<RuntimeState> ReadRuntimeAsync(CancellationToken cancellationToken)
    {
        var models = await _backend.GetModelsAsync(cancellationToken).ConfigureAwait(false);
        var services = await _backend.GetServicesAsync(cancellationToken).ConfigureAwait(false);
        var service = services.Services.FirstOrDefault(
            item => string.Equals(item.ServiceId, LocalModelServiceId, StringComparison.Ordinal));

        if (service is null)
        {
            return NotReady(
                new ConversationRuntimeSnapshot(
                    false, LocalModelServiceId, "Missing", null, models.ActiveModelId, null,
                    "Local model API service was not returned by the backend."),
                "SERVICE_NOT_FOUND");
        }

        if (service.State != ManagedServiceState.Running)
        {
            return NotReady(
                Snapshot(service, models, false, "Local model API is not running."),
                "SERVICE_NOT_RUNNING");
        }

        if (string.IsNullOrWhiteSpace(models.ActiveModelId) && string.IsNullOrWhiteSpace(service.ModelId))
        {
            return NotReady(
                Snapshot(service, models, false, "No active model is available for conversation testing."),
                "ACTIVE_MODEL_MISSING");
        }

        try
        {
            var endpoint = LocalConversationEndpoint.FromService(service);
            if (string.IsNullOrWhiteSpace(endpoint.ModelId) && !string.IsNullOrWhiteSpace(models.ActiveModelId))
                endpoint = endpoint with { ModelId = models.ActiveModelId };
            return new RuntimeState(Snapshot(service, models, true, null), endpoint, null);
        }
        catch (ConversationEndpointException ex)
        {
            return NotReady(Snapshot(service, models, false, ex.Message), ex.Code);
        }
    }

    private static ConversationRuntimeSnapshot Snapshot(
        ServiceDescriptor service,
        ModelSnapshot models,
        bool ready,
        string? blockedReason) =>
        new(
            ready,
            service.ServiceId,
            service.State.ToString(),
            service.BaseUrl,
            models.ActiveModelId,
            service.ModelId,
            blockedReason);

    private static RuntimeState NotReady(ConversationRuntimeSnapshot snapshot, string errorCode) =>
        new(snapshot, null, errorCode);

    private static void ValidateRequest(ConversationRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        if (string.IsNullOrWhiteSpace(request.UserPrompt))
            throw new ConversationRunException("PROMPT_REQUIRED", "User prompt is required.");
        if (request.Temperature is < 0d or > 2d)
            throw new ConversationRunException("TEMPERATURE_INVALID", "Temperature must be between 0 and 2.");
        if (request.MaxOutputTokens is < 1 or > 8192)
            throw new ConversationRunException("MAX_TOKENS_INVALID", "Maximum output tokens must be between 1 and 8192.");
    }

    private static string BuildGroundedSystemPrompt(string systemPrompt, RagContext rag)
    {
        var instruction =
            "只允许使用下面提供的知识证据回答。每个事实必须使用对应的 [K1]、[K2] 等证据编号；证据不足时明确说明不足，不得补造。";
        return string.IsNullOrWhiteSpace(systemPrompt)
            ? instruction + Environment.NewLine + Environment.NewLine + rag.ContextText
            : systemPrompt.Trim() + Environment.NewLine + Environment.NewLine + instruction +
              Environment.NewLine + Environment.NewLine + rag.ContextText;
    }

    private sealed record RuntimeState(
        ConversationRuntimeSnapshot Snapshot,
        LocalConversationEndpoint? Endpoint,
        string? ErrorCode);
}
