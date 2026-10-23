# Native latent correlation (Task 3)

These are incremental patches for the existing Dream-instrumented native trees,
both based on upstream commit `6b3edaaf32cc19e5bb2d819c788bd557eddc8eba`.
They require the pre-existing latent callback API, sampler callback, CLI options,
and (for H7) research instrumentation. They do not claim to recreate that earlier
instrumentation from a pristine upstream checkout.

- `production.patch`: extracts the existing inline CLI writer into
  `examples/cli/latent_trace_writer.h`, adds correlation, spatial delta images,
  and their CPU tests.
- `h7.patch`: extends the existing H7 writer and adds the same helper/tests.
- `latent_correlation.h`: readable copy of the identical helper in both patches.

The patches include every Task 3 native source/test change, including the delta
follow-up. Applying each patch to saved pre-task fixtures reproduced the native
files after newline normalization. Updated fixtures remain at
`E:/Dream/test-runs/latent-delta-patch-check`.

For an unpatched **instrumented** checkout, run `git apply --check` before
`git apply`. The two current local checkouts are already patched; use
`git apply --reverse --check` to check that state without changing anything.

```powershell
git -C E:/Dream/src/stable-diffusion.cpp apply --reverse --check E:/Dream/worktrees/identity-sd15/native/latent-correlation/production.patch
git -C E:/Dream/src/stable-diffusion.cpp-h7 apply --reverse --check E:/Dream/worktrees/identity-sd15/native/latent-correlation/h7.patch
```

Compile and run the real writer's CPU fixtures, then rebuild the CLI using the
existing CUDA/MSVC build cache (run from the Dream worktree):

```powershell
./scripts/build_latent_correlation.ps1 -SourceDirectory E:/Dream/src/stable-diffusion.cpp -BuildDirectory E:/Dream/builds/stable-diffusion-cuda-12.9.1-latent
./scripts/build_latent_correlation.ps1 -SourceDirectory E:/Dream/src/stable-diffusion.cpp-h7 -BuildDirectory E:/Dream/src/stable-diffusion.cpp-h7/build-h7-cuda-ninja
python scripts/verify_latent_correlation.py <EVIDENCE>/fixtures --delta-fixtures <EVIDENCE>/delta-fixtures
```

Run the verifier once for each build's emitted `EVIDENCE` directory. Python needs
the existing Dream backend test dependencies (FastAPI/TestClient/Pillow). The
build helper validates cache/source correspondence, uses the existing isolated
toolchain, and produces fresh evidence directories. It neither runs the CUDA
engine nor installs or activates binaries. Do not substitute the older
`build_dream_cuda_engine.ps1`: that script executes a GPU probe and packages files
into the installation directory.

The helper computes centered Pearson coefficients over contiguous
`[batch][channel][spatial]` original float values, using double accumulators.
Memory overhead is O(channels²); values are never normalized from PNGs. Constant
and nonfinite channels have null rows/columns, including their diagonals.
The CPU tests exercise +1, -1, 0, 1/2, constants, one observation, large offsets,
nonfinite inputs, and reduction across batches whose PNGs each have one pixel.

The additional delta test executes seven cases through the real writer and PNG
encoder/decoder. Spatial mean absolute float differences reduce over channels
and batches, and use zero-to-per-step-maximum grayscale. First/incompatible or
nonfinite pairs and failed image writes omit `delta_file_name`; zero change is
black. The intentional image-write failure emits an expected warning in the test
log. The verifier serves three decoded delta maps through the existing HTTP
frame route and compares their pixels to hand-derived values.

See `docs/dream-windows/LATENT_CORRELATION_20260928.md` for built artifact paths,
hashes, validation evidence, and release boundaries.
