# Task 1 — DreamShaper default consumer regression (2026-09-28)

Scope: only Task 1 code/default regression from
`docs/superpowers/plans/2026-09-28-core-completion.md` and its design spec.
Real-GPU prompt/seed acceptance remains with the main agent.

## Evidence and intended behavior

The historical [2026-09-20 audit](NEW_MODELS_AUDIT_20260920.md) reports that
4 steps / CFG 2 / DPM++ 2M / Discrete failed visual inspection in basic and
H7 runs. Its 8 steps / CFG 2 / DPM++ 2M SDE / Karras comparison improved the
same prompt and seed, but establishes only a single-seed smoke result.
This task does not claim new image-quality acceptance.

The app's actual sampler spelling is `dpm++2m_sde` (API `GenerateRequest`,
browser sampler option and native command forwarding); scheduler is `karras`.
The intended registered profile remains 768 × 768, with 8 steps and CFG 2.
The model name and legacy `dreamshaper-xl-lightning-4step` alias remain stable;
the alias identifies the same checkpoint, not a forced four-step request.
`dmd2.enabled` remains false and `variant` remains `lightning`.

The model-selection UI consumes the API's `generationDefaults`. The API does
not merge model-specific defaults into a request that omits generation fields;
that existing global `GenerateRequest` behavior is unchanged. Explicit API
requests remain authoritative. The existing browser quality guard uses an
8-step minimum unless a model recommends fewer steps, so this corrected
profile no longer grants DreamShaper the old four-step UI exception. Saved
values are not rewritten; a four-step form is blocked by that existing guard.
Changing that UI policy is outside this config-only fix. Normal custom values
that satisfy the existing guard remain editable.

## Task ledger

- Read the plan, spec, historical audit, model API, generation validation and
  queue serialization. Existing identity changes are outside this task.
- Ruling: keep the work in the explicitly assigned worktree and record this
  task in this new note; leave other agents' plan/progress files untouched.
- Ruling: update the old registry test's obsolete four-step expectation in
  place because it would contradict the requested fix. New behavioral tests
  live in `server/tests/test_dreamshaper_defaults.py`.
- Regression tests read the actual registry with only artifact paths replaced
  by temporary files. They exercise `/api/models`, canonical/legacy detail,
  `/api/generate` and `/api/jobs` through the real in-process application.
  Only background scheduling is stopped; inference and network listeners are
  never started. Public queued requests are checked for off/basic/H6/H7.
- Explicit dimensions, steps, CFG, sampler, scheduler, seed and prompt fields
  must survive, including CFG 0, seed 0 and historical four-step requests.
- TDD RED: focused pytest (`-k dreamshaper`) produced 8 failed / 4 passed /
  8 deselected. Seven public API cases reported the old 4-step / `dpm++2m` /
  `discrete` profile; the existing registry contract failed on
  `dmd2.steps_default == 8`. All four explicit-request cases already passed.
- Implemented the minimal registry change: `generation_defaults` now selects
  8 / 2 / `dpm++2m_sde` / `karras`; fallback `dmd2.steps_default` is also 8.
  The reason text describes the local single-seed evidence and its limits.
- TDD GREEN and adjacent regression verification: 71 passed / 1 deselected
  (5.82 seconds), covering the new 11-case API file, existing API and generation
  job tests, and registry contracts. Command from the worktree root:

  ```powershell
  $task1Temp = Join-Path 'E:/Dream/temp' ('task1-defaults-green-' + [guid]::NewGuid().ToString('N'))
  python -m pytest -q apps/dream-windows/server/tests/test_dreamshaper_defaults.py apps/dream-windows/server/tests/test_api_contract.py apps/dream-windows/server/tests/test_generation_jobs.py tests/dream-windows/test_model_registry_contract.py -k 'not test_validator_has_fail_closed_markers_and_accepts_uninstalled_registry' --basetemp $task1Temp
  ```

