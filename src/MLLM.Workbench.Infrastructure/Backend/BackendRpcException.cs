namespace MLLM.Workbench.Infrastructure.Backend;

public sealed class BackendRpcException : Exception
{
    public BackendRpcException(string code, string message) : base(message)
    {
        Code = code;
    }

    public string Code { get; }
}
