# OKF v0.2 Android A/B Validation — Takeover Baseline

Status: ACTIVE
Owner line: ChatGPT takeover / 2026-09-02
Target: S24U local-model handset validation

## 1. Locked upstream baselines

- Google Open Knowledge Format canonical repository: `GoogleCloudPlatform/open-knowledge-format`
  - locked commit: `ad30107c31c06aec8a7d5636e0d1058118604e6f`
  - specification: OKF v0.2
- LangChain OpenWiki producer: `langchain-ai/openwiki`
  - locked commit: `64903f920bb4305246cec9356f07cf91c92b3d25`
  - observed package version: `0.5.0`
- This implementation line is based on the last green S24U Image Harness H6R4 branch:
  - source branch: `feature/s24u-image-harness-h6r4-token-truth`
  - source commit: `1449a03c04c1e81b414f040dceaf213b8651d494`

The frozen `knowledge-catalog/okf` snapshot is not an implementation source. The canonical OKF repository above is authoritative.

## 2. Question this branch must answer

Does an OKF v0.2 knowledge bundle materially improve the answer quality and evidence discipline of the same local small model on the same Android handset, compared with both no external knowledge and ordinary Markdown/RAG?

The experiment must separate model capability from knowledge-packaging capability.

## 3. Required three-arm experiment

Every benchmark case runs with the same model, inference parameters, prompt question and device state:

A. `BARE` — no external corpus.
B. `MARKDOWN` — ordinary Markdown corpus using the same underlying factual content.
C. `OKF_V02` — the same content represented as OKF v0.2 and consumed with OKF-aware routing.

No arm may silently receive facts that are absent from the other knowledge-backed arm.

## 4. OKF v0.2 fields to consume

Minimum parser/consumer support:

- required `type`
- recommended `title`, `description`, `resource`, `tags`
- provenance: `sources[]`, including stable source ids where present
- producer state: `generated`
- verification state: `verified`
- lifecycle: `status`, `stale_after`
- cross-links between concepts
- root/directory `index.md` progressive disclosure
- `Attested Computation` metadata (`runtime`, `parameters`, `computation`, `executor`, `attester`) as a first-class observable contract

Unknown frontmatter keys must be preserved/tolerated rather than rejected.

## 5. Android runtime architecture

```text
Benchmark question
      |
      +--> BARE ------------------------------+
      |
      +--> MARKDOWN -> common retrieval ------+--> same local model -> answer
      |                                       |
      `--> OKF -> OKF parser                   |
                -> trust/freshness gate        |
                -> progressive navigation      |
                -> graph/source expansion -----+
                                                |
                                                `-> evidence + metrics
```

OKF must not be implemented as a second model. It is a deterministic knowledge representation, routing and evidence layer around the same local inference runtime.

## 6. Retrieval fairness contract

- Same chunk text payload where semantically equivalent.
- Same embedding model/index configuration for Markdown and OKF when vector retrieval is used.
- Same top-k budget unless an explicitly reported OKF progressive-disclosure step is under test.
- Every final answer records which concepts/chunks were selected.
- OKF-only gains must be attributable to explicit OKF signals such as links, type, provenance, verification, freshness or attested-computation routing.

## 7. Handset observability

The APK must show, per run:

- selected experiment arm
- model id and runtime parameters
- TTFT
- decode tokens/s
- total latency
- prompt/input token estimate
- generated token count
- retrieval latency
- selected concept/chunk ids
- source/provenance ids
- trust tier derived from `verified`
- freshness/stale decision
- answer text
- benchmark score/verdict

A run must be exportable as a machine-readable evidence record for later comparison.

## 8. Acceptance gates

### G0 — baseline protection
Current S24U harness build/token/source/baseline gates remain green.

### G1 — OKF parser
Conformance fixtures cover required type, optional fields, unknown extensions, links, index files, provenance, trust, lifecycle and Attested Computation metadata.

### G2 — deterministic retrieval
Given the same corpus and query, concept selection is reproducible for deterministic stages and every selected item is explainable.

### G3 — three-arm benchmark
One action runs BARE / MARKDOWN / OKF_V02 against an identical benchmark suite and emits a comparison record.

### G4 — human-readable handset GUI
The user can see the actual knowledge text, selected concepts, links, trust/freshness signals and final evidence chain; raw ids alone are insufficient.

### G5 — physical handset
S24U installation, inference, thermal behavior, performance and repeated-run stability pass.

### G6 — APK delivery
A signed/accepted APK is produced only after automated regression plus the explicit physical-phone gate.

## 9. Initial implementation order

1. Add an OKF v0.2 parser and immutable domain model.
2. Add canonical sample fixtures derived from the upstream spec.
3. Add the three-arm experiment contract and evidence schema.
4. Implement Markdown and OKF knowledge adapters over a shared retrieval interface.
5. Add OKF trust/freshness/link expansion without changing the model runtime.
6. Wire into the existing S24U handset harness and observability screen.
7. Add deterministic unit/golden tests and branch CI.
8. Build APK and perform one consolidated S24U acceptance rather than repeated tiny probes.

## 10. Reuse policy

- Reuse this repository's current green S24U model/runtime harness rather than rebuilding inference.
- Reuse proven local retrieval/embedding ideas from existing user Android projects only where they reduce code and preserve the experiment contract.
- OpenWiki is a producer/reference implementation, not a runtime dependency required on the phone.
- Do not depend on Google Cloud/BigQuery/Gemini for the handset A/B experiment.

## 11. Non-goals for the first APK

- No organization-scale Knowledge Catalog deployment.
- No requirement for network access during inference.
- No cloud LLM in the scored path.
- No attempt to prove that OKF increases base-model intelligence; only measure whether it improves effective task performance through structured knowledge context.

## 12. Takeover state

The prior OKF discussion did not leave a dedicated implementation commit or APK to recover. This branch is the first explicit, reproducible implementation baseline for the OKF Android validation line.
