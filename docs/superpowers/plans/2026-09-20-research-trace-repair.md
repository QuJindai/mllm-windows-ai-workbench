# Research trace repair

User-approved scope: complete H6 conditioning influence and H7 self/cross attention in the browser app. Preserve existing dirty GUI work and ordinary generation. No commits, pushes, unrelated cleanup, or EXE work.

## Contract and limits

Existing cross attention contract and endpoints stay unchanged.

Self attention: `self-attention-index.json` with contractVersion `h7-self-attention-v1`, kind `self-attention`, truth `observed`, source `debug-unet`, layers (same shape as cross), maps [{id,step,layerId,queryIndex,queryX,queryY,width,height,entropy,peak,coverage,fileName}]. Individual map has the same identity/marker fields plus values, no fileName. Values are raw head-mean softmax probabilities, not display-normalized. Query coordinates are integer positions on the width/height latent grid. Nine fixed spatial anchors per layer, five sampled steps, three representative layers, at most 512 maps, <=128x128 finite values in [0,1]. APIs GET `/api/traces/{runId}/self-attention` and `/api/traces/{runId}/self-attention/maps/{mapId}` parallel the cross responses with available, runId, mapUrl and unavailable reason.

H6: `conditioning-influence.json` with contractVersion `h6-conditioning-v1`, kind `conditioning-influence`, truth `observed`, source `debug-unet`, method `chunk-vs-full-guided`, chunkSize 77, totalChunks integer, capturedChunks <=3, steps [{step,width,height,cfgDeltaL2,cfgCosine,chunks:[{chunk,tokenStart,tokenEnd,meanAbs,l2,cosineFull,deltaL2,spatialDelta:[...]}]}]. Raw finite metrics and channel-mean absolute difference maps; cosine in [-1,1]. Step is zero based. Maps <=128x128; <=5 steps, <=3 chunks. Conditional chunk prediction is guided with the same unconditioned tensor and CFG; compare against actual full-context guided prediction. This is a diagnostic comparison, NOT evidence that Windows production averages chunk predictions. One chunk has an exact zero delta; CFG=1 has no unconditioned pass and zero CFG delta. API GET `/api/traces/{runId}/influence` adds available/runId or truthful unavailable reason. No raw filesystem paths exposed.

H6/H7 research runs use upgraded isolated CLI. H6 enables conditioning+latent only; H7 enables conditioning+latent+self+cross. Basic/off preserve current persistent fast path. CLI new `--conditioning-trace-path DIR`; existing attention flag also writes bounded self maps. Packaging manifest adds h6-conditioning-v1,h7-self-attention-v1 only after built help and real validation.

## Tasks

1. Native engine: test math/sampling first; add bounded self reduction and H6 opt-in callback and CLI serialization without altering production tensors; build CUDA target. Files only under separate native H7 source tree.
2. Server: strict bounded fail-closed validation, safe artifact paths, endpoints, compatible trace listing and capability truthfulness. Files only apps/dream-windows/server/**. Test absent/valid/malformed artifacts and routes. Do not infer new capabilities from old manifests.
3. UI: domain/provider contracts, real H6 metrics/maps and self anchor selection, truthful empty states and compatible run discovery; preserve existing GUI fixes. Files only apps/dream-windows/src/**. Test rendering, provider calls, unavailable records.
4. Integration: wrapper/packager research selection, tests, safe binary deployment with backup, sequential real GPU research run and output parity check, production build and browser QA.

## Acceptance

Test suites pass; live multi-chunk run contains nonzero H6 differences and finite self/cross maps; basic still works with no research instrumentation. Browser can choose correct run and display measured panels. Never use mock traces or generated decorative heatmaps as evidence. Report measured timing/limits and any unverified boundary.

## Ledger

- Preflight: native output -> server contract -> UI contract fixed above. Disjoint write scopes.
- Ruling: extend current user-requested working checkout with existing uncommitted GUI fixes rather than isolate and lose the live continuation state; preserve all unrelated changes.
- Ruling: distinguish chunk-vs-full diagnostics from phone arithmetic-mean fusion because the Windows production conditioning architecture differs. Cost: extra sampled research passes, disclosed in UI.
- Task 1 complete: native CUDA engine built, helper assertions and callback contracts pass, actual H6/Self/Cross emitted. Production latent callback ported to preserve raw telemetry.
- Task 2 complete: strict interfaces and validations, focused RED/GREEN, final backend+wrapper 204 passed.
- Task 3 complete: Chinese measured panels, safe empty states and compatibility discovery; final frontend 155 passed, production build passed.
- Task 4 complete: backed up installed research binaries, deployed, real final job-53a948ac3474, 135 Self/480 Cross/5 H6 samples/20 latent steps, output parity exactly zero; GUI operated and inspected.
- Final review: independent native review, no browser-path P0/P1. Classified direct CLI oversized request as important due allocation risk; added shared dimension guard RED/GREEN and actual rejection check. H7 CLI now consistently disables FA. API guard also rejects research sizes over1024 before submitting jobs.
- Acceptance report: docs/dream-windows/H6_H7_REPAIR_ACCEPTANCE_20260920.md. No Git commits or automatic merges: user changes and concurrent model-registry work preserved.
