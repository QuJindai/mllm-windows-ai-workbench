using System.Collections.ObjectModel;
using System.Globalization;
using System.Windows.Input;
using MLLM.Workbench.Desktop.Services.Conversation;
using MLLM.Workbench.Desktop.Services.Knowledge;
using MLLM.Workbench.Desktop.Shell;
using MLLM.Workbench.Knowledge;

namespace MLLM.Workbench.Desktop.Pages.Conversation;

public sealed class ConversationPageViewModel : ObservableObject
{
    private const int MaximumHistoryMessages = 20;
    private const int MaximumHistoryCharacters = 12_000;
    private readonly IConversationTestService _service;
    private readonly IGoldenTestCatalog _catalog;
    private readonly GoldenTestEvaluator _evaluator;
    private readonly IEvidenceLauncher _evidenceLauncher;
    private readonly SynchronizationContext? _uiContext;
    private readonly AsyncRelayCommand _sendCommand;
    private readonly RelayCommand _cancelCommand;
    private readonly RelayCommand _clearCommand;
    private readonly AsyncRelayCommand _saveGoldenAsNewCommand;
    private readonly AsyncRelayCommand _updateSelectedGoldenCommand;
    private readonly AsyncRelayCommand _deleteGoldenCommand;
    private readonly AsyncRelayCommand _runSelectedGoldenCommand;
    private readonly AsyncRelayCommand _runAllGoldenCommand;
    private readonly AsyncRelayCommand _openEvidenceCommand;
    private readonly List<ConversationMessage> _completedHistory = [];
    private CancellationTokenSource? _activeRun;
    private string _systemPrompt = string.Empty;
    private string _userPrompt = string.Empty;
    private double _temperature = 0.2;
    private int _maxOutputTokens = 512;
    private bool _includeHistory = true;
    private bool _useKnowledge;
    private bool _isRuntimeReady;
    private string _runtimeStatus = "Not checked";
    private string _endpoint = "-";
    private string _activeModel = "-";
    private string _serviceModel = "-";
    private string _timeToFirstTokenText = "-";
    private string _totalLatencyText = "-";
    private string _completionTokensText = "-";
    private string _tokensPerSecondText = "-";
    private string? _lastError;
    private string? _lastErrorCode;
    private bool _isBusy;
    private bool _isRunActive;
    private RagEvidence? _selectedEvidence;
    private GoldenTestCase? _selectedGoldenCase;
    private string _goldenName = string.Empty;
    private string _goldenMustContain = string.Empty;
    private string _goldenMustNotContain = string.Empty;
    private long? _goldenMaximumLatencyMilliseconds;

    public ConversationPageViewModel(
        IConversationTestService service,
        IGoldenTestCatalog catalog,
        GoldenTestEvaluator evaluator,
        IEvidenceLauncher evidenceLauncher)
    {
        _service = service ?? throw new ArgumentNullException(nameof(service));
        _catalog = catalog ?? throw new ArgumentNullException(nameof(catalog));
        _evaluator = evaluator ?? throw new ArgumentNullException(nameof(evaluator));
        _evidenceLauncher = evidenceLauncher ?? throw new ArgumentNullException(nameof(evidenceLauncher));
        _uiContext = SynchronizationContext.Current;

        RefreshCommand = new AsyncRelayCommand(RefreshAsync);
        _sendCommand = new AsyncRelayCommand(SendAsync, () => CanSend);
        SendCommand = _sendCommand;
        _cancelCommand = new RelayCommand(CancelActiveRun, () => IsRunActive);
        CancelCommand = _cancelCommand;
        _clearCommand = new RelayCommand(ClearConversation, () => !IsRunActive);
        ClearCommand = _clearCommand;
        _saveGoldenAsNewCommand = new AsyncRelayCommand(SaveGoldenAsNewAsync, () => !IsBusy);
        SaveGoldenAsNewCommand = _saveGoldenAsNewCommand;
        _updateSelectedGoldenCommand = new AsyncRelayCommand(
            UpdateSelectedGoldenAsync,
            () => !IsBusy && SelectedGoldenCase is not null);
        UpdateSelectedGoldenCommand = _updateSelectedGoldenCommand;
        _deleteGoldenCommand = new AsyncRelayCommand(DeleteGoldenAsync, () => !IsBusy && SelectedGoldenCase is not null);
        DeleteGoldenCommand = _deleteGoldenCommand;
        _runSelectedGoldenCommand = new AsyncRelayCommand(
            RunSelectedGoldenAsync,
            () => !IsBusy && SelectedGoldenCase is not null);
        RunSelectedGoldenCommand = _runSelectedGoldenCommand;
        _runAllGoldenCommand = new AsyncRelayCommand(RunAllGoldenAsync, () => !IsBusy && GoldenCases.Count > 0);
        RunAllGoldenCommand = _runAllGoldenCommand;
        _openEvidenceCommand = new AsyncRelayCommand(
            OpenSelectedEvidenceAsync,
            () => !IsBusy && SelectedEvidence is not null);
        OpenSelectedEvidenceCommand = _openEvidenceCommand;
    }

