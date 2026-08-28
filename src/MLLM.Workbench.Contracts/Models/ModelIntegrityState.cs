namespace MLLM.Workbench.Contracts.Models;

public enum ModelIntegrityState
{
    Missing,
    StructuralPass,
    Sha256Pass,
    HashComputedUnanchored,
    Failed,
    Unknown
}
