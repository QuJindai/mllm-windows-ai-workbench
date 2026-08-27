namespace MLLM.Workbench.Contracts.Snapshots;

public sealed record InstallerSnapshot(
    string? RunId,
    string? VersionId,
    string Stage,
    bool CanResume,
    string? ActiveVersion,
    string? LastError,
    string EvidenceRoot,
    bool CanRollback = false);