    public string Title => "对话测试";
    public string Subtitle => "本机 OpenAI API · 流式指标 · Knowledge 证据 · Golden Test";
    public ObservableCollection<ConversationTranscriptEntry> Transcript { get; } = [];
    public ObservableCollection<RagEvidence> Evidence { get; } = [];
    public ObservableCollection<GoldenTestCase> GoldenCases { get; } = [];
    public ObservableCollection<GoldenTestResult> GoldenResults { get; } = [];

    public ICommand RefreshCommand { get; }
    public ICommand SendCommand { get; }
    public ICommand CancelCommand { get; }
    public ICommand ClearCommand { get; }
    public ICommand SaveGoldenAsNewCommand { get; }
    public ICommand UpdateSelectedGoldenCommand { get; }
    public ICommand DeleteGoldenCommand { get; }
    public ICommand RunSelectedGoldenCommand { get; }
    public ICommand RunAllGoldenCommand { get; }
    public ICommand OpenSelectedEvidenceCommand { get; }

    public string SystemPrompt { get => _systemPrompt; set => SetProperty(ref _systemPrompt, value); }
    public string UserPrompt
    {
        get => _userPrompt;
        set
        {
            if (SetProperty(ref _userPrompt, value)) RaiseCommandStates();
        }
    }
    public double Temperature { get => _temperature; set => SetProperty(ref _temperature, value); }
    public int MaxOutputTokens { get => _maxOutputTokens; set => SetProperty(ref _maxOutputTokens, value); }
    public bool IncludeHistory { get => _includeHistory; set => SetProperty(ref _includeHistory, value); }
    public bool UseKnowledge { get => _useKnowledge; set => SetProperty(ref _useKnowledge, value); }
    public bool IsRuntimeReady { get => _isRuntimeReady; private set => SetProperty(ref _isRuntimeReady, value); }
    public string RuntimeStatus { get => _runtimeStatus; private set => SetProperty(ref _runtimeStatus, value); }
    public string Endpoint { get => _endpoint; private set => SetProperty(ref _endpoint, value); }
    public string ActiveModel { get => _activeModel; private set => SetProperty(ref _activeModel, value); }
    public string ServiceModel { get => _serviceModel; private set => SetProperty(ref _serviceModel, value); }
    public string TimeToFirstTokenText { get => _timeToFirstTokenText; private set => SetProperty(ref _timeToFirstTokenText, value); }
    public string TotalLatencyText { get => _totalLatencyText; private set => SetProperty(ref _totalLatencyText, value); }
    public string CompletionTokensText { get => _completionTokensText; private set => SetProperty(ref _completionTokensText, value); }
    public string TokensPerSecondText { get => _tokensPerSecondText; private set => SetProperty(ref _tokensPerSecondText, value); }
    public string? LastError { get => _lastError; private set => SetProperty(ref _lastError, value); }
    public string? LastErrorCode { get => _lastErrorCode; private set => SetProperty(ref _lastErrorCode, value); }
    public bool IsBusy { get => _isBusy; private set => SetProperty(ref _isBusy, value); }
    public bool IsRunActive { get => _isRunActive; private set => SetProperty(ref _isRunActive, value); }
    public bool CanSend =>
        IsRuntimeReady &&
        !IsBusy &&
        !IsRunActive &&
        !string.IsNullOrWhiteSpace(UserPrompt);

