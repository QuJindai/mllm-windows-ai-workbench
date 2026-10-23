import { useSyncExternalStore } from "react";
import { announceImageDeleted } from "./image-deletion";

type DeletionState = { busy: boolean; error: string };
const idle: DeletionState = { busy: false, error: "" };
function createStore() {
  const states = new Map<string, DeletionState>();
  const listeners = new Set<() => void>();
  return {
    get: (id: string) => states.get(id) ?? idle,
    set(id: string, state: DeletionState) {
      if (state.busy || state.error) states.set(id, state); else states.delete(id);
      listeners.forEach(listener => listener());
    },
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
  };
}
const stores = new WeakMap<object, ReturnType<typeof createStore>>();

export function useImageDeletion(scope: object, id: string) {
  let store = stores.get(scope);
  if (!store) { store = createStore(); stores.set(scope, store); }
  const current = store;
  const state = useSyncExternalStore(current.subscribe, () => current.get(id), () => idle);
  return {
    ...state,
    async remove(onDelete: (id: string) => Promise<void>) {
      if (current.get(id).busy) return false;
      current.set(id, { busy: true, error: "" });
      try {
        await onDelete(id);
        announceImageDeleted(id);
        current.set(id, idle);
        return true;
      } catch (reason) {
        current.set(id, { busy: false, error: reason instanceof Error ? reason.message : "删除失败，图片仍保留，请重试" });
        return false;
      }
    },
  };
}
