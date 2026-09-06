# Dream Windows W0-W1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first verifiable Windows Dream runtime line on the HP ZBook, with all Dream assets rooted at `E:\Dream`, truthful hardware/CUDA evidence, a model registry, and a real `dream-core.exe generate` gate when the native CUDA engine and model are available.

**Architecture:** Keep the existing M-LLM Safe Core WPF product unchanged and add a separate Dream Windows runtime layer in this branch. PowerShell scripts own E-drive bootstrap, environment redirection, hardware probing, and C-drive asset policy; a small native core adapter will own the stable-diffusion.cpp/CUDA CLI contract; model identity and generation metadata remain file-based under `E:\Dream\data`.

**Tech Stack:** Windows PowerShell 7/5.1-compatible scripts, Python contract tests, C++/CMake when the native engine toolchain is available, `stable-diffusion.cpp + CUDA`, JSON/JSONL, PNG, and the existing repository's deterministic CI conventions.

**Spec:** `E:\Dream\handoff\Dream_Windows_Codex_Handoff_20260906\CODEX_START_PROMPT.md`, `README_FIRST.md`, `docs/00_PROJECT_BACKGROUND.md` through `docs/16_DEFINITION_OF_DONE.md`, and `references/Dream_Windows_E盘全量部署_详细开发方案_20260906.md`.

## Global Constraints

