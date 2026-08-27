from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path

import build_universal_seed as base

ROOT = Path(__file__).resolve().parents[1]
BOOT_MARKER = "__MLLM_SEED_BOOTSTRAP__"
PAYLOAD_MARKER = "__MLLM_SEED_PAYLOAD__"


def git_safe_patch_seed(path: Path) -> dict[str, str | int]:
    text = path.read_text(encoding="ascii")
    text = text.replace("$a=$c.IndexOf($m);$b=$c.IndexOf($p);", "$a=$c.LastIndexOf($m);$b=$c.LastIndexOf($p);")
    boot_pos = text.rfind(BOOT_MARKER + "\n")
    if boot_pos < 0:
        boot_pos = text.rfind(BOOT_MARKER + "\r\n")
    payload_pos = text.rfind(PAYLOAD_MARKER)
    if boot_pos < 0 or payload_pos <= boot_pos:
        raise SystemExit("seed marker layout invalid")
    start = boot_pos + len(BOOT_MARKER)
    boot_blob = "".join(text[start:payload_pos].split())
    bootstrap = base64.b64decode(boot_blob).decode("utf-8")
    old = "$pos=$content.IndexOf($marker,[StringComparison]::Ordinal)"
    new = "$pos=$content.LastIndexOf($marker,[StringComparison]::Ordinal)"
    if old not in bootstrap:
        raise SystemExit("bootstrap payload marker lookup was not found")
    bootstrap = bootstrap.replace(old, new)
    patched_b64 = base64.b64encode(bootstrap.encode("utf-8")).decode("ascii")
    patched_lines = "\r\n".join(patched_b64[i:i+76] for i in range(0, len(patched_b64), 76))
    prefix = text[:start].rstrip("\r\n")
    suffix = text[payload_pos:]
    final = (prefix + "\r\n" + patched_lines + "\r\n" + suffix.lstrip("\r\n")).replace("\n", "\r\n").replace("\r\r\n", "\r\n")
    data = final.encode("ascii")
    path.write_bytes(data)
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="dist/M_LLM_UNIVERSAL_INSTALLER_FULL.cmd")
    ap.add_argument("--version", default="")
    args = ap.parse_args()
    sha = os.environ.get("GITHUB_SHA", "")
    version = args.version or ("phase1-" + (sha[:12] if sha else "local"))
    output = Path(args.output)
    if not output.is_absolute():
        output = (ROOT / output).resolve()
    report = base.build_seed(output, version)
    report.update(git_safe_patch_seed(output))
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
