# Knowledge Workbench Phase C Design

## Goal

Add a local-first, restart-persistent knowledge retrieval core to the existing Windows AI Workbench without changing the already-green Phase B model/service contracts.

## Scope

Phase C is intentionally split into independently verifiable vertical slices:

1. **C1 — FTS5 persistent evidence store**: SQLite database, FTS5 full-text index, document/chunk import, evidence-bearing search results, reopen persistence.
2. **C2 — Embedding provider contract + vector persistence**: provider is injectable; CI uses a deterministic provider, production providers are added separately so tests never download models.
3. **C3 — Hybrid retrieval**: reciprocal-rank fusion of FTS5 and vector candidates with deterministic ranking and provenance.
4. **C4 — RAG evidence contract**: every result must expose document id, chunk id, source path/URI, score, and exact excerpt; no answer may become detached from its source record.
5. **C5 — desktop integration**: expose import/search/status in the native desktop UI only after C1–C4 are green.

This first implementation pass starts with **C1** and establishes the contracts needed by C2–C4.

## Architecture

Create a new `MLLM.Workbench.Knowledge` .NET 8 library. It owns only local knowledge indexing and retrieval. It does not start models, services, installers, or network operations.

`KnowledgeStore` wraps a SQLite database under a caller-provided data root. The schema contains normalized `documents` and `chunks` tables plus an FTS5 virtual table. FTS rows reference durable chunk ids so search results can always be joined back to evidence metadata.

FTS5 uses SQLite's `trigram` tokenizer for robust CJK substring matching while preserving a single SQLite-backed implementation. The store exposes a health snapshot including SQLite version and FTS5 availability so the GUI/Doctor can later make failures visible instead of silently degrading.

## Data model

- `documents`: `document_id`, `source_uri`, `title`, `content_sha256`, `updated_at_utc`
- `chunks`: `chunk_id`, `document_id`, `ordinal`, `content`, `content_sha256`
- `chunks_fts`: FTS5 virtual table over `content`, keyed by chunk row id

`document_id` and `chunk_id` are caller-controlled stable identifiers. Imports are transactional and idempotent by `document_id`: re-import replaces that document's chunks and FTS rows atomically.

## Public contracts

- `KnowledgeStoreOptions(string DatabasePath)`
- `KnowledgeDocument(string DocumentId, string SourceUri, string Title, IReadOnlyList<KnowledgeChunk> Chunks)`
- `KnowledgeChunk(string ChunkId, int Ordinal, string Content)`
- `KnowledgeSearchHit(string DocumentId, string ChunkId, string SourceUri, string Title, int Ordinal, string Excerpt, double Score)`
- `KnowledgeStoreHealth(bool DatabaseReady, bool Fts5Ready, string SQLiteVersion, string DatabasePath)`
- `KnowledgeStore.InitializeAsync(...)`
- `KnowledgeStore.UpsertDocumentAsync(...)`
- `KnowledgeStore.SearchFtsAsync(query, limit, ...)`
- `KnowledgeStore.GetHealthAsync(...)`

## Safety and persistence

- Database path is explicit and local; Phase C performs no network access.
- Every write uses a transaction.
- Foreign keys are enabled.
- Re-import of one document cannot delete another document.
- Search returns evidence metadata from normalized tables, not only FTS text.
- Closing and reopening the store must preserve imported data and search behavior.

## Testing

CI runs on `windows-2022` and `windows-2025` with .NET 8. C1 acceptance requires:

1. FTS5 is available and reported by the health API.
2. Chinese and English content can be imported and searched.
3. Search results contain exact source/document/chunk provenance.
4. Re-import replaces only the target document's index rows.
5. Database close/reopen preserves results.
6. Existing Phase B workflow remains untouched.

## Dependency

Use `Microsoft.Data.Sqlite` 8.0.30, matching the current .NET 8 servicing line. No ORM is introduced.
