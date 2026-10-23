# Identity profiles, batches and observation Implementation Plan

> **For agentic workers:** Use test-driven-development. Coordinate disjoint backend and frontend work through dispatching-parallel-agents; coordinator owns inference/event implementation and final integration/review.

**Goal:** Create a named person once, reuse it after restart, generate several images in one model session and observe real sampling progress/previews.

**Architecture:** Extend the existing isolated FaceID process and shared GPU queue, preserve old single-job APIs. Profiles own reusable reference features; batches own several individually persisted output jobs. Real callback events are read incrementally by the web service and polled by the UI.

**Tech Stack:** Existing FastAPI/Pydantic, React/TypeScript, Diffusers 0.36/PyTorch CUDA, local JSON/NDJSON/safetensors. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-20-identity-profiles-batches-design.md` (complete HTTP, worker and event interfaces).

## Global Constraints

- Keep Realistic Vision V5.1 SD1.5, FaceID Plus V2, companion LoRA and original read-only weight locations. E-drive new data only.
- One GPU job at a time; batch serial items reuse one loaded pipeline; process exits after batch. Preserve Windows child lifetime and storage lease protections.
- Feature extraction and calibration are distinct; no personal LoRA training or auto replacing reference with generated face.
- Only delta after 6f16d1d belongs to this upgrade; main repo contains unrelated dirty changes. Hash-check touched files before integration. Do not push or merge unrelated history.
- count 1..8, unique stepValues 1..50 up to4, max16 total; previewEvery 0/5/10; matching-seed step comparisons; no fake images/progress.

## Review Focus

1. Crash/cancel after first completed item must preserve that image and history while stopping remaining samples.
2. Archive or change profile while queued jobs exist must not silently apply another person's face; frozen binding required.
3. Worker event partial writes, nonfinite values and forged file names must not escape preview storage or corrupt progress.
4. Warm profile reuse must bypass face re-extraction; weights/reference changes must invalidate stale fingerprints/features.
5. Browser refresh/late responses must not submit again or replace the newly selected profile/batch.

## Task 1: Feature reuse, batched inference, real events (coordinator)

Files: new `server/identity_features.py`, `identity_events.py`, `tests/test_identity_events.py`, `tests/test_identity_batch_worker.py`; modify `identity_pipeline.py`, `identity_worker.py`. Paths relative to `apps/dream-windows`.

Interfaces: produce prepare(config,request), generate_batch(config,request), emit_event(path,event), read_events(path,offset) exactly as spec; old generate(config,request) retained. Backend consumes worker operation prepare/batch and the read_events function.

- [x] RED tests: partial event line invisible until newline; malformed/oversized lines fail safe; deterministic paired seeds in backend contract; cached fingerprint invalidation; fake slow pipeline boundary demonstrates one construction for two real coordinator-loop outputs.

```python
def test_partial_event_is_not_consumed(tmp_path):
    from identity_events import read_events
    path = tmp_path / 'events.ndjson'
    path.write_bytes(b'{"type":"step"')
    assert read_events(path, 0) == ([], 0)
    path.write_bytes(b'{"type":"step"}\n')
    assert read_events(path, 0) == ([{'type':'step'}], 16)
```

- [x] Run `python -m pytest apps/dream-windows/server/tests/test_identity_events.py apps/dream-windows/server/tests/test_identity_batch_worker.py -q`; observe missing production behavior RED.
- [x] Implement stdlib-only bounded event IO and file fingerprint registry; extract reusable feature preparation; construct one Diffusers pipeline then loop images with callback events and optional atomic 256px VAE preview. Write complete image+metadata before item_complete.
- [x] Run targeted tests then server suite; capture actual two-image CUDA worker batch after integration.

## Task 2: Profiles, batch persistence, queue and API (backend worker)

Files: `server/identity_service.py`, `identity_routes.py`; new `identity_profiles.py` / `identity_batches.py` as needed; new `tests/test_identity_profiles.py`, `test_identity_batches.py`. Do not edit coordinator's pipeline/worker/events nor frontend.

Interfaces: all HTTP models and endpoints exactly in spec; use existing `_worker(operation,payload,cancelled)` with event callback support internally. Its normal 3-argument use must remain compatible. Legacy generate unchanged. All asynchronous profile preparation uses same executor and lifetime barriers as batches.

- [x] RED tests using TestClient + real temp storage and controlled worker boundary: create profile -> ready -> new service restore; wrong face/unknown ID; batch seeds paired across stepValues; total limit rejected; another person's job cannot become preset.

```python
def test_calibration_pairs_seed_across_steps(client, ready_profile, request):
    response = client.post('/api/identity/batches', json={'profileId':ready_profile['id'], 'request':request, 'count':2, 'stepValues':[20,28], 'previewEvery':0})
    assert response.status_code == 200
    assert [(j['request']['seed'],j['request']['steps']) for j in response.json()['items']] == [(42,20),(42,28),(43,20),(43,28)]
