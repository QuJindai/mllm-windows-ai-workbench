#!/system/bin/sh
set -eu

PKG="io.github.xororz.localdream.s24uharness"
SHARED_DIR="/sdcard/Download"
OUT="$SHARED_DIR/S24U_Image_Harness_model_backup.tar"
HASH="${OUT}.sha256"
TMP="${OUT}.part"
RISH_HOME="${HOME:-/data/data/com.termux/files/home}/.s24u-rish"
RISH_WRAPPER="$RISH_HOME/rish"
RISH_DEX="$RISH_HOME/rish_shizuku.dex"
REEXEC_COPY="$SHARED_DIR/.S24U_H1_MODEL_BACKUP_R2_EXEC.sh"

progress() {
  printf '[S24U-H2][%s] %s\n' "$1" "$2"
}

find_download_dex() {
  for p in \
    "${HOME:-}/rish_shizuku.dex" \
    "${HOME:-}/.rish/rish_shizuku.dex" \
    "$SHARED_DIR/rish_shizuku.dex" \
    "/storage/emulated/0/Download/rish_shizuku.dex"
  do
    [ -n "$p" ] && [ -f "$p" ] && { printf '%s\n' "$p"; return 0; }
  done

  if [ -d "$SHARED_DIR" ]; then
    p="$(find "$SHARED_DIR" -maxdepth 4 -type f -name rish_shizuku.dex -print 2>/dev/null | head -n 1 || true)"
    [ -n "$p" ] && { printf '%s\n' "$p"; return 0; }
  fi
  return 1
}

bootstrap_private_rish() {
  if command -v rish >/dev/null 2>&1; then
    command -v rish
    return 0
  fi

  for p in \
    "${PREFIX:-}/bin/rish" \
    "${HOME:-}/bin/rish" \
    "${HOME:-}/rish" \
    "$RISH_WRAPPER"
  do
    [ -n "$p" ] && [ -x "$p" ] && { printf '%s\n' "$p"; return 0; }
  done

  dex_src="$(find_download_dex || true)"
  if [ -z "$dex_src" ]; then
    return 1
  fi

  progress '04%' "Found Shizuku rish_shizuku.dex; installing a private Termux rish wrapper."
  mkdir -p "$RISH_HOME"
  cp -f "$dex_src" "$RISH_DEX"
  chmod 400 "$RISH_DEX"
  if [ -w "$RISH_DEX" ]; then
    echo "ERROR: Android 14+ requires rish_shizuku.dex to be non-writable; private copy is still writable." >&2
    return 2
  fi

  cat > "$RISH_WRAPPER" <<RISH_EOF
#!/system/bin/sh
export RISH_APPLICATION_ID="com.termux"
/system/bin/app_process -Djava.class.path="$RISH_DEX" /system/bin --nice-name=rish rikka.shizuku.shell.ShizukuShellLoader "\$@"
RISH_EOF
  chmod 700 "$RISH_WRAPPER"
  printf '%s\n' "$RISH_WRAPPER"
}

ensure_shell_uid() {
  uid="$(id -u)"
  if [ "$uid" = "2000" ] || [ "$uid" = "0" ]; then
    progress '06%' "Android shell identity acquired (uid=$uid)."
    return 0
  fi

  [ "${S24U_RISH_REEXEC:-0}" = "1" ] && {
    echo "ERROR: rish returned but Android shell/root identity was not acquired (uid=$uid)." >&2
    exit 20
  }

  rish_bin="$(bootstrap_private_rish || true)"
  if [ -z "$rish_bin" ]; then
    cat >&2 <<'MSG'
[S24U-H2][05%] RISH_NOT_READY
No usable rish/rish_shizuku.dex was found in Termux or Download.

ONE-TIME PHONE ACTION:
1. Open Shizuku and make sure the Shizuku service is running.
2. Open "Use Shizuku in terminal apps" / "在终端应用程序中使用 Shizuku".
3. Export the rish files to the phone Download folder (rish_shizuku.dex is the key file).
4. Return to Termux and run THIS SAME R2 script again.

Do NOT uninstall H1 and do NOT clear Local Dream data.
MSG
    exit 20
  fi

  progress '05%' "Testing Shizuku rish shell: $rish_bin"
  probe="$($rish_bin -c 'id -u' 2>&1 || true)"
  probe_uid="$(printf '%s\n' "$probe" | tail -n 1 | tr -d '\r[:space:]')"
  case "$probe_uid" in
    2000|0) ;;
    *)
      printf '%s\n' "$probe" >&2
      cat >&2 <<'MSG'
ERROR: rish exists, but Shizuku shell is not ready/authorized.
Open Shizuku, start the service and allow terminal/rish access, then rerun this same script.
Do NOT uninstall H1.
MSG
      exit 20
      ;;
  esac

  progress '07%' "Shizuku rish PASS (uid=$probe_uid); re-entering backup through Android shell."
  cp -f "$0" "$REEXEC_COPY"
  chmod 644 "$REEXEC_COPY" 2>/dev/null || true
  exec "$rish_bin" -c "S24U_RISH_REEXEC=1 sh '$REEXEC_COPY'"
}

ensure_shell_uid
progress '10%' 'Checking H1 package and debuggable run-as access.'
run-as "$PKG" sh -c 'test -d files/models && test -n "$(ls -A files/models 2>/dev/null)"' || {
  echo "ERROR: H1 model directory is not accessible or is empty: files/models" >&2
  exit 21
}

progress '25%' 'Measuring model data and shared-storage free space.'
MODEL_KB="$(run-as "$PKG" du -sk files/models | awk 'NR==1 {print $1}')"
FREE_KB="$(df -k "$SHARED_DIR" | awk 'END {print $4}')"
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

case "$0" in
  "$REEXEC_COPY") rm -f "$REEXEC_COPY" 2>/dev/null || true ;;
esac
