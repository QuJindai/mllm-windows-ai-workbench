# Android Knowledge Workbench APK Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, self-test, and publish an installable Android Knowledge Workbench APK that preserves the verified Windows Phase C baseline and provides a real offline import/index/search/restart-persistence acceptance path.

**Architecture:** Add an isolated native Android application under `android/knowledge-workbench/`. Use Android SDK + Java 17 + SQLiteOpenHelper, FTS5 with fallback lexical search, deterministic local vectors, cosine retrieval, RRF hybrid ranking, and a diagnostic single-activity UI. CI performs unit, lint, emulator database/UI, install/launch, and APK integrity gates before publishing a prerelease APK.

**Tech Stack:** Android Gradle Plugin 8.9.2, Gradle 8.11.1, Java 17, Android API 35, SQLite/FTS5, JUnit 4, AndroidX Test/Espresso, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-29-knowledge-android-apk-design.md`

## Global Constraints

- Do not modify the verified Windows Phase C product behavior.
- Android package id is `com.mllm.knowledgeworkbench`.
- Min SDK 26; compile/target SDK 35; Java 17.
- No INTERNET permission or cloud fallback in APK v1.
- Unsupported PDF/Office input is rejected, not faked.
- Stable test-only signing key is used so later acceptance APKs can update in place.
- CI-generated versionCode must monotonically increase with GitHub run number.
- APK release occurs only after unit, lint, emulator DB/UI, install/launch, and integrity gates succeed.

---

### Task 1: Android project and pure retrieval core

**Files:**
- Create: `android/knowledge-workbench/settings.gradle.kts`
- Create: `android/knowledge-workbench/build.gradle.kts`
- Create: `android/knowledge-workbench/gradle.properties`
- Create: `android/knowledge-workbench/app/build.gradle.kts`
- Create: `android/knowledge-workbench/app/src/main/AndroidManifest.xml`
- Create: `android/knowledge-workbench/app/src/main/java/com/mllm/knowledgeworkbench/core/TextChunker.java`
- Create: `android/knowledge-workbench/app/src/main/java/com/mllm/knowledgeworkbench/core/LocalHashEmbeddingProvider.java`
- Create: `android/knowledge-workbench/app/src/main/java/com/mllm/knowledgeworkbench/core/ReciprocalRankFusion.java`
- Test: matching `app/src/test/...` JUnit tests.

**Interfaces:**
- `TextChunker.chunk(String documentId, String text) -> List<ChunkDraft>`
- `LocalHashEmbeddingProvider.embed(String text) -> float[]`
- `ReciprocalRankFusion.fuse(List<SearchHit> lexical, List<SearchHit> vector, int limit) -> List<SearchHit>`

- [ ] Write JUnit tests that assert chunk boundaries/overlap, deterministic non-zero finite 128-d vectors, cosine ordering, and RRF ordering/de-duplication.
- [ ] Commit RED tests before the corresponding production classes exist.
- [ ] Add minimal project scaffolding and production classes.
- [ ] Run `gradle testDebugUnitTest` in CI and require PASS.

### Task 2: Persistent Android knowledge repository

**Files:**
- Create: `.../data/KnowledgeContracts.java`
- Create: `.../data/KnowledgeDatabase.java`
- Create: `.../data/KnowledgeRepository.java`
- Create: `app/src/main/assets/sample_knowledge.md`
- Test: `app/src/androidTest/.../KnowledgeRepositoryInstrumentedTest.java`

**Interfaces:**
- `snapshot()` returns lexical readiness, FTS5-vs-fallback mode, vector provider/model, total/indexed chunk coverage, and Hybrid readiness.
- `importText(sourceUri, title, text)` transactionally replaces a document and stale vectors.
- `buildMissingEmbeddings(ProgressListener)` indexes only missing/stale vectors.
- `search(query, SearchMode, limit)` returns durable evidence hits.

- [ ] Write instrumentation test that opens a real device SQLite database, imports a document, verifies lexical search, builds vectors with progress, verifies vector/hybrid search, closes, reopens, and confirms indexed vectors persist.
- [ ] Implement schema creation and runtime FTS5 capability detection with lexical fallback.
- [ ] Implement content hashing, transactional replacement, vector blob encoding/decoding, cosine search, and RRF hybrid search.
- [ ] Seed bundled Markdown exactly once.
- [ ] Run the instrumentation test on Android API 35 emulator and require PASS.

### Task 3: Diagnostic Android UI

**Files:**
- Create: `.../MainActivity.java`
- Create: `.../ui/UiPalette.java`
- Create/update: `AndroidManifest.xml`
- Test: `app/src/androidTest/.../MainActivityInstrumentedTest.java`

**Interfaces:**
- Stable view ids: `status_lexical`, `status_embedding`, `status_hybrid`, `button_import`, `button_build_index`, `progress_index`, `text_index_progress`, `input_query`, `spinner_mode`, `button_search`, `results_container`, `evidence_detail`.

- [ ] Write UI instrumentation test that launches the real Activity and asserts all acceptance controls are present and sample data reaches a ready/searchable state.
- [ ] Implement dense dark diagnostic UI using native Android widgets only.
- [ ] Implement SAF Markdown/Text import and post-import snapshot refresh.
- [ ] Bind vector index progress to percent, completed/total, current chunk and status cards.
- [ ] Bind lexical/vector/hybrid search results and selected evidence detail.
- [ ] Run UI instrumentation test and require PASS.

### Task 4: Update-compatible signing and CI APK publication

**Files:**
- Create: `android/knowledge-workbench/acceptance-debug.keystore` (binary, test-only)
- Create: `.github/workflows/knowledge-android-apk.yml`
- Create: `android/knowledge-workbench/README.md`

**Interfaces:**
- CI output: `MLLM_KNOWLEDGE_WORKBENCH_ANDROID_<run>.apk`
- CI checksum: matching `.sha256`
- GitHub prerelease tag: `knowledge-android-apk-<run>` when commit message contains `[release-apk]`.

- [ ] Configure signing with stable test-only keystore and `versionCode = GITHUB_RUN_NUMBER`.
- [ ] CI: setup Java 17, Android SDK 35, Gradle 8.11.1; run unit tests, lint, assemble.
- [ ] CI: API 35 emulator runs repository and UI instrumentation tests.
- [ ] CI: `adb install -r`, launch MainActivity, capture screenshot and UI XML.
- [ ] CI: inspect package/version, calculate SHA-256, upload APK + evidence artifact.
- [ ] If and only if all gates pass and commit contains `[release-apk]`, publish GitHub prerelease with APK and SHA-256.
- [ ] Verify branch HEAD SHA equals successful workflow HEAD SHA and release asset exists before reporting completion.
