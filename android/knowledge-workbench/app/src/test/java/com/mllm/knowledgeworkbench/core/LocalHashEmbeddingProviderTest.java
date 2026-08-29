package com.mllm.knowledgeworkbench.core;

import org.junit.Test;

import static org.junit.Assert.*;

public class LocalHashEmbeddingProviderTest {
    @Test
    public void embedding_is_deterministic_finite_nonzero_and_128d() {
        LocalHashEmbeddingProvider provider = new LocalHashEmbeddingProvider();
        float[] first = provider.embed("整车软件制造版本追溯");
        float[] second = provider.embed("整车软件制造版本追溯");

        assertEquals(128, first.length);
        assertArrayEquals(first, second, 0f);
        double norm = 0d;
        for (float value : first) {
            assertTrue(Float.isFinite(value));
            norm += value * value;
        }
        assertTrue(norm > 0.9d);
    }

    @Test
    public void related_chinese_phrases_are_closer_than_unrelated_text() {
        LocalHashEmbeddingProvider provider = new LocalHashEmbeddingProvider();
        float[] vehicle = provider.embed("整车软件版本制造追溯证据");
        float[] related = provider.embed("车辆软件制造版本追溯");
        float[] fruit = provider.embed("香蕉苹果水果库存管理");

        double relatedScore = LocalHashEmbeddingProvider.cosine(vehicle, related);
        double unrelatedScore = LocalHashEmbeddingProvider.cosine(vehicle, fruit);
        assertTrue("related=" + relatedScore + " unrelated=" + unrelatedScore, relatedScore > unrelatedScore);
    }
}
