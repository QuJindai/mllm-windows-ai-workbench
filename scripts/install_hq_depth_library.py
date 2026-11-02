"""Install the pinned R2 depth release for Dream's local worker."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import zipfile

PACK = Path(__file__).resolve().parents[1] / "config/dream/hq-paired-depth-v1"


def checksum(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data):
    if path.is_file() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".install-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_manifest(data, release):
    if checksum(data) != release["manifestSHA256"]:
        raise ValueError("Incorrect depth manifest checksum")
    manifest = json.loads(data)
    rows = manifest["items"]
    if (manifest["depthRelease"] != release["depthRelease"] or manifest["release"] != release["whiteRelease"]
            or len({row["id"] for row in rows}) != release["count"] or len(rows) != release["count"]):
        raise ValueError("Incorrect depth release or pose inventory")
    objects = {}
    for row in rows:
        digest = row["depthSha256"]
        if not re.fullmatch("[a-f0-9]{64}", digest) or row["r2Object"] != f"hq-tryon-assets/dream-depth/v1/objects/{digest}.webp":
            raise ValueError("Unexpected R2 object")
        objects[f"objects/{digest}.webp"] = row
    if len(objects) != release["uniqueObjects"]:
        raise ValueError("Incorrect depth object inventory")
    return objects


def read_remote(reader, key, target):
    subprocess.run([*reader, "r2", "object", "get", key, "--remote", "--file", str(target),
                    "--config", str(PACK / "reader.jsonc")], check=True, timeout=240,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   env={**os.environ, "CI":"1", "WRANGLER_SEND_METRICS":"false", "WRANGLER_LOG":"error"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("E:/Dream"))
    parser.add_argument("--bundle", type=Path, help="Previously downloaded R2 bundle; verified against the pinned SHA-256")
    parser.add_argument("--index-only", action="store_true", help="Fetch individual depth maps on first use")
    parser.add_argument("--activate", action="store_true", help="Enable the installed library in the trusted Dream config")
    parser.add_argument("--reader-node", default=shutil.which("node"))
    parser.add_argument("--reader-cli", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    lock = json.loads((PACK / "full-release.json").read_text(encoding="utf-8"))
    install = root / "models/hq/depth-library" / lock["depthRelease"]
    install.mkdir(parents=True, exist_ok=True)
    cli = args.reader_cli or root / "tools/hq-depth-r2/node_modules/wrangler/wrangler-dist/cli.js"
    reader = [str(Path(args.reader_node).resolve()), str(cli.resolve())] if args.reader_node and cli.is_file() else None
    if not reader and (not args.bundle or args.index_only and args.activate):
        raise ValueError("Install Wrangler under E:/Dream/tools/hq-depth-r2 or supply --reader-node and --reader-cli")
    with tempfile.TemporaryDirectory(dir=install, prefix=".install-") as temp:
        bundle = args.bundle
        if not bundle and args.index_only:
            local = Path(temp) / "manifest.json"
            read_remote(reader, lock["manifestObject"], local)
            manifest = local.read_bytes()
            validate_manifest(manifest, lock)
        else:
            if not bundle:
                bundle = Path(temp) / "bundle.zip"
                read_remote(reader, lock["bundleObject"], bundle)
            if bundle.stat().st_size != lock["bundleBytes"] or checksum(bundle.read_bytes()) != lock["bundleSHA256"]:
                raise ValueError("Incorrect R2 bundle checksum")
            with zipfile.ZipFile(bundle) as archive:
                manifest = archive.read("manifest.json")
                objects = validate_manifest(manifest, lock)
                names = archive.namelist()
                if len(names) != len(objects) + 1 or set(names) != {"manifest.json", *objects}:
                    raise ValueError("Unexpected or missing archive entries")
                if not args.index_only:
                    for member, row in objects.items():
                        data = archive.read(member)
                        if len(data) != row["bytes"] or checksum(data) != row["depthSha256"]:
                            raise ValueError("Incorrect depth payload: " + member)
                        atomic_write(install / member, data)
        atomic_write(install / "manifest.json", manifest)
    if args.activate:
        settings = json.loads((root / "data/hq/config.json").read_text(encoding="utf-8-sig"))
        config_file = Path(settings["pipelineConfig"])
        previous = config_file.read_bytes()
        config = json.loads(previous.decode("utf-8-sig"))
        if config.get("poseEstimator") != "paired-depth-r2-v1":
            raise ValueError("Enable the HQ paired-depth preset before activation")
        updated = {**config, "pairedDepthLibrary": str(install)}
        if reader:
            updated.update(depthReaderNode=reader[0], depthReaderCli=reader[1])
        if updated != config:
            backup = config_file.with_name(config_file.name + f".pre-full-depth-{time.time_ns()}.bak")
            atomic_write(backup, previous)
            atomic_write(config_file, (json.dumps(updated, ensure_ascii=False, indent=2) + "\n").encode())
            print("Previous config:", backup)
    print(json.dumps({"depthRelease":lock["depthRelease"], "poses":lock["count"], "root":str(install),
                      "preloaded":0 if args.index_only else lock["uniqueObjects"], "activated":args.activate}))


if __name__ == "__main__":
    main()
