namespace MLLM.Workbench.Desktop.Services.Conversation;

public interface IGoldenTestCatalog
{
    Task<IReadOnlyList<GoldenTestCase>> LoadAsync(CancellationToken cancellationToken);
    Task<GoldenTestCase> UpsertAsync(GoldenTestCase testCase, CancellationToken cancellationToken);
    Task DeleteAsync(string id, CancellationToken cancellationToken);
}
