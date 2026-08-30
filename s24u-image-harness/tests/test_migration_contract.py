#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "io.github.xororz.localdream.s24uharness"
BACKUP = "/sdcard/Download/S24U_Image_Harness_model_backup.tar"


def require(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(message)


def main() -> int:
    backup = (ROOT / "scripts/S24U_H1_MODEL_BACKUP.sh").read_text(encoding="utf-8")
    restore = (ROOT / "scripts/S24U_H2_MODEL_RESTORE.sh").read_text(encoding="utf-8")
    signing = (ROOT / "signing/README.md").read_text(encoding="utf-8")
    key = (ROOT / "signing/s24u-test-signing-key.pem").read_text(encoding="utf-8")
    cert = (ROOT / "signing/s24u-test-signing-cert.pem").read_text(encoding="utf-8")

    for text, name in ((backup, "backup"), (restore, "restore")):
        require(PACKAGE in text, f"{name}: package id missing")
        require(BACKUP in text, f"{name}: shared backup path missing")
        require("run-as" in text, f"{name}: run-as bridge missing")
        require("files/models" in text, f"{name}: internal model path missing")
        require("sha256sum" in text, f"{name}: SHA-256 verification missing")

    require("df -k" in backup, "backup: free-space preflight missing")
    require("du -sk" in backup, "backup: model-size preflight missing")
    require("tar -cf -" in backup, "backup: streaming archive missing")
    require("tar -xf -" in restore, "restore: streaming extraction missing")
    require("rm -rf files/models" in restore, "restore: deterministic replace missing")

    upper = signing.upper()
    require("TEST-ONLY" in upper or "TEST ONLY" in upper, "signing warning: TEST-ONLY missing")
    require("PUBLIC" in upper, "signing warning: PUBLIC missing")
    require("DO NOT USE" in upper, "signing warning: production prohibition missing")
    require("B6:07:48:D6:46:1E:F1:F5:E2:68:14:62:F0:8E:EB:CA:28:7B:56:B7:8B:FA:FC:80:14:99:CC:2B:A4:61:E0:05" in signing,
            "signing certificate fingerprint missing")
    require("BEGIN PRIVATE KEY" in key, "public lab private key file missing")
    require("BEGIN CERTIFICATE" in cert, "certificate file missing")

    print("MIGRATION_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
