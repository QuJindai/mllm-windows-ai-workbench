using MLLM.Workbench.Contracts.Models;
using MLLM.Workbench.Contracts.Protocol;
using MLLM.Workbench.Contracts.Services;
using MLLM.Workbench.Contracts.Snapshots;

namespace MLLM.Workbench.Infrastructure.Backend;

public interface IWorkbenchBackendClient : IAsyncDisposable
{
    Task<BackendHandshakeResponse> ConnectAsync(CancellationToken cancellationToken);
    Task<TResponse> InvokeAsync<TResponse>(string method, object? payload, CancellationToken cancellationToken);
    Task<DashboardSnapshot> GetDashboardAsync(CancellationToken cancellationToken);
    Task<DoctorSnapshot> GetDoctorAsync(CancellationToken cancellationToken);
    Task<InstallerSnapshot> GetInstallerAsync(CancellationToken cancellationToken);

    Task<BackendCapabilitiesSnapshot> GetCapabilitiesAsync(CancellationToken cancellationToken) =>
        InvokeAsync<BackendCapabilitiesSnapshot>("system.capabilities", null, cancellationToken);

    Task<ModelSnapshot> GetModelsAsync(CancellationToken cancellationToken) =>
        InvokeAsync<ModelSnapshot>("models.snapshot", null, cancellationToken);

    Task<ModelDescriptor> VerifyModelAsync(ModelVerifyRequest request, CancellationToken cancellationToken) =>
        InvokeAsync<ModelDescriptor>("models.verify", request, cancellationToken);

    Task<ModelDescriptor> ImportModelAsync(ModelImportRequest request, CancellationToken cancellationToken) =>
        InvokeAsync<ModelDescriptor>("models.import", request, cancellationToken);

    Task<ModelDescriptor> ActivateModelAsync(ModelActivateRequest request, CancellationToken cancellationToken) =>
        InvokeAsync<ModelDescriptor>("models.activate", request, cancellationToken);

    Task<ServicesSnapshot> GetServicesAsync(CancellationToken cancellationToken) =>
        InvokeAsync<ServicesSnapshot>("services.snapshot", null, cancellationToken);

    Task<ServiceDescriptor> StartServiceAsync(ServiceActionRequest request, CancellationToken cancellationToken) =>
        InvokeAsync<ServiceDescriptor>("service.start", request, cancellationToken);

    Task<ServiceDescriptor> StopServiceAsync(ServiceActionRequest request, CancellationToken cancellationToken) =>
        InvokeAsync<ServiceDescriptor>("service.stop", request, cancellationToken);

    Task<ServiceDescriptor> RestartServiceAsync(ServiceActionRequest request, CancellationToken cancellationToken) =>
        InvokeAsync<ServiceDescriptor>("service.restart", request, cancellationToken);

    Task<ServiceLogTail> GetServiceLogsAsync(ServiceLogRequest request, CancellationToken cancellationToken) =>
        InvokeAsync<ServiceLogTail>("service.logs", request, cancellationToken);
}
