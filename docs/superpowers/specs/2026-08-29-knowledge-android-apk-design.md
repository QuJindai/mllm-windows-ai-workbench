# Android Knowledge Workbench APK Design

## Goal

Extend the existing M-LLM Knowledge Workbench with an installable Android acceptance client without modifying the verified Windows Phase C baseline. The APK must be self-contained enough to validate import, persistent local retrieval, vector indexing, hybrid ranking, evidence display, and visible indexing progress on a physical Android device.

## Branch and compatibility

- Base: `feature/knowledge-phase-c@22f61dc9fcb9e00140df2881d546411d18b676e4`.
- Android work lives on `feature/knowledge-android-apk` and under `android/knowledge-workbench/`.
- Existing Windows/.NET/WPF source files are not rewritten for the APK milestone.
- Package id: `com.mllm.knowledgeworkbench`.
- Minimum Android API: 26. Compile/target API: 35. Java runtime/toolchain: 17.
- CI-generated versionCode uses GitHub run number so a newer APK can update an older one.
- APKs use one committed test-only debug keystore so acceptance builds remain update-compatible. This key is never a production signing identity.

## Architecture

The Android client is a native single-activity application using Android SDK widgets and `SQLiteOpenHelper`; no WebView and no remote backend are required for the acceptance path. The repository owns documents, chunks, an FTS5 virtual table, persisted float vectors, lexical/vector search, and reciprocal-rank-fusion hybrid search.

The first APK uses `LocalHashEmbeddingProvider`, a deterministic offline local vectorizer. It is intentionally identified as a local hash embedding provider rather than presented as a neural embedding model. The provider interface is isolated so a later on-device neural provider can replace it without changing repository or UI contracts.

## Data model

SQLite contains:

- `documents(document_id, source_uri, title, content_sha256, updated_at_ms)`
- `chunks(chunk_id, document_id, ordinal, content, content_sha256)`
- `chunks_fts` using FTS5 when available
- `embeddings(chunk_id, provider_id, model_id, dimension, vector, content_sha256, updated_at_ms)`

If device SQLite lacks FTS5, initialization reports lexical fallback mode and uses a deterministic `LIKE` fallback rather than crashing or falsely reporting FTS5 readiness.

## Import and persistence

- Android Storage Access Framework selects `.md`, `.markdown`, or `.txt` sources.
- Imported content is copied into app-private storage and indexed transactionally.
- Re-import replaces stale chunks and invalidates stale vectors.
- A bundled sample Markdown document is seeded once so the APK can be verified immediately after install.
- Database and vectors survive process restart and APK relaunch.

## Retrieval

- Lexical mode: FTS5 phrase/term query when available, fallback lexical query otherwise.
- Embedding mode: cosine similarity over persisted local vectors.
- Hybrid mode: reciprocal-rank fusion over lexical and vector result rankings.
- Every hit includes durable document id, chunk id, source, title, ordinal, excerpt, and score.

## UI

The screen is intentionally dense and diagnostic rather than decorative. It contains:

1. FTS/lexical, Embedding, and Hybrid status cards.
2. Database path and index coverage `indexed/total`.
3. Import button and last imported source.
4. Explicit `Build / Repair Vector Index` control.
5. Progress bar, percentage, `completed/total`, and current chunk id.
6. Search query, mode selector, and search button.
7. Ranked result list with title, score, source, and excerpt.
8. Evidence detail panel for the selected hit.

Hybrid is shown as ready only when lexical indexing is ready and current-provider vector coverage is complete for a non-empty knowledge base.

## Safety and offline behavior

- No OpenAI API key, cloud embedding endpoint, account login, or network permission is required.
- The application manifest omits Internet permission for the first APK.
- Unsupported binary formats such as PDF are rejected rather than silently treated as text.
- Imported external URIs are read through SAF; the persisted indexed copy is app-private.

## Acceptance gates

The user is not required to run development tests. CI must complete all gates before APK publication:

1. JVM unit tests for chunking, deterministic vectors, cosine ranking, and RRF.
2. Android Lint.
3. Debug APK assembly with stable acceptance signing identity.
4. Emulator instrumentation test that creates a real SQLite database, seeds/imports content, builds vectors, exercises lexical/vector/hybrid search, closes the repository, reopens it, and verifies persistence.
5. Emulator UI smoke test that launches the real Activity and verifies key status/import/index/search/evidence controls.
6. `adb install -r` of the produced APK and Activity launch smoke.
7. APK manifest/package/version inspection and SHA-256 generation.
8. Screenshot and UI hierarchy capture as CI evidence.
9. Only after all prior gates pass, publish a GitHub prerelease asset containing the APK and SHA-256 file.

## Non-goals for this APK milestone

- PDF/Office parsing.
- Bundled neural embedding model.
- RAG answer generation by an LLM.
- Cloud synchronization.
- Play Store production signing.

These are later milestones and are not faked in the acceptance APK.
