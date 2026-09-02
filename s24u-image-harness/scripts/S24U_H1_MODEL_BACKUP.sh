#!/system/bin/sh
set -eu

PKG="io.github.xororz.localdream.s24uharness"
OUT="/sdcard/Download/S24U_Image_Harness_model_backup.tar"
HASH="${OUT}.sha256"
TMP="${OUT}.part"

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
  echo "ERROR: this backup needs Android shell/root identity so run-as can read H1 data." >&2
  echo "Run it through Shizuku rish (or adb shell), then execute this script again." >&2
  exit 20
}

ensure_shell_uid
progress '10%' 'Checking H1 package and debuggable run-as access.'
run-as "$PKG" sh -c 'test -d files/models && test -n "$(ls -A files/models 2>/dev/null)"' || {
  echo "ERROR: H1 model directory is not accessible or is empty: files/models" >&2
  exit 21
}

progress '25%' 'Measuring model data and shared-storage free space.'
MODEL_KB="$(run-as "$PKG" du -sk files/models | awk 'NR==1 {print $1}')"
FREE_KB="$(df -k /sdcard/Download | awk 'END {print $4}')"
case "$MODEL_KB:$FREE_KB" in
  *[!0-9:]*|:*)
    echo "ERROR: could not determine model/free-space size." >&2
    exit 22
    ;;
esac
NEEDED_KB=$((MODEL_KB + MODEL_KB / 20 + 65536))
if [ "$FREE_KB" -lt "$NEEDED_KB" ]; then
  echo "ERROR: not enough shared-storage space for safe backup." >&2
  echo "MODEL_KB=$MODEL_KB FREE_KB=$FREE_KB NEEDED_KB=$NEEDED_KB" >&2
  exit 23
fi
printf 'MODEL_KB=%s FREE_KB=%s NEEDED_KB=%s\n' "$MODEL_KB" "$FREE_KB" "$NEEDED_KB"

progress '40%' 'Streaming H1 files/models to shared storage; no model network download is involved.'
rm -f "$TMP"
run-as "$PKG" sh -c 'tar -cf - files/models' > "$TMP"
test -s "$TMP" || {
  echo "ERROR: backup archive is empty." >&2
  rm -f "$TMP"
  exit 24
}
mv -f "$TMP" "$OUT"

progress '75%' 'Writing SHA-256 sidecar and verifying it immediately.'
sha256sum "$OUT" > "$HASH"
(
  cd "$(dirname "$OUT")"
  sha256sum -c "$(basename "$HASH")"
)

progress '90%' 'Verifying archive contains model files.'
tar -tf "$OUT" | grep -q '^files/models/' || {
  echo "ERROR: archive does not contain files/models." >&2
  exit 25
}

BYTES="$(wc -c < "$OUT" | tr -d ' ')"
SHA="$(awk 'NR==1 {print $1}' "$HASH")"
progress '100%' 'H1 model backup PASS. Do NOT uninstall H1 until this PASS is shown.'
printf 'BACKUP=%s\nBYTES=%s\nSHA256=%s\n' "$OUT" "$BYTES" "$SHA"
