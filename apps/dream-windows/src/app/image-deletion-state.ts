import { useSyncExternalStore } from "react";
import { DreamHttpProvider } from "../providers/DreamHttpProvider";
import { identityApi } from "../providers/identity-api";

type DeletionState = { busy: boolean; error: string; deleted: boolean };
const idle: DeletionState = { busy: false, error: "", deleted: false };
const removed: DeletionState = { ...idle, deleted: true };
const storageKey = "dream.image-deletions.backend.v1";
const validId = (id: unknown): id is string => typeof id === "string" && id.trim().length > 0;

function storedIds(raw: string): string[] | null {
  try {
    const value: unknown = JSON.parse(raw);
    if (value && typeof value === "object" && "version" in value && value.version === 1
      && "deleted" in value && Array.isArray(value.deleted) && value.deleted.every(validId)) return value.deleted;
  } catch { /* A malformed browser message is not a deletion receipt. */ }
  return null;
}

function createStore(persistent: boolean) {
  const states = new Map<string, DeletionState>();
  const listeners = new Set<() => void>();
  let deletedIds: ReadonlySet<string> = new Set();
  let lastStored: string | null | undefined;
  const emit = () => listeners.forEach(listener => listener());
  const merge = (ids: string[]) => {
    if (ids.some(id => !deletedIds.has(id))) deletedIds = new Set([...deletedIds, ...ids]);
  };
  const readDeleted = () => {
    if (persistent) {
      try {
        const raw = localStorage.getItem(storageKey);
        if (raw !== lastStored) {
          // Explicitly clearing site data starts a fresh snapshot (also isolates test environments).
          if (raw === null && lastStored != null) deletedIds = new Set();
          lastStored = raw;
          if (raw !== null) merge(storedIds(raw) ?? []);
        }
      } catch { /* Browser storage can be unavailable; retain in-memory confirmations. */ }
    }
    return deletedIds;
  };
  const persist = () => {
    if (!persistent) return;
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw !== null) merge(storedIds(raw) ?? []);
      const next = JSON.stringify({ version: 1, deleted: [...deletedIds].sort() });
      if (raw !== next) localStorage.setItem(storageKey, next);
      lastStored = next;
    } catch { /* A storage failure must not undo a server-confirmed deletion. */ }
  };
  const receive = (event: StorageEvent) => {
    if (event.storageArea !== localStorage || (event.key !== storageKey && event.key !== null)) return;
    readDeleted();
    // Merge concurrent confirmations from different tabs instead of overwriting either result.
    const incoming = event.key === storageKey && event.newValue !== null ? storedIds(event.newValue) : null;
    if (incoming) {
      merge(incoming);
      persist();
    }
    // A synchronous reader may already have merged the new snapshot before this event arrives.
    emit();
  };
  return {
    readDeleted,
    get: (id: string) => readDeleted().has(id) ? removed : states.get(id) ?? idle,
    set(id: string, state: DeletionState) {
      if (state.busy || state.error) states.set(id, state); else states.delete(id);
      emit();
    },
    confirm(id: string) {
      if (!validId(id)) return;
      states.delete(id);
      if (readDeleted().has(id)) return;
      merge([id]);
      persist();
      emit();
    },
    subscribe(listener: () => void) {
      if (persistent && listeners.size === 0) window.addEventListener("storage", receive);
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
        if (persistent && listeners.size === 0) window.removeEventListener("storage", receive);
      };
    },
  };
}
const stores = new WeakMap<object, ReturnType<typeof createStore>>();

export function imageDeletionStore(scope: object = identityApi) {
  // Only the actual same-origin adapter joins backend storage; mock/custom providers stay private.
  const backend = scope === identityApi || (scope instanceof DreamHttpProvider
    && scope.deleteHistory === DreamHttpProvider.prototype.deleteHistory);
  const key = backend ? identityApi : scope;
  let store = stores.get(key);
  if (!store) { store = createStore(backend); stores.set(key, store); }
  return store;
}

export function useImageDeletion(scope: object, id: string) {
  const current = imageDeletionStore(scope);
  const state = useSyncExternalStore(current.subscribe, () => current.get(id), () => idle);
  return {
    ...state,
    async remove(onDelete: (id: string) => Promise<void>) {
      if (!validId(id) || current.get(id).busy || current.get(id).deleted) return false;
      current.set(id, { ...idle, busy: true });
      try {
        // Adapters must reject failed, missing or mismatched deletion receipts.
        await onDelete(id);
      } catch (reason) {
        current.set(id, { ...idle, error: reason instanceof Error ? reason.message : "删除失败，记录仍保留，请重试" });
        return false;
      }
      current.confirm(id);
      return true;
    },
  };
}
