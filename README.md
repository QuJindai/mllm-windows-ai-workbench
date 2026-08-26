# M-LLM Windows AI Workbench — Safe Core

M-LLM Windows AI Workbench is a rerunnable Windows local-AI installer, Doctor, recovery shell, WPF control plane and optional Web Workbench.

> **Current status:** V1.0.x / HF1 physical-machine installation paths are withdrawn after field failures. The active development line is **1.1.0 Safe Core**. A new physical-machine installer will not be published until the public Windows CI gate is green.

## Safe Core rule

The default `Core`, `Local AI Fast`, `Web Workbench`, and `Full Setup` presets are user-space/portable paths. They must not install system Python, drivers, MSI packages, scheduled tasks, registry changes, Git, or Git-LFS.

- Python fallback: portable Windows embeddable Python under `<DataRoot>\runtime\python-portable`.
- ModelScope: isolated target under `<DataRoot>\runtime\modelscope\site-packages`.
- llama.cpp: portable CPU runtime under `<DataRoot>\runtime\llama.cpp`.
- Models/state/logs/evidence remain below the selected data root.
- Git and Git-LFS are separate **Developer Tools** and are excluded from `Full Setup`.
- Startup scheduling is not part of Safe Core and is never automatic.

## Public CI release gate

The repository deliberately uses deterministic, AI-free CI:

- standard GitHub-hosted runners only;
- `windows-2022` and `windows-2025` for Windows PowerShell 5.1;
- real WPF XAML load smoke via `powershell.exe -STA`;
- standalone Emergency Doctor smoke;
- repository and Safe Core policy tests;
- FastAPI backend tests;
- no OpenAI/Codex/Copilot/Anthropic API calls;
- no GitHub larger runners;
- no Actions artifact/cache uploads in the default validation workflow.

A physical-machine release is blocked while any required CI job is red.

## Architecture

```text
Bootstrap / Start script
        |
        v
Single engine loader
  |-- task registry
  |-- state/network/download/security/runtime
  |-- WPF adapter
  |-- Web adapter
  `-- Doctor / Evidence

Independent recovery lane
  `-- EmergencyDoctor.ps1
```

Task scripts run in the engine loader scope and do not recursively import `Core.psm1`.

## Network modes

- `AUTO_CN_FIRST` — China-friendly routes first, allowed global fallbacks second.
- `CHINA_ONLY` — configured China-friendly routes only.
- `GLOBAL_FIRST` — global routes first, China routes second.
- `OFFLINE_CACHE` — no external requests; use `<DataRoot>\cache` artifacts only.
- `CUSTOM_PROXY` — use the current process/system proxy environment without writing proxy credentials to normal state/logs.

## Data roots

The runtime/data location is selected independently from source code, preferring:

- `D:\M-LLM`
- `C:\M-LLM`
- `%LOCALAPPDATA%\M-LLM\Data`

## Repository validation

Linux-side deterministic checks:

```bash
python -m pytest -q tests/ci/test_repo_contract.py tests/ci/test_safety_policy.py web/backend/tests
python tools/validate_source.py
```

Windows-only validation is performed by GitHub Actions before physical-machine acceptance.

## Historical note

`docs/operations/V1_HF1.md` documents the HF1 Dashboard refresh fix for traceability. It is historical evidence, not approval to use the withdrawn HF1 installation path.
