import { useEffect, useState } from "react";

export type UiPreferences = {
  textSize: "standard" | "large";
  density: "comfortable" | "compact";
  reduceMotion: boolean;
  historyAutoRefresh: boolean;
  historyInterval: 15 | 30 | 60;
};
export const UI_PREFERENCES_KEY = "dream.ui.preferences.v1";
const changeEvent = "dream:ui-preferences";
export const defaultUiPreferences: UiPreferences = {
  textSize: "standard", density: "comfortable", reduceMotion: false,
  historyAutoRefresh: true, historyInterval: 30,
};

export function readUiPreferences(): UiPreferences {
  try {
    const value = JSON.parse(localStorage.getItem(UI_PREFERENCES_KEY) ?? "null");
    return {
      textSize: value?.textSize === "large" ? "large" : "standard",
      density: value?.density === "compact" ? "compact" : "comfortable",
      reduceMotion: value?.reduceMotion === true,
      historyAutoRefresh: value?.historyAutoRefresh !== false,
      historyInterval: [15, 30, 60].includes(value?.historyInterval) ? value.historyInterval : 30,
    };
  } catch { return { ...defaultUiPreferences }; }
}

export function saveUiPreferences(changes: Partial<UiPreferences>) {
  localStorage.setItem(UI_PREFERENCES_KEY, JSON.stringify({ ...readUiPreferences(), ...changes }));
  window.dispatchEvent(new Event(changeEvent));
}

export function useUiPreferences() {
  const [preferences, setPreferences] = useState(readUiPreferences);
  useEffect(() => {
    const sync = () => setPreferences(readUiPreferences());
    window.addEventListener(changeEvent, sync);
    window.addEventListener("storage", sync);
    return () => { window.removeEventListener(changeEvent, sync); window.removeEventListener("storage", sync); };
  }, []);
  return preferences;
}
