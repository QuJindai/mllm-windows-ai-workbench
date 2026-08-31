using System.Text.Json;
using MLLM.Workbench.Contracts.Models;
using MLLM.Workbench.Contracts.Protocol;
using MLLM.Workbench.Contracts.Services;
using MLLM.Workbench.Contracts.Snapshots;
using MLLM.Workbench.Desktop.Services.Conversation;
using MLLM.Workbench.Desktop.Services.Knowledge;
using MLLM.Workbench.Infrastructure.Backend;
using MLLM.Workbench.Knowledge;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class ConversationTestServiceTests
{
    [Fact]
    public async Task Runtime_refresh_uses_only_typed_model_and_exact_local_service_snapshots()
    {
        await using var backend = new FakeBackend(
            new ModelSnapshot([], "active-model", "OFFLINE_CACHE"),
            new ServicesSnapshot([Service("web-workbench"), Service("local-model-api")], "OFFLINE_CACHE"));
        var client = new FakeConversationClient();
        var service = new ConversationTestService(backend, client, new FakeKnowledgeService());

        var runtime = await service.RefreshRuntimeAsync(CancellationToken.None);

        Assert.True(runtime.IsReady);
        Assert.Equal("local-model-api", runtime.ServiceId);
        Assert.Equal("http://127.0.0.1:8080", runtime.BaseUrl);
        Assert.Equal("active-model", runtime.ActiveModelId);
        Assert.Equal("service-model", runtime.ServiceModelId);
        Assert.Equal(["models.snapshot", "services.snapshot"], backend.Methods);
        Assert.DoesNotContain(backend.Methods, value => value.Contains("start", StringComparison.OrdinalIgnoreCase));
        Assert.DoesNotContain(backend.Methods, value => value.Contains("activate", StringComparison.OrdinalIgnoreCase));
    }

    [Theory]
    [InlineData(ManagedServiceState.Stopped, "SERVICE_NOT_RUNNING")]
    [InlineData(ManagedServiceState.Blocked, "SERVICE_NOT_RUNNING")]
    public async Task Nonrunning_service_is_not_ready_and_cannot_run(
        ManagedServiceState state,
        string expectedCode)
    {
        await using var backend = new FakeBackend(
            new ModelSnapshot([], "active-model", "OFFLINE_CACHE"),
            new ServicesSnapshot([Service("local-model-api") with { State = state }], "OFFLINE_CACHE"));
        var client = new FakeConversationClient();
        var service = new ConversationTestService(backend, client, new FakeKnowledgeService());

        var runtime = await service.RefreshRuntimeAsync(CancellationToken.None);
        var error = await Assert.ThrowsAsync<ConversationRunException>(
            () => service.RunAsync(Request(), null, CancellationToken.None));

        Assert.False(runtime.IsReady);
        Assert.Equal(expectedCode, error.Code);
        Assert.Equal(0, client.CallCount);
    }

    [Fact]
    public async Task Hybrid_ready_knowledge_is_bounded_and_injected_as_trusted_evidence()
    {
        await using var backend = ReadyBackend();
        var client = new FakeConversationClient();
        var knowledge = new FakeKnowledgeService
        {
            Snapshot = new KnowledgeWorkspaceSnapshot(
                @"C:\Data\knowledge.db", true, true, "local", "embed", null, 1, 1),
            SearchResults = [Hit()]
        };
        var service = new ConversationTestService(backend, client, knowledge);

        var result = await service.RunAsync(Request(useKnowledge: true), null, CancellationToken.None);

        Assert.Equal(KnowledgeSearchMode.Hybrid, Assert.Single(knowledge.SearchModes));
        Assert.Equal(8, Assert.Single(knowledge.Limits));
        Assert.Contains("[K1]", client.LastRequest!.SystemPrompt, StringComparison.Ordinal);
        Assert.Contains("只允许使用", client.LastRequest.SystemPrompt, StringComparison.Ordinal);
        var evidence = Assert.Single(result.Evidence);
        Assert.Equal("K1", evidence.CitationId);
        Assert.Equal("page=2", evidence.Locator);
        Assert.Equal(1, client.CallCount);
    }

    [Fact]
    public async Task Knowledge_without_complete_embeddings_falls_back_to_fts5()
    {
        await using var backend = ReadyBackend();
        var client = new FakeConversationClient();
        var knowledge = new FakeKnowledgeService
        {
            Snapshot = new KnowledgeWorkspaceSnapshot(
                @"C:\Data\knowledge.db", true, true, "local", "embed", null, 0, 1),
            SearchResults = [Hit()]
        };
        var service = new ConversationTestService(backend, client, knowledge);

        await service.RunAsync(Request(useKnowledge: true), null, CancellationToken.None);

        Assert.Equal(KnowledgeSearchMode.Fts5, Assert.Single(knowledge.SearchModes));
        Assert.Equal(1, client.CallCount);
    }

    [Fact]
    public async Task No_evidence_stops_before_http_inference()
    {
        await using var backend = ReadyBackend();
        var client = new FakeConversationClient();
        var knowledge = new FakeKnowledgeService { SearchResults = [] };
        var service = new ConversationTestService(backend, client, knowledge);

        var error = await Assert.ThrowsAsync<ConversationRunException>(
            () => service.RunAsync(Request(useKnowledge: true), null, CancellationToken.None));

        Assert.Equal("NO_EVIDENCE", error.Code);
        Assert.Equal(0, client.CallCount);
    }

    [Theory]
    [InlineData("", 0.2, 512, "PROMPT_REQUIRED")]
    [InlineData("prompt", -0.1, 512, "TEMPERATURE_INVALID")]
    [InlineData("prompt", 2.1, 512, "TEMPERATURE_INVALID")]
    [InlineData("prompt", 0.2, 0, "MAX_TOKENS_INVALID")]
    [InlineData("prompt", 0.2, 8193, "MAX_TOKENS_INVALID")]
    public async Task Invalid_request_is_rejected_before_backend_or_http(
        string prompt,
        double temperature,
        int maxTokens,
        string expectedCode)
    {
        await using var backend = ReadyBackend();
        var client = new FakeConversationClient();
        var service = new ConversationTestService(backend, client, new FakeKnowledgeService());
        var request = Request() with { UserPrompt = prompt, Temperature = temperature, MaxOutputTokens = maxTokens };

        var error = await Assert.ThrowsAsync<ConversationRunException>(
            () => service.RunAsync(request, null, CancellationToken.None));

        Assert.Equal(expectedCode, error.Code);
        Assert.Empty(backend.Methods);
        Assert.Equal(0, client.CallCount);
    }

    private static FakeBackend ReadyBackend() =>
        new(
            new ModelSnapshot([], "active-model", "OFFLINE_CACHE"),
            new ServicesSnapshot([Service("local-model-api")], "OFFLINE_CACHE"));

    private static ConversationRequest Request(bool useKnowledge = false) =>
        new("Base system prompt.", "车辆证据是什么？", [], 0.2, 512, useKnowledge);

    private static ServiceDescriptor Service(string id) =>
        new(
            id,
            id,
            ManagedServiceState.Running,
            42,
            8080,
            "http://127.0.0.1:8080",
            DateTimeOffset.UtcNow,
            1,
            "service-model",
            @"C:\Models\qwen.gguf",
            "Healthy",
            null,
            null,
            false,
            true,
            true,
            null);

    private static KnowledgeSearchHit Hit() =>
        new(
            "doc-1",
            KnowledgeChunkLocator.CreateChunkId("doc-1", "page=2", 0),
            @"C:\Docs\vehicle.pdf",
            "Vehicle",
            0,
            "整车车辆制造软件版本追溯证据",
            0.9);

    private sealed class FakeConversationClient : ILocalConversationClient
    {
        public int CallCount { get; private set; }
        public ConversationRequest? LastRequest { get; private set; }

        public Task<ConversationRunResult> StreamAsync(
            LocalConversationEndpoint endpoint,
            ConversationRequest request,
            IProgress<ConversationDelta>? progress,
            CancellationToken cancellationToken)
        {
            CallCount++;
            LastRequest = request;
            return Task.FromResult(new ConversationRunResult(
                ConversationRunState.Completed,
                "answer [K1]",
                new ConversationMetrics(TimeSpan.FromMilliseconds(10), TimeSpan.FromMilliseconds(20), 2, 100),
                []));
        }
    }

    private sealed class FakeKnowledgeService : IKnowledgeWorkbenchService
    {
        public KnowledgeWorkspaceSnapshot Snapshot { get; set; } =
            new(@"C:\Data\knowledge.db", true, false, null, null);
        public IReadOnlyList<KnowledgeSearchHit> SearchResults { get; set; } = [Hit()];
        public List<KnowledgeSearchMode> SearchModes { get; } = [];
        public List<int> Limits { get; } = [];

        public Task<KnowledgeWorkspaceSnapshot> GetSnapshotAsync(CancellationToken cancellationToken) =>
            Task.FromResult(Snapshot);

        public Task ImportFileAsync(string path, CancellationToken cancellationToken) =>
            throw new NotSupportedException();

        public Task<KnowledgeWorkspaceSnapshot> BuildEmbeddingIndexAsync(
            IProgress<KnowledgeEmbeddingProgress>? progress,
            CancellationToken cancellationToken) => throw new NotSupportedException();

        public Task<IReadOnlyList<KnowledgeSearchHit>> SearchAsync(
            string query,
            KnowledgeSearchMode mode,
            int limit,
            CancellationToken cancellationToken)
        {
            SearchModes.Add(mode);
            Limits.Add(limit);
            return Task.FromResult(SearchResults);
        }
    }

    private sealed class FakeBackend(ModelSnapshot models, ServicesSnapshot services) : IWorkbenchBackendClient
    {
        public List<string> Methods { get; } = [];

        public Task<TResponse> InvokeAsync<TResponse>(
            string method,
            object? payload,
            CancellationToken cancellationToken)
        {
            Methods.Add(method);
            object response = method switch
            {
                "models.snapshot" => models,
                "services.snapshot" => services,
                _ => throw new InvalidOperationException("Unexpected backend method: " + method)
            };
            return Task.FromResult((TResponse)response);
        }

        public Task<BackendHandshakeResponse> ConnectAsync(CancellationToken cancellationToken) =>
            throw new NotSupportedException();
        public Task<DashboardSnapshot> GetDashboardAsync(CancellationToken cancellationToken) =>
            throw new NotSupportedException();
        public Task<DoctorSnapshot> GetDoctorAsync(CancellationToken cancellationToken) =>
            throw new NotSupportedException();
        public Task<InstallerSnapshot> GetInstallerAsync(CancellationToken cancellationToken) =>
            throw new NotSupportedException();
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
