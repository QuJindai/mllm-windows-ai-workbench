import { useCallback, useEffect, useRef, useState } from "react";
import { identityJobSeed, identityProfileRequest, identityReferenceKind, isIdentityJobActive } from "../../../domain/identity";
import type { IdentityBatch, IdentityBatchRequest, IdentityJob, IdentityProfile, IdentityReference, IdentityRequest, IdentityStatus, ReferenceKind } from "../../../domain/identity";
import { identityApi, readBatchRetryOperation, readReferenceFile } from "../../../providers/identity-api";
import { useDeletedImageIds } from "../../image-deletion";

const PROFILE_KEY = "dream.identity.selected-profile.v1";
const BATCH_KEY = "dream.identity.last-batch.v1";
const LEGACY_JOB_KEY = "dream.identity.last-job.v1";
const LAST_VIEW_KEY = "dream.identity.last-view.v1";
const POLL_MS = 750;
type LastView = { kind: "batch" | "job" | "profile"; id: string };
export type IdentityReplay = { id: string; revision: number };
export type RestoredIdentity = { request: IdentityRequest; batch?: IdentityBatchRequest; allowDraft?: boolean; polishDraftContext?: string };
const failure = (reason: unknown) => reason instanceof Error ? reason.message : "人物服务暂时不可用，请重试";
function readId(key: string) { try { return localStorage.getItem(key) ?? ""; } catch { return ""; } }
function readLastView(): LastView | null {
  try {
    const value: unknown = JSON.parse(readId(LAST_VIEW_KEY));
    if (value && typeof value === "object" && "kind" in value && "id" in value
      && (value.kind === "batch" || value.kind === "job" || value.kind === "profile") && typeof value.id === "string" && value.id) {
      return { kind: value.kind, id: value.id };
    }
  } catch { /* Fall back to pre-upgrade IDs when the view record is absent or corrupt. */ }
  return null;
}
function upsert<T extends { id: string }>(items: T[], value: T): T[] {
  return items.some((item) => item.id === value.id) ? items.map((item) => item.id === value.id ? value : item) : [value, ...items];
}

