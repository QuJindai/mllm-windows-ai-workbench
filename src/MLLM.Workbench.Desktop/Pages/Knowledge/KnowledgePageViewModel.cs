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
    private readonly SynchronizationContext? _uiContext;
    private readonly AsyncRelayCommand _buildEmbeddingIndexCommand;
    private string _databasePath = "-";
    private string _fts5Status = "检测中";
    private string _embeddingStatus = "检测中";
    private string _embeddingIndexStatus = "检测中";
    private string _embeddingProgressText = "等待状态刷新";
    private double _embeddingProgressPercent;
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
    private bool _hybridReady;
    private int _embeddingIndexedChunks;
    private int _embeddingTotalChunks;

    public KnowledgePageViewModel(IKnowledgeWorkbenchService service, IEvidenceLauncher evidenceLauncher)
    {
        _service = service ?? throw new ArgumentNullException(nameof(service));
        _evidenceLauncher = evidenceLauncher ?? throw new ArgumentNullException(nameof(evidenceLauncher));
        _uiContext = SynchronizationContext.Current;

        RefreshCommand = new AsyncRelayCommand(RefreshAsync);
        ImportCommand = new AsyncRelayCommand(ImportAsync);
        SearchCommand = new AsyncRelayCommand(SearchAsync);
        _buildEmbeddingIndexCommand = new AsyncRelayCommand(BuildEmbeddingIndexAsync, () => CanBuildEmbeddingIndex);
        BuildEmbeddingIndexCommand = _buildEmbeddingIndexCommand;
        OpenSelectedEvidenceCommand = new AsyncRelayCommand(OpenSelectedEvidenceAsync);
    }

    public string Title => "知识工作台";
    public string Subtitle => "本地 FTS5 · Embedding · Hybrid · RAG 证据链";
    public IReadOnlyList<KnowledgeSearchMode> SearchModes { get; } = Enum.GetValues<KnowledgeSearchMode>();
    public ObservableCollection<KnowledgeSearchHit> Results { get; } = [];

    public ICommand RefreshCommand { get; }
    public ICommand ImportCommand { get; }
    public ICommand SearchCommand { get; }
    public ICommand BuildEmbeddingIndexCommand { get; }
    public ICommand OpenSelectedEvidenceCommand { get; }

    public string DatabasePath { get => _databasePath; private set => SetProperty(ref _databasePath, value); }
    public string Fts5Status { get => _fts5Status; private set => SetProperty(ref _fts5Status, value); }
    public string EmbeddingStatus { get => _embeddingStatus; private set => SetProperty(ref _embeddingStatus, value); }
    public string EmbeddingIndexStatus { get => _embeddingIndexStatus; private set => SetProperty(ref _embeddingIndexStatus, value); }
    public string EmbeddingProgressText { get => _embeddingProgressText; private set => SetProperty(ref _embeddingProgressText, value); }
    public double EmbeddingProgressPercent { get => _embeddingProgressPercent; private set => SetProperty(ref _embeddingProgressPercent, value); }
    public string HybridStatus { get => _hybridStatus; private set => SetProperty(ref _hybridStatus, value); }
    public string ImportPath { get => _importPath; set => SetProperty(ref _importPath, value); }
    public string Query { get => _query; set => SetProperty(ref _query, value); }
    public KnowledgeSearchMode SelectedSearchMode { get => _selectedSearchMode; set => SetProperty(ref _selectedSearchMode, value); }
    public KnowledgeSearchHit? SelectedResult { get => _selectedResult; set => SetProperty(ref _selectedResult, value); }
    public string RagContextText { get => _ragContextText; private set => SetProperty(ref _ragContextText, value); }
    public string ResultSummary { get => _resultSummary; private set => SetProperty(ref _resultSummary, value); }
    public string? LastError { get => _lastError; private set => SetProperty(ref _lastError, value); }
    public bool IsBusy { get => _isBusy; private set => SetProperty(ref _isBusy, value); }
    public bool CanHybridSearch => _hybridReady;
    public bool CanBuildEmbeddingIndex =>
        _embeddingConfigured && _embeddingTotalChunks > _embeddingIndexedChunks;

    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        if (IsBusy) return;
        IsBusy = true;
        try
        {
            var snapshot = await _service.GetSnapshotAsync(cancellationToken).ConfigureAwait(true);
            ApplySnapshot(snapshot, resetProgressText: true);
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
            var snapshot = await _service.GetSnapshotAsync(cancellationToken).ConfigureAwait(true);
            ApplySnapshot(snapshot, resetProgressText: true);
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

    public async Task BuildEmbeddingIndexAsync(CancellationToken cancellationToken)
    {
        if (!CanBuildEmbeddingIndex)
        {
            LastError = _embeddingConfigured
                ? "当前向量索引已完整，无需补建。"
                : "Embedding provider 尚未配置。";
            return;
        }

        if (IsBusy) return;
        IsBusy = true;
        try
        {
            EmbeddingProgressText = "准备构建向量索引...";
            LastError = null;

            var progress = new InlineProgress<KnowledgeEmbeddingProgress>(ReportEmbeddingProgress);
            var snapshot = await _service
                .BuildEmbeddingIndexAsync(progress, cancellationToken)
                .ConfigureAwait(true);

            ApplySnapshot(snapshot, resetProgressText: false);
            EmbeddingProgressText = $"完成 · {snapshot.EmbeddingIndexedChunks}/{snapshot.EmbeddingTotalChunks} · {EmbeddingProgressPercent:0}%";
            LastError = null;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception ex)
        {
            EmbeddingProgressText = "构建失败";
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

        if (SelectedSearchMode == KnowledgeSearchMode.Embedding && !_embeddingConfigured)
        {
            ClearResults();
            LastError = "Embedding provider 尚未配置。";
            return;
        }

        if (SelectedSearchMode == KnowledgeSearchMode.Hybrid && !CanHybridSearch)
        {
            ClearResults();
            LastError = _embeddingConfigured
                ? "Hybrid 检索尚不可用：请先补齐当前知识库的向量索引。"
                : "Embedding provider 尚未配置。";
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

    private void ApplySnapshot(KnowledgeWorkspaceSnapshot snapshot, bool resetProgressText)
    {
        DatabasePath = snapshot.DatabasePath;
        _fts5Ready = snapshot.Fts5Ready;
        _embeddingConfigured = snapshot.EmbeddingConfigured;
        _hybridReady = snapshot.HybridReady;
        _embeddingIndexedChunks = snapshot.EmbeddingIndexedChunks;
        _embeddingTotalChunks = snapshot.EmbeddingTotalChunks;

        Fts5Status = snapshot.Fts5Ready ? "可用" : "不可用";

        if (!string.IsNullOrWhiteSpace(snapshot.EmbeddingConfigurationError))
        {
            EmbeddingStatus = $"配置错误: {snapshot.EmbeddingConfigurationError}";
            EmbeddingIndexStatus = $"配置错误: {snapshot.EmbeddingConfigurationError}";
        }
        else if (!snapshot.EmbeddingConfigured)
        {
            EmbeddingStatus = "未配置";
            EmbeddingIndexStatus = "未配置";
        }
        else
        {
            EmbeddingStatus = FormatEmbeddingStatus(snapshot);
            EmbeddingIndexStatus = $"已配置 · {snapshot.EmbeddingIndexedChunks}/{snapshot.EmbeddingTotalChunks} 已索引";
        }

        HybridStatus = snapshot.HybridReady
            ? "可用"
            : snapshot.EmbeddingConfigured
                ? "待补齐向量索引"
                : "不可用";

        EmbeddingProgressPercent = snapshot.EmbeddingConfigured
            ? Math.Clamp(snapshot.EmbeddingCoverage * 100d, 0d, 100d)
            : 0d;

        if (resetProgressText)
        {
            EmbeddingProgressText = !string.IsNullOrWhiteSpace(snapshot.EmbeddingConfigurationError)
                ? "配置错误"
                : snapshot.EmbeddingConfigured
                    ? $"{snapshot.EmbeddingIndexedChunks}/{snapshot.EmbeddingTotalChunks} · {EmbeddingProgressPercent:0}%"
                    : "未配置";
        }

        OnPropertyChanged(nameof(CanHybridSearch));
        OnPropertyChanged(nameof(CanBuildEmbeddingIndex));
        _buildEmbeddingIndexCommand.RaiseCanExecuteChanged();
    }

    private void ReportEmbeddingProgress(KnowledgeEmbeddingProgress progress)
    {
        if (_uiContext is null || ReferenceEquals(SynchronizationContext.Current, _uiContext))
        {
            ApplyEmbeddingProgress(progress);
            return;
        }

        _uiContext.Send(_ => ApplyEmbeddingProgress(progress), null);
    }

    private void ApplyEmbeddingProgress(KnowledgeEmbeddingProgress progress)
    {
        var percent = Math.Clamp(progress.Fraction * 100d, 0d, 100d);
        EmbeddingProgressPercent = percent;
        EmbeddingProgressText = $"{progress.Completed}/{progress.Total} · {percent:0}% · {progress.CurrentChunkId}";
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

    private sealed class InlineProgress<T>(Action<T> report) : IProgress<T>
    {
        public void Report(T value) => report(value);
    }
}
