package com.mllm.knowledgeworkbench.core;

import org.junit.Test;

import java.util.List;
import java.util.Map;

import static org.junit.Assert.*;

public class ReciprocalRankFusionTest {
    @Test
    public void rrf_fuses_and_deduplicates_rankings() {
        Map<String, Double> scores = ReciprocalRankFusion.fuse(
            List.of("a", "b", "c"),
            List.of("b", "d", "a"),
            10);

        assertEquals(4, scores.size());
        assertEquals("b", scores.keySet().iterator().next());
        assertTrue(scores.get("b") > scores.get("c"));
        assertTrue(scores.get("a") > scores.get("c"));
    }

    @Test
    public void rrf_honors_limit() {
        Map<String, Double> scores = ReciprocalRankFusion.fuse(
            List.of("a", "b", "c"),
            List.of("d", "e", "f"),
            3);

        assertEquals(3, scores.size());
    }
}