export function useIdentityWorkspace(replay: IdentityReplay | null | undefined, onRestore: (value: RestoredIdentity) => void) {
  const deletedImages = useDeletedImageIds();
  const removedHistory = useRef(new Set<string>());
  for (const id of deletedImages) removedHistory.current.add(id);
  // A successful delete is irreversible in this view. Older requests must not
  // resurrect it; server tombstones also survive later cached job responses.
  const availableJob = useCallback((value: IdentityJob): IdentityJob => {
    if (value.resultDeleted || value.historyDeleted) removedHistory.current.add(value.id);
    return removedHistory.current.has(value.id)
      ? { ...value, historyDeleted: true } : value;
  }, []);
  const availableBatch = useCallback((value: IdentityBatch): IdentityBatch => ({ ...value, items: value.items.map(availableJob) }), [availableJob]);
  const [status, setStatus] = useState<IdentityStatus | null>(null);
  const [references, setReferences] = useState<IdentityReference[]>([]);
  const [profiles, setProfiles] = useState<IdentityProfile[]>([]);
  const [profileId, setProfileId] = useState("");
  // null is unresolved restoration, not an explicitly empty workspace.
  const [draftContext, setDraftContext] = useState<string | null>(null);
  const [jobs, setJobs] = useState<IdentityJob[]>([]);
  const [job, setJob] = useState<IdentityJob | null>(null);
  const [batches, setBatches] = useState<IdentityBatch[]>([]);
  const [batch, setBatch] = useState<IdentityBatch | null>(null);
  const [initializing, setInitializing] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [opening, setOpening] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [storageNotice, setStorageNotice] = useState<string | null>(null);
  const mounted = useRef(false), selection = useRef(0), writePending = useRef(false);
  const currentJob = useRef<IdentityJob | null>(null), currentBatch = useRef<IdentityBatch | null>(null);
  const selectedProfile = profiles.find((item) => item.id === profileId) ?? null;
  const currentProfile = useRef<IdentityProfile | null>(null);
  useEffect(() => { currentProfile.current = selectedProfile; }, [selectedProfile]);
  const active = isIdentityJobActive(job) || isIdentityJobActive(batch) || jobs.some(isIdentityJobActive) || batches.some(isIdentityJobActive);
  const locked = active || !!pending || opening || refreshing || initializing;

  const persist = useCallback((key: string, value: string) => {
    try { if (value) localStorage.setItem(key, value); else localStorage.removeItem(key); }
    catch { setStorageNotice("浏览器存储不可用，刷新后可能无法恢复草稿或任务。"); }
  }, []);
  const bindProfile = useCallback((id: string) => { setProfileId(id); persist(PROFILE_KEY, id); }, [persist]);
  const rememberView = useCallback((kind: LastView["kind"], id: string) => {
    persist(LAST_VIEW_KEY, id ? JSON.stringify({ kind, id }) : "");
  }, [persist]);
  const recordJob = useCallback((value: IdentityJob) => setJobs((current) => upsert(current, value)), []);
  const recordProfile = useCallback((value: IdentityProfile) => setProfiles((current) => upsert(current, value)), []);
  const recordBatch = useCallback((value: IdentityBatch) => {
    setBatches((current) => upsert(current, value));
    setJobs((current) => value.items.reduce((items, item) => upsert(items, item), current));
  }, []);
  const acceptJob = useCallback((value: IdentityJob) => {
    setDraftContext(`job:${value.id}`);
    currentJob.current = value; setJob(value); recordJob(value);
    currentBatch.current = null; setBatch(null); persist(BATCH_KEY, ""); persist(LEGACY_JOB_KEY, value.id);
    rememberView("job", value.id);
  }, [recordJob, persist, rememberView]);
  const acceptBatch = useCallback((value: IdentityBatch) => {
    setDraftContext(`batch:${value.id}`);
    currentBatch.current = value; setBatch(value); recordBatch(value);
    currentJob.current = null; setJob(null); persist(BATCH_KEY, value.id); persist(LEGACY_JOB_KEY, "");
    rememberView("batch", value.id);
  }, [recordBatch, persist, rememberView]);

  const openJob = useCallback(async (id: string, allowDraft = false, restoredProfileId = "") => {
    const version = ++selection.current; setOpening(true); setError(null); setPollError(null);
    try {
      // A saved person is context only: never apply its defaults over the historical job.
      // An unavailable person must not prevent opening an otherwise valid historical result.
      const [value, profile] = await Promise.all([
        identityApi.job(id),
        restoredProfileId ? identityApi.profile(restoredProfileId).catch(() => null) : currentProfile.current,
      ]);
      if (!mounted.current || version !== selection.current) return;
      acceptJob(value);
      if (profile) recordProfile(profile);
      bindProfile(profile && profile.state !== "archived" && profile.referenceId === value.request.referenceId && profile.faceIndex === value.request.faceIndex
        && (profile.referenceKind ?? "faceid") === identityReferenceKind(value.request.modelId) ? profile.id : "");
      const restoreDraft = allowDraft && !isIdentityJobActive(value);
      onRestore({ request: { ...value.request, seed: identityJobSeed(value) }, allowDraft: restoreDraft,
        ...(restoreDraft ? { polishDraftContext: `job:${value.id}` } : {}) });
    } catch (reason) { if (mounted.current && version === selection.current) setError(`无法打开人物任务：${failure(reason)}`); }
    finally { if (mounted.current && version === selection.current) setOpening(false); }
  }, [acceptJob, bindProfile, onRestore, recordProfile]);

  const openBatch = useCallback(async (id: string, allowDraft = false) => {
    const version = ++selection.current; setOpening(true); setError(null); setPollError(null);
    try {
      const value = await identityApi.batch(id);
      if (!mounted.current || version !== selection.current) return;
      acceptBatch(value); bindProfile(value.request.profileId ?? "");
      const seed = value.request.request.seed === "random" && value.items[0] ? identityJobSeed(value.items[0]) : value.request.request.seed;
      const restoreDraft = allowDraft && !isIdentityJobActive(value);
      onRestore({ request: { ...value.request.request, seed }, batch: value.request, allowDraft: restoreDraft,
        ...(restoreDraft ? { polishDraftContext: `batch:${value.id}` } : {}) });
      if (value.request.profileId) {
        const profile = await identityApi.profile(value.request.profileId);
        if (mounted.current && version === selection.current) recordProfile(profile);
      }
    } catch (reason) { if (mounted.current && version === selection.current) setError(`无法打开人物批次：${failure(reason)}`); }
    finally { if (mounted.current && version === selection.current) setOpening(false); }
  }, [acceptBatch, bindProfile, onRestore, recordProfile]);

  const selectProfile = useCallback(async (id: string, restoreDraft = false) => {
    const version = ++selection.current; bindProfile(id); setOpening(!!id); setError(null); setNotice(null);
    currentJob.current = null; setJob(null); currentBatch.current = null; setBatch(null);
    persist(BATCH_KEY, ""); persist(LEGACY_JOB_KEY, "");
    rememberView("profile", id);
    if (!id) { setDraftContext(""); return; }
    try {
      const value = await identityApi.profile(id);
      if (!mounted.current || version !== selection.current) return;
      setDraftContext(`profile:${id}`);
      recordProfile(value);
      onRestore({ request: identityProfileRequest(value), allowDraft: restoreDraft, ...(restoreDraft ? { polishDraftContext: `profile:${id}` } : {}) });
      if (value.state === "archived") setError("该人物档案已撤下。请明确选择其他档案或参考照；历史结果仍保留。");
    } catch (reason) { if (mounted.current && version === selection.current) setError(`无法打开人物档案：${failure(reason)}`); }
    finally { if (mounted.current && version === selection.current) setOpening(false); }
  }, [bindProfile, onRestore, persist, recordProfile, rememberView]);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    setRefreshing(true); setLoadError(null);
    const results = await Promise.allSettled([identityApi.status(signal), identityApi.references(signal), identityApi.jobs(signal), identityApi.profiles(signal), identityApi.batches(signal)]);
    if (!mounted.current || signal?.aborted) return;
    const [runtime, assets, history, library, runs] = results;
    setStatus(runtime.status === "fulfilled" ? runtime.value : null);
    if (assets.status === "fulfilled") setReferences(assets.value);
    if (history.status === "fulfilled") {
      const fresh = history.value.map(availableJob);
      const selected = currentJob.current;
      if (selected) {
        const updated = fresh.find(item => item.id === selected.id) ?? availableJob(selected);
        currentJob.current = updated; setJob(updated);
        setJobs(fresh.some(item => item.id === selected.id) ? fresh : upsert(fresh, updated));
      } else setJobs(fresh);
    }
    if (library.status === "fulfilled") setProfiles(library.value);
    if (runs.status === "fulfilled") {
      const fresh = runs.value.map(availableBatch);
      const selected = currentBatch.current;
      if (selected) {
        const updated = fresh.find(item => item.id === selected.id) ?? availableBatch(selected);
        currentBatch.current = updated; setBatch(updated);
        setBatches(fresh.some(item => item.id === selected.id) ? fresh : upsert(fresh, updated));
      } else setBatches(fresh);
    }
    const errors = results.flatMap((result) => result.status === "rejected" ? [failure(result.reason)] : []);
    setLoadError(errors.length ? errors.join("；") : null); setInitializing(false); setRefreshing(false);
  }, [availableJob, availableBatch]);

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; selection.current += 1; }; }, []);
  useEffect(() => { const controller = new AbortController(); void refresh(controller.signal); return () => controller.abort(); }, [refresh]);
  useEffect(() => {
    if (replay?.id) { void openJob(replay.id, false, readId(PROFILE_KEY)); return; }
    const batchId = readId(BATCH_KEY), savedProfileId = readId(PROFILE_KEY), legacyId = readId(LEGACY_JOB_KEY);
    const lastView = readLastView();
    if (lastView) {
      if (lastView.kind === "job") void openJob(lastView.id, true, savedProfileId);
      else if (lastView.kind === "batch") void openBatch(lastView.id, true);
      else void selectProfile(lastView.id, true);
      return;
    }
    // Upgrade existing stores without letting a bound profile shadow the last viewed job.
    if (batchId) void openBatch(batchId, true);
    else if (legacyId) void openJob(legacyId, true, savedProfileId);
    else if (savedProfileId) void selectProfile(savedProfileId, true);
    else setDraftContext("");
  }, [replay?.id, replay?.revision, openBatch, openJob, selectProfile]);

  const preparingIds = profiles.filter((value) => value.state === "preparing").map((value) => value.id).sort().join(",");
  useEffect(() => {
    if ((!active && !preparingIds) || opening || pending) return;
    const controller = new AbortController(), version = selection.current;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const valid = () => !controller.signal.aborted && version === selection.current;
      try {
        const [nextBatch, nextJob, history, runs, people] = await Promise.all([
          batch && isIdentityJobActive(batch) ? identityApi.batch(batch.id, controller.signal) : null,
          job && isIdentityJobActive(job) ? identityApi.job(job.id, controller.signal) : null,
          active ? identityApi.jobs(controller.signal) : null,
          active ? identityApi.batches(controller.signal) : null,
          Promise.all(preparingIds ? preparingIds.split(",").map((id) => identityApi.profile(id, controller.signal)) : []),
        ]);
        if (!valid()) return;
        if (history) setJobs(history);
        if (runs) setBatches(runs);
        if (nextBatch) acceptBatch(nextBatch);
        if (nextJob) acceptJob(nextJob);
        people.forEach(recordProfile); setPollError(null);
      } catch (reason) { if (valid()) setPollError(`任务状态暂时无法更新，将自动重试：${failure(reason)}`); }
      finally { if (valid()) timer = setTimeout(() => void poll(), POLL_MS); }
    };
    timer = setTimeout(() => void poll(), POLL_MS);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [active, preparingIds, batch?.id, batch?.state, job?.id, job?.state, opening, pending, acceptBatch, acceptJob, recordProfile]);

  async function write<T>(kind: string, operation: () => Promise<T>, accept: (value: T, selected: boolean) => void) {
    if (writePending.current) return false;
    writePending.current = true; const version = selection.current;
    setPending(kind); setError(null); setNotice(null);
    try {
      const value = await operation();
      if (mounted.current) accept(value, version === selection.current);
      return true;
    } catch (reason) { if (mounted.current && version === selection.current) setError(failure(reason)); return false; }
    finally { writePending.current = false; if (mounted.current) setPending(null); }
  }

  function clearProfile() {
    setDraftContext("");
    selection.current += 1; bindProfile(""); setOpening(false); setError(null);
    persist(LEGACY_JOB_KEY, ""); persist(BATCH_KEY, ""); rememberView("profile", "");
  }
  async function upload(file: File, onSelected: (reference: IdentityReference) => void, referenceKind: ReferenceKind = "faceid") {
    if (locked) return;
    clearProfile();
    await write("upload", async () => identityApi.uploadReference(file.name, await readReferenceFile(file), referenceKind === "visual" ? "visual" : undefined), (value, selected) => {
      setReferences((current) => upsert(current, value));
      if (selected) { onSelected(value); if (!value.faces.length) setError("没有检测到人脸，请更换参考照。"); }
    });
  }
  async function createProfile(name: string, referenceId: string, faceIndex: number, referenceKind: ReferenceKind = "faceid") {
    if (locked) return false;
    if (referenceKind === "faceid" && references.find(value => value.id === referenceId)?.referenceKind === "visual") return false;
    return write("profile", () => identityApi.createProfile({ name: name.trim(), referenceId, faceIndex, ...(referenceKind === "visual" ? { referenceKind } : {}) }), (value, selected) => {
      recordProfile(value);
      if (selected) {
        setDraftContext(`profile:${value.id}`);
        bindProfile(value.id); onRestore({ request: identityProfileRequest(value) });
        persist(BATCH_KEY, ""); persist(LEGACY_JOB_KEY, ""); rememberView("profile", value.id);
      }
    });
  }
  async function renameProfile(name: string) {
    if (locked || !selectedProfile) return false;
    return write("rename", () => identityApi.renameProfile(selectedProfile.id, name.trim()), (value) => recordProfile(value));
  }
  async function archiveProfile() {
    if (locked || !selectedProfile) return false;
    return write("archive", () => identityApi.archiveProfile(selectedProfile.id), (value, selected) => {
      setProfiles((current) => current.filter((item) => item.id !== value.id));
      if (selected) {
        bindProfile("");
        if (readLastView()?.kind === "profile") rememberView("profile", "");
        setNotice("人物档案已撤下；参考照和历史结果仍保留。");
      }
    });
  }
  async function submit(body: IdentityBatchRequest) {
    if (locked || profileId && (selectedProfile?.state !== "ready" || selectedProfile.referenceId !== body.request.referenceId || selectedProfile.faceIndex !== body.request.faceIndex)) return;
    if (selectedProfile && (selectedProfile.referenceKind ?? "faceid") !== identityReferenceKind(body.request.modelId)) return;
    if (identityReferenceKind(body.request.modelId) === "faceid" && references.find(value => value.id === body.request.referenceId)?.referenceKind === "visual") return;
    const version = selection.current;
    const submitted = await write("submit", () => identityApi.createBatch(body), (value, selected) => { if (selected) acceptBatch(value); else recordBatch(value); });
    return submitted && version === selection.current;
  }
  async function cancel() {
    if (batch && isIdentityJobActive(batch)) await write("cancel", () => identityApi.cancelBatch(batch.id), (value, selected) => { if (selected) acceptBatch(value); else recordBatch(value); });
    else if (job && isIdentityJobActive(job)) await write("cancel", () => identityApi.cancel(job.id), (value, selected) => { if (selected) acceptJob(value); else recordJob(value); });
  }
  async function retryBatch(id: string, payload: { mode: "failed" | "unfinished"; idempotencyKey: string }) {
    const operation = readBatchRetryOperation(id);
    const recovering = operation?.mode === payload.mode && operation.idempotencyKey === payload.idempotencyKey;
    // Discovery of an accepted-but-unacknowledged child must not lock out its
    // recovery. Only the already persisted operation may bypass the active lock.
    if (pending || opening || refreshing || initializing || active && !recovering) throw new Error("请等待当前操作结束后再重试");
    const succeeded = await write("retry", () => identityApi.retryBatch(id, payload), (value, selected) => {
      if (selected) {
        acceptBatch(value); bindProfile(value.request.profileId ?? "");
        onRestore({ request: value.request.request, batch: value.request });
      } else recordBatch(value);
    });
    if (!succeeded) throw new Error("重试未确认，请重试；相同请求编号不会重复生成。");
  }
  async function savePreset(value: IdentityJob) {
    // Saving defaults cannot alter the already frozen batch request or its identity binding.
    if (pending || opening || refreshing || initializing || !selectedProfile || selectedProfile.state !== "ready" || value.state !== "complete" || !value.result || selectedProfile.referenceId !== value.request.referenceId || selectedProfile.faceIndex !== value.request.faceIndex) return;
    await write("preset", () => identityApi.savePreset(selectedProfile.id, value.id), (profile, selected) => {
      recordProfile(profile); if (selected) setNotice("已保存人物预设，不改变身份特征。");
    });
  }

  // Decorate all views, including a selected item that is no longer in a list.
  for (const item of [...jobs, ...batches.flatMap(value => value.items), ...(job ? [job] : []), ...(batch?.items ?? [])]) {
    if (item.resultDeleted || item.historyDeleted) removedHistory.current.add(item.id);
  }
  const visibleJobs = jobs.map(availableJob), visibleBatches = batches.map(availableBatch);
  return { status, references, profiles, profileId, draftContext, selectedProfile,
    jobs: visibleJobs, job: job ? availableJob(job) : null, batches: visibleBatches, batch: batch ? availableBatch(batch) : null,
    initializing, refreshing, opening, pending, active, locked,
    error, loadError, pollError, notice, storageNotice, persist, refresh, openJob, openBatch, selectProfile, clearProfile, upload, createProfile, renameProfile, archiveProfile, submit, cancel, retryBatch, savePreset };
}