- Base branch is `main` at `df7d8da4c398e05dc54475c656a5638158b1478c`; Android reference is read-only at `feature/s24u-image-harness-h6r5-semantic-fidelity` / `381713f6985e1d48da16a14636989a4b27f1ae98`.
- All Dream repositories, worktrees, models, caches, environments, builds, temporary files, logs, history, SQLite files, traces, experiments, and installers must be below `E:\Dream\`.
- Production engine is `stable-diffusion.cpp + CUDA`; DirectML, TensorRT, ComfyUI, WSL, Docker, and cloud inference are not W0/W1 primary paths.
- The local hardware baseline is RTX 1000 Ada Laptop GPU with 6 GB GDDR6, 64 GB RAM, i7-14700HX, and two approximately 1 TB NVMe drives; the Dream data drive is E:.
- First model is CyberRealistic v10 DMD2; Android QNN binaries are reference-only and must not be used as Windows CUDA model files.
- No fake generation, fake attention, latent-as-VAE claims, theoretical-as-observed counters, or unverified model identity may be presented as passed evidence.
- Existing Safe Core files and existing main history are preserved; no reset, force checkout, broad merge, or unrelated cleanup is allowed.
- Existing baseline is known to be non-green: Python contract tests currently report 8 failures and 7 passes because main lacks legacy `engine/`, `gui/`, and `tasks/` files; .NET tests are blocked because only SDK `10.0.302` is installed while `global.json` requires `8.0.424`.

## TaskSpec

- **Objective:** Create and verify the first Windows-native Dream foundation and its W0/W1 gates.
- **Mode:** Build and test; preserve the existing Safe Core product boundary.
- **Scenario/audience:** Local engineering handoff for the owner's HP ZBook; evidence must be suitable for later review and reproducible on the same machine.
- **Baseline:** Clean `main` clone at `df7d8da4...`, isolated branch `feature/dream-windows-w0-hardware` in `E:\Dream\worktrees\dream-windows-w0-hardware`.
- **Required deliverables:** E-drive layout, environment redirect script, hardware JSON, CUDA/VRAM evidence, C-drive asset gate, model registry, W1 CLI contract, and either a real first image with complete metadata or an explicit environment blocker.
- **Preserve/change/delete/prohibit:** Preserve Safe Core and Android reference history; add only Dream W0/W1 files and documentation; do not delete user files, modify the Android branch, place Dream assets on C:, or claim W1 generation without native execution evidence.
- **Evidence level:** Local command output plus persisted JSON/JSONL and test artifacts; native generation additionally requires PNG, runtime metrics, hashes, and command transcript.
- **History level:** R2 — use the supplied handoff package, current repository state, and pinned Android reference facts; do not retrieve unrelated personal history.
- **Verification level:** W0 full local gates; W1 contract tests plus CUDA smoke and real-image acceptance when dependencies are available; preserve baseline failures separately.

---

### Task 1: E-drive bootstrap and environment contract

**Files:**
- Create: `scripts/bootstrap_e_drive.ps1`
- Create: `scripts/set_dream_env.ps1`
- Create: `tests/dream-windows/Invoke-DreamBootstrapSmoke.ps1`
- Create: `tests/dream-windows/test_dream_path_contract.py`
- Modify: `.gitignore` only if required to ignore Dream-generated local folders without hiding source scripts.

**Interfaces:**
- `bootstrap_e_drive.ps1 [-Root <path>]` creates the complete Dream directory tree and emits `E_DRIVE_LAYOUT_PASS`.
- `set_dream_env.ps1 [-Root <path>]` sets process-scoped `DREAM_HOME`, model/data/trace/experiment roots, Hugging Face/Torch/Cargo/npm caches, and `TEMP`/`TMP`; it emits `DREAM_ENV_READY`.
- The smoke script consumes both scripts and asserts every generated path is inside the supplied E-drive root.

- [x] **Step 1: Write the failing path contract.** Assert the required directory names, default root, and that no default points to `C:\`.
- [x] **Step 2: Run the contract and smoke test against a unique `E:\Dream\test-runs\w0-<id>` root;** confirm it fails before the scripts exist.
- [x] **Step 3: Implement the scripts with a parameterized root defaulting to `E:\Dream`;** create `app`, `src`, `models`, `cache`, `env`, `data`, `experiments`, `traces`, `exports`, `logs`, `temp`, `builds`, `backups`, and `ci` subtrees exactly as defined by the handoff.
- [x] **Step 4: Run both tests again;** require `E_DRIVE_LAYOUT_PASS`, `DREAM_ENV_READY`, and zero C-drive path violations.
- [x] **Step 5: Commit** with `feat(dream): bootstrap E-drive runtime layout`.

### Task 2: Hardware probe and C-drive asset gate

**Files:**
- Create: `scripts/collect_hardware.ps1`
- Create: `scripts/verify_cuda.ps1`
- Create: `scripts/verify_no_c_drive_assets.ps1`
- Create: `tests/dream-windows/Invoke-DreamW0Acceptance.ps1`
- Create: `tests/dream-windows/test_hardware_json_contract.py`
- Create: `templates/dream-hardware.template.json`

**Interfaces:**
- `collect_hardware.ps1 [-Root <path>]` writes `<Root>\data\hardware.json` with timestamp, OS/build, CPU cores/threads, RAM, NVIDIA name/VRAM/free memory/driver/power, and E-drive free/used bytes; it emits `HARDWARE_PROBE_PASS` and `CUDA_VISIBLE_PASS` only when `nvidia-smi` succeeds.
- `verify_cuda.ps1` runs read-only `nvidia-smi` queries and emits `CUDA_VISIBLE_PASS`.
- `verify_no_c_drive_assets.ps1 [-Root <path>]` scans the Dream-specific C-drive candidates and verifies all Dream environment variables resolve below `<Root>`; it emits `NO_C_DRIVE_DREAM_ASSET_PASS` or a structured violation list.

- [x] **Step 1: Write RED tests** for the required JSON keys, 6 GB VRAM profile, E-drive path, and fail-closed CUDA behavior.
- [x] **Step 2: Run them before implementation** and capture the expected missing-file failure.
- [x] **Step 3: Implement the probe using `nvidia-smi` plus Windows CIM queries;** parse CSV defensively, preserve MiB units, and do not store serial numbers or secrets.
- [x] **Step 4: Run the probe with `DREAM_HOME=E:\Dream`;** confirm local output reports RTX 1000 Ada, approximately 6141 MiB total VRAM, 64 GB RAM, i7-14700HX, and E-drive capacity.
- [x] **Step 5: Run the no-C-drive gate** with the process-scoped E-drive environment and save its output under `E:\Dream\logs\w0`.
- [x] **Step 6: Run W0 acceptance** and require `E_DRIVE_LAYOUT_PASS`, `HARDWARE_PROBE_PASS`, `CUDA_VISIBLE_PASS`, and `NO_C_DRIVE_DREAM_ASSET_PASS`.
- [x] **Step 7: Commit** with `feat(dream): add truthful Windows hardware and storage gates`.

### Task 3: Model registry and identity contract

**Files:**
- Create: `config/dream/model-registry.json`
- Create: `templates/dream-model-manifest.template.json`
- Create: `scripts/validate_model_registry.ps1`
- Create: `tests/dream-windows/test_model_registry_contract.py`
- Create: `docs/dream-windows/W1_MODEL_IMPORT.md`

**Interfaces:**
- Registry entries contain `model_id`, `display_name`, `architecture`, `dmd2`, source path/hash, Windows GGUF path/hash, and Android reference branch/commit without copying Android QNN binaries.
- `validate_model_registry.ps1 [-Root <path>]` validates paths, required fields, and hash format without hashing large models repeatedly; it emits `MODEL_REGISTRY_PASS`.

- [x] **Step 1: Write RED tests** for the CyberRealistic v10 DMD2 manifest schema, E-drive-only paths, and rejection of `unet.bin` as a Windows model.
- [x] **Step 2: Run the tests** and capture the missing registry failure.
- [x] **Step 3: Implement the registry and validator** with a path/size/mtime hash-cache shape ready for later SHA-256 calculation.
- [x] **Step 4: Add an explicit uninstalled state** for the first model so a missing model is reported as a gate blocker rather than silently substituted.
- [x] **Step 5: Run validation** and save machine-readable evidence under `E:\Dream\data\metadata`.
- [ ] **Step 6: Commit** with `feat(dream): define Windows model identity registry`.

### Task 4: W1 native CLI contract and dependency preflight

**Files:**
- Create: `dream/core/CMakeLists.txt`
- Create: `dream/core/src/main.cpp`
- Create: `dream/core/README.md`
- Create: `dream/core/tests/test_cli_contract.py`
- Create: `scripts/prepare_dream_core.ps1`
- Create: `tests/dream-windows/Invoke-DreamW1Preflight.ps1`
- Modify: `docs/dream-windows/W1_MODEL_IMPORT.md` with the actual engine/model acquisition evidence.

**Interfaces:**
- `dream-core.exe --version` returns a stable version and backend identity.
- `dream-core.exe hardware` returns the persisted hardware schema.
- `dream-core.exe generate --model <id> --prompt <text> --negative <text> --seed <int> --steps <int> --cfg <float> --width <int> --height <int> --output <E-drive-png> --metadata <E-drive-json>` either performs a real CUDA generation or fails with a structured missing-dependency/model error.
- The executable never writes models, caches, builds, history, or traces outside `E:\Dream`.

- [x] **Step 1: Write RED CLI contract tests** for help/version/hardware, required generation arguments, E-drive output validation, and structured failure.
- [x] **Step 2: Run the tests** before adding the adapter and record the expected failure.
- [x] **Step 3: Implement the minimum adapter boundary** without a fake image path: locate a configured `stable-diffusion.cpp` build, validate CUDA availability and the model manifest, then invoke the native backend with captured stdout/stderr and runtime metrics.
- [x] **Step 4: Run dependency preflight** for CMake, CUDA toolkit/runtime, stable-diffusion.cpp, and CyberRealistic model artifacts; record each result under `E:\Dream\logs\w1`.
- [ ] **Step 5: If all dependencies are present, build `dream-core.exe` into `E:\Dream\app\current`, run one fixed generation, calculate model/runtime hashes, and write PNG plus metadata under `E:\Dream\exports` and `E:\Dream\data`.
- [x] **Step 6: If a dependency is absent, stop at the preflight gate** and report the exact missing dependency; do not create a placeholder PNG or mark `WINDOWS_CUDA_GENERATION_PASS`.
- [ ] **Step 7: Commit** with `feat(dream): add truthful CUDA CLI boundary` only after the contract and preflight are reproducible.

### Task 5: W0/W1 evidence bundle and regression gate

**Files:**
- Create: `tests/dream-windows/Invoke-DreamAcceptance.ps1`
- Create: `docs/dream-windows/W0_W1_ACCEPTANCE.md`
- Create: `docs/dream-windows/evidence/.gitkeep`
- Modify: `README.md` only with a concise pointer to the Dream Windows lane, without changing Safe Core behavior.

**Interfaces:**
- `Invoke-DreamAcceptance.ps1` runs W0 gates, model validation, W1 preflight/generation, and C-drive scan; it emits a summary with each gate state and evidence path.
- The acceptance report includes `branch`, `HEAD`, GPU, VRAM, CUDA status, model identity/path, output path, seed, steps, CFG, generation time, peak VRAM, peak RAM, and `NO_C_DRIVE_DREAM_ASSET_PASS`.

- [x] **Step 1: Write the acceptance report contract** and make it fail when any required field is absent.
- [x] **Step 2: Run the report against the current environment** and preserve baseline failures separately from W0/W1 results.
- [x] **Step 3: Implement the orchestrator** so it never converts a skipped or unavailable gate into PASS.
- [x] **Step 4: Run the existing Python tests and all Dream tests** with E-drive caches; record the known legacy failures without altering unrelated files.
- [x] **Step 5: Run `git diff --check`, `git status`, and path scans** to confirm only intended branch files changed and no Dream assets landed in C:.
- [ ] **Step 6: Commit** with `test(dream): add W0 and W1 acceptance evidence`.

## Review checklist

- [ ] The plan has no fake W1 image path or unverified CUDA claim.
- [ ] W0 can be rerun without destroying existing E-drive data.
- [ ] All temporary/build/cache/output roots are parameterized and default to `E:\Dream`.
- [ ] Existing Safe Core baseline failures are reported, not silently repaired in this branch.
- [ ] W1 is marked complete only with a real native CUDA image and complete metadata; otherwise the exact dependency blocker remains explicit.
