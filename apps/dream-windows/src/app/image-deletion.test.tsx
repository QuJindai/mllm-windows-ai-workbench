import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DeleteImageButton } from "./components/DeleteImageButton";
import { DreamProviderContext } from "./providers";
import { announceImageDeleted, onImageDeleted, readDeletedImageIds, useDeletedImageIds } from "./image-deletion";
import { useImageDeletion } from "./image-deletion-state";
import { DreamHttpProvider } from "../providers/DreamHttpProvider";
import { MockDreamProvider } from "../providers/MockDreamProvider";
import { identityApi } from "../providers/identity-api";

beforeEach(() => localStorage.clear());
afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function deferred() {
  let resolve!: () => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<void>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function DeletedPreview({ name }: { name: string }) {
  const ids = useDeletedImageIds();
  return <output aria-label={name}>{[...ids].join(",") || "visible"}</output>;
}

describe("provider-scoped image deletion", () => {
  it("shares pending, failure, retry and confirmed deletion across buttons, including later mounts", async () => {
    const provider = new MockDreamProvider();
    const first = deferred();
    const remove = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValueOnce(undefined);
    const view = render(<DreamProviderContext.Provider value={provider}>
      <DeleteImageButton id="same" onDelete={remove} />
      <DeleteImageButton id="same" onDelete={remove} />
      <DeletedPreview name="snapshot" />
    </DreamProviderContext.Provider>);
    screen.getAllByRole("button", { name: "删除图片 same" }).forEach(button => fireEvent.click(button));
    fireEvent.click(screen.getAllByRole("button", { name: "确认删除图片" })[0]);
    screen.getAllByRole("button", { name: "正在删除…" }).forEach(button => expect(button).toBeDisabled());
    expect(remove).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("snapshot")).toHaveTextContent("visible");
    await act(async () => first.reject(new Error("删除未得到确认")));
    expect(screen.getAllByRole("alert")).toHaveLength(2);
    expect(readDeletedImageIds(provider).has("same")).toBe(false);
    fireEvent.click(screen.getAllByRole("button", { name: "确认删除图片" })[1]);
    await waitFor(() => expect(screen.getAllByText("图片已删除")).toHaveLength(2));
    expect(remove).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByLabelText("snapshot")).toHaveTextContent("same");
    view.unmount();
    render(<DreamProviderContext.Provider value={provider}>
      <DeleteImageButton id="same" onDelete={remove} /><DeletedPreview name="late" />
    </DreamProviderContext.Provider>);
    expect(screen.getByText("图片已删除")).toBeInTheDocument();
    expect(screen.getByLabelText("late")).toHaveTextContent("same");
    expect(screen.queryByRole("button", { name: "删除图片 same" })).not.toBeInTheDocument();
  });

  it("deduplicates same-tick requests and never repeats an already confirmed deletion", async () => {
    const scope = {};
    const pending = deferred();
    const remove = vi.fn(() => pending.promise);
    const { result } = renderHook(() => useImageDeletion(scope, "duplicate"));
    let first!: Promise<boolean>;
    await act(async () => {
      first = result.current.remove(remove);
      expect(await result.current.remove(remove)).toBe(false);
    });
    expect(remove).toHaveBeenCalledTimes(1);
    await act(async () => { pending.resolve(); expect(await first).toBe(true); });
    expect(result.current.deleted).toBe(true);
    await act(async () => expect(await result.current.remove(remove)).toBe(false));
    expect(remove).toHaveBeenCalledTimes(1);
  });

  it("keeps mock and custom provider snapshots isolated from each other and the real backend", async () => {
    const mock = new MockDreamProvider();
    const other = new MockDreamProvider();
    const custom = { mode: "backend" }; // A mode string alone must not authorize backend storage.
    const { result, rerender } = renderHook(({ scope }) => useDeletedImageIds(scope), { initialProps: { scope: mock as object } });
    act(() => announceImageDeleted("private", mock));
    const saved = result.current;
    expect(saved.has("private")).toBe(true);
    act(() => announceImageDeleted("custom", custom));
    expect(localStorage.length).toBe(0);
    expect(readDeletedImageIds()).not.toContain("private");
    expect(readDeletedImageIds(custom)).toEqual(new Set(["custom"]));
    rerender({ scope: other });
    expect(result.current.size).toBe(0);
    rerender({ scope: mock });
    expect(result.current).toBe(saved);
  });

  it("delivers scoped notifications once and allows synchronous reads after all subscribers unmount", () => {
    const scope = {};
    const listener = vi.fn();
    const unrelated = vi.fn();
    const stop = onImageDeleted(listener, scope);
    const stopOther = onImageDeleted(unrelated, {});
    announceImageDeleted("confirmed", scope);
    announceImageDeleted("confirmed", scope);
    expect(listener).toHaveBeenCalledExactlyOnceWith("confirmed");
    expect(unrelated).not.toHaveBeenCalled();
    stop(); stopOther();
    const snapshot = readDeletedImageIds(scope);
    announceImageDeleted("later", scope);
    expect(snapshot).toEqual(new Set(["confirmed"]));
    expect(readDeletedImageIds(scope)).toEqual(new Set(["confirmed", "later"]));
  });

  it("retains confirmation when the initiating component unmounts during the request", async () => {
    const scope = {};
    const pending = deferred();
    const view = renderHook(() => useImageDeletion(scope, "unmounted"));
    let request!: Promise<boolean>;
    act(() => { request = view.result.current.remove(() => pending.promise); });
    view.unmount();
    pending.resolve();
    expect(await request).toBe(true);
    expect(readDeletedImageIds(scope)).toContain("unmounted");
  });
});

