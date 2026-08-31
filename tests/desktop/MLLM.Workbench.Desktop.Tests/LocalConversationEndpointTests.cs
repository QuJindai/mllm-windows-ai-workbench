using MLLM.Workbench.Contracts.Services;
using MLLM.Workbench.Desktop.Services.Conversation;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class LocalConversationEndpointTests
{
    [Theory]
    [InlineData("http://localhost:8080", "ENDPOINT_NOT_LOOPBACK")]
    [InlineData("http://192.168.1.2:8080", "ENDPOINT_NOT_LOOPBACK")]
    [InlineData("http://8.8.8.8:8080", "ENDPOINT_NOT_LOOPBACK")]
    [InlineData("https://127.0.0.1:8443", "ENDPOINT_SCHEME_INVALID")]
    [InlineData("http://127.0.0.1", "ENDPOINT_PORT_REQUIRED")]
    [InlineData("file:///C:/model.gguf", "ENDPOINT_SCHEME_INVALID")]
    [InlineData("http://user:pass@127.0.0.1:8080", "ENDPOINT_AUTHORITY_INVALID")]
    [InlineData("http://127.0.0.1:8080?x=1", "ENDPOINT_AUTHORITY_INVALID")]
    [InlineData("http://127.0.0.1:8080/#fragment", "ENDPOINT_AUTHORITY_INVALID")]
    public void Unsafe_service_urls_are_rejected(string value, string expectedCode)
    {
        var error = Assert.Throws<ConversationEndpointException>(
            () => LocalConversationEndpoint.FromService(Service(value)));

        Assert.Equal(expectedCode, error.Code);
    }

    [Theory]
    [InlineData("http://127.0.0.1:8080", "http://127.0.0.1:8080/")]
    [InlineData("http://127.1.2.3:9090/", "http://127.1.2.3:9090/")]
    [InlineData("http://[::1]:8123", "http://[::1]:8123/")]
    public void Ip_loopback_with_explicit_port_is_normalized(string value, string expected)
    {
        var endpoint = LocalConversationEndpoint.FromService(Service(value));

        Assert.Equal(expected, endpoint.BaseUri.AbsoluteUri);
        Assert.Equal("local-model-api", endpoint.ServiceId);
        Assert.Equal("qwen-fixture", endpoint.ModelId);
    }

    [Fact]
    public void Only_the_running_authoritative_local_model_service_can_create_an_endpoint()
    {
        AssertEndpointError(Service("http://127.0.0.1:8080") with { ServiceId = "web-workbench" }, "SERVICE_NOT_LOCAL_MODEL_API");
        AssertEndpointError(Service("http://127.0.0.1:8080") with { State = ManagedServiceState.Stopped }, "SERVICE_NOT_RUNNING");
        AssertEndpointError(Service(null), "ENDPOINT_MISSING");
    }

    [Fact]
    public void Malformed_url_is_rejected_without_dns_or_fallback()
    {
        AssertEndpointError(Service("not a uri"), "ENDPOINT_INVALID");
    }

    private static void AssertEndpointError(ServiceDescriptor service, string expectedCode)
    {
        var error = Assert.Throws<ConversationEndpointException>(
            () => LocalConversationEndpoint.FromService(service));
        Assert.Equal(expectedCode, error.Code);
    }

    private static ServiceDescriptor Service(string? baseUrl) =>
        new(
            ServiceId: "local-model-api",
            DisplayName: "Local Model API",
            State: ManagedServiceState.Running,
            Pid: 42,
            Port: 8080,
            BaseUrl: baseUrl,
            StartedAt: DateTimeOffset.Parse("2026-09-01T00:00:00+08:00"),
            UptimeSeconds: 10,
            ModelId: "qwen-fixture",
            ModelPath: @"C:\Models\qwen.gguf",
            HealthSummary: "Healthy",
            StdoutLog: null,
            StderrLog: null,
            CanStart: false,
            CanStop: true,
            CanRestart: true,
            BlockedReason: null);
}
