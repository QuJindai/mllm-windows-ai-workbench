using MLLM.Workbench.Knowledge.Embeddings;

namespace MLLM.Workbench.Desktop.Services.Knowledge;

public static class KnowledgeServiceFactory
{
    public static KnowledgeWorkbenchService Create(
        string dataRoot,
        Func<string, string?> readVariable)
    {
        ArgumentNullException.ThrowIfNull(readVariable);
        var resolution = LocalEmbeddingEnvironment.Resolve(readVariable);
        return new KnowledgeWorkbenchService(
            dataRoot,
            resolution.Provider,
            resolution.Error);
    }
}