    public RagEvidence? SelectedEvidence
    {
        get => _selectedEvidence;
        set
        {
            if (SetProperty(ref _selectedEvidence, value)) RaiseCommandStates();
        }
    }

    public GoldenTestCase? SelectedGoldenCase
    {
        get => _selectedGoldenCase;
        set
        {
            if (!SetProperty(ref _selectedGoldenCase, value)) return;
            if (value is not null) ApplyGoldenCase(value);
            RaiseCommandStates();
        }
    }

    public string GoldenName { get => _goldenName; set => SetProperty(ref _goldenName, value); }
    public string GoldenMustContain { get => _goldenMustContain; set => SetProperty(ref _goldenMustContain, value); }
    public string GoldenMustNotContain { get => _goldenMustNotContain; set => SetProperty(ref _goldenMustNotContain, value); }
    public long? GoldenMaximumLatencyMilliseconds
    {
        get => _goldenMaximumLatencyMilliseconds;
        set => SetProperty(ref _goldenMaximumLatencyMilliseconds, value);
    }

    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        if (IsBusy) return;
        SetBusy(true);
        try
        {
            var runtime = await _service.RefreshRuntimeAsync(cancellationToken).ConfigureAwait(true);
            ClearError();
            ApplyRuntime(runtime);
            await ReloadGoldenCasesAsync(SelectedGoldenCase?.Id, cancellationToken).ConfigureAwait(true);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (ConversationException ex)
        {
            SetError(ex.Code, ex.Message);
        }
        catch (Exception ex)
        {
            SetError("REFRESH_FAILED", ex.Message);
        }
        finally
        {
            SetBusy(false);
        }
    }

    public async Task SendAsync(CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(UserPrompt))
        {
            SetError("PROMPT_REQUIRED", "请输入对话内容。");
            return;
        }
        if (IsBusy || IsRunActive) return;

        var history = IncludeHistory ? BuildHistory() : [];
        var userText = UserPrompt.Trim();
        var userEntry = new ConversationTranscriptEntry(ConversationTranscriptRole.User, userText);
        var assistantEntry = new ConversationTranscriptEntry(ConversationTranscriptRole.Assistant, string.Empty);
        Transcript.Add(userEntry);
        Transcript.Add(assistantEntry);
        var assistantIndex = Transcript.Count - 1;
        var partial = string.Empty;

        var activeRun = BeginActiveRun(cancellationToken);
        ClearError();
        ResetMetrics();
        Evidence.Clear();

        var progress = new InlineProgress<ConversationDelta>(delta =>
        {
            partial += delta.Content;
            Dispatch(() => Transcript[assistantIndex] = assistantEntry with { Content = partial });
        });

