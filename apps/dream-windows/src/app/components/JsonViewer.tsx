import { useEffect, useMemo, useState } from "react";

export function JsonViewer({ value, filename, highlight = true }: { value: unknown; filename: string; highlight?: boolean }) {
  const json = useMemo(() => JSON.stringify(value, null, 2), [value]);
  const [url, setUrl] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    if (typeof URL.createObjectURL !== "function") return;
    const next = URL.createObjectURL(new Blob([json], { type: "application/json" }));
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [json]);
  const copy = async () => {
    try { await navigator.clipboard.writeText(json); setNotice("已复制"); }
    catch { setNotice("复制不可用，请下载记录。"); }
  };
  return <div className="json-viewer"><div className="json-actions">
    <button type="button" className="secondary-button" onClick={() => void copy()}>复制 JSON</button>
    {url && <a className="secondary-button" href={url} download={filename}>下载 JSON</a>}
    <span role="status">{notice}</span>
  </div><details><summary>展开原始记录（{(new Blob([json]).size / 1024).toFixed(1)} KB）</summary>
    <pre className="trace-json">{highlight ? json.split(/("(?:[^"\\]|\\.)*"\s*:|"(?:[^"\\]|\\.)*"|\b(?:true|false|null|-?\d+(?:\.\d+)?)\b)/g).map((part, index) => <span key={index} className={/^".*:\s*$/.test(part) ? "json-key" : part.startsWith('"') ? "json-string" : /^(true|false|null|-?\d)/.test(part) ? "json-value" : undefined}>{part}</span>) : json}</pre>
  </details></div>;
}
