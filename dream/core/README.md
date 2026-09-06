# dream-core

`dream-core` is the Windows-native boundary for the production
`stable-diffusion.cpp + CUDA` path. It is deliberately small: it validates the
model registry, the persisted hardware evidence, and all output paths before a
native backend is allowed to run.

`generate` never substitutes a model and never writes a synthetic result. A
real W1 run requires all of the following to be configured in the process:

- `DREAM_HOME=E:\Dream`
- `DREAM_MODEL_REGISTRY` pointing to the validated registry
- `DREAM_STABLE_DIFFUSION_CPP_EXE` pointing to the verified CUDA executable
- `DREAM_SDCPP_GENERATE_WRAPPER` pointing to a verified wrapper for the exact
  installed stable-diffusion.cpp CLI build

The wrapper boundary exists because stable-diffusion.cpp CLI flags can vary by
revision. The wrapper must accept the validated request and return a non-zero
code on failure; the adapter will only be extended to persist metadata after a
real native invocation is verified.

Build output belongs under `E:\Dream\app\current` and build/cache/temporary
files belong under `E:\Dream\builds`, `E:\Dream\cache`, or `E:\Dream\temp`.
