using System.IO;
using System.Text.Json;

namespace MLLM.Workbench.Desktop.Services.Conversation;

public sealed class JsonGoldenTestCatalog : IGoldenTestCatalog, IDisposable
{
    private const int CurrentSchemaVersion = 1;
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true
    };

    private readonly string _path;
    private readonly TimeProvider _timeProvider;
    private readonly SemaphoreSlim _gate = new(1, 1);
    private bool _disposed;

    public JsonGoldenTestCatalog(string dataRoot, TimeProvider? timeProvider = null)
    {
        if (string.IsNullOrWhiteSpace(dataRoot))
            throw new ArgumentException("Golden Test data root is required.", nameof(dataRoot));

        _path = Path.Combine(Path.GetFullPath(dataRoot), "conversation", "golden-tests.json");
        _timeProvider = timeProvider ?? TimeProvider.System;
    }

    public async Task<IReadOnlyList<GoldenTestCase>> LoadAsync(CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        await _gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            return await LoadCoreAsync(cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            _gate.Release();
        }
    }

    public async Task<GoldenTestCase> UpsertAsync(
        GoldenTestCase testCase,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        ArgumentNullException.ThrowIfNull(testCase);
        await _gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            var cases = (await LoadCoreAsync(cancellationToken).ConfigureAwait(false)).ToList();
            var id = RequireText(testCase.Id, "Golden Test id");
            var index = cases.FindIndex(item => string.Equals(item.Id, id, StringComparison.Ordinal));
            var now = _timeProvider.GetUtcNow();
            var normalized = Normalize(
                testCase with
                {
                    Id = id,
                    CreatedAt = index >= 0 ? cases[index].CreatedAt : now,
                    UpdatedAt = now
                });

            if (index >= 0) cases[index] = normalized;
            else cases.Add(normalized);
            await SaveCoreAsync(Sort(cases), cancellationToken).ConfigureAwait(false);
            return normalized;
        }
        finally
        {
            _gate.Release();
        }
    }

    public async Task DeleteAsync(string id, CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        var normalizedId = RequireText(id, "Golden Test id");
        await _gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            var cases = (await LoadCoreAsync(cancellationToken).ConfigureAwait(false)).ToList();
            var removed = cases.RemoveAll(item => string.Equals(item.Id, normalizedId, StringComparison.Ordinal));
            if (removed > 0)
                await SaveCoreAsync(Sort(cases), cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            _gate.Release();
        }
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _gate.Dispose();
    }

    private async Task<IReadOnlyList<GoldenTestCase>> LoadCoreAsync(CancellationToken cancellationToken)
    {
        if (!File.Exists(_path)) return [];

        try
        {
            await using var stream = new FileStream(
                _path,
                FileMode.Open,
                FileAccess.Read,
                FileShare.Read,
                4096,
                FileOptions.Asynchronous | FileOptions.SequentialScan);
            var document = await JsonSerializer
                .DeserializeAsync<GoldenCatalogDocument>(stream, JsonOptions, cancellationToken)
                .ConfigureAwait(false);
            if (document is null)
                throw Corrupt("Golden Test catalog is empty.");
            if (document.SchemaVersion != CurrentSchemaVersion)
                throw Corrupt($"Unsupported Golden Test catalog schema version: {document.SchemaVersion}.");
            if (document.Cases is null)
                throw Corrupt("Golden Test catalog cases are missing.");

            var ids = new HashSet<string>(StringComparer.Ordinal);
            var normalized = new List<GoldenTestCase>(document.Cases.Count);
            foreach (var testCase in document.Cases)
            {
                var item = Normalize(testCase);
                if (!ids.Add(item.Id)) throw Corrupt("Golden Test catalog contains duplicate ids.");
                normalized.Add(item);
            }
            return Sort(normalized);
        }
        catch (GoldenCatalogException)
        {
            throw;
        }
        catch (JsonException ex)
        {
            throw Corrupt("Golden Test catalog contains invalid JSON.", ex);
        }
        catch (InvalidDataException ex)
        {
            throw Corrupt(ex.Message, ex);
        }
    }

    private async Task SaveCoreAsync(
        IReadOnlyList<GoldenTestCase> cases,
        CancellationToken cancellationToken)
    {
        var parent = Path.GetDirectoryName(_path)!;
        Directory.CreateDirectory(parent);
        var temporary = _path + ".tmp";
        var document = new GoldenCatalogDocument(CurrentSchemaVersion, cases);
        var bytes = JsonSerializer.SerializeToUtf8Bytes(document, JsonOptions);

        try
        {
            await using (var stream = new FileStream(
                temporary,
                FileMode.Create,
                FileAccess.Write,
                FileShare.None,
                4096,
                FileOptions.Asynchronous | FileOptions.WriteThrough))
            {
                await stream.WriteAsync(bytes, cancellationToken).ConfigureAwait(false);
                await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
            }
            File.Move(temporary, _path, overwrite: true);
        }
        catch
        {
            try
            {
                if (File.Exists(temporary)) File.Delete(temporary);
            }
            catch
            {
            }
            throw;
        }
    }

    private static GoldenTestCase Normalize(GoldenTestCase testCase)
    {
        ArgumentNullException.ThrowIfNull(testCase);
        var id = RequireText(testCase.Id, "Golden Test id");
        var name = RequireText(testCase.Name, "Golden Test name");
        var userPrompt = RequireText(testCase.UserPrompt, "Golden Test user prompt");
        if (testCase.Temperature is < 0d or > 2d)
            throw new InvalidDataException("Golden Test temperature must be between 0 and 2.");
        if (testCase.MaxOutputTokens is < 1 or > 8192)
            throw new InvalidDataException("Golden Test maximum output tokens must be between 1 and 8192.");
        if (testCase.MaximumTotalLatencyMilliseconds is <= 0)
            throw new InvalidDataException("Golden Test maximum latency must be positive.");
        if (testCase.CreatedAt == default || testCase.UpdatedAt == default)
            throw new InvalidDataException("Golden Test timestamps are required.");

        return testCase with
        {
            Id = id,
            Name = name,
            SystemPrompt = testCase.SystemPrompt?.Trim() ?? string.Empty,
            UserPrompt = userPrompt,
            MustContain = NormalizeFragments(testCase.MustContain, "mustContain"),
            MustNotContain = NormalizeFragments(testCase.MustNotContain, "mustNotContain")
        };
    }

    private static IReadOnlyList<string> NormalizeFragments(
        IReadOnlyList<string>? values,
        string field)
    {
        if (values is null) throw new InvalidDataException($"Golden Test {field} is required.");
        var normalized = values.Select(value => RequireText(value, $"Golden Test {field} fragment")).ToArray();
        return normalized;
    }

    private static IReadOnlyList<GoldenTestCase> Sort(IEnumerable<GoldenTestCase> cases) =>
        cases
            .OrderBy(item => item.Name, StringComparer.OrdinalIgnoreCase)
            .ThenBy(item => item.Id, StringComparer.Ordinal)
            .ToArray();

    private static string RequireText(string? value, string name)
    {
        if (string.IsNullOrWhiteSpace(value)) throw new InvalidDataException(name + " is required.");
        return value.Trim();
    }

    private GoldenCatalogException Corrupt(string message, Exception? inner = null) =>
        new("GOLDEN_CATALOG_CORRUPT", $"{message} Catalog: {_path}", inner);

    private void ThrowIfDisposed() => ObjectDisposedException.ThrowIf(_disposed, this);

    private sealed record GoldenCatalogDocument(
        int SchemaVersion,
        IReadOnlyList<GoldenTestCase> Cases);
}
