package com.mllm.knowledgeworkbench.data;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;

import com.mllm.knowledgeworkbench.core.Compat;
import com.mllm.knowledgeworkbench.core.LocalHashEmbeddingProvider;
import com.mllm.knowledgeworkbench.core.ReciprocalRankFusion;
import com.mllm.knowledgeworkbench.core.TextChunker;
import com.mllm.knowledgeworkbench.data.KnowledgeContracts.IndexProgress;
import com.mllm.knowledgeworkbench.data.KnowledgeContracts.ProgressListener;
import com.mllm.knowledgeworkbench.data.KnowledgeContracts.SearchHit;
import com.mllm.knowledgeworkbench.data.KnowledgeContracts.SearchMode;
import com.mllm.knowledgeworkbench.data.KnowledgeContracts.Snapshot;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public final class KnowledgeRepository implements AutoCloseable {
    private final KnowledgeDatabase helper;
    private final LocalHashEmbeddingProvider embeddingProvider = new LocalHashEmbeddingProvider();
    private final String databasePath;
    private boolean closed;

    public KnowledgeRepository(Context context, String databaseName) {
        if (context == null) throw new IllegalArgumentException("context is required");
        if (Compat.isBlank(databaseName)) throw new IllegalArgumentException("databaseName is required");
        Context app = context.getApplicationContext();
        this.databasePath = app.getDatabasePath(databaseName).getAbsolutePath();
        this.helper = new KnowledgeDatabase(app, databaseName);
        this.helper.getWritableDatabase();
    }

    public synchronized Snapshot snapshot() {
        SQLiteDatabase db = db();
        int total = scalarInt(db, "SELECT COUNT(*) FROM chunks", null);
        int indexed = scalarInt(db,
            "SELECT COUNT(*) FROM embeddings e " +
                "JOIN chunks c ON c.chunk_id=e.chunk_id " +
                "WHERE e.provider_id=? AND e.model_id=? AND e.dimension=? AND e.content_sha256=c.content_sha256",
            new String[] {
                embeddingProvider.providerId(),
                embeddingProvider.modelId(),
                Integer.toString(embeddingProvider.dimension())
            });
        boolean fts5 = helper.isFts5Ready(db);
        return new Snapshot(
            true,
            fts5,
            fts5 ? "FTS5 trigram" : "LIKE fallback",
            embeddingProvider.providerId(),
            embeddingProvider.modelId(),
            total,
            indexed,
            databasePath);
    }

    public synchronized void importText(String sourceUri, String title, String text) {
        requireOpen();
        if (Compat.isBlank(sourceUri)) throw new IllegalArgumentException("sourceUri is required");
        if (Compat.isBlank(title)) throw new IllegalArgumentException("title is required");
        if (Compat.isBlank(text)) throw new IllegalArgumentException("text is required");

        String documentId = "doc-" + sha256(sourceUri).substring(0, 32);
        List<TextChunker.ChunkDraft> chunks = TextChunker.chunk(documentId, text);
        SQLiteDatabase db = helper.getWritableDatabase();
        boolean fts5 = helper.isFts5Ready(db);

        db.beginTransaction();
        try {
            if (fts5) {
                db.execSQL(
                    "DELETE FROM chunks_fts WHERE chunk_id IN (SELECT chunk_id FROM chunks WHERE document_id=?)",
                    new Object[] { documentId });
            }
            db.delete("chunks", "document_id=?", new String[] { documentId });

            ContentValues document = new ContentValues();
            document.put("document_id", documentId);
            document.put("source_uri", sourceUri);
            document.put("title", title);
            document.put("content_sha256", sha256(sourceUri + "\n" + title + "\n" + text));
            document.put("updated_at_ms", System.currentTimeMillis());
            long docRow = db.insertWithOnConflict("documents", null, document, SQLiteDatabase.CONFLICT_REPLACE);
            if (docRow == -1L) throw new IllegalStateException("Failed to persist knowledge document");

            for (TextChunker.ChunkDraft draft : chunks) {
                String contentHash = sha256(draft.content());
                ContentValues chunk = new ContentValues();
                chunk.put("chunk_id", draft.chunkId());
                chunk.put("document_id", documentId);
                chunk.put("ordinal", draft.ordinal());
                chunk.put("content", draft.content());
                chunk.put("content_sha256", contentHash);
                long chunkRow = db.insertOrThrow("chunks", null, chunk);
                if (chunkRow == -1L) throw new IllegalStateException("Failed to persist knowledge chunk");

                if (fts5) {
                    ContentValues fts = new ContentValues();
                    fts.put("chunk_id", draft.chunkId());
                    fts.put("content", draft.content());
                    db.insertOrThrow("chunks_fts", null, fts);
                }
            }
            db.setTransactionSuccessful();
        } finally {
            db.endTransaction();
        }
    }

    public synchronized Snapshot buildMissingEmbeddings(ProgressListener listener) {
        SQLiteDatabase db = db();
        List<PendingEmbedding> pending = new ArrayList<>();
        String sql = "SELECT c.chunk_id,c.content,c.content_sha256 " +
            "FROM chunks c LEFT JOIN embeddings e " +
            "ON e.chunk_id=c.chunk_id AND e.provider_id=? AND e.model_id=? " +
            "WHERE e.chunk_id IS NULL OR e.dimension<>? OR e.content_sha256<>c.content_sha256 " +
            "ORDER BY c.document_id,c.ordinal,c.chunk_id";
        try (Cursor cursor = db.rawQuery(sql, new String[] {
            embeddingProvider.providerId(),
            embeddingProvider.modelId(),
            Integer.toString(embeddingProvider.dimension())
        })) {
            while (cursor.moveToNext()) {
                pending.add(new PendingEmbedding(cursor.getString(0), cursor.getString(1), cursor.getString(2)));
            }
        }

        int total = pending.size();
        for (int i = 0; i < pending.size(); i++) {
            PendingEmbedding item = pending.get(i);
            float[] vector = embeddingProvider.embed(item.content());
            if (vector.length != embeddingProvider.dimension()) {
                throw new IllegalStateException("Embedding dimension mismatch");
            }
            ContentValues values = new ContentValues();
            values.put("chunk_id", item.chunkId());
            values.put("provider_id", embeddingProvider.providerId());
            values.put("model_id", embeddingProvider.modelId());
            values.put("dimension", embeddingProvider.dimension());
            values.put("vector", encodeVector(vector));
            values.put("content_sha256", item.contentHash());
            values.put("updated_at_ms", System.currentTimeMillis());
            long row = db.insertWithOnConflict("embeddings", null, values, SQLiteDatabase.CONFLICT_REPLACE);
            if (row == -1L) throw new IllegalStateException("Failed to persist embedding vector");
            if (listener != null) listener.onProgress(new IndexProgress(i + 1, total, item.chunkId()));
        }
        return snapshot();
    }

    public synchronized List<SearchHit> search(String query, SearchMode mode, int limit) {
        requireOpen();
        if (Compat.isBlank(query)) return Collections.emptyList();
        if (mode == null) throw new IllegalArgumentException("mode is required");
        if (limit < 1 || limit > 100) throw new IllegalArgumentException("limit must be 1..100");
        String normalized = query.trim();

        return switch (mode) {
            case LEXICAL -> searchLexical(normalized, limit);
            case EMBEDDING -> searchVector(normalized, limit);
            case HYBRID -> searchHybrid(normalized, limit);
        };
    }

    private List<SearchHit> searchLexical(String query, int limit) {
        SQLiteDatabase db = db();
        if (helper.isFts5Ready(db)) {
            List<SearchHit> hits = new ArrayList<>();
            String sql = "SELECT d.document_id,c.chunk_id,d.source_uri,d.title,c.ordinal,c.content,bm25(chunks_fts) " +
                "FROM chunks_fts JOIN chunks c ON c.chunk_id=chunks_fts.chunk_id " +
                "JOIN documents d ON d.document_id=c.document_id " +
                "WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts),c.ordinal,c.chunk_id LIMIT ?";
            try (Cursor cursor = db.rawQuery(sql, new String[] { quoteFts(query), Integer.toString(limit) })) {
                while (cursor.moveToNext()) {
                    double rank = cursor.getDouble(6);
                    hits.add(readHit(cursor, 1d / (1d + Math.abs(rank))));
                }
            } catch (RuntimeException ignored) {
                return searchLike(query, limit);
            }
            return Compat.immutableCopy(hits);
        }
        return searchLike(query, limit);
    }

    private List<SearchHit> searchLike(String query, int limit) {
        SQLiteDatabase db = db();
        List<SearchHit> hits = new ArrayList<>();
        String sql = "SELECT d.document_id,c.chunk_id,d.source_uri,d.title,c.ordinal,c.content " +
            "FROM chunks c JOIN documents d ON d.document_id=c.document_id " +
            "WHERE c.content LIKE ? ORDER BY c.ordinal,c.chunk_id LIMIT ?";
        try (Cursor cursor = db.rawQuery(sql, new String[] { "%" + query + "%", Integer.toString(limit) })) {
            int rank = 0;
            while (cursor.moveToNext()) {
                hits.add(readHit(cursor, 1d / (1d + rank++)));
            }
        }
        return Compat.immutableCopy(hits);
    }

    private List<SearchHit> searchVector(String query, int limit) {
        SQLiteDatabase db = db();
        float[] queryVector = embeddingProvider.embed(query);
        List<SearchHit> hits = new ArrayList<>();
        String sql = "SELECT d.document_id,c.chunk_id,d.source_uri,d.title,c.ordinal,c.content,e.vector,e.dimension " +
            "FROM embeddings e JOIN chunks c ON c.chunk_id=e.chunk_id " +
            "JOIN documents d ON d.document_id=c.document_id " +
            "WHERE e.provider_id=? AND e.model_id=? AND e.dimension=? AND e.content_sha256=c.content_sha256";
        try (Cursor cursor = db.rawQuery(sql, new String[] {
            embeddingProvider.providerId(),
            embeddingProvider.modelId(),
            Integer.toString(embeddingProvider.dimension())
        })) {
            while (cursor.moveToNext()) {
                float[] stored = decodeVector(cursor.getBlob(6), cursor.getInt(7));
                double score = LocalHashEmbeddingProvider.cosine(queryVector, stored);
                if (score <= 0d) continue;
                hits.add(readHit(cursor, score));
            }
        }
        hits.sort(Comparator.comparingDouble(SearchHit::score).reversed()
            .thenComparingInt(SearchHit::ordinal)
            .thenComparing(SearchHit::chunkId));
        if (hits.size() > limit) return Compat.immutableCopy(hits.subList(0, limit));
        return Compat.immutableCopy(hits);
    }

    private List<SearchHit> searchHybrid(String query, int limit) {
        Snapshot current = snapshot();
        if (!current.hybridReady()) {
            throw new IllegalStateException("Hybrid search requires complete local vector coverage");
        }
        int candidateLimit = Math.min(100, Math.max(20, limit * 4));
        List<SearchHit> lexical = searchLexical(query, candidateLimit);
        List<SearchHit> vector = searchVector(query, candidateLimit);

        List<String> lexicalIds = new ArrayList<>(lexical.size());
        for (SearchHit hit : lexical) lexicalIds.add(hit.chunkId());
        List<String> vectorIds = new ArrayList<>(vector.size());
        for (SearchHit hit : vector) vectorIds.add(hit.chunkId());
        Map<String, Double> fused = ReciprocalRankFusion.fuse(lexicalIds, vectorIds, limit);

        Map<String, SearchHit> byId = new LinkedHashMap<>();
        for (SearchHit hit : lexical) byId.putIfAbsent(hit.chunkId(), hit);
        for (SearchHit hit : vector) byId.putIfAbsent(hit.chunkId(), hit);

        List<SearchHit> result = new ArrayList<>();
        for (Map.Entry<String, Double> entry : fused.entrySet()) {
            SearchHit hit = byId.get(entry.getKey());
            if (hit != null) result.add(hit.withScore(entry.getValue()));
        }
        return Compat.immutableCopy(result);
    }

    private SearchHit readHit(Cursor cursor, double score) {
        return new SearchHit(
            cursor.getString(0),
            cursor.getString(1),
            cursor.getString(2),
            cursor.getString(3),
            cursor.getInt(4),
            cursor.getString(5),
            score);
    }

    private SQLiteDatabase db() {
        requireOpen();
        return helper.getWritableDatabase();
    }

    private void requireOpen() {
        if (closed) throw new IllegalStateException("KnowledgeRepository is closed");
    }

    @Override
    public synchronized void close() {
        if (closed) return;
        closed = true;
        helper.close();
    }

    private static int scalarInt(SQLiteDatabase db, String sql, String[] args) {
        try (Cursor cursor = db.rawQuery(sql, args)) {
            if (!cursor.moveToFirst()) return 0;
            return cursor.getInt(0);
        }
    }

    private static String quoteFts(String query) {
        return "\"" + query.replace("\"", "\"\"") + "\"";
    }

    private static byte[] encodeVector(float[] vector) {
        ByteBuffer buffer = ByteBuffer.allocate(vector.length * Float.BYTES).order(ByteOrder.LITTLE_ENDIAN);
        for (float value : vector) buffer.putFloat(value);
        return buffer.array();
    }

    private static float[] decodeVector(byte[] blob, int dimension) {
        if (blob == null || dimension < 1 || blob.length != dimension * Float.BYTES) {
            throw new IllegalStateException("Stored embedding vector has invalid dimension");
        }
        ByteBuffer buffer = ByteBuffer.wrap(blob).order(ByteOrder.LITTLE_ENDIAN);
        float[] vector = new float[dimension];
        for (int i = 0; i < dimension; i++) vector[i] = buffer.getFloat();
        return vector;
    }

    private static String sha256(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest(value.getBytes(StandardCharsets.UTF_8));
            StringBuilder builder = new StringBuilder(hash.length * 2);
            for (byte b : hash) builder.append(String.format("%02x", b & 0xff));
            return builder.toString();
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("SHA-256 is unavailable", ex);
        }
    }

    private record PendingEmbedding(String chunkId, String content, String contentHash) {}
}
