# Dream browser workstation P0–P2 upgrade

## Approved intent and constraints

The user requests that current code be consolidated on main, pushed to GitHub, and all P0/P1/P2 items from the preceding assessment be implemented. Earlier instructions explicitly reject repeated small-step confirmations. Execute continuously, documenting decisions and stopping only for a genuine new authority or evidence blocker.

Use the existing browser application, localhost:8766, E-drive storage, and RTX 1000 Ada 6 GB. Preserve profiles, references, original/results, existing completed jobs, and mobile source. No EXE work, driver/CUDA upgrade, automatic deletion, LoRA training, ControlNet, remote GPU usage, or new paid services. GitHub is public: only reviewed source/config examples/tests/docs; no user assets, embeddings, runtime data, or credentials. Push main without force and preserve remote commits.

## Approach

Choose additive extension of existing Diffusers identity and native production engines. Replacing the app with ComfyUI would discard working flows; replacing the inference stack would make the quality/performance baseline incomparable. New visual capabilities must be tested against the current CyberRealistic route and available Illustrious weights rather than downloading another checkpoint.

### P0 — operational and release baseline

Version existing served code on main after baseline tests and a credential/data exclusion scan. Merge the remote workflow update. Add read-only operations diagnostics that reports release/build identity, disk free bytes, pending work and recovery guidance without dumping personal paths or request content. Disk free <10 GiB is a warning; <2 GiB blocks new generation with a clear error, never deletes existing data. Preserve unknown versus zero. Provide reproducible dependency inventory and a source-only release/rollback manifest. Launch errors must identify port conflict, missing assets/dependencies and service health failure; never kill an unrelated listener. No automatic system startup registration.

### P1 — consistent character creation and visual control

Retain both existing FaceID routes and visual CyberRealistic route. Add an allowlisted Illustrious visual-reference bundle that reuses the installed SDXL checkpoint and Plus Face assets without falling back to SD1.5. Keep reference kind separate from identity recognition. Extend visual-reference control with a normalized start/end sampling interval, defaults 0/1 to preserve legacy results. Reference strength is already supported; expose and persist the schedule in draft, history and profile presets. Schedule changes must be reset each render, including errors, research interventions and optional face detail. Add repeatable comparison tooling with fixed seeds/prompts, original/detailer views, measured stage time/VRAM and user-review outcomes. No numerical likeness guarantee or synthetic identity score. Compare new route/control with existing route on actual local generation before recommending defaults.

### P1 — visual H6/H7

Enable representative H6/H7 only after real local verification. H6 disables visual-reference adapter contribution on the same latent/timestep without feeding intervention output back into sampling. H7 captures measured self attention and conditional text cross attention; these are not reference-image token attribution, not FaceID identity attention, and not full per-head dumps. Mark reference route and intervention method in artifacts and UI. Preserve artifact contracts and historic FaceID readers. Bound artifact output to 512 MiB and retain original generation when publication fails. Capture must restore adapters/hooks after exceptions. SDXL extended capture remains disallowed.

### P2 — performance

Measure cold setup, inference/preview and optional detail stages independently. Existing batch reuse stays. Evaluate cross-batch reuse only with a bounded worker lifetime, single-GPU ownership, compatibility key including model/reference/adapter/LoRA and relevant settings, and explicit idle cleanup. Do not trade correctness or other apps' VRAM for speed. A measured rejection of a risky reuse design is not implementation of cross-batch reuse: report its status separately. A reproducible comparison and truthful phase reporting are required regardless.

### P2 — continue unfinished batch items

Add explicit retry-failed and continue-unfinished actions. Create a new child batch linked to its parent; do not mutate old completed items or reuse old output paths. Preserve frozen per-item seeds, steps and request values. Failed-only excludes cancelled/queued; unfinished includes all non-complete items in a terminal parent. Reject an active parent, empty selection, malformed ancestry, missing reference and deleted completed results as retry targets. An idempotency key prevents a double click/retry from submitting twice. Restart recovery never silently resumes GPU work. Browser offers the actions and displays parent provenance.

## Acceptance and evidence boundaries

Run TDD for new contracts, full frontend/backend suites, build, independent review, real browser operations and safe local generation. Use benign landscape/clothed portrait prompts only; do not replay unrelated historical prompts. Compare fixed reference inputs without changing archive files. Unit tests do not establish image quality. Do not claim all work complete if visual controls or research lack real CUDA evidence. Record intermediate status in a local progress ledger, with each P0/P1/P2 item separately closed or still open.
