# Dream Windows W0/W1 acceptance

Run from the checked-out branch:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\dream-windows\Invoke-DreamAcceptance.ps1 `
  -Root E:\Dream
```

The report is written to `E:\Dream\logs\acceptance\acceptance.json`. It
records branch/HEAD, GPU and VRAM, CUDA visibility, model identity/path, every
gate result, and the generation fields required for a real W1 image.

W0 is complete only when the E-drive layout, hardware probe, NVIDIA visibility,
and `NO_C_DRIVE_DREAM_ASSET_PASS` all pass. A generic pre-existing user cache
is not treated as a Dream asset unless Dream configuration points to it; Dream
environment variables and named Dream directories are checked.

W1 is complete only after native `stable-diffusion.cpp + CUDA` execution has
produced a real PNG and metadata with model hash, seed, steps, CFG, runtime,
peak VRAM, and peak RAM evidence. If any dependency is missing, the report
must remain `DREAM_ACCEPTANCE_BLOCKED` with the exact codes from
`W1_PREFLIGHT_BLOCKED`; the system does not generate a placeholder and does
not mark `windows_cuda_generation_pass` true.

The current machine is expected to pass W0 and stop at W1 preflight until
CMake, the CUDA toolkit (`nvcc`), the configured stable-diffusion.cpp CUDA
build, the verified CyberRealistic GGUF, and the native invocation wrapper are
available under the E-drive policy.
