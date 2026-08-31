using System.Net;
using MLLM.Workbench.Contracts.Services;

namespace MLLM.Workbench.Desktop.Services.Conversation;

public sealed record LocalConversationEndpoint(
    Uri BaseUri,
    string ServiceId,
    string? ModelId)
{
    public static LocalConversationEndpoint FromService(ServiceDescriptor service)
    {
        ArgumentNullException.ThrowIfNull(service);

        if (!string.Equals(service.ServiceId, "local-model-api", StringComparison.Ordinal))
            throw Error("SERVICE_NOT_LOCAL_MODEL_API", "Conversation endpoint must come from local-model-api.");

        if (service.State != ManagedServiceState.Running)
            throw Error("SERVICE_NOT_RUNNING", "Local model API is not running.");

        if (string.IsNullOrWhiteSpace(service.BaseUrl))
            throw Error("ENDPOINT_MISSING", "Local model API did not report an endpoint.");

        if (!Uri.TryCreate(service.BaseUrl.Trim(), UriKind.Absolute, out var parsed))
            throw Error("ENDPOINT_INVALID", "Local model API endpoint is not a valid absolute URI.");

        if (!string.Equals(parsed.Scheme, Uri.UriSchemeHttp, StringComparison.OrdinalIgnoreCase))
            throw Error("ENDPOINT_SCHEME_INVALID", "Local model API endpoint must use HTTP.");

        if (!string.IsNullOrEmpty(parsed.UserInfo) ||
            !string.IsNullOrEmpty(parsed.Query) ||
            !string.IsNullOrEmpty(parsed.Fragment) ||
            (parsed.AbsolutePath.Length > 1 && parsed.AbsolutePath != "/"))
        {
            throw Error("ENDPOINT_AUTHORITY_INVALID", "Local model API endpoint contains unsupported authority or path data.");
        }

        if (parsed.IsDefaultPort || parsed.Port <= 0)
            throw Error("ENDPOINT_PORT_REQUIRED", "Local model API endpoint must include an explicit non-default port.");

        if (!IPAddress.TryParse(parsed.Host, out var address) || !IPAddress.IsLoopback(address))
            throw Error("ENDPOINT_NOT_LOOPBACK", "Local model API endpoint must use an IP loopback address.");

        var normalized = new UriBuilder(Uri.UriSchemeHttp, parsed.Host, parsed.Port, "/").Uri;
        return new LocalConversationEndpoint(normalized, service.ServiceId, service.ModelId);
    }

    private static ConversationEndpointException Error(string code, string message) => new(code, message);
}
