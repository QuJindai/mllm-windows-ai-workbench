import { useContext, useSyncExternalStore } from "react";
import { DreamProviderContext } from "./providers";
import { imageDeletionStore } from "./image-deletion-state";

/** Call only after the provider has confirmed deletion of this exact ID. */
export function announceImageDeleted(id: string, scope?: object) {
  imageDeletionStore(scope).confirm(id);
}

export function readDeletedImageIds(scope?: object): ReadonlySet<string> {
  return imageDeletionStore(scope).readDeleted();
}

/** Future confirmations; use readDeletedImageIds for already confirmed deletions. */
export function onImageDeleted(listener: (id: string) => void, scope?: object) {
  const store = imageDeletionStore(scope);
  let previous = store.readDeleted();
  return store.subscribe(() => {
    const next = store.readDeleted();
    const added = [...next].filter(id => !previous.has(id));
    previous = next;
    added.forEach(id => listener(id));
  });
}

export function useDeletedImageIds(scope?: object) {
  const provider = useContext(DreamProviderContext);
  const store = imageDeletionStore(scope ?? provider ?? undefined);
  return useSyncExternalStore(store.subscribe, store.readDeleted, store.readDeleted);
}
