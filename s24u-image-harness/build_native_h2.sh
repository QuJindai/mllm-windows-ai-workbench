#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LD="$ROOT/local-dream"
RUST_FILE="$LD/app/src/main/cpp/3rdparty/tokenizers-cpp/rust/src/lib.rs"

: "${ANDROID_NDK_ROOT:?ANDROID_NDK_ROOT is required}"
: "${QNN_SDK_ROOT:?QNN_SDK_ROOT is required}"

test -f "$RUST_FILE"

# Local Dream v2.8.1 pins tokenizers-cpp code written before recent Rust
# toolchains made dangerous_implicit_autorefs deny-by-default. Make the two
# raw-pointer method-call references explicit. This is semantics-preserving and
# keeps the public upstream dependency source otherwise unchanged.
python3 - "$RUST_FILE" <<'PY'
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text(encoding="utf-8")
repls = {
    "*out_len = (*handle).decode_str.len();":
        "*out_len = (&(*handle).decode_str).len();",
    "*out_len = (*handle).id_to_token_result.len();":
        "*out_len = (&(*handle).id_to_token_result).len();",
}
for old, new in repls.items():
    count = s.count(old)
    if count != 1:
        raise SystemExit(f"rust compatibility anchor mismatch: {old!r}, count={count}")
    s = s.replace(old, new, 1)
p.write_text(s, encoding="utf-8")
print("TOKENIZERS_RUST_COMPAT_PATCH_PASS")
PY

grep -Fq '(&(*handle).decode_str).len()' "$RUST_FILE"
grep -Fq '(&(*handle).id_to_token_result).len()' "$RUST_FILE"

rustup target list --installed | grep -qx 'aarch64-linux-android'

cd "$LD/app/src/main/cpp"
bash build.sh
