# Knowledge Workbench Phase C Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local persistent knowledge retrieval core beginning with SQLite FTS5 evidence search, then extend it to vector and hybrid retrieval without changing Phase B baselines.

**Architecture:** A new `MLLM.Workbench.Knowledge` .NET 8 library owns SQLite persistence and retrieval. Phase C1 delivers the full FTS5 vertical slice first; later slices inject embeddings and hybrid ranking through explicit contracts.

**Tech Stack:** .NET 8, C#, Microsoft.Data.Sqlite 8.0.30, SQLite FTS5, xUnit, GitHub Actions Windows 2022/2025.

**Spec:** `docs/superpowers/specs/2026-08-29-knowledge-phase-c-design.md`

## Global Constraints

- Do not modify frozen/green Phase B backend model/service behavior.
- Knowledge indexing is local-only and performs no network actions.
- Every returned search hit carries durable document/chunk/source provenance.
- Database writes are transactional and restart-persistent.
- CI must run on both `windows-2022` and `windows-2025`.

---

### Task 1: RED gate for FTS5 evidence persistence

**Files:**
- Create: `tests/knowledge/MLLM.Workbench.Knowledge.Tests/MLLM.Workbench.Knowledge.Tests.csproj`
- Create: `tests/knowledge/MLLM.Workbench.Knowledge.Tests/KnowledgeStoreTests.cs`
- Create: `.github/workflows/knowledge-phase-c.yml`

**Interfaces:**
- Consumes: none.
- Produces test expectations for `KnowledgeStore`, `KnowledgeStoreOptions`, `KnowledgeDocument`, `KnowledgeChunk`, and `KnowledgeSearchHit`.

- [ ] **Step 1: Write failing tests** covering FTS5 health, Chinese/English evidence search, targeted re-import, and reopen persistence.
- [ ] **Step 2: Push the RED gate and verify both Windows jobs fail because the production knowledge project/types are missing.**
- [ ] **Step 3: Keep the RED commit unchanged as evidence of the feature gate.**

### Task 2: Minimal C1 knowledge library

**Files:**
- Create: `src/MLLM.Workbench.Knowledge/MLLM.Workbench.Knowledge.csproj`
- Create: `src/MLLM.Workbench.Knowledge/KnowledgeContracts.cs`
- Create: `src/MLLM.Workbench.Knowledge/KnowledgeStore.cs`
- Modify: `Directory.Packages.props`
- Modify: `tests/knowledge/MLLM.Workbench.Knowledge.Tests/MLLM.Workbench.Knowledge.Tests.csproj`

**Interfaces:**
- Consumes test contracts from Task 1.
- Produces persistent FTS5 store APIs defined by the design spec.

- [ ] **Step 1: Add `Microsoft.Data.Sqlite` 8.0.30 centrally and reference it only from the knowledge project.**
- [ ] **Step 2: Implement schema initialization with foreign keys, documents, chunks, and `chunks_fts` using FTS5 trigram.**
- [ ] **Step 3: Implement transactional document upsert/re-index.**
- [ ] **Step 4: Implement FTS search joined back to source metadata and return ranked evidence hits.**
- [ ] **Step 5: Implement health reporting including SQLite version and explicit FTS5 readiness.**
- [ ] **Step 6: Run the complete Phase C matrix and require 0 failures / 0 skipped tests.**

### Task 3: C2 embedding contract and persistence

**Files:**
- Create: `src/MLLM.Workbench.Knowledge/Embeddings/IEmbeddingProvider.cs`
- Create: `src/MLLM.Workbench.Knowledge/Embeddings/VectorCodec.cs`
- Modify: `src/MLLM.Workbench.Knowledge/KnowledgeStore.cs`
- Create: `tests/knowledge/MLLM.Workbench.Knowledge.Tests/EmbeddingStoreTests.cs`

**Interfaces:**
- `Task<ReadOnlyMemory<float>> EmbedAsync(string text, CancellationToken cancellationToken)`
- vector persistence keyed by `chunk_id` plus provider/model identity and dimension.

- [ ] **Step 1: Add failing vector persistence/reopen tests using a deterministic test provider.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement binary float vector serialization and metadata validation.**
- [ ] **Step 4: Verify GREEN on both Windows versions.**

### Task 4: C3 hybrid retrieval

**Files:**
- Create: `src/MLLM.Workbench.Knowledge/HybridSearch.cs`
- Create: `tests/knowledge/MLLM.Workbench.Knowledge.Tests/HybridSearchTests.cs`

**Interfaces:**
- consumes FTS ranked hits and vector ranked hits.
- produces deterministic reciprocal-rank-fusion hits retaining evidence provenance.

- [ ] **Step 1: Add failing ranking tests for lexical-only, semantic-only, overlap, and tie stability.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement minimal reciprocal-rank fusion.**
- [ ] **Step 4: Verify GREEN and no Phase B regression.**

### Task 5: C4/C5 evidence and desktop integration

**Files:**
- Create: `src/MLLM.Workbench.Desktop/Pages/Knowledge/*`
- Create: `tests/desktop/MLLM.Workbench.Desktop.Tests/KnowledgePageViewModelTests.cs`
- Modify: desktop navigation/composition files only after C1–C4 are green.

**Interfaces:**
- native UI consumes knowledge status/import/search APIs; it never directly manipulates SQLite.

- [ ] **Step 1: RED test for import/search/evidence-open state.**
- [ ] **Step 2: Implement view model against the green knowledge core.**
- [ ] **Step 3: Add restart-persistence GUI acceptance.**
- [ ] **Step 4: Run complete desktop + knowledge matrices before packaging.**
