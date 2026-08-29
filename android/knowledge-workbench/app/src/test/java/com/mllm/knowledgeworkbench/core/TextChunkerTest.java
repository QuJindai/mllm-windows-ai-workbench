package com.mllm.knowledgeworkbench.core;

import org.junit.Test;

import java.util.List;

import static org.junit.Assert.*;

public class TextChunkerTest {
    @Test
    public void chunking_has_stable_ids_and_overlap_for_long_text() {
        String paragraph = "整车软件制造管控要求版本可追溯。".repeat(140);
        List<TextChunker.ChunkDraft> chunks = TextChunker.chunk("doc-a", paragraph, 420, 64);

        assertTrue(chunks.size() > 2);
        assertEquals("doc-a:000000", chunks.get(0).chunkId());
        assertEquals(0, chunks.get(0).ordinal());
        assertEquals("doc-a:000001", chunks.get(1).chunkId());

        String firstTail = chunks.get(0).content().substring(chunks.get(0).content().length() - 32);
        assertTrue(chunks.get(1).content().contains(firstTail));
        assertTrue(chunks.stream().allMatch(c -> !c.content().isBlank()));
    }

    @Test
    public void paragraph_boundaries_are_preserved_when_possible() {
        String text = "第一段：软件版本可追溯。\n\n第二段：证据链完整。\n\n第三段：工位版本一致。";
        List<TextChunker.ChunkDraft> chunks = TextChunker.chunk("doc-b", text, 80, 12);

        assertEquals(1, chunks.size());
        assertTrue(chunks.get(0).content().contains("第一段"));
        assertTrue(chunks.get(0).content().contains("第三段"));
    }
}
