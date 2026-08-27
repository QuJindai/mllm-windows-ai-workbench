# Desktop Phase A Plan Self-Review

This file is a binding correction to `2026-08-27-desktop-workbench-phase-a.md` and must be read with it during execution.

1. **Installer NoGui/action ordering:** current `Start-UniversalInstaller.ps1` exits on `if($NoGui)` before `$actions` is built. Task 7 must change this to `if($NoGui -and $Action -eq 'None')` so CLI actions continue to the existing action table. Action dispatch then runs after `$actions` is created and before WPF launch.
2. **Protocol support files:** Task 1 creates `Protocol/RpcProtocol.cs` and `Protocol/WorkbenchJson.cs` in addition to the listed contract files. `RpcProtocol.Version` is exactly `1.0`; `WorkbenchJson.Options` uses camelCase and `JsonStringEnumConverter`.
3. **Backend abstraction:** Task 2 creates `Backend/IWorkbenchBackendClient.cs` with `ConnectAsync`, `InvokeAsync<TResponse>`, `GetDashboardAsync`, `GetDoctorAsync`, and `GetInstallerAsync`; ViewModels depend on this interface, not the concrete pipe client.
4. **Separate backend logs:** RPC never carries diagnostic console logs. `BackendProcessHost` redirects PowerShell stdout/stderr into a separate `BackendLogReceived` event/stream and redacts the session token. Named pipe content remains request/response only.
5. **CI .NET setup:** `desktop-phase-a.yml` must use `actions/setup-dotnet@v4` with `dotnet-version: 8.0.x` before `.NET 8 identity` and tests.
6. **No phase-A seed expansion:** the existing single-file Universal Installer seed remains foundation-only. Phase A produces and validates a separate self-contained desktop version ZIP; embedding the .NET desktop into the CMD is a later distribution decision.

These corrections resolve the self-review findings without changing the approved architecture or Phase A scope.
