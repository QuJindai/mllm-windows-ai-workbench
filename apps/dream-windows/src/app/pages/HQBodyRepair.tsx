import { useEffect, useState } from "react";
import type { HQJob } from "../../domain/hq-tryon";
import { hqApi } from "../../providers/hq-tryon-api";
import { ResultPreview } from "../components/identity/IdentityResults";

const labels = { queued: "等候本机资源", running: "正在检查与局部修整", applied: "已生成修整版", partial: "部分区域通过检查", unchanged: "未检出可可靠修整的区域，已保留原图", rejected: "修整未通过检查，已保留原图", failed: "修整未完成" };
type View = "result" | "original" | "mask";

export function HQBodyRepair({ job, original, refresh }: { job: HQJob; original: string; refresh: () => void }) {
  const repair = job.bodyRepair, state = repair?.state;
  const ready = state === "applied" || state === "partial";
  const busy = state === "running" || state === "queued";
  const [view, setView] = useState<View>("result");
  const [image, setImage] = useState<{ url: string; key: string } | null>(null);
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [retry, setRetry] = useState(0);
  const digest = view === "mask" ? repair?.maskSha256 : repair?.sha256;
  const key = [job.id, view, digest].join("|");
  useEffect(() => {
    setImage(null); setError("");
    if (!ready || view === "original") return;
    const controller = new AbortController(); let object = "";
    hqApi.repairResult(job.id, view, digest, controller.signal).then(blob => {
      if (!controller.signal.aborted) { object = URL.createObjectURL(blob); setImage({ url: object, key }); }
    }).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "修整版读取失败"); });
    return () => { controller.abort(); if (object) URL.revokeObjectURL(object); };
  }, [key, job.id, digest, ready, view, retry]);
  const shown = view === "original" ? original : image?.key === key ? image.url : "";
  async function start() {
    setSending(true); setError("");
    try { await hqApi.repair(job.id); refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "未能提交修整"); }
    finally { setSending(false); }
  }
  return <section className="hq-body-repair" aria-label="自动识别修图">
    <div className="card-head"><h3>自动识别修图</h3>{(!state || state === "failed" || (job.bodyRepairCurrent === false && !busy)) && <button type="button" className="secondary-button" disabled={sending} onClick={start}>{sending ? "正在提交…" : state === "failed" ? "重试局部修整" : state ? "使用新版重新检查" : "检查并修整此图"}</button>}</div>
    <p role="status">{state ? labels[state] : "可检查这张成片的膝部圆斑和衣料硬壳，原图会保留。"}{busy && "；可切换页面，稍后回来查看。"}</p>
    {state === "failed" && <p className="hq-error">{repair?.message} {repair?.errorCode}</p>}
    {ready && <>
      <p>{["knee","bodice"].map(part => { const n = repair?.regions?.filter(r => r.part === part).length || 0; return n ? (part === "knee" ? "膝部" : "上身衣料") + " " + n + " 处" : ""; }).filter(Boolean).join(" · ")}</p>
      <div className="hq-result-actions">{([["result","修整版"],["original","原始成片"],["mask","实际改动范围"]] as const).map(([k,l])=><button type="button" className="secondary-button" key={k} aria-pressed={view===k} onClick={()=>setView(k)}>{l}</button>)}</div>
      {shown ? <><ResultPreview key={shown} imageUrl={shown} label={view==="mask" ? "白色为实际改动像素" : view==="original" ? "修整前的原始成片" : "自动修整成片"} />
        {view==="result" && <a className="primary-button" href={shown} download={job.id+"-repaired.png"}>下载修整版</a>}</> : !error && <p role="status">正在读取图片…</p>}
    </>}
    {error && <p role="alert" className="hq-error">{error} {ready && <button className="secondary-button" onClick={()=>setRetry(n=>n+1)}>重新读取</button>}</p>}
  </section>;
}
