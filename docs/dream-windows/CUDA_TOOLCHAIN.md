# Windows CUDA toolchain

The Dream CUDA development toolchain is installed on E:. The GPU driver remains
Windows-managed; do not reinstall it merely because `nvidia-smi` reports a newer
CUDA driver API version than the toolkit runtime.

## Installed layout

| Component | Location |
| --- | --- |
| CUDA 12.9.1 development/runtime components | `E:\Dream\tools\cuda\12.9.1` |
| MSVC Build Tools 2022 / v143 | `E:\Dream\tools\vs2022` |
| NVIDIA download manifest and verified archives | `E:\Dream\cache\toolchain-downloads` |
| Per-component versions, SHA256 and source URLs | `E:\Dream\tools\cuda\12.9.1\receipts` |
| CUDA native build and compiler cache | `E:\Dream\builds\stable-diffusion-cuda-12.9.1-latent` |
| Packaged native engine | `E:\Dream\app\stable-diffusion-cuda-12.9.1-latent` |
| Active native engine selection | `E:\Dream\app\native-engine.json` |
| Previous prebuilt engine (retained) | `E:\Dream\app\stable-diffusion-cpp` |

The toolkit includes all 26 Windows redistributable core components in NVIDIA's
12.9.1 manifest: compiler, runtime/driver import libraries, CCCL, cuBLAS,
cuFFT, cuRAND, cuSOLVER, cuSPARSE, NPP, NVRTC, nvJitLink, nvJPEG and diagnostic
tools. Standalone Nsight GUIs, legacy Visual Profiler and Visual Studio IDE
integration are optional and not installed. The existing Windows SDK is reused;
Microsoft's shared installer/registration files remain Windows-managed on C:.

## Reproduce and verify

Run from the Dream Windows worktree in PowerShell:

```powershell
.\scripts\install_cuda_toolchain.ps1
.\scripts\verify_cuda.ps1 -Compile
.\scripts\build_dream_cuda_engine.ps1 -Parallel 4
.\scripts\set_dream_env.ps1
.\scripts\prepare_dream_core.ps1
.\scripts\run_dream_web.ps1 -Port 8866
```

`verify_cuda.ps1 -Compile` must report `CUDA_KERNEL_PASS`, not merely find
`nvidia-smi` or `nvcc`. The native build targets Ada `sm_89` and does not disable
CUDA's host compiler compatibility checks. The `sd-cli` and `sd-server` targets are built;
the upstream example web server/frontend is not modified or deployed.

`build_dream_cuda_engine.ps1` packages all linked Dream/GGML and CUDA DLLs,
checks `--latent-trace-path`, and records release SHA256 values. It does not
activate an untested build. Test generation on a separate localhost port using
`run_dream_web.ps1 -EngineExe <new-sd-cli-path> -Port 8767`, then select the
verified engine using `app\native-engine.json` and restart port 8866 while idle.

Activation is reversible: set `engineExe` in the selection file to the retained
previous executable and restart the Dream service. No old engine, model, history
or output needs to be deleted.

Sources: [NVIDIA 12.9.1 redistribution manifest](https://developer.download.nvidia.com/compute/cuda/redist/redistrib_12.9.1.json),
[NVIDIA Windows installation guide](https://docs.nvidia.com/cuda/archive/12.9.1/cuda-installation-guide-microsoft-windows/index.html),
[Microsoft Build Tools installer options](https://learn.microsoft.com/en-us/visualstudio/install/use-command-line-parameters-to-install-visual-studio?view=vs-2022).

## Verified deployment — 2026-09-07

- Official deviceQuery and the locally compiled CUDA kernel probe: PASS.
- MSVC 19.44 / CUDA 12.9.86: successful native build. MSVC `/bigobj` is
  required by this large source file; standard exception/RTTI flags are retained.
- Active localhost service: `http://127.0.0.1:8866/`; temporary staging service
  on port 8767 was stopped after verification.
- GUI-generated landscape: `job-b596e3d01c70`, 832×1216, 20 steps, 65.164 s.
- GUI-generated fox on production port: `job-11a198c8166d`, 832×1216,
  20 steps, 63.536 s. Both full-resolution images were visually inspected.
- Each run: 20 original latent samples, 80 four-channel PNGs, 20 RGB projection
  previews. Every channel image was retrieved through the browser API; shape,
  histogram counts and native/API delta values matched exactly.
- Frontend 55 tests and backend 36 tests pass; TypeScript/Vite build passes.
  One pre-existing HistoryPage immediate-keyboard assertion failed in the first
  full parallel test run, then passed in focused and full reruns. It was not
  silently removed or weakened. Existing SettingsPage `act` warnings remain.
- Native compiler retains upstream numeric conversion warnings; there are no
  compilation/link failures in the deployed build.
- GUI fixes accompanying activation: preserve raw delta fields through trace
  persistence; show the missing-raw-channel notice only when raw data is absent.
- Both runs reached 5841 MiB total GPU memory at peak and returned to 0 MiB after
  completion. This is a two-run acceptance check, not proof that all possible GPU
  pressure or Codex crash scenarios are eliminated.

Evidence: `E:\Dream\logs\cuda-latent-production-acceptance-20260907.json`,
`E:\Dream\logs\cuda-fox-production-acceptance-20260907.json`,
and `E:\Dream\logs\w1\preflight.json`.

Scope: this closes the missing CUDA toolchain and native H6 raw-latent export
blocker. The separate H7 Debug UNet research graph and browser attention viewer
were subsequently delivered and verified on 2026-09-09; installing the toolkit
alone did not provide that functionality.
