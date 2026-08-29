namespace MLLM.Workbench.Knowledge.Embeddings;

public interface IEmbeddingProvider
{
    string ProviderId { get; }
    string ModelId { get; }
    int Dimension { get; }

    Task<ReadOnlyMemory<float>> EmbedAsync(string text, CancellationToken cancellationToken);
}
