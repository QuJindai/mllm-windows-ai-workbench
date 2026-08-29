package com.mllm.knowledgeworkbench;

import android.app.Activity;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.provider.OpenableColumns;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.Spinner;
import android.widget.TextView;

import com.mllm.knowledgeworkbench.core.Compat;
import com.mllm.knowledgeworkbench.data.KnowledgeContracts.IndexProgress;
import com.mllm.knowledgeworkbench.data.KnowledgeContracts.SearchHit;
import com.mllm.knowledgeworkbench.data.KnowledgeContracts.SearchMode;
import com.mllm.knowledgeworkbench.data.KnowledgeContracts.Snapshot;
import com.mllm.knowledgeworkbench.data.KnowledgeRepository;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final int PICK_TEXT_REQUEST = 41;
    private static final String DATABASE_NAME = "knowledge-workbench.db";
    private static final String SAMPLE_SOURCE = "asset://sample_knowledge.md";

    private final ExecutorService worker = Executors.newSingleThreadExecutor();

    private KnowledgeRepository repository;
    private Snapshot latestSnapshot;
    private volatile boolean destroyed;

    private TextView statusLexical;
    private TextView statusEmbedding;
    private TextView statusHybrid;
    private TextView textDatabase;
    private TextView textIndexCoverage;
    private TextView textImportSource;
    private TextView textIndexProgress;
    private TextView evidenceDetail;
    private TextView textError;
    private ProgressBar progressIndex;
    private Button buttonImport;
    private Button buttonBuildIndex;
    private Button buttonSearch;
    private EditText inputQuery;
    private Spinner spinnerMode;
    private LinearLayout resultsContainer;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        bindViews();
        configureSearchModes();
        configureActions();

        repository = new KnowledgeRepository(this, DATABASE_NAME);
        setBusyState(true, "初始化本地知识库…");
        worker.execute(this::initializeKnowledgeBase);
    }

    private void bindViews() {
        statusLexical = findViewById(R.id.status_lexical);
        statusEmbedding = findViewById(R.id.status_embedding);
        statusHybrid = findViewById(R.id.status_hybrid);
        textDatabase = findViewById(R.id.text_database);
        textIndexCoverage = findViewById(R.id.text_index_coverage);
        textImportSource = findViewById(R.id.text_import_source);
        textIndexProgress = findViewById(R.id.text_index_progress);
        evidenceDetail = findViewById(R.id.evidence_detail);
        textError = findViewById(R.id.text_error);
        progressIndex = findViewById(R.id.progress_index);
        buttonImport = findViewById(R.id.button_import);
        buttonBuildIndex = findViewById(R.id.button_build_index);
        buttonSearch = findViewById(R.id.button_search);
        inputQuery = findViewById(R.id.input_query);
        spinnerMode = findViewById(R.id.spinner_mode);
        resultsContainer = findViewById(R.id.results_container);
    }

    private void configureSearchModes() {
        String[] values = new String[] { "LEXICAL", "EMBEDDING", "HYBRID" };
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, values);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spinnerMode.setAdapter(adapter);
    }

    private void configureActions() {
        buttonImport.setOnClickListener(v -> openKnowledgePicker());
        buttonBuildIndex.setOnClickListener(v -> buildVectorIndex());
        buttonSearch.setOnClickListener(v -> search());
    }

    private void initializeKnowledgeBase() {
        try {
            Snapshot snapshot = repository.snapshot();
            if (snapshot.totalChunks() == 0) {
                String sample = readStream(getAssets().open("sample_knowledge.md"));
                repository.importText(SAMPLE_SOURCE, "验收样例 · 整车软件制造", sample);
                snapshot = repository.snapshot();
            }
            Snapshot finalSnapshot = snapshot;
            ui(() -> {
                latestSnapshot = finalSnapshot;
                textImportSource.setText("来源: " + SAMPLE_SOURCE);
                renderSnapshot(finalSnapshot);
                setBusyState(false, "本地知识库就绪");
            });
        } catch (Exception ex) {
            showFailure("知识库初始化失败", ex);
        }
    }

    private void openKnowledgePicker() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("text/*");
        intent.putExtra(Intent.EXTRA_MIME_TYPES, new String[] {
            "text/plain", "text/markdown", "text/x-markdown"
        });
        startActivityForResult(intent, PICK_TEXT_REQUEST);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != PICK_TEXT_REQUEST || resultCode != RESULT_OK || data == null || data.getData() == null) {
            return;
        }

        Uri uri = data.getData();
        try {
            int takeFlags = data.getFlags() & (Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
            if ((takeFlags & Intent.FLAG_GRANT_READ_URI_PERMISSION) != 0) {
                getContentResolver().takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
            }
        } catch (RuntimeException ignored) {
        }

        String displayName = resolveDisplayName(uri);
        if (!isSupportedTextName(displayName)) {
            textError.setText("不支持的文件类型: " + displayName + "。当前仅支持 .md / .markdown / .txt。");
            return;
        }

        setBusyState(true, "正在导入 " + displayName + "…");
        worker.execute(() -> {
            try (InputStream input = getContentResolver().openInputStream(uri)) {
                if (input == null) throw new IOException("无法打开所选文件");
                String text = readStream(input);
                if (Compat.isBlank(text)) throw new IOException("所选文件为空");
                repository.importText(uri.toString(), displayName, text);
                Snapshot snapshot = repository.snapshot();
                ui(() -> {
                    latestSnapshot = snapshot;
                    textImportSource.setText("来源: " + displayName + "\n" + uri);
                    progressIndex.setProgress(coveragePercent(snapshot));
                    textIndexProgress.setText(progressTextForSnapshot(snapshot));
                    renderSnapshot(snapshot);
                    setBusyState(false, "导入完成；如向量覆盖不足，请构建 / 补齐索引");
                });
            } catch (Exception ex) {
                showFailure("知识文件导入失败", ex);
            }
        });
    }

    private void buildVectorIndex() {
        Snapshot snapshot = latestSnapshot;
        if (snapshot == null || snapshot.totalChunks() == 0) {
            textError.setText("当前没有可索引的知识切片。");
            return;
        }
        if (snapshot.indexedChunks() == snapshot.totalChunks()) {
            progressIndex.setProgress(100);
            textIndexProgress.setText(snapshot.indexedChunks() + "/" + snapshot.totalChunks() + " · 100% · 已完成");
            return;
        }

        setBusyState(true, "正在构建本地向量索引…");
        progressIndex.setProgress(0);
        worker.execute(() -> {
            try {
                Snapshot completed = repository.buildMissingEmbeddings(progress -> ui(() -> renderProgress(progress)));
                ui(() -> {
                    latestSnapshot = completed;
                    progressIndex.setProgress(coveragePercent(completed));
                    textIndexProgress.setText(completed.indexedChunks() + "/" + completed.totalChunks() + " · 100% · 完成");
                    renderSnapshot(completed);
                    setBusyState(false, "向量索引构建完成");
                });
            } catch (Exception ex) {
                showFailure("向量索引构建失败", ex);
            }
        });
    }

    private void search() {
        String query = inputQuery.getText().toString().trim();
        if (Compat.isBlank(query)) {
            textError.setText("请输入检索内容。");
            return;
        }

        String selected = String.valueOf(spinnerMode.getSelectedItem());
        SearchMode mode = SearchMode.valueOf(selected);
        Snapshot snapshot = latestSnapshot;
        if (mode == SearchMode.HYBRID && (snapshot == null || !snapshot.hybridReady())) {
            textError.setText("Hybrid 尚未可用：请先完成全部本地向量索引。");
            return;
        }
        if (mode == SearchMode.EMBEDDING && (snapshot == null || snapshot.indexedChunks() == 0)) {
            textError.setText("Embedding 尚无可检索向量：请先构建本地向量索引。");
            return;
        }

        setBusyState(true, "正在执行 " + mode + " 检索…");
        worker.execute(() -> {
            try {
                List<SearchHit> hits = repository.search(query, mode, 20);
                ui(() -> {
                    renderResults(hits, mode);
                    setBusyState(false, hits.isEmpty() ? "检索完成：0 条证据" : "检索完成：" + hits.size() + " 条证据");
                });
            } catch (Exception ex) {
                showFailure("检索失败", ex);
            }
        });
    }

    private void renderSnapshot(Snapshot snapshot) {
        statusLexical.setText(snapshot.fts5Ready() ? "FTS5 · 可用" : "LIKE fallback · 可用");
        statusEmbedding.setText(snapshot.providerId() + "\n" + snapshot.modelId() + " · 本机");
        if (snapshot.hybridReady()) {
            statusHybrid.setText("可用 · " + snapshot.indexedChunks() + "/" + snapshot.totalChunks());
        } else if (snapshot.totalChunks() == 0) {
            statusHybrid.setText("等待知识");
        } else {
            statusHybrid.setText("待补索引 · " + snapshot.indexedChunks() + "/" + snapshot.totalChunks());
        }
        textDatabase.setText("SQLite: " + snapshot.databasePath() + "\nLexical: " + snapshot.lexicalMode());
        textIndexCoverage.setText("向量覆盖: " + snapshot.indexedChunks() + "/" + snapshot.totalChunks() + " chunks");
        buttonBuildIndex.setEnabled(snapshot.totalChunks() > snapshot.indexedChunks());
        buttonSearch.setEnabled(snapshot.totalChunks() > 0);
        buttonImport.setEnabled(true);
    }

    private void renderProgress(IndexProgress progress) {
        progressIndex.setProgress(progress.percent());
        textIndexProgress.setText(progress.completed() + "/" + progress.total() + " · " + progress.percent() + "% · " + progress.currentChunkId());
    }

    private void renderResults(List<SearchHit> hits, SearchMode mode) {
        resultsContainer.removeAllViews();
        if (hits.isEmpty()) {
            TextView empty = new TextView(this);
            empty.setText("未找到证据 · mode=" + mode);
            empty.setTextColor(0xFF87A5B7);
            empty.setPadding(8, 12, 8, 12);
            resultsContainer.addView(empty);
            evidenceDetail.setText("本次检索未返回证据。");
            return;
        }

        for (int i = 0; i < hits.size(); i++) {
            SearchHit hit = hits.get(i);
            TextView card = new TextView(this);
            card.setText(String.format(Locale.ROOT,
                "#%d  %s  · score %.4f\n%s\n%s",
                i + 1, hit.title(), hit.score(), hit.sourceUri(), truncate(hit.excerpt(), 180)));
            card.setTextColor(0xFFD7F9FF);
            card.setTextSize(12f);
            card.setPadding(12, 14, 12, 14);
            card.setBackgroundResource(R.drawable.card_background);
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
            params.topMargin = i == 0 ? 0 : 8;
            card.setLayoutParams(params);
            card.setOnClickListener(v -> showEvidence(hit, mode));
            resultsContainer.addView(card);
        }
        showEvidence(hits.get(0), mode);
    }

    private void showEvidence(SearchHit hit, SearchMode mode) {
        evidenceDetail.setText(
            "mode: " + mode +
            "\nscore: " + String.format(Locale.ROOT, "%.6f", hit.score()) +
            "\ndocument: " + hit.documentId() +
            "\nchunk: " + hit.chunkId() + " · ordinal " + hit.ordinal() +
            "\nsource: " + hit.sourceUri() +
            "\n\n" + hit.excerpt());
    }

    private void setBusyState(boolean busy, String message) {
        textError.setText(message);
        if (busy) {
            buttonBuildIndex.setEnabled(false);
            buttonSearch.setEnabled(false);
            buttonImport.setEnabled(false);
        } else if (latestSnapshot != null) {
            renderSnapshot(latestSnapshot);
        }
    }

    private void showFailure(String prefix, Exception ex) {
        ui(() -> {
            textError.setText(prefix + ": " + safeMessage(ex));
            if (latestSnapshot != null) renderSnapshot(latestSnapshot);
            else buttonImport.setEnabled(true);
        });
    }

    private void ui(Runnable runnable) {
        if (destroyed) return;
        runOnUiThread(() -> {
            if (!destroyed) runnable.run();
        });
    }

    private String resolveDisplayName(Uri uri) {
        String name = null;
        try (Cursor cursor = getContentResolver().query(uri, new String[] { OpenableColumns.DISPLAY_NAME }, null, null, null)) {
            if (cursor != null && cursor.moveToFirst()) name = cursor.getString(0);
        } catch (RuntimeException ignored) {
        }
        if (Compat.isBlank(name)) {
            String segment = uri.getLastPathSegment();
            name = Compat.isBlank(segment) ? "knowledge.txt" : segment;
        }
        return name;
    }

    private static boolean isSupportedTextName(String name) {
        String lower = name.toLowerCase(Locale.ROOT);
        return lower.endsWith(".md") || lower.endsWith(".markdown") || lower.endsWith(".txt");
    }

    private static String readStream(InputStream input) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int read;
        while ((read = input.read(buffer)) != -1) output.write(buffer, 0, read);
        return output.toString(StandardCharsets.UTF_8.name());
    }

    private static String truncate(String value, int max) {
        if (value == null) return "";
        if (value.length() <= max) return value;
        return value.substring(0, Math.max(0, max - 1)) + "…";
    }

    private static String safeMessage(Throwable error) {
        String value = error.getMessage();
        return Compat.isBlank(value) ? error.getClass().getSimpleName() : value;
    }

    private static int coveragePercent(Snapshot snapshot) {
        if (snapshot.totalChunks() <= 0) return 0;
        return (int) Math.round(snapshot.indexedChunks() * 100.0d / snapshot.totalChunks());
    }

    private static String progressTextForSnapshot(Snapshot snapshot) {
        int percent = coveragePercent(snapshot);
        return snapshot.indexedChunks() + "/" + snapshot.totalChunks() + " · " + percent + "% · " +
            (percent == 100 ? "完成" : "待补索引");
    }

    @Override
    protected void onDestroy() {
        destroyed = true;
        worker.shutdownNow();
        if (repository != null) repository.close();
        super.onDestroy();
    }
}