```

- [x] Run new profile/batch tests and confirm RED before implementation.
- [x] Implement bounded profile/batch contracts, freeze references/seeds, async profile warmup, incremental worker event consumption with strict bounds, atomic persistence, scoped preview serving; cancellation/restart preserve complete items. Protect all new writes with origin/size checks.
- [x] Add tests for cancellation after item1, restart recovery, in-use archive conflict, dirty/partial events, forged preview paths, shutdown errors. Run new plus existing server suites.

## Task 3: Browser profile library, batch controls and observation (frontend worker)

Files: `src/domain/identity.ts`, `src/providers/identity-api.ts`, `src/app/pages/IdentityPage.tsx`, scoped CSS and new components under `src/app/components/identity/`; corresponding tests. Do not edit backend.

Interfaces: exact Profile/Batch/BatchRequest from spec. Legacy single Job history still supported. LocalStorage only draft + selectedProfileId/lastBatchId; no biometric bytes.

- [x] RED tests at HTTP boundary: create/archive named profile, restore after mount, select defaults, batch count + step comparison payload, real step text/preview, cancel retains completed grid, save chosen result preset; no auto submission on refresh.

```typescript
expect(screen.getByRole('status', { name: '批次进度' })).toHaveTextContent('第 2 / 4 张');
expect(screen.getByText('12 / 28 步')).toBeInTheDocument();
expect(screen.getByAltText('采样中间预览')).toHaveAttribute('src', previewUrl);
```

- [x] Run focused tests to RED, implement using scoped components and existing dark Chinese UI.
- [x] Show stage/elapsed/estimated ETA distinctly, visible complete cards before batch ends, 0/5/10 preview setting, disabled conflicting changes, error explanations, accessible form/buttons. Poll same batch across navigation and remount.
- [x] Run full frontend test suite and build only to `E:/Dream/test-runs/identity-profiles-20260920/frontend` until release.

## Task 4: End-to-end and release (coordinator)

Files: guide and acceptance report. No new models/installers.

- [x] Full server/config and frontend suites + build; independent final review focused on five failure classes, fix with RED/GREEN.
- [x] Isolated QA on 8870 with separate data root to avoid taking live8766 lease; only one real GPU workload at once. Real named profile, restart reuse, two-image batch, paired-step calibration, progress/intermediate-image UI, cancel after one result, resume via new batch, original history.
- [x] Open actual original images and preview; measure batch warm vs cold/model load count, no unsupported quality/speed claims.
- [x] Verify main touched files still equal baseline6f16d1d, integrate only task delta, backup frontend, build and restart verified idle Dream8766, verify actual live GUI/API and existing desktop launcher.
- [x] Record tests, measured performance, known limitations and local commit; leave main user's other edits intact.

## Execution ledger

User approved the full in-chat workflow and previously explicitly rejected repeated small confirmations. Ruling: write spec/plan and execute continuously under that preference, without additional spec/plan approval prompts; no expansion to models, training, or remote publishing. Reuse existing verified worktree `E:/Dream/worktrees/identity-sd15`, baseline6f16d1d. Ignore two pre-existing `.identity-build` compiler caches.

Execution method: coordinator implements critical inference/events, independent bounded frontend/backend slices use parallel-agent skill, one whole-delta reviewer. This is not the per-task inline executing-plans flow. Contract above is frozen before delegation; changes require a recorded interface note to both workers.

Completion evidence: final Python 424 passed, frontend 214 passed (bounded maxWorkers=2), production build passed, independent findings closed. Only 28 approved delta files integrated; 68 unrelated main dirty files retained byte-for-byte. Actual 8766 browser profile/batch/preview, 2/2 images, 43.734s with previews; prior isolated restart and cancellation each retained completed items. See docs/dream-windows/IDENTITY_PROFILES_ACCEPTANCE_20260920.md. Code and docs committed on the isolated feature branch only; no push or unrelated merge.