- The explicitly deselected legacy test writes
  `E:/Dream/data/metadata/model-registry-validation.json`; it was not run to
  preserve the live audit report. The validator's temporary Windows-only
  fixture test did run and pass.
- Frontend consumer regressions: 56 passed across 3 files (8.20 seconds).
  Command from `apps/dream-windows`:

  ```powershell
  npm.cmd run test:run -- src/app/pages/GeneratePage.test.tsx src/app/pages/HistoryPage.test.tsx src/providers/DreamHttpProvider.test.ts
  ```

- Scoped `git diff --check` passed. Git reported only its existing LF-to-CRLF
  checkout conversion notices.
- Final focused rerun after concurrent worktree changes: 12 passed / 8
  deselected (2.27 seconds), using the same two files and `-k dreamshaper`
  as RED, with a fresh temporary directory on E:.
- Final review: self-review of these four paths and their consumer behavior.
  No agent-reviewed branch or release acceptance is claimed. Whole-project
  integration, builds and real-GPU acceptance remain with the main agent,
  including the other agents' concurrently changing files.

## Changed paths

- `config/dream/model-registry.json`
- `tests/dream-windows/test_model_registry_contract.py` (obsolete expectation)
- `apps/dream-windows/server/tests/test_dreamshaper_defaults.py` (new)
- `docs/dream-windows/TASK1_DREAMSHAPER_DEFAULTS_20260928.md` (new)

## Optional read-only Android/browser inventory

This is a source snapshot during concurrent development, not an installed
Android or browser acceptance run. The mobile evidence is Kotlin/C++/WebView
code embedded in repository patch scripts targeting the Android app.
No patches were applied and no mobile or browser features were edited.

| Feature | Concrete mobile code | Current browser boundary |
| --- | --- | --- |
| Native conditioning fusion controls | `s24u-image-harness/patch_h6_v7_fusion_android.py` adds Equal Mean, First Only, Token Weighted and Anchor + Residual with an alpha slider. `patch_h6_v7_fusion_core_v2.py` computes effective weights and the anchor/residual noise prediction. | `src/app/pages/LabPage.tsx` and `server/runtime.py::_experiment_variants` offer prompt-text rewrites. They do not expose those native fusion modes or alpha control; the UI/backend message explicitly distinguishes text rewrites from embedding/token fusion. |
| Spatial per-step latent change map | `s24u-image-harness/patch_h6_v8_dynamics_ui.py` renders `dynamics_samples[].image_base64` as the spatial Mean absolute delta-z map, with separate decoded-preview UI. Decoded frames are shown only when the backend actually decodes them. | `src/app/pages/MicroscopePage.tsx::LatentPanel` exposes numeric delta L2, mean absolute delta and cosine, plus latent RGB projection frames. A dedicated spatial delta-z image field/view is absent from the current `RuntimeLatentTelemetry` contract. Numeric metrics and projection previews are present. |
| Selected-channel temporal comparison | `s24u-image-harness/patch_h6_v9_latent_ui.py::renderLatentInspector` compares the selected channel's mean/std at previous/current/final steps. | `MicroscopePage.tsx::LatentTelemetryInspector` has previous/current/final comparison for whole-tensor mean/std and all four current-step channel statistics. The equivalent selected-channel temporal comparison is absent. |

Browser paths in this table are relative to `apps/dream-windows`.

No source synchronization, server launch, GPU inference, commit or push is
part of this task. No identity or face-polish behavior is changed.

## Authorized release follow-up — local launcher probe

The later launcher request expands this note's original Task 1 scope only to
`scripts/start_dream_web_background.ps1` and the new dedicated
`tests/dream-windows/test_background_launcher_proxy.py`.

`Test-DreamWebReady` previously inherited proxy settings. The local listener
could be healthy while the proxy returned 502, causing a false occupied-port
failure. Conversely, a proxy returning a Dream title could incorrectly make
an unrelated listener look ready. The scoped fix adds PowerShell 7
`Invoke-WebRequest -NoProxy` to the shared loopback readiness probe. Existing
HTTP-200/title validation, occupied-port rejection, polling, and reuse of a
running listener remain intact. No global proxy variables are changed.

