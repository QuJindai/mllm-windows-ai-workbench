package com.mllm.knowledgeworkbench.core;

import java.text.Normalizer;
import java.util.Locale;

public final class LocalHashEmbeddingProvider {
    public static final String PROVIDER_ID = "local-hash";
    public static final String MODEL_ID = "hash-chargram-128-v1";
    public static final int DIMENSION = 128;

    public String providerId() { return PROVIDER_ID; }
    public String modelId() { return MODEL_ID; }
    public int dimension() { return DIMENSION; }

    public float[] embed(String text) {
        if (text == null || text.isBlank()) throw new IllegalArgumentException("text is required");
        String normalized = Normalizer.normalize(text, Normalizer.Form.NFKC)
            .toLowerCase(Locale.ROOT)
            .replaceAll("\\s+", " ")
            .trim();
        float[] vector = new float[DIMENSION];
        addNgrams(vector, normalized, 1, 0.55f);
        addNgrams(vector, normalized, 2, 1.0f);
        addNgrams(vector, normalized, 3, 1.35f);

        double norm = 0d;
        for (float value : vector) norm += value * value;
        if (norm <= 0d) throw new IllegalStateException("embedding has zero magnitude");
        float scale = (float) (1d / Math.sqrt(norm));
        for (int i = 0; i < vector.length; i++) vector[i] *= scale;
        return vector;
    }

    public static double cosine(float[] left, float[] right) {
        if (left == null || right == null || left.length != right.length || left.length == 0) {
            throw new IllegalArgumentException("vector dimensions must match");
        }
        double dot = 0d;
        double leftNorm = 0d;
        double rightNorm = 0d;
        for (int i = 0; i < left.length; i++) {
            dot += left[i] * right[i];
            leftNorm += left[i] * left[i];
            rightNorm += right[i] * right[i];
        }
        if (leftNorm == 0d || rightNorm == 0d) return 0d;
        return dot / (Math.sqrt(leftNorm) * Math.sqrt(rightNorm));
    }

    private static void addNgrams(float[] vector, String text, int n, float weight) {
        if (text.length() < n) return;
        for (int i = 0; i <= text.length() - n; i++) {
            String gram = text.substring(i, i + n);
            int hash = stableHash(gram);
            int index = Math.floorMod(hash, DIMENSION);
            float sign = ((hash >>> 8) & 1) == 0 ? 1f : -1f;
            vector[index] += sign * weight;
        }
    }

    private static int stableHash(String value) {
        int hash = 0x811c9dc5;
        for (int i = 0; i < value.length(); i++) {
            hash ^= value.charAt(i);
            hash *= 0x01000193;
        }
        return hash;
    }
}
