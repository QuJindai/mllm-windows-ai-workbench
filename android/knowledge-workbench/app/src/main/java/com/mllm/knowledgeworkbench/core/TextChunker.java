package com.mllm.knowledgeworkbench.core;

import java.util.ArrayList;
import java.util.List;

public final class TextChunker {
    private TextChunker() {}

    public record ChunkDraft(String chunkId, int ordinal, String content) {}

    public static List<ChunkDraft> chunk(String documentId, String text, int targetChars, int overlapChars) {
        if (documentId == null || documentId.isBlank()) throw new IllegalArgumentException("documentId is required");
        if (text == null || text.isBlank()) throw new IllegalArgumentException("text is required");
        if (targetChars < 32) throw new IllegalArgumentException("targetChars must be >= 32");
        if (overlapChars < 0 || overlapChars >= targetChars) throw new IllegalArgumentException("overlapChars must be >= 0 and < targetChars");

        String normalized = text.replace("\r\n", "\n").replace('\r', '\n').trim();
        String[] paragraphs = normalized.split("\\n\\s*\\n");
        List<String> raw = new ArrayList<>();
        StringBuilder current = new StringBuilder();

        for (String original : paragraphs) {
            String paragraph = original.trim();
            if (paragraph.isBlank()) continue;

            if (paragraph.length() > targetChars) {
                flush(current, raw);
                splitLongParagraph(paragraph, targetChars, overlapChars, raw);
                continue;
            }

            int separator = current.isEmpty() ? 0 : 2;
            if (!current.isEmpty() && current.length() + separator + paragraph.length() > targetChars) {
                flush(current, raw);
            }
            if (!current.isEmpty()) current.append("\n\n");
            current.append(paragraph);
        }
        flush(current, raw);

        if (raw.isEmpty()) throw new IllegalArgumentException("text produced no chunks");
        List<ChunkDraft> result = new ArrayList<>(raw.size());
        for (int i = 0; i < raw.size(); i++) {
            result.add(new ChunkDraft(documentId + ":" + String.format("%06d", i), i, raw.get(i)));
        }
        return List.copyOf(result);
    }

    public static List<ChunkDraft> chunk(String documentId, String text) {
        return chunk(documentId, text, 1200, 120);
    }

    private static void splitLongParagraph(String paragraph, int targetChars, int overlapChars, List<String> raw) {
        int start = 0;
        while (start < paragraph.length()) {
            int end = Math.min(paragraph.length(), start + targetChars);
            String piece = paragraph.substring(start, end).trim();
            if (!piece.isBlank()) raw.add(piece);
            if (end >= paragraph.length()) break;
            start = Math.max(start + 1, end - overlapChars);
        }
    }

    private static void flush(StringBuilder current, List<String> raw) {
        if (current.isEmpty()) return;
        String value = current.toString().trim();
        if (!value.isBlank()) raw.add(value);
        current.setLength(0);
    }
}
