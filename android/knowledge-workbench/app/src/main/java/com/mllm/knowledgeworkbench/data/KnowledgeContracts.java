package com.mllm.knowledgeworkbench.data;

public final class KnowledgeContracts {
    private KnowledgeContracts() {}

    public enum SearchMode {
        LEXICAL,
        EMBEDDING,
        HYBRID
    }

    public record SearchHit(
        String documentId,
        String chunkId,
        String sourceUri,
        String title,
        int ordinal,
        String excerpt,
        double score
    ) {
        public SearchHit withScore(double newScore) {
            return new SearchHit(documentId, chunkId, sourceUri, title, ordinal, excerpt, newScore);
        }
    }

    public record Snapshot(
        boolean lexicalReady,
        boolean fts5Ready,
        String lexicalMode,
        String providerId,
        String modelId,
        int totalChunks,
        int indexedChunks,
        String databasePath
    ) {
        public boolean hybridReady() {
            return lexicalReady && totalChunks > 0 && totalChunks == indexedChunks;
        }
    }

    public record IndexProgress(
        int completed,
        int total,
        String currentChunkId
    ) {
        public int percent() {
            if (total <= 0) return 0;
            return (int) Math.round((completed * 100.0d) / total);
        }
    }

    @FunctionalInterface
    public interface ProgressListener {
        void onProgress(IndexProgress progress);
    }
}
