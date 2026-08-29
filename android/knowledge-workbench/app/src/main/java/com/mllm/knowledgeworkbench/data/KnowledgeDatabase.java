package com.mllm.knowledgeworkbench.data;

import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteException;
import android.database.sqlite.SQLiteOpenHelper;

final class KnowledgeDatabase extends SQLiteOpenHelper {
    private static final int VERSION = 1;

    KnowledgeDatabase(Context context, String name) {
        super(context.getApplicationContext(), name, null, VERSION);
    }

    @Override
    public void onConfigure(SQLiteDatabase db) {
        super.onConfigure(db);
        db.setForeignKeyConstraintsEnabled(true);
    }

    @Override
    public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE IF NOT EXISTS documents (" +
            "document_id TEXT PRIMARY KEY NOT NULL," +
            "source_uri TEXT NOT NULL," +
            "title TEXT NOT NULL," +
            "content_sha256 TEXT NOT NULL," +
            "updated_at_ms INTEGER NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS chunks (" +
            "chunk_id TEXT PRIMARY KEY NOT NULL," +
            "document_id TEXT NOT NULL," +
            "ordinal INTEGER NOT NULL," +
            "content TEXT NOT NULL," +
            "content_sha256 TEXT NOT NULL," +
            "FOREIGN KEY(document_id) REFERENCES documents(document_id) ON DELETE CASCADE)");
        db.execSQL("CREATE INDEX IF NOT EXISTS ix_chunks_document_ordinal ON chunks(document_id, ordinal)");
        db.execSQL("CREATE TABLE IF NOT EXISTS embeddings (" +
            "chunk_id TEXT NOT NULL," +
            "provider_id TEXT NOT NULL," +
            "model_id TEXT NOT NULL," +
            "dimension INTEGER NOT NULL," +
            "vector BLOB NOT NULL," +
            "content_sha256 TEXT NOT NULL," +
            "updated_at_ms INTEGER NOT NULL," +
            "PRIMARY KEY(chunk_id, provider_id, model_id)," +
            "FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id) ON DELETE CASCADE)");
        db.execSQL("CREATE INDEX IF NOT EXISTS ix_embeddings_provider_model ON embeddings(provider_id, model_id, dimension)");

        try {
            db.execSQL("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_id UNINDEXED, content, tokenize='trigram')");
        } catch (SQLiteException ignored) {
            // Some vendor SQLite builds omit FTS5 or the trigram tokenizer. The repository
            // deliberately falls back to deterministic LIKE retrieval rather than failing startup.
        }
    }

    @Override
    public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        throw new IllegalStateException("Knowledge database migration is not defined for " + oldVersion + " -> " + newVersion);
    }

    boolean isFts5Ready(SQLiteDatabase db) {
        try (Cursor cursor = db.rawQuery(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='chunks_fts'", null)) {
            if (!cursor.moveToFirst()) return false;
            String sql = cursor.getString(0);
            return sql != null && sql.toLowerCase(java.util.Locale.ROOT).contains("fts5");
        }
    }
}
