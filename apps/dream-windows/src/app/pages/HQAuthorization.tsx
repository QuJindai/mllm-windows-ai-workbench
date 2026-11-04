import { useEffect, useRef, useState } from "react";
import type { HQStatus } from "../../domain/hq-tryon";
import { hqError } from "../../domain/hq-tryon";
import { hqApi } from "../../providers/hq-tryon-api";

export function HQAuthorization({ status, offline, onAuthorized }: { status: HQStatus | null; offline: boolean; onAuthorized: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [expires, setExpires] = useState<number | null>(null);
  const locked = useRef(false), mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  async function authorize() {
    if (locked.current || offline || !status?.authorization?.available) return;
    locked.current = true; setBusy(true); setError(""); setExpires(null);
    try {
      const result = await hqApi.renewAuthorization();
      if (mounted.current) { setExpires(result.expiresAt); onAuthorized(); }
    } catch (e) {
      if (mounted.current) setError(e instanceof Error ? e.message : "授权失败，请稍后重试");
    } finally {
      locked.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  return <div className="hq-authorization" aria-label="人物图库授权" aria-busy={busy}>
    {status && !status.authorized && <>
      <p className="hq-hint">点击后使用本机已有的 Cloudflare 登录恢复图库访问，无需粘贴密钥。授权完成后自动刷新人物列表。</p>
      <button className="primary-button" disabled={busy || offline || !status.authorization?.available} onClick={authorize}>{busy ? "正在授权…" : "一键授权"}</button>
      {!status.authorization && <p className="hq-hint">当前后端尚未提供一键授权，请更新本机服务后使用。</p>}
      {status.authorization?.available === false && <p className="hq-error">{hqError(status.authorization.error) || "本机授权组件尚未就绪"}</p>}
    </>}
    {busy && <p role="status">正在更新短期授权并核验人物图库，请稍候…</p>}
    {error && <p className="hq-error" role="alert">{error}</p>}
    {expires && !busy && !error && <p role="status" className="hq-hint">图库授权已恢复，有效期至 {new Date(expires).toLocaleString("zh-CN", { hour12: false })}。</p>}
  </div>;
}
