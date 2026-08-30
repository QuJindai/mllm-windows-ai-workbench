#!/system/bin/sh
set -eu

PKG="io.github.xororz.localdream.s24uharness"
OUT="/sdcard/Download/S24U_Image_Harness_model_backup.tar"
HASH="${OUT}.sha256"

progress() {
  printf '[S24U-H2][%s] %s\n' "$1" "$2"
}

ensure_shell_uid() {
  uid="$(id -u)"
  if [ "$uid" = "2000" ] || [ "$uid" = "0" ]; then
    return 0
  fi
  if command -v rish >/dev/null 2>&1 && [ "${S24U_RISH_REEXEC:-0}" != "1" ]; then
    progress '05%' 'Termux UID detected; re-entering through Shizuku rish shell.'
    export S24U_RISH_REEXEC=1
    exec rish -c "S24U_RISH_REEXEC=1 sh '$0'"
  fi
  echo "ERROR: restore needs Android shell/root identity so run-as can write H2 data." >&2
  echo "Run it through Shizuku rish (or adb shell), then execute this script again." >&2
  exit 30
}

ensure_shell_uid
progress '10%' 'Checking verified H1 backup files.'
test -s "$OUT" || {
  echo "ERROR: backup not found: $OUT" >&2
  exit 31
}
test -s "$HASH" || {
  echo "ERROR: SHA-256 sidecar not found: $HASH" >&2
  exit 32
}
(
  cd "$(dirname "$OUT")"
  sha256sum -c "$(basename "$HASH")"
)
tar -tf "$OUT" | grep -q '^files/models/' || {
  echo "ERROR: archive does not contain files/models." >&2
  exit 33
}

progress '35%' 'Checking H2 package and debuggable run-as access.'
run-as "$PKG" sh -c 'test -d files || mkdir -p files' || {
  echo "ERROR: H2 is not installed or run-as is unavailable." >&2
  exit 34
}

progress '50%' 'Restoring model directory into H2 private storage.'
run-as "$PKG" sh -c 'rm -rf files/models && mkdir -p files && tar -xf - -C .' < "$OUT"

progress '80%' 'Verifying restored private model data.'
run-as "$PKG" sh -c 'test -d files/models && test -n "$(ls -A files/models 2>/dev/null)"' || {
  echo "ERROR: restored files/models is empty." >&2
  exit 35
}
RESTORED_KB="$(run-as "$PKG" du -sk files/models | awk 'NR==1 {print $1}')"
MODEL_FILES="$(run-as "$PKG" find files/models -type f | wc -l | tr -d ' ')"

progress '100%' 'H2 model restore PASS. Existing model can be used without downloading again.'
printf 'RESTORED_KB=%s\nMODEL_FILES=%s\nBACKUP=%s\n' "$RESTORED_KB" "$MODEL_FILES" "$OUT"
