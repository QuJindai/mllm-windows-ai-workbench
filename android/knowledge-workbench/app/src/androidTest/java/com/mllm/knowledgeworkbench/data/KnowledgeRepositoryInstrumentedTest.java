package com.mllm.knowledgeworkbench.data;

import android.content.Context;

import androidx.test.core.app.ApplicationProvider;
import androidx.test.ext.junit.runners.AndroidJUnit4;

import com.mllm.knowledgeworkbench.data.KnowledgeContracts.IndexProgress;
import com.mllm.knowledgeworkbench.data.KnowledgeContracts.SearchHit;
import com.mllm.knowledgeworkbench.data.KnowledgeContracts.SearchMode;
import com.mllm.knowledgeworkbench.data.KnowledgeContracts.Snapshot;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

import java.util.ArrayList;
import java.util.List;

import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class KnowledgeRepositoryInstrumentedTest {
    private static final String DB = "knowledge-acceptance-test.db";
    private Context context;

    @Before
    public void setUp() {
        context = ApplicationProvider.getApplicationContext();
        context.deleteDatabase(DB);
    }

    @After
    public void tearDown() {
        context.deleteDatabase(DB);
    }

    @Test
    public void import_index_hybrid_and_vectors_survive_repository_reopen() {
        String source = "memory://vehicle-standard.md";
        List<IndexProgress> progress = new ArrayList<>();

        try (KnowledgeRepository first = new KnowledgeRepository(context, DB)) {
            Snapshot empty = first.snapshot();
            assertTrue(empty.lexicalReady());
            assertEquals(0, empty.totalChunks());
            assertEquals(0, empty.indexedChunks());
            assertFalse(empty.hybridReady());

            first.importText(source, "整车软件制造管控", "整车车辆制造软件版本追溯证据链完整。\n\n工位版本必须保持一致并可追溯。");
            Snapshot imported = first.snapshot();
            assertTrue(imported.totalChunks() > 0);
            assertEquals(0, imported.indexedChunks());
            assertFalse(imported.hybridReady());

            List<SearchHit> lexical = first.search("车辆制造", SearchMode.LEXICAL, 10);
            assertFalse(lexical.isEmpty());
            assertEquals(source, lexical.get(0).sourceUri());

            Snapshot indexed = first.buildMissingEmbeddings(progress::add);
            assertEquals(indexed.totalChunks(), indexed.indexedChunks());
            assertTrue(indexed.hybridReady());
            assertEquals(indexed.totalChunks(), progress.size());
            assertEquals(indexed.totalChunks(), progress.get(progress.size() - 1).completed());
            assertEquals(100, progress.get(progress.size() - 1).percent());

            List<SearchHit> semantic = first.search("车辆软件版本追溯", SearchMode.EMBEDDING, 10);
            assertFalse(semantic.isEmpty());
            assertEquals(source, semantic.get(0).sourceUri());

            List<SearchHit> hybrid = first.search("车辆制造", SearchMode.HYBRID, 10);
            assertFalse(hybrid.isEmpty());
            assertEquals(source, hybrid.get(0).sourceUri());
        }

        try (KnowledgeRepository reopened = new KnowledgeRepository(context, DB)) {
            Snapshot persisted = reopened.snapshot();
            assertTrue(persisted.hybridReady());
            assertTrue(persisted.totalChunks() > 0);
            assertEquals(persisted.totalChunks(), persisted.indexedChunks());

            List<IndexProgress> secondPass = new ArrayList<>();
            reopened.buildMissingEmbeddings(secondPass::add);
            assertTrue("persisted vectors must not be recomputed", secondPass.isEmpty());
            assertFalse(reopened.search("版本追溯", SearchMode.HYBRID, 10).isEmpty());
        }
    }

    @Test
    public void reimport_invalidates_stale_vectors_until_reindexed() {
        try (KnowledgeRepository repository = new KnowledgeRepository(context, DB)) {
            repository.importText("memory://a.md", "A", "车辆制造版本追溯");
            repository.buildMissingEmbeddings(progress -> {});
            assertTrue(repository.snapshot().hybridReady());

            repository.importText("memory://a.md", "A", "香蕉苹果水果库存");
            Snapshot changed = repository.snapshot();
            assertTrue(changed.totalChunks() > 0);
            assertEquals(0, changed.indexedChunks());
            assertFalse(changed.hybridReady());
        }
    }
}
