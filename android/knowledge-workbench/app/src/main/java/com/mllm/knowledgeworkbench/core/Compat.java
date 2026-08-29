package com.mllm.knowledgeworkbench.core;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public final class Compat {
    private Compat() {}

    public static boolean isBlank(CharSequence value) {
        if (value == null || value.length() == 0) return true;
        for (int i = 0; i < value.length(); i++) {
            if (!Character.isWhitespace(value.charAt(i))) return false;
        }
        return true;
    }

    public static <T> List<T> immutableCopy(List<T> source) {
        return Collections.unmodifiableList(new ArrayList<>(source));
    }
}
