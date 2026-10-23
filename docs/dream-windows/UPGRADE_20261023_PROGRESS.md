# Upgrade progress — 2026-10-23

Plan: `docs/superpowers/plans/2026-10-23-dream-upgrade.md`

## Rulings

- User explicitly requested main/push and previously rejected small-step approval prompts. Execute the approved P0–P2 scope continuously; design/plan remain reviewable. No new credentials, remote compute or destructive cleanup authority is inferred.
- Reuse main at E:/Dream/repo as requested. Do not overwrite or reset the separate identity-sd15 worktree. Public repository excludes local identity data and generated media.
- Existing installed models and environment are the baseline; no blind framework/driver upgrade. Unknown likeness/pose quality is not completion.

## State

- [ ] T1 source baseline/main and remote publication. Remote workflow_dispatch commit9ea8961 merged on main as e05ef04. Reviewed implementation is ready to commit/push; publication receipt follows independent remote readback.
- [x] T2 operations/low-disk safeguards implemented and tested; live diagnostics shows a real low-space warning (approximately 5.4 GiB at final check). No files deleted.
- [x] T3 unfinished batch retry implemented and GUI/API-tested. Lost-response duplication was fixed and independently re-reviewed; new elapsed-time handling includes preparation and terminal failures.
- [ ] T4 visual sampling-window and H6/H7 hooks implemented and real artifacts viewed. Illustrious + Plus Face failed visual quality acceptance (including strength comparisons); experimental route is gated OFF by default, with live API422 and disabled GUI submission verified. No silent substitution.
- [ ] T5 bounded cross-batch worker implemented; Windows reader deadlock and process-tree ownership/exit barrier fixed and tested. Real CUDA cold/warm completed before the final ownership repair. Uncontended performance and final GPU cancel/release/native hand-off acceptance remain open.

## Latest verified evidence (release candidate)

- Final controller backend suite: 1158 passed, 2 opt-in skipped, one Pillow deprecation warning, 268.97 s. Independent identity-Python opt-in run: 1160 passed, one warning, 315.67 s. Focused lifecycle:69 passed including13 real Win32 CPU tests. Root Dream contract suite:25 passed.
- Frontend: 442 passed in 34 files, 98.54 s; TypeScript/Vite build successful. Assets index-Bx5hOPSL.js / index-BiV0RNIK.css.
- Local release `dream-upgrade-20261023` deployed to the existing frontend directory after backup. Service restarted with all pending counts zero; API/hardware/gate readback passed. Five protected profile/reference hashes remain unchanged.
- GUI failed-batch retry created a new child; it completed after the Windows stdin-reader lock repair. Original failed record and protected profiles remain intact.
- Independent review closed both Important issues after 75 focused frontend tests: retry mode/key locking and unknown/read-failed capture reporting.
- Real visual H7: 5 H6 steps, 135 self maps, 480 text-cross maps; self probability sums validated and all three panels opened in the browser. Artifacts are real but do not imply image-quality acceptance.
- Illustrious cold/warm same-seed PNG hashes match, but both images are visually broken. Strength zero restores a coherent base image; 0.25 remains degraded. These are failed quality cases, retained locally.
- Cyber produces a coherent character. Its first cold/warm experiment overlaps other workload (177.234 / 208.453 s wall time), so it does not prove a speed gain. Further controlled lifecycle/performance acceptance is required.
- Read-only GPU inventory subsequently showed an external Blender process at 100% GPU / 1399 MiB and no Dream worker. This both confirms observed idle worker release and invalidates any uncontended performance claim. Blender was not stopped.
- Backups under `E:/Dream/backups/upgrade-20261023`: prior frontend, runtime configuration and profile/source hashes. Identity runtime persistent worker is enabled for acceptance, with a 60-second idle limit.

Initial state: service8766 not listening; E-drive free approximately7–8 GiB, no deletion authorized or performed. Serving source main c0140fe; identity worktree54f8b04; disk release gui-acceptance-fixes-20261011.