        try
        {
            var result = await _service.RunAsync(
                new ConversationRequest(
                    SystemPrompt,
                    userText,
                    history,
                    Temperature,
                    MaxOutputTokens,
                    UseKnowledge),
                progress,
                activeRun.Token).ConfigureAwait(true);

            Transcript[assistantIndex] = assistantEntry with
            {
                Content = string.IsNullOrEmpty(result.ResponseText) ? partial : result.ResponseText
            };
            ApplyRunResult(result);
            if (result.State == ConversationRunState.Completed && !string.IsNullOrWhiteSpace(result.ResponseText))
                AppendCompletedTurn(userText, result.ResponseText);
        }
        catch (OperationCanceledException) when (activeRun.IsCancellationRequested)
        {
            Transcript[assistantIndex] = assistantEntry with { Content = partial };
            SetError("RUN_CANCELLED", "对话已取消，已保留部分回答。");
            AddStatus("RUN_CANCELLED", "对话已取消，已保留部分回答。");
        }
        catch (ConversationException ex)
        {
            Transcript[assistantIndex] = assistantEntry with { Content = partial };
            SetError(ex.Code, ex.Message);
            AddStatus(ex.Code, ex.Message);
        }
        catch (Exception ex)
        {
            Transcript[assistantIndex] = assistantEntry with { Content = partial };
            SetError("RUN_FAILED", ex.Message);
            AddStatus("RUN_FAILED", ex.Message);
        }
        finally
        {
            EndActiveRun(activeRun);
        }
    }

    public Task SaveGoldenAsNewAsync(CancellationToken cancellationToken) =>
        PersistGoldenAsync(null, cancellationToken);

    public Task UpdateSelectedGoldenAsync(CancellationToken cancellationToken)
    {
        if (SelectedGoldenCase is null)
        {
            SetError("GOLDEN_SELECTION_REQUIRED", "请先选择要更新的 Golden Test。");
            return Task.CompletedTask;
        }
        return PersistGoldenAsync(SelectedGoldenCase, cancellationToken);
    }

    private async Task PersistGoldenAsync(
        GoldenTestCase? existing,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(GoldenName))
        {
            SetError("GOLDEN_NAME_REQUIRED", "请输入 Golden Test 名称。");
            return;
        }
        if (string.IsNullOrWhiteSpace(UserPrompt))
        {
            SetError("PROMPT_REQUIRED", "请先填写要保存的用户提示词。");
            return;
        }
        if (IsBusy) return;

        SetBusy(true);
        try
        {
            var saved = await _catalog.UpsertAsync(
                new GoldenTestCase(
                    existing?.Id ?? Guid.NewGuid().ToString("N"),
                    GoldenName.Trim(),
                    SystemPrompt,
                    UserPrompt.Trim(),
                    Temperature,
                    MaxOutputTokens,
                    UseKnowledge,
                    SplitRules(GoldenMustContain),
                    SplitRules(GoldenMustNotContain),
                    GoldenMaximumLatencyMilliseconds,
                    existing?.CreatedAt ?? default,
                    default),
                cancellationToken).ConfigureAwait(true);
            await ReloadGoldenCasesAsync(saved.Id, cancellationToken).ConfigureAwait(true);
            ClearError();
        }
        catch (ConversationException ex)
        {
            SetError(ex.Code, ex.Message);
        }
        catch (Exception ex)
        {
            SetError("GOLDEN_SAVE_FAILED", ex.Message);
        }
        finally
        {
            SetBusy(false);
        }
    }

    public async Task DeleteGoldenAsync(CancellationToken cancellationToken)
    {
        if (SelectedGoldenCase is null || IsBusy) return;
        var id = SelectedGoldenCase.Id;
        SetBusy(true);
        try
        {
            await _catalog.DeleteAsync(id, cancellationToken).ConfigureAwait(true);
            await ReloadGoldenCasesAsync(null, cancellationToken).ConfigureAwait(true);
            ClearError();
        }
        catch (ConversationException ex)
        {
            SetError(ex.Code, ex.Message);
        }
        catch (Exception ex)
        {
            SetError("GOLDEN_DELETE_FAILED", ex.Message);
        }
        finally
        {
            SetBusy(false);
        }
    }

    public Task RunSelectedGoldenAsync(CancellationToken cancellationToken) =>
        SelectedGoldenCase is null
            ? Task.CompletedTask
            : RunGoldenAsync([SelectedGoldenCase], cancellationToken);

    public Task RunAllGoldenAsync(CancellationToken cancellationToken) =>
        RunGoldenAsync(GoldenCases.ToArray(), cancellationToken);

    public async Task OpenSelectedEvidenceAsync(CancellationToken cancellationToken)
    {
        if (SelectedEvidence is null) return;
        try
        {
            await _evidenceLauncher
                .OpenAsync(SelectedEvidence.SourceUri, SelectedEvidence.Locator, cancellationToken)
                .ConfigureAwait(true);
            ClearError();
        }
        catch (Exception ex)
        {
            SetError("EVIDENCE_OPEN_FAILED", ex.Message);
        }
    }

    private async Task RunGoldenAsync(
        IReadOnlyList<GoldenTestCase> cases,
        CancellationToken cancellationToken)
    {
        if (cases.Count == 0 || IsBusy) return;
        var activeRun = BeginActiveRun(cancellationToken);
        GoldenResults.Clear();
        try
        {
            var results = await _evaluator.RunAsync(cases, activeRun.Token).ConfigureAwait(true);
            foreach (var result in results) GoldenResults.Add(result);
            var batchWasCancelled = activeRun.IsCancellationRequested &&
                                    (results.Count < cases.Count ||
                                     results.LastOrDefault()?.FailureCode == "RUN_CANCELLED");
            if (batchWasCancelled)
                SetError("RUN_CANCELLED", "Golden Test 已取消，已保留完成及当前用例结果。");
            else
                ClearError();
        }
        catch (OperationCanceledException) when (activeRun.IsCancellationRequested)
        {
            SetError("RUN_CANCELLED", "Golden Test 已取消。");
        }
        catch (Exception ex)
        {
            SetError("GOLDEN_RUN_FAILED", ex.Message);
        }
        finally
        {
            EndActiveRun(activeRun);
        }
    }

    private async Task ReloadGoldenCasesAsync(string? selectedId, CancellationToken cancellationToken)
    {
        var cases = await _catalog.LoadAsync(cancellationToken).ConfigureAwait(true);
        GoldenCases.Clear();
        foreach (var testCase in cases) GoldenCases.Add(testCase);
        SelectedGoldenCase = selectedId is null
            ? GoldenCases.FirstOrDefault()
            : GoldenCases.FirstOrDefault(item => item.Id == selectedId) ?? GoldenCases.FirstOrDefault();
        RaiseCommandStates();
    }

    private void ApplyRuntime(ConversationRuntimeSnapshot runtime)
    {
        IsRuntimeReady = runtime.IsReady;
        RuntimeStatus = runtime.IsReady ? "Ready" : "Not ready";
        Endpoint = runtime.BaseUrl ?? "-";
        ActiveModel = runtime.ActiveModelId ?? "-";
        ServiceModel = runtime.ServiceModelId ?? "-";
        if (!runtime.IsReady && !string.IsNullOrWhiteSpace(runtime.BlockedReason))
            SetError("RUNTIME_NOT_READY", runtime.BlockedReason);
        RaiseCommandStates();
    }

    private void ApplyRunResult(ConversationRunResult result)
    {
        TimeToFirstTokenText = result.Metrics.TimeToFirstToken.HasValue
            ? FormatMilliseconds(result.Metrics.TimeToFirstToken.Value)
            : "-";
        TotalLatencyText = FormatMilliseconds(result.Metrics.TotalLatency);
        CompletionTokensText = result.Metrics.CompletionTokens?.ToString(CultureInfo.InvariantCulture) ?? "Unavailable";
        TokensPerSecondText = result.Metrics.TokensPerSecond?.ToString("0.00", CultureInfo.InvariantCulture) ?? "Unavailable";
        Evidence.Clear();
        foreach (var item in result.Evidence) Evidence.Add(item);
        SelectedEvidence = Evidence.FirstOrDefault();

        if (result.State == ConversationRunState.Completed)
        {
            ClearError();
            return;
        }

        var code = result.ErrorCode ?? (result.State == ConversationRunState.Cancelled ? "RUN_CANCELLED" : "RUN_FAILED");
        var message = result.ErrorMessage ?? result.State.ToString();
        SetError(code, message);
        AddStatus(code, message);
    }

    private IReadOnlyList<ConversationMessage> BuildHistory() => _completedHistory.ToArray();

    private void AppendCompletedTurn(string userText, string assistantText)
    {
        _completedHistory.Add(new ConversationMessage("user", userText));
        _completedHistory.Add(new ConversationMessage("assistant", assistantText));
        while (_completedHistory.Count > MaximumHistoryMessages ||
               _completedHistory.Sum(item => item.Content.Length) > MaximumHistoryCharacters)
        {
            if (_completedHistory.Count < 2)
            {
                _completedHistory.Clear();
                break;
            }
            _completedHistory.RemoveRange(0, 2);
        }
    }

    private CancellationTokenSource BeginActiveRun(CancellationToken cancellationToken)
    {
        var activeRun = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        _activeRun = activeRun;
        IsRunActive = true;
        SetBusy(true);
        return activeRun;
    }

    private void EndActiveRun(CancellationTokenSource activeRun)
    {
        if (ReferenceEquals(_activeRun, activeRun)) _activeRun = null;
        activeRun.Dispose();
        IsRunActive = false;
        SetBusy(false);
    }

    private void CancelActiveRun() => _activeRun?.Cancel();

    private void ClearConversation()
    {
        if (IsRunActive) return;
        Transcript.Clear();
        _completedHistory.Clear();
        Evidence.Clear();
        SelectedEvidence = null;
        GoldenResults.Clear();
        ResetMetrics();
        ClearError();
    }

    private void ApplyGoldenCase(GoldenTestCase testCase)
    {
        GoldenName = testCase.Name;
        SystemPrompt = testCase.SystemPrompt;
        UserPrompt = testCase.UserPrompt;
        Temperature = testCase.Temperature;
        MaxOutputTokens = testCase.MaxOutputTokens;
        UseKnowledge = testCase.UseKnowledge;
        GoldenMustContain = string.Join(Environment.NewLine, testCase.MustContain);
        GoldenMustNotContain = string.Join(Environment.NewLine, testCase.MustNotContain);
        GoldenMaximumLatencyMilliseconds = testCase.MaximumTotalLatencyMilliseconds;
    }

    private static IReadOnlyList<string> SplitRules(string value) =>
        (value ?? string.Empty)
            .Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Where(item => item.Length > 0)
            .ToArray();

    private static string FormatMilliseconds(TimeSpan value) =>
        Math.Round(value.TotalMilliseconds, MidpointRounding.AwayFromZero)
            .ToString("0", CultureInfo.InvariantCulture) + " ms";

    private void AddStatus(string code, string message) =>
        Transcript.Add(new ConversationTranscriptEntry(ConversationTranscriptRole.Status, message, code));

    private void ResetMetrics()
    {
        TimeToFirstTokenText = "-";
        TotalLatencyText = "-";
        CompletionTokensText = "-";
        TokensPerSecondText = "-";
    }

    private void SetError(string code, string message)
    {
        LastErrorCode = code;
        LastError = message;
    }

    private void ClearError()
    {
        LastErrorCode = null;
        LastError = null;
    }

    private void SetBusy(bool value)
    {
        IsBusy = value;
        RaiseCommandStates();
    }

    private void RaiseCommandStates()
    {
        OnPropertyChanged(nameof(CanSend));
        _sendCommand.RaiseCanExecuteChanged();
        _cancelCommand.RaiseCanExecuteChanged();
        _clearCommand.RaiseCanExecuteChanged();
        _saveGoldenAsNewCommand.RaiseCanExecuteChanged();
        _updateSelectedGoldenCommand.RaiseCanExecuteChanged();
        _deleteGoldenCommand.RaiseCanExecuteChanged();
        _runSelectedGoldenCommand.RaiseCanExecuteChanged();
        _runAllGoldenCommand.RaiseCanExecuteChanged();
        _openEvidenceCommand.RaiseCanExecuteChanged();
    }

    private void Dispatch(Action action)
    {
        if (_uiContext is null || ReferenceEquals(SynchronizationContext.Current, _uiContext))
        {
            action();
            return;
        }
        _uiContext.Send(_ => action(), null);
    }

    private void OnPropertyChanged(string propertyName) =>
        SetProperty(ref _propertyChangePulse, !_propertyChangePulse, propertyName);

    private bool _propertyChangePulse;

    private sealed class InlineProgress<T>(Action<T> report) : IProgress<T>
    {
        public void Report(T value) => report(value);
    }
}
