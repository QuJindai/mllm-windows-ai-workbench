namespace MLLM.Workbench.Contracts.Protocol;

public sealed record BackendHandshakeRequest(
    string Protocol,
    string SessionToken,
    string ClientVersion);

public sealed record BackendHandshakeResponse(
    bool Accepted,
    string Protocol,
    string BackendVersion,
    string? Error);
