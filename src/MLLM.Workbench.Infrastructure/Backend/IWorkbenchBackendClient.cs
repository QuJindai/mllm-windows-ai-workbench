using MLLM.Workbench.Contracts.Protocol;
using MLLM.Workbench.Contracts.Snapshots;

namespace MLLM.Workbench.Infrastructure.Backend;

public interface IWorkbenchBackendClient : IAsyncDisposable
{
    Task<BackendHandshakeResponse> ConnectAsync(CancellationToken cancellationToken);
    Task<TResponse> InvokeAsync<TResponse>(string method, object? payload, CancellationToken cancellationToken);
    Task<DashboardSnapshot> GetDashboardAsync(CancellationToken cancellationToken);
    Task<DoctorSnapshot> GetDoctorAsync(CancellationToken cancellationToken);
    Task<InstallerSnapshot> GetInstallerAsync(CancellationToken cancellationToken);
}
