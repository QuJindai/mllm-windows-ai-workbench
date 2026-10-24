# PowerShell runtime checks

`safe-core-ci` runs both native parsers on Windows Server 2022 and 2025:

- **Windows PowerShell 5.1:** every `.ps1` / `.psm1` except the exact modern-only
  paths in `powershell-runtimes.json`.
- **PowerShell 7:** every `.ps1` / `.psm1`, including the legacy/shared scripts.

Both retain the generated `dist/` directory exclusion. New unlisted scripts
receive both checks. A stale, duplicate, wildcard, or missing manifest path
fails the gate; a modern-only entry cannot remove a file from both parsers.
The checker only parses source; it never executes or imports the scanned files.

The modern-only list currently contains the Dream diagnostic and background
launcher, which use PowerShell 7's `Invoke-WebRequest -NoProxy`. Shared Dream
scripts still invoked by `powershell.exe` remain covered by 5.1. Add a file to
the manifest only after checking its callers and declaring `#Requires -Version
7.0` in that script. Keep legacy scripts ASCII-only or UTF-8 with BOM when they
contain non-ASCII text: 5.1's native parser uses the Windows ANSI code page for
files without a BOM.

Run from the repository root on Windows with both hosts installed:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ci/Test-PowerShellSource.ps1 -RuntimeGroup Legacy51
pwsh.exe -NoProfile -ExecutionPolicy Bypass -File ci/Test-PowerShellSource.ps1 -RuntimeGroup PowerShell7
python -m pytest -q tests/ci/test_powershell_runtime_groups.py
```

The tests use real child parsers, deliberately malformed fixtures, wrong hosts,
and Chinese/English legacy decoding. They do not start Dream or run inference.
The standalone `tests/ci/Invoke-WindowsPS51Smoke.ps1` uses the same legacy gate
before its module, configuration, task registry, and XAML checks.

For CI parity, run `python ci/materialize.py` **in a disposable checkout** first;
it extracts the Safe Core overlay and replaces generated files. To reproduce
the Linux static validator on Chinese Windows, use
`python -X utf8 tools/validate_source.py`: that legacy validator uses Python's
default text encoding in several reads, whereas Linux CI already uses UTF-8.
Do not replace the native PowerShell 5.1 gate with forced UTF-8 decoding; doing
so would hide real legacy-runtime encoding failures.
