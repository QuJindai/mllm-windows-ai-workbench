# Dream H6R5 Semantic Fidelity + Truth Plan

Baseline: `main@df7d8da4c398e05dc54475c656a5638158b1478c` (clean H6R4 backport)

## Goal
Fix remaining generation-semantic and observability gaps before H7 attention work.

## P0
1. Semantic A/B harness: same model/prompt/negative/seed, compare `first_only`, `equal_mean`, `token_weighted`, `anchor_residual`.
2. Step sweep: same model/prompt/negative/seed/fusion, compare 8/16/24 steps.
3. Model Identity Truth: record model id/name/backend, SDXL/SD1.5, DMD2, LoRA list, scheduler, seed, steps, CFG, and model-file identity (at minimum `unet.bin` SHA-256 when present).
4. Preserve H6R4 token invariants; no text->escape->retokenize regression.

## P1
1. Conditioning Influence image completeness: every numeric sample must have a corresponding image or an explicit capture error state.
2. Human-readable token UI by default; raw BPE (`</w>`) and raw IDs stay behind Raw Evidence.
3. Process Dynamics visual density: signed/magnitude delta views and explicit metric labels.
4. Time Accounting: keep native observed counters and reduce/identify unattributed time.

## H7 gate
Do not start Debug UNet cross-attention export until H6R5 P0/P1 handset acceptance passes.

## Merge gate
- Token Preservation PASS
- four fusion modes reproducible with same seed
- 8/16/24 step sweep reproducible
- model identity provable per result
- influence image coverage complete
- default UI free of raw `</w>` pollution
- Runtime Graph expected/observed truth preserved
- S24U acceptance complete