describe("confirmed backend deletion", () => {
  it("shares real history and identity deletion state and reads the latest snapshot synchronously", async () => {
    const provider = new DreamHttpProvider();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ deleted: "real" }))));
    const view = renderHook(() => useImageDeletion(provider, "real"));
    const identity = renderHook(() => useDeletedImageIds());
    await act(async () => expect(await view.result.current.remove(id => provider.deleteHistory(id))).toBe(true));
    expect(identity.result.current).toContain("real");
    expect(readDeletedImageIds(identityApi)).toContain("real");
    expect(readDeletedImageIds(new DreamHttpProvider())).toContain("real");
  });

  for (const source of ["history", "identity"] as const) {
    it.each([
      ["missing receipt", {}], ["wrong id", { deleted: "another" }], ["null", null],
      ["boolean", { deleted: true }], ["invalid JSON", "invalid JSON"],
    ])(`does not publish ${source} deletion after a 200 response with %s`, async (_name, body) => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(typeof body === "string" ? body : JSON.stringify(body))));
      const provider = new DreamHttpProvider();
      const scope = source === "history" ? provider : identityApi;
      const listener = vi.fn();
      const stop = onImageDeleted(listener, scope);
      const view = renderHook(() => useImageDeletion(scope, "unconfirmed"));
      await act(async () => expect(await view.result.current.remove(id => source === "history" ? provider.deleteHistory(id) : identityApi.deleteResult(id))).toBe(false));
      expect(view.result.current.error).not.toBe("");
      expect(readDeletedImageIds(scope)).not.toContain("unconfirmed");
      expect(listener).not.toHaveBeenCalled();
      expect(localStorage.length).toBe(0);
      stop();
    });
  }

  it("does not publish a lost response and allows a later confirmed retry", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValueOnce(new Error("connection lost"))
      .mockResolvedValueOnce(new Response(JSON.stringify({ deleted: "retry" }))));
    const view = renderHook(() => useImageDeletion(identityApi, "retry"));
    await act(async () => expect(await view.result.current.remove(identityApi.deleteResult)).toBe(false));
    expect(readDeletedImageIds()).not.toContain("retry");
    await act(async () => expect(await view.result.current.remove(identityApi.deleteResult)).toBe(true));
    expect(readDeletedImageIds()).toContain("retry");
  });

  it("synchronizes confirmed same-origin storage snapshots without affecting mock providers or accepting malformed events", async () => {
    const backend = new DreamHttpProvider();
    const mock = new MockDreamProvider();
    const view = renderHook(() => useImageDeletion(backend, "remote"));
    const listener = vi.fn();
    const stop = onImageDeleted(listener, backend);
    act(() => announceImageDeleted("seed", backend));
    const key = localStorage.key(0)!;
    expect(key).toBeTruthy();
    const seed = JSON.parse(localStorage.getItem(key)!);
    const send = (body: unknown) => act(() => {
      const newValue = JSON.stringify(body);
      localStorage.setItem(key, newValue);
      window.dispatchEvent(new StorageEvent("storage", { key, newValue, storageArea: localStorage }));
    });
    send({ ...seed, deleted: ["seed", "remote"] });
    expect(view.result.current.deleted).toBe(true);
    expect(readDeletedImageIds()).toContain("remote");
    expect(readDeletedImageIds(mock).size).toBe(0);
    expect(listener.mock.calls.map(call => call[0])).toEqual(["seed", "remote"]);
    send({ ...seed, deleted: ["fake", 42] });
    expect(readDeletedImageIds()).not.toContain("fake");
    const remove = vi.fn();
    await act(async () => expect(await view.result.current.remove(remove)).toBe(false));
    expect(remove).not.toHaveBeenCalled();
    stop();
  });

  it("merges concurrent tab snapshots and still notifies if an async consumer reads before the storage event", () => {
    const scope = new DreamHttpProvider();
    const view = renderHook(() => useDeletedImageIds(scope));
    act(() => announceImageDeleted("z-local", scope));
    const key = localStorage.key(0)!;
    const remote = JSON.stringify({ version: 1, deleted: ["a-remote"] });
    // A concurrent tab wrote from an earlier snapshot. An async response reads it before the event.
    localStorage.setItem(key, remote);
    expect(readDeletedImageIds(scope)).toEqual(new Set(["z-local", "a-remote"]));
    act(() => window.dispatchEvent(new StorageEvent("storage", { key, newValue: remote, storageArea: localStorage })));
    expect(view.result.current).toContain("a-remote");
    expect(JSON.parse(localStorage.getItem(key)!).deleted).toEqual(["a-remote", "z-local"]);
    const write = vi.spyOn(Storage.prototype, "setItem");
    // Identical IDs arriving in another insertion order must not cause an endless storage-event echo.
    act(() => window.dispatchEvent(new StorageEvent("storage", {
      key, newValue: JSON.stringify({ version: 1, deleted: ["z-local", "a-remote"] }), storageArea: localStorage,
    })));
    expect(write).not.toHaveBeenCalled();
  });

  it("reads persisted confirmations for a late subscriber and resets them when site data is cleared", () => {
    const scope = new DreamHttpProvider();
    announceImageDeleted("from-previous-mount", scope);
    const key = localStorage.key(0)!;
    localStorage.setItem(key, JSON.stringify({ version: 1, deleted: ["from-previous-mount", "before-mount"] }));
    const view = renderHook(() => useDeletedImageIds());
    expect(view.result.current).toContain("before-mount");
    view.unmount();
    localStorage.clear();
    const fresh = renderHook(() => useDeletedImageIds());
    expect(fresh.result.current.size).toBe(0);
  });

  it("does not turn a confirmed deletion into failure if browser storage is blocked", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ deleted: "storage-blocked" }))));
    const view = renderHook(() => useImageDeletion(identityApi, "storage-blocked"));
    await act(async () => expect(await view.result.current.remove(identityApi.deleteResult)).toBe(true));
    expect(view.result.current).toMatchObject({ deleted: true, error: "", busy: false });
  });
});

it("uses record-only confirmation while sharing deletion state with another control for the same ID", async () => {
  const provider = new MockDreamProvider();
  const remove = vi.fn().mockResolvedValue(undefined);
  render(<DreamProviderContext.Provider value={provider}>
    <DeleteImageButton id="failed-task" recordOnly onDelete={remove} />
    <DeleteImageButton id="failed-task" onDelete={remove} />
  </DreamProviderContext.Provider>);
  fireEvent.click(screen.getByRole("button", { name: "删除记录 failed-task" }));
  const dialog = screen.getByRole("dialog", { name: "删除人物任务记录" });
  expect(dialog).toHaveTextContent("保留人物档案和参考照片");
  expect(dialog).not.toHaveTextContent("文件移入");
  expect(remove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "确认删除记录" }));
  await screen.findByText("记录已删除");
  expect(screen.getByText("图片已删除")).toBeInTheDocument();
  expect(remove).toHaveBeenCalledExactlyOnceWith("failed-task");
});
