using MLLM.Workbench.Contracts.Protocol;

namespace MLLM.Workbench.Infrastructure.Backend;

public sealed record BackendClientOptions(
    string PipeName,
    string SessionToken,
    string ProjectRoot,
    string DataRoot,
    string NetworkMode,
    string ProtocolVersion = RpcProtocol.Version);
