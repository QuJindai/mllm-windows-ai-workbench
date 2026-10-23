import { useEffect, useState } from "react";

const IMAGE_DELETED = "dream:image-deleted";
export function announceImageDeleted(id: string) {
  window.dispatchEvent(new CustomEvent(IMAGE_DELETED, { detail: id }));
}
export function onImageDeleted(listener: (id: string) => void) {
  const receive = (event: Event) => {
    const id: unknown = (event as CustomEvent).detail;
    if (typeof id === "string" && id) listener(id);
  };
  window.addEventListener(IMAGE_DELETED, receive);
  return () => window.removeEventListener(IMAGE_DELETED, receive);
}
export function useDeletedImageIds() {
  const [ids, setIds] = useState<ReadonlySet<string>>(() => new Set());
  useEffect(() => onImageDeleted(id => setIds(previous => new Set([...previous, id]))), []);
  return ids;
}
