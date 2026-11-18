from argparse import ArgumentParser
from hashlib import file_digest
from pathlib import Path
import shutil
import subprocess
from zipfile import ZipFile

APK_SHA256 = "e9196897399d268091410615bb3cd704aed0b2376099f5d1e68fced39696e090"
HERE = Path(__file__).resolve().parent

parser = ArgumentParser(description="Apply the 7421 DiT microscope sources to the T8U 7416 source tree.")
parser.add_argument("source", type=Path)
parser.add_argument("hexanima_apk", type=Path)
args = parser.parse_args()
source = args.source.resolve()
with args.hexanima_apk.open("rb") as apk:
    if file_digest(apk, "sha256").hexdigest() != APK_SHA256:
        parser.error("Expected the verified HexAnima 1.7.1 APK")

patch = str(HERE / "integration.patch")
subprocess.run(["git", "apply", "--check", patch], cwd=source, check=True)
with ZipFile(args.hexanima_apk) as apk:
    for entry in apk.infolist():
        path = Path(entry.filename)
        if entry.is_dir() or path.is_absolute() or ".." in path.parts:
            continue
        if path.parts[0] == "assets":
            dest = source / "app/src/main" / path
        elif path.parts[:2] == ("lib", "arm64-v8a"):
            dest = source / "app/src/main/jniLibs" / Path(*path.parts[1:])
        else:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        with apk.open(entry) as inp, dest.open("wb") as out:
            shutil.copyfileobj(inp, out)
subprocess.run(["git", "apply", patch], cwd=source, check=True)
shutil.copytree(HERE / "overlay", source, dirs_exist_ok=True)
