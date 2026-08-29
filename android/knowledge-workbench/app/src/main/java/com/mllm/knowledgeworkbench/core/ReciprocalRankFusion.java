package com.mllm.knowledgeworkbench.core;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public final class ReciprocalRankFusion {
    private static final double K = 60d;

    private ReciprocalRankFusion() {}

    public static Map<String, Double> fuse(List<String> lexical, List<String> vector, int limit) {
        if (limit < 1) throw new IllegalArgumentException("limit must be positive");
        Map<String, Double> scores = new LinkedHashMap<>();
        add(scores, lexical);
        add(scores, vector);

        List<Map.Entry<String, Double>> ranked = new ArrayList<>(scores.entrySet());
        ranked.sort(Comparator.<Map.Entry<String, Double>>comparingDouble(Map.Entry::getValue)
            .reversed()
            .thenComparing(Map.Entry::getKey));

        LinkedHashMap<String, Double> result = new LinkedHashMap<>();
        for (Map.Entry<String, Double> entry : ranked) {
            if (result.size() >= limit) break;
            result.put(entry.getKey(), entry.getValue());
        }
        return result;
    }

    private static void add(Map<String, Double> scores, List<String> ranking) {
        if (ranking == null) return;
        for (int i = 0; i < ranking.size(); i++) {
            String id = ranking.get(i);
            if (Compat.isBlank(id)) continue;
            double score = 1d / (K + i + 1d);
            Double current = scores.get(id);
            scores.put(id, current == null ? score : current + score);
        }
    }
}
