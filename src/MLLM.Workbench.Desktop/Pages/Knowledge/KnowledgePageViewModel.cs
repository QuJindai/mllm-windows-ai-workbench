using System.Collections.ObjectModel;
using System.Windows.Input;
using MLLM.Workbench.Desktop.Services.Knowledge;
using MLLM.Workbench.Desktop.Shell;
using MLLM.Workbench.Knowledge;

namespace MLLM.Workbench.Desktop.Pages.Knowledge;

public sealed class KnowledgePageViewModel : ObservableObject
{
    private readonly IKnowledgeWorkbenchService _service;
    private readonly IEvidenceLauncher _evidenceLauncher;
    private string _databasePath = "-";
    private string _fts5Status = "检测中";
    private string _embeddingStatus = "检测中";
    private string _hybridStatus = "检测中";
    private string _importPath = string.Empty;
    private string _query = string.Empty;
    private KnowledgeSearchMode _selectedSearchMode = KnowledgeSearchMode.Fts5;
    private KnowledgeSearchHit? _selectedResult;
    private string _ragContextText = string.Empty;
    private string _resultSummary = "0 条证据";
    private string? _lastError;
    private bool _isBusy;
    private bool _embeddingConfigured;
    private bool _fts5Ready;

    public KnowledgePageViewModel(IKnowledgeWorkbenchService service, IEvidenceLauncher evidenceLauncher)
    {
        _service = service ?? throw new ArgumentNullException(nameof(service));
        _evidenceLauncher = evidenceLauncher ?? throw new ArgumentNullException(nameof(evidenceLauncher));

        RefreshCommand = new AsyncRelayCommand(RefreshAsync);
        ImportCommand = new AsyncRelayCommand(ImportAsync);
        SearchCommand = new AsyncRelayCommand(SearchAsync);
        OpenSelectedEvidenceCommand = new AsyncRelayCommand(OpenSelectedEvidenceAsync);
    }

    public string Title => "知识工作台";
    public string Subtitle => "本地 FTS5 · Embedding · Hybrid · RAG 证据链";
    public IReadOnlyList<KnowledgeSearchMode> SearchModes { get; } = Enum.GetValues<KnowledgeSearchMode>();
    public ObservableCollection<KnowledgeSearchHit> Results { get; } = [];

    public ICommand RefreshCommand { get; }
    public ICommand ImportCommand { get; }
    public ICommand SearchCommand { get; }
    public ICommand OpenSelectedEvidenceCommand { get; }

    public string DatabasePath { get => _databasePath; private set => SetProperty(ref _databasePath, value); }
    public string Fts5Status { get => _fts5Status; private set => SetProperty(ref _fts5Status, value); }
    public string EmbeddingStatus { get => _embeddingStatus; private set => SetProperty(ref _embeddingStatus, value); }
    public string HybridStatus { get => _hybridStatus; private set => SetProperty(ref _hybridStatus, value); }
    public string ImportPath { get => _importPath; set => SetProperty(ref _importPath, value); }
    public string Query { get => _query; set => SetProperty(ref _query, value); }
    public KnowledgeSearchMode SelectedSearchMode { get => _selectedSearchMode; set => SetProperty(ref _selectedSearchMode, value); }
    public KnowledgeSearchHit? SelectedResult { get => _selectedResult; set => SetProperty(ref _selectedResult, value); }
    public string RagContextText { get => _ragContextText; private set => SetProperty(ref _ragContextText, value); }
    public string ResultSummary { get => _resultSummary; private set => SetProperty(ref _resultSummary, value); }
    public string? LastError { get => _lastError; private set => SetProperty(ref _lastError, value); }
    public bool IsBusy { get => _isBusy; private set => SetProperty(ref _isBusy, value); }
    public bool CanHybridSearch => _fts5Ready && _embeddingConfigured;

    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        if (IsBusy) return;
        IsBusy = true;
        try
        {
            var snapshot = await _service.GetSnapshotAsync(cancellationToken).ConfigureAwait(true);
            DatabasePath = snapshot.DatabasePath;
            _fts5Ready = snapshot.Fts5Ready;
            _embeddingConfigured = snapshot.EmbeddingConfigured;
            Fts5Status = snapshot.Fts5Ready ? "可用" : "不可用";
            EmbeddingStatus = snapshot.EmbeddingConfigured
                ? FormatEmbeddingStatus(snapshot)
                : "未配置";
            HybridStatus = snapshot.HybridReady ? "可用" : "不可用";
            OnPropertyChanged(nameof(CanHybridSearch));
            LastError = null;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception ex)
        {
            LastError = ex.Message;
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task ImportAsync(CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(ImportPath))
        {
            LastError = "请选择要导入的知识文件。";
            return;
        }

        if (IsBusy) return;
        IsBusy = true;
        try
        {
            await _service.ImportFileAsync(ImportPath.Trim(), cancellationToken).ConfigureAwait(true);
            LastError = null;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception ex)
        {
            LastError = ex.Message;
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task SearchAsync(CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(Query))
        {
            ClearResults();
            LastError = "请输入检索内容。";
            return;
        }

        if (SelectedSearchMode is KnowledgeSearchMode.Embedding or KnowledgeSearchMode.Hybrid && !_embeddingConfigured)
        {
            ClearResults();
            LastError = "Embedding provider 尚未配置。";
            return;
        }

        if (IsBusy) return;
        IsBusy = true;
        try
        {
            var hits = await _service.SearchAsync(Query.Trim(), SelectedSearchMode, 20, cancellationToken).ConfigureAwait(true);
            Results.Clear();
            foreach (var hit in hits) Results.Add(hit);
            SelectedResult = Results.FirstOrDefault();

            var rag = RagContextBuilder.Build(hits, maxEvidence: 8, maxCharacters: 12_000);
            RagContextText = rag.ContextText;
            ResultSummary = $"{rag.Evidence.Count} 条证据";
            LastError = null;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception ex)
        {
            ClearResults();
            LastError = ex.Message;
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task OpenSelectedEvidenceAsync(CancellationToken cancellationToken)
    {
        if (SelectedResult is null)
        {
            LastError = "请先选择一条证据。";
            return;
        }

        try
        {
            await _evidenceLauncher.OpenAsync(SelectedResult.SourceUri, cancellationToken).ConfigureAwait(true);
            LastError = null;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception ex)
        {
            LastError = ex.Message;
        }
    }

    private static string FormatEmbeddingStatus(KnowledgeWorkspaceSnapshot snapshot)
    {
        var provider = string.IsNullOrWhiteSpace(snapshot.EmbeddingProvider) ? "Embedding" : snapshot.EmbeddingProvider;
        return string.IsNullOrWhiteSpace(snapshot.EmbeddingModel)
            ? provider
            : $"{provider} · {snapshot.EmbeddingModel}";
    }

    private void ClearResults()
    {
        Results.Clear();
        SelectedResult = null;
        RagContextText = string.Empty;
        ResultSummary = "0 条证据";
    }

    private void OnPropertyChanged(string propertyName)
    {
        SetProperty(ref _propertyChangePulse, !_propertyChangePulse, propertyName);
    }

    private bool _propertyChangePulse;
}
