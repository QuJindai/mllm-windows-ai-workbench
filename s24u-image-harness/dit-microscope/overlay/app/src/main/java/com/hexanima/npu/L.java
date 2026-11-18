package com.hexanima.npu;

import android.content.Context;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.HashMap;
import java.util.Locale;

/** Languages: Russian and English are written at the call sites, L.s(ru, en); every other language is a table assets/lang/<code>.tsv (English string -> translation, "\n" escaped)
 *  and falls back to the English text when a string is missing. The choice is stored in the "anima" prefs (default: the system language). */
final class L {
    static final String[] CODES = {"ru", "en", "zh", "ja", "ko", "es", "pt", "de", "fr", "id", "tr", "vi", "hi"};
    static final String[] NAMES = {"Русский", "English", "中文（简体）", "日本語", "한국어", "Español", "Português", "Deutsch", "Français", "Bahasa Indonesia", "Türkçe", "Tiếng Việt", "हिन्दी"};
    static String lang = "ru";
    static final HashMap<String, String> T = new HashMap<>();

    static void init(Context c) {
        String l = c.getSharedPreferences("anima", 0).getString("lang", null);
        if (l == null) { l = Locale.getDefault().getLanguage(); if (l.equals("in")) l = "id"; }
        lang = index(l) >= 0 ? l : "en";
        load(c);
    }

    static void set(Context c, String l) { c.getSharedPreferences("anima", 0).edit().putString("lang", l).apply(); lang = l; load(c); }

    static int index() { return index(lang); }
    static int index(String l) { for (int i = 0; i < CODES.length; i++) if (CODES[i].equals(l)) return i; return -1; }

    static void load(Context c) {
        T.clear();
        if (lang.equals("ru") || lang.equals("en")) return;
        try (BufferedReader r = new BufferedReader(new InputStreamReader(c.getAssets().open("lang/" + lang + ".tsv"), "UTF-8"))) {
            for (String line; (line = r.readLine()) != null; ) {
                int t = line.indexOf('\t');
                if (t > 0) T.put(line.substring(0, t).replace("\\n", "\n"), line.substring(t + 1).replace("\\n", "\n"));
            }
        } catch (Exception ignored) { }   // no table: English
    }

    static String s(String r, String e) { return lang.equals("ru") ? r : lang.equals("en") ? e : T.getOrDefault(e, e); }

    /** s() with String.format arguments */
    static String f(String r, String e, Object... a) { return String.format(s(r, e), a); }
}
