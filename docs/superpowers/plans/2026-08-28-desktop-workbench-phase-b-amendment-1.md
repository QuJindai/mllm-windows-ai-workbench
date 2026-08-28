# Phase B Implementation Plan Amendment 1

This amendment is normative for `2026-08-28-desktop-workbench-phase-b.md` and resolves two self-review findings before implementation.

## 1. Shared mutation serialization

The Phase B design requires model and service mutations to be serialized for the whole Desktop session. Therefore Tasks 7 and 8 do **not** create independent ViewModel-local mutation gates.

Create `src/MLLM.Workbench.Desktop/Services/WorkbenchMutationGate.cs` in Task 7 and register it as a singleton in `App.BuildHost`.

Exact interface:

```csharp
public sealed class WorkbenchMutationGate
{
    private readonly SemaphoreSlim _gate = new(1, 1);
    public bool IsBusy => _gate.CurrentCount == 0;
    public async Task<IAsyncDisposable> EnterAsync(CancellationToken cancellationToken);
}
```

`EnterAsync` waits on the one-slot semaphore and returns a private releaser that releases exactly once. `ModelManagementPageViewModel` and `LocalServicesPageViewModel` receive the same singleton instance. Their mutating commands are disabled while `IsBusy` is true. Tests must prove a model mutation blocks a concurrent service mutation until the first releaser is disposed.

## 2. Phase B workflow starts at Task 1

Create `.github/workflows/desktop-phase-b.yml` during Task 1 with the first RED contract gate and expand it task-by-task. Do not wait until Task 10 to create the workflow. The final Task 10 matrix/order/markers in the main plan remain the required end state.

This ensures every RED and GREEN has GitHub Actions evidence on `feature/desktop-phase-b`.

## 3. Task 9 formatting clarification

Task 9 Step 4 is:

> Register both ViewModels in `App.BuildHost`, add DataTemplates/navigation routes, and change the shell badge from `Desktop Phase A` to `Desktop Phase B`.

No behavior change beyond the original Task 9 requirement is introduced by this amendment.
