# Identity history deletion repair — 2026-10-25

## Behavior

Person task history now offers the same confirmed deletion controls as result cards. Completed results, failed/cancelled records, and terminal records with missing output files can be removed. Active tasks cannot be deleted. The person workspace, selected preview, batch available/deleted counts, global history and same-origin browser tabs synchronize acknowledged deletions. Older async responses cannot resurrect a deleted item.

Frozen job/batch metadata, retry lineage, person profiles and reference photos remain unchanged. Generated files (including original and polish stages) use the recoverable history-trash transaction. Empty terminal records use an explicit committed tombstone. Repeated deletion is idempotent; failed commits are rolled back and never announced as successful. Historical completed-item counts remain factual; available results are shown separately.

## Verification

- Frontend: 37 files / 576 tests passed; TypeScript and production build passed.
- Backend: 1438 passed, 2 optional-runtime tests skipped. Existing Pillow deprecation warning only.
- Real browser, isolated loopback backend on port 8877, synthetic images and real routes/file transactions:
  - Person task-history deletion removed the batch result card and task row; batch showed one available / one deleted.
  - A second already-open browser tab updated global history from 3 images to 2 without refreshing.
  - Global-history deletion propagated back to the person-history tab.
  - Failed and cancelled no-result records were removed with record-specific confirmation.
  - Browser reload and server restart did not restore deleted entries.
  - Final state: four hidden task records, two deleted result sets, one preserved sibling result. Nine profile/reference/frozen-record hashes remained unchanged.
  - Screenshot inspection found and corrected the shared delete-control width squeezing the history title; final row is readable.

The fixture disables real inference. No user-generated image or profile was deleted during acceptance, and no GPU generation was needed. This validates deletion behavior, not portrait quality.

## Reproduction and local evidence

`scripts/qa_identity_deletion.py` provides prepare/check/serve/verify commands for the isolated root `E:/Dream/test-runs/identity-deletion-20261025`; it does not reseed an existing fixture. Build the frontend into that root's `frontend` directory before preparing it. The real service remains on port 8766.

- `E:/Dream/test-runs/identity-deletion-20261025/fixture.json`: synthetic IDs and preservation hashes.
- `E:/Dream/test-runs/identity-deletion-20261025/frontend-tests.log`: full frontend run.
- `E:/Dream/repo/output/playwright/identity-history-deletion.png`: final history layout.
- `E:/Dream/repo/output/playwright/deletion-second-tab.txt` and `deletion-reverse.txt`: cross-tab UI evidence.
- Backend full-run log: `C:/Users/Admin/AppData/Local/Temp/dream-history-delete-backend-20261025-061945.log`.