TDD command from this worktree:

```powershell
python -m pytest -q tests/dream-windows/test_background_launcher_proxy.py
```

- RED: 3 failed in 15.31 seconds. The correct listener was falsely rejected
  behind a 502 proxy; both a different application and a 503 listener were
  falsely accepted behind a proxy returning the Dream title.
- GREEN: 3 passed in 21.48 seconds. Two consecutive invocations reuse the
  same listener PID and never attempt a process start. The wrong-title and
  503 cases reject the occupied port. All probes reach the local listener;
  the configured fake proxy receives zero requests.
- Tests use real HTTP listeners bound to OS-selected loopback ports. They
  set proxy variables only in child PowerShell processes and replace
  `Start-Process` with a throwing guard. No Dream server, browser, model,
  inference worker or production listener is started or stopped.
- Scoped `git diff --check` passed. The older
  `scripts/tests/start_dream_web_background.test.ps1` was deliberately not
  run because it starts a real Dream service, outside this request.

## Native fusion feasibility — read-only installed-engine check

Checked the locally selected native engine from
`E:/Dream/app/native-engine.json` and the installed H7 engine:

```text
E:/Dream/app/stable-diffusion-cuda-12.9.1-latent/sd-cli.exe --help
E:/Dream/app/stable-diffusion-cuda-h7/sd-cli.exe --help
```

Both help commands exited 0. Before invoking them, the cached CLI source's
argument parser was inspected: `--help` prints usage and exits before model
context creation. No generation command or GPU workload was run.

Observed interfaces and limits:

- Both binaries expose prompt/negative-prompt, CFG, sampler and scheduler
  controls. Neither exposes `fusion_mode`, `fusion_alpha`, `equal_mean`,
  `first_only`, `token_weighted` or `anchor_residual` selection.
- H7 exposes `--conditioning-trace-path` for bounded chunk-vs-full diagnostic
  passes. In cached `E:/Dream/src/stable-diffusion.cpp-h7/src/stable-diffusion.cpp`
  (conditioning callback near line 2923), at most three chunks are evaluated
  on selected capture steps. The results are emitted as measurements; the
  scheduler still receives the original `guided.pred` near line 2961.
- The cached CLIP conditioner concatenates chunk embeddings and supports
  token weighting. That does not implement the Android harness's weighted
  combination of separate per-chunk denoising predictions. The existing H6
  slice/run helpers are a useful starting point, not a ready fusion switch.
- Browser `GenerateRequest.fusionMode` is currently a string, but neither
  `JobRunner._command` nor `PersistentEngineClient._payload` forwards native
  fusion settings. Lab's current prompt-rewrite description is accurate.

Scope/cost assessment (engineering inference from those interfaces):

1. Define an explicit opt-in SDXL fusion contract, chunk/token weighting,
   alpha bounds, and negative-conditioning/CFG semantics; retain the current
   default output path exactly when fusion is off.
2. Implement per-step prediction combination in the native sampler and
   expose it through the C API, CLI and persistent-server request parsing.
   Reuse diagnostic helpers only where their assumptions apply. Sampling
   must cover the selected chunks on every step, not H6's sampled subset.
3. Plumb fields through Dream core/wrappers, backend validation and job
   persistence, then add actual Lab controls and output metadata. Keep CLI
   research and persistent basic execution consistent.
4. Rebuild/package the affected native binaries; test known weighted tensor
   results, unchanged OFF/single-chunk behavior, alpha endpoints, malformed
   weights and cancellation; then run serial same-seed GPU/visual acceptance.

This spans at least four implementation layers and a native build/acceptance
cycle, so it belongs in a separate feature task. Runtime cost also grows with
the number of per-chunk conditional UNet evaluations at each sampling step;
unconditional predictions may be reusable when semantics permit. No timing
or memory multiplier has been measured. No fusion implementation or native
source/binary changes were made in this follow-up.
