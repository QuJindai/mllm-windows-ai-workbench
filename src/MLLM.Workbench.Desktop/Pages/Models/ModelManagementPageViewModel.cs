using System.Collections.ObjectModel;
using System.Windows.Input;
using MLLM.Workbench.Contracts.Models;
using MLLM.Workbench.Contracts.Services;
using MLLM.Workbench.Desktop.Services;
using MLLM.Workbench.Desktop.Shell;
using MLLM.Workbench.Infrastructure.Backend;

namespace MLLM.Workbench.Desktop.Pages.Models;

public sealed class ModelManagementPageViewModel : ObservableObject
{
    private static readonly HashSet<ModelIntegrityState> StructurallyValidStates =
    [
        ModelIntegrityState.StructuralPass,
        ModelIntegrityState.HashComputedUnanchored,
        ModelIntegrityState.Sha256Pass
    ];

    private readonly IWorkbenchBackendClient _backend;
    private readonly WorkbenchMutationGate _mutationGate;
    private ServicesSnapshot? _services;
    private ModelDescriptor? _selectedModel;
    private string _networkMode = "-";
    private string _activeModelDisplay = "未激活";
    private string? _backendError;
    private bool _isBusy;
    private int _totalCount;
    private int _structurallyValidCount;
    private int _trustedShaCount;

    public ModelManagementPageViewModel(IWorkbenchBackendClient backend, WorkbenchMutationGate mutationGate)
    {
        _backend = backend ?? throw new ArgumentNullException(nameof(backend));
        _mutationGate = mutationGate ?? throw new ArgumentNullException(nameof(mutationGate));
        RefreshCommand = new AsyncRelayCommand(RefreshAsync);
    }

    public string Title => "模型管理";
    public string Subtitle => "本地 GGUF 模型发现、校验、导入和激活";
    public ObservableCollection<ModelDescriptor> Models { get; } = [];
    public ICommand RefreshCommand { get; }

    public ModelDescriptor? SelectedModel
    {
        get => _selectedModel;
        set => SetProperty(ref _selectedModel, value);
    }

    public string NetworkMode { get => _networkMode; private set => SetProperty(ref _networkMode, value); }
    public string ActiveModelDisplay { get => _activeModelDisplay; private set => SetProperty(ref _activeModelDisplay, value); }
    public string? BackendError { get => _backendError; private set => SetProperty(ref _backendError, value); }
    public bool IsBusy { get => _isBusy; private set => SetProperty(ref _isBusy, value); }
    public int TotalCount { get => _totalCount; private set => SetProperty(ref _totalCount, value); }
    public int StructurallyValidCount { get => _structurallyValidCount; private set => SetProperty(ref _structurallyValidCount, value); }
    public int TrustedShaCount { get => _trustedShaCount; private set => SetProperty(ref _trustedShaCount, value); }

    public bool CanActivate =>
        SelectedModel is not null &&
        StructurallyValidStates.Contains(SelectedModel.IntegrityState) &&
        string.IsNullOrWhiteSpace(SelectedModel.ActivationBlockedReason) &&
        IsLocalModelServiceStopped();

    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        if (IsBusy) return;
        IsBusy = true;
        try
        {
            var selectedId = SelectedModel?.Id;
            var modelsTask = _backend.GetModelsAsync(cancellationToken);
            var servicesTask = _backend.GetServicesAsync(cancellationToken);
            await Task.WhenAll(modelsTask, servicesTask).ConfigureAwait(true);

            var snapshot = await modelsTask.ConfigureAwait(true);
            _services = await servicesTask.ConfigureAwait(true);
            Apply(snapshot, selectedId);
            BackendError = null;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception ex)
        {
            BackendError = ex.Message;
        }
        finally
        {
            IsBusy = false;
        }
    }

    public Task ImportAsync(string sourcePath, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(sourcePath))
            throw new ArgumentException("Model source path is required.", nameof(sourcePath));

        return RunMutationAsync(
            ct => _backend.ImportModelAsync(new ModelImportRequest(sourcePath, null, NewOperationId()), ct),
            cancellationToken);
    }

    public Task VerifyAsync(CancellationToken cancellationToken)
    {
        var model = SelectedModel ?? throw new InvalidOperationException("Select a model before verification.");
        return RunMutationAsync(
            ct => _backend.VerifyModelAsync(new ModelVerifyRequest(model.Id, NewOperationId()), ct),
            cancellationToken);
    }

    public Task ActivateAsync(CancellationToken cancellationToken)
    {
        var model = SelectedModel ?? throw new InvalidOperationException("Select a model before activation.");
        if (!CanActivate)
            throw new InvalidOperationException("The selected model cannot be activated while invalid, blocked, or the local model service is running.");

        return RunMutationAsync(
            ct => _backend.ActivateModelAsync(new ModelActivateRequest(model.Id, NewOperationId()), ct),
            cancellationToken);
    }

    private async Task RunMutationAsync(Func<CancellationToken, Task<ModelDescriptor>> action, CancellationToken cancellationToken)
    {
        try
        {
            await _mutationGate.RunAsync(async ct =>
            {
                await action(ct).ConfigureAwait(false);
            }, cancellationToken).ConfigureAwait(true);
            BackendError = null;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception ex)
        {
            BackendError = ex.Message;
            throw;
        }
    }

    private void Apply(ModelSnapshot snapshot, string? selectedId)
    {
        NetworkMode = snapshot.NetworkMode;
        Models.Clear();
        foreach (var model in snapshot.Models) Models.Add(model);

        TotalCount = snapshot.Models.Count;
        StructurallyValidCount = snapshot.Models.Count(x => StructurallyValidStates.Contains(x.IntegrityState));
        TrustedShaCount = snapshot.Models.Count(x => x.IntegrityState == ModelIntegrityState.Sha256Pass);

        var active = snapshot.Models.FirstOrDefault(x => x.IsActive || string.Equals(x.Id, snapshot.ActiveModelId, StringComparison.OrdinalIgnoreCase));
        ActiveModelDisplay = active is null
            ? (string.IsNullOrWhiteSpace(snapshot.ActiveModelId) ? "未激活" : snapshot.ActiveModelId)
            : $"{active.DisplayName} ({active.Id})";

        SelectedModel = string.IsNullOrWhiteSpace(selectedId)
            ? null
            : snapshot.Models.FirstOrDefault(x => string.Equals(x.Id, selectedId, StringComparison.OrdinalIgnoreCase));
    }

    private bool IsLocalModelServiceStopped()
    {
        if (_services is null) return false;
        var local = _services.Services.FirstOrDefault(x =>
            string.Equals(x.ServiceId, "local-model-api", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(x.ServiceId, "local-api", StringComparison.OrdinalIgnoreCase));
        return local is null || local.State == ManagedServiceState.Stopped;
    }

    private static string NewOperationId() => Guid.NewGuid().ToString("N");
}
