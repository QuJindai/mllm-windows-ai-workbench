package com.hexanima.npu;

import android.content.Intent;
import android.os.Bundle;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.util.List;

/** First launch: does this phone fit, what to expect, and a way to the model catalog. */
public class Welcome extends Base {
    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        getSharedPreferences("anima", 0).edit().putBoolean("welcomed", true).apply();
        LinearLayout col = screen(L.s("Добро пожаловать", "Welcome"), null);
        TextView intro = text(L.s("Генерация картинок прямо на телефоне, без интернета и без root: нейросеть считается на NPU чипа Snapdragon.", "Image generation right on your phone, offline and without root: the network runs on the Snapdragon NPU."), 15, TXT, false);
        intro.setPadding(dp(2), dp(4), dp(2), dp(14)); intro.setLineSpacing(0, 1.15f);
        col.addView(intro);

        LinearLayout c1 = card(col);
        c1.addView(text(L.s("Ваш телефон", "Your phone"), 16, TXT, true));
        List<String[]> rep = Compat.report(this);
        boolean chipOk = rep.get(0)[0].equals("1");
        for (String[] r : rep) {
            boolean ok = r[0].equals("1");
            TextView t = text((ok ? "✓  " : "⚠  ") + r[1], 14, ok ? TXT : WARN, false); t.setPadding(0, dp(8), 0, 0); c1.addView(t);
        }
        LinearLayout c2 = card(col);
        c2.addView(text(L.s("Что важно знать", "Good to know"), 16, TXT, true));
        String[] tips = {
            L.s("Скорость: около 7 секунд на картинку 512×768 (модель 2B) и 12 секунд (2.9B).", "Speed: about 7 seconds per 512×768 picture (2B model) and 12 seconds (2.9B)."),
            L.s("Всегда 4 шага и нет негативного промпта: так устроены turbo-модели.", "Always 4 steps and no negative prompt: that is how turbo models work."),
            L.s("Картинки хранятся только в приложении, в галерею они попадают после «Скачать».", "Pictures stay inside the app and reach the gallery only after Download."),
        };
        for (String t : tips) { TextView v = text("•  " + t, 14, DIM, false); v.setPadding(0, dp(8), 0, 0); v.setLineSpacing(0, 1.1f); c2.addView(v); }

        Button go = button(L.s("Скачать модель", "Get a model"), ACC, ON_ACC); go.setTextSize(16);
        go.setOnClickListener(v -> { if (!Compat.chipOk()) Compat.allowChip(this); startActivity(new Intent(this, ModelsActivity.class)); finish(); });
        LinearLayout.LayoutParams gl = new LinearLayout.LayoutParams(-1, dp(52)); gl.topMargin = dp(6);
        col.addView(go, gl);
        Button later = button(L.s("Позже", "Later"), CARD, TXT);
        later.setOnClickListener(v -> finish());
        LinearLayout.LayoutParams ll = new LinearLayout.LayoutParams(-1, dp(46)); ll.topMargin = dp(8);
        col.addView(later, ll);
        if (!chipOk) { TextView n = text(L.s("«Скачать модель» на неподдерживаемом чипе — на ваш риск: скорее всего, приложение не заработает.", "Downloading on an unsupported chip is at your own risk: the app will most likely not work."), 12, DIM, false); n.setPadding(dp(2), dp(10), dp(2), 0); col.addView(n); }
    }
}
