package com.mllm.knowledgeworkbench;

import android.os.SystemClock;

import androidx.test.core.app.ActivityScenario;
import androidx.test.espresso.Espresso;
import androidx.test.ext.junit.runners.AndroidJUnit4;

import org.junit.Test;
import org.junit.runner.RunWith;

import static androidx.test.espresso.Espresso.onView;
import static androidx.test.espresso.action.ViewActions.click;
import static androidx.test.espresso.action.ViewActions.replaceText;
import static androidx.test.espresso.assertion.ViewAssertions.matches;
import static androidx.test.espresso.matcher.ViewMatchers.Visibility.VISIBLE;
import static androidx.test.espresso.matcher.ViewMatchers.isDisplayed;
import static androidx.test.espresso.matcher.ViewMatchers.withEffectiveVisibility;
import static androidx.test.espresso.matcher.ViewMatchers.withId;
import static androidx.test.espresso.matcher.ViewMatchers.withText;
import static org.hamcrest.Matchers.containsString;

@RunWith(AndroidJUnit4.class)
public class MainActivityInstrumentedTest {
    @Test
    public void diagnostic_screen_exposes_real_status_index_search_and_evidence_controls() {
        try (ActivityScenario<MainActivity> ignored = ActivityScenario.launch(MainActivity.class)) {
            assertVisibleContract(R.id.status_lexical);
            assertVisibleContract(R.id.status_embedding);
            assertVisibleContract(R.id.status_hybrid);
            assertVisibleContract(R.id.text_database);
            assertVisibleContract(R.id.text_index_coverage);
            assertVisibleContract(R.id.button_import);
            assertVisibleContract(R.id.button_build_index);
            assertVisibleContract(R.id.progress_index);
            assertVisibleContract(R.id.text_index_progress);
            assertVisibleContract(R.id.input_query);
            assertVisibleContract(R.id.spinner_mode);
            assertVisibleContract(R.id.button_search);
            assertVisibleContract(R.id.results_container);
            assertVisibleContract(R.id.evidence_detail);
        }
    }

    @Test
    public void bundled_sample_can_build_vectors_and_return_hybrid_evidence() {
        try (ActivityScenario<MainActivity> ignored = ActivityScenario.launch(MainActivity.class)) {
            awaitText(R.id.text_index_coverage, "0/", 8_000);
            onView(withId(R.id.button_build_index)).perform(click());
            awaitText(R.id.status_hybrid, "可用", 12_000);
            awaitText(R.id.text_index_progress, "100%", 12_000);

            onView(withId(R.id.input_query)).perform(replaceText("车辆制造"));
            onView(withId(R.id.spinner_mode)).perform(click());
            Espresso.onData(org.hamcrest.Matchers.is("HYBRID")).perform(click());
            onView(withId(R.id.button_search)).perform(click());

            awaitText(R.id.evidence_detail, "车辆", 12_000);
            onView(withId(R.id.results_container)).check(matches(isDisplayed()));
        }
    }

    private static void assertVisibleContract(int viewId) {
        onView(withId(viewId)).check(matches(withEffectiveVisibility(VISIBLE)));
    }

    private static void awaitText(int viewId, String expectedSubstring, long timeoutMs) {
        long deadline = SystemClock.uptimeMillis() + timeoutMs;
        AssertionError last = null;
        while (SystemClock.uptimeMillis() < deadline) {
            try {
                onView(withId(viewId)).check(matches(withText(containsString(expectedSubstring))));
                return;
            } catch (AssertionError error) {
                last = error;
                SystemClock.sleep(100);
            }
        }
        if (last != null) throw last;
        throw new AssertionError("Timed out waiting for view " + viewId + " to contain " + expectedSubstring);
    }
}
