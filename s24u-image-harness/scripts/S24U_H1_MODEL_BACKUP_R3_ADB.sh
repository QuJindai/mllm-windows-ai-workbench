#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
IFS=$'\n\t'

VERSION="R3-ADB"
PKG="io.github.xororz.localdream.s24uharness"
STATE_ROOT="${HOME}/.local/share/s24u-image-harness-migration"
ADB_HOME="${STATE_ROOT}/adb-client"
DOWNLOADS_DIR="${HOME}/storage/downloads"
OUT="${DOWNLOADS_DIR}/S24U_Image_Harness_H1_models.tar"
HASH="${OUT}.sha256"
TMP="${OUT}.part"
TOTAL_STEPS=10
ADB_BIN=""
ADB_SERIAL=""

progress() {
  local step="$1" checkpoint="$2" task="$3" result="${4:-RUN}"
  local pct filled empty bar
  pct=$((step * 100 / TOTAL_STEPS))
  filled=$((step * 20 / TOTAL_STEPS))
  empty=$((20 - filled))
  bar="$(printf '%*s' "$filled" '' | tr ' ' '#')$(printf '%*s' "$empty" '' | tr ' ' '-')"
  printf '[%s] %3d%% step=%d/%d checkpoint=%s task=%s result=%s\n' \
    "$bar" "$pct" "$step" "$TOTAL_STEPS" "$checkpoint" "$task" "$result"
}

fail() {
  printf 'RESULT=FAIL\nERROR=%s\n' "$1" >&2
  exit "${2:-20}"
}

preflight() {
  [[ "${PREFIX:-}" == "/data/data/com.termux/files/usr" || -n "${TERMUX_VERSION:-}" ]] || \
    fail "TERMUX_REQUIRED"
  [[ -d "$DOWNLOADS_DIR" && -w "$DOWNLOADS_DIR" ]] || {
    printf '请先运行一次 termux-setup-storage。\n' >&2
    fail "TERMUX_STORAGE_NOT_READY"
  }
  local c
  for c in bash awk grep sed tr cut head tail sha256sum tar stat df wc timeout; do
    command -v "$c" >/dev/null 2>&1 || fail "MISSING_COMMAND_${c}"
  done
  mkdir -p "$STATE_ROOT" "$ADB_HOME/.android"
  chmod 700 "$STATE_ROOT" "$ADB_HOME" "$ADB_HOME/.android"
}

find_existing_adb_keypair() {
  local private_key public_key candidate_dir
  for candidate_dir in \
    "$HOME/.android" \
    "$HOME/.local/share/s24u-workbuddy/adb-client/.android" \
    "$HOME/.local/share/s24u-toolbox/adb-client/.android" \
    "$HOME/.local/share/mllm-s24u/adb-client/.android" \
    "$HOME/.local/share/m-harness/adb-client/.android"
  do
    private_key="$candidate_dir/adbkey"
    public_key="$candidate_dir/adbkey.pub"
    if [[ -f "$private_key" && -f "$public_key" ]]; then
      printf '%s\n' "$candidate_dir"
      return 0
    fi
  done

  while IFS= read -r private_key; do
    [[ -n "$private_key" ]] || continue
    public_key="${private_key}.pub"
    [[ -f "$public_key" ]] || continue
    candidate_dir="$(dirname "$private_key")"
    [[ "$candidate_dir" == "$ADB_HOME/.android" ]] && continue
    printf '%s\n' "$candidate_dir"
    return 0
  done < <(find "$HOME/.local/share" -maxdepth 5 -type f -name adbkey -path '*/adb-client/.android/adbkey' -print 2>/dev/null || true)
  return 1
}

reuse_existing_adb_identity() {
  [[ -f "$ADB_HOME/.android/adbkey" && -f "$ADB_HOME/.android/adbkey.pub" ]] && return 0
  local source_dir
  source_dir="$(find_existing_adb_keypair || true)"
  [[ -n "$source_dir" ]] || return 0
  cp -f "$source_dir/adbkey" "$ADB_HOME/.android/adbkey"
  cp -f "$source_dir/adbkey.pub" "$ADB_HOME/.android/adbkey.pub"
  chmod 600 "$ADB_HOME/.android/adbkey" "$ADB_HOME/.android/adbkey.pub"
  printf 'ADB_IDENTITY_REUSED_FROM=%s\n' "$source_dir"
}

ensure_adb_client() {
  if command -v adb >/dev/null 2>&1; then
    ADB_BIN="$(command -v adb)"
  else
    command -v pkg >/dev/null 2>&1 || fail "MISSING_PACKAGE_MANAGER_pkg"
    progress 2 adb installing_android_tools RUN
    DEBIAN_FRONTEND=noninteractive pkg install -y android-tools || fail "ANDROID_TOOLS_INSTALL_FAILED"
    hash -r
    command -v adb >/dev/null 2>&1 || fail "ADB_MISSING_AFTER_INSTALL"
    ADB_BIN="$(command -v adb)"
  fi
  reuse_existing_adb_identity
  HOME="$ADB_HOME" "$ADB_BIN" version >/dev/null || fail "ADB_CLIENT_UNUSABLE"
}

adb_client() {
  HOME="$ADB_HOME" "$ADB_BIN" "$@"
}

adb_bounded() {
  local seconds="$1"; shift
  HOME="$ADB_HOME" timeout "$seconds" "$ADB_BIN" "$@"
}

stop_adb_client() {
  [[ -n "$ADB_BIN" ]] || return 0
  adb_client kill-server >/dev/null 2>&1 || true
}
trap stop_adb_client EXIT

open_wireless_pairing_dialog() {
  local am_bin=""
  if command -v am >/dev/null 2>&1; then
    am_bin="$(command -v am)"
  elif [[ -x /system/bin/am ]]; then
    am_bin="/system/bin/am"
  else
    return 10
  fi
  "$am_bin" start -a android.settings.WIRELESS_DEBUGGING_PAIRING_DIALOG >/dev/null 2>&1 && return 0
  "$am_bin" start -a android.settings.WIRELESS_DEBUGGING_SETTINGS >/dev/null 2>&1 && return 0
  "$am_bin" start -a android.settings.APPLICATION_DEVELOPMENT_SETTINGS >/dev/null 2>&1 && return 0
  return 10
}

discover_mdns_endpoint() {
  local service="$1" attempts="$2" attempt output endpoint port
  for ((attempt=1; attempt<=attempts; attempt++)); do
    output="$(adb_bounded 5 mdns services 2>/dev/null || true)"
    endpoint="$(awk -v wanted="$service" '
      index($0, wanted) {
        for (i = NF; i >= 1; i--) {
          if ($i ~ /:[0-9]+$/) { print $i; exit }
        }
      }
    ' <<<"$output")"
    if [[ -n "$endpoint" ]]; then
      port="${endpoint##*:}"
      if [[ "$port" =~ ^[0-9]+$ ]] && ((10#$port >= 1 && 10#$port <= 65535)); then
        printf '%s\n' "$endpoint"
        return 0
      fi
    fi
    sleep 2
  done
  return 10
}

connect_endpoint() {
  local discovered="$1" port loopback candidate output previous=""
  port="${discovered##*:}"
  loopback="127.0.0.1:${port}"
  for candidate in "$loopback" "$discovered"; do
    [[ -n "$candidate" && "$candidate" != "$previous" ]] || continue
    previous="$candidate"
    output="$(adb_bounded 8 connect "$candidate" 2>&1 || true)"
    if grep -Eq '(^| )(connected to|already connected to) ' <<<"$output"; then
      ADB_SERIAL="$candidate"
      return 0
    fi
  done
  return 10
}

pair_endpoint() {
  local discovered="$1" code="$2" port loopback candidate output previous=""
  port="${discovered##*:}"
  loopback="127.0.0.1:${port}"
  for candidate in "$loopback" "$discovered"; do
    [[ -n "$candidate" && "$candidate" != "$previous" ]] || continue
    previous="$candidate"
    output="$(adb_bounded 10 pair "$candidate" "$code" 2>&1 || true)"
    if grep -Fq 'Successfully paired' <<<"$output"; then
      chmod 600 "$ADB_HOME/.android/adbkey" "$ADB_HOME/.android/adbkey.pub" 2>/dev/null || true
      return 0
    fi
  done
  return 10
}

verify_shell_uid() {
  [[ -n "$ADB_SERIAL" ]] || return 10
  local uid
  uid="$(adb_bounded 5 -s "$ADB_SERIAL" shell id -u 2>/dev/null | tr -dc '0-9' | head -c 8 || true)"
  [[ "$uid" == "2000" ]]
}

manual_connect_port() {
  local port extra=""
  printf '\n无线调试页显示的“IP 地址和端口”中，只输入冒号后的连接端口，例如 40077：\n> ' >&2
  IFS=' ' read -r -t 300 port extra || return 10
  [[ -z "$extra" && "$port" =~ ^[0-9]{1,5}$ ]] || return 10
  ((10#$port >= 1 && 10#$port <= 65535)) || return 10
  connect_endpoint "127.0.0.1:${port}"
}

acquire_local_adb_shell() {
  adb_bounded 10 start-server >/dev/null 2>&1 || fail "ADB_SERVER_START_FAILED"

  local endpoint pairing_endpoint pairing_code manual_endpoint extra=""
  endpoint="$(discover_mdns_endpoint _adb-tls-connect._tcp 3 || true)"
  if [[ -n "$endpoint" ]] && connect_endpoint "$endpoint" && verify_shell_uid; then
    printf 'ADB_CONNECTION=existing_mdns\n'
    return 0
  fi
  ADB_SERIAL=""

  if [[ -f "$ADB_HOME/.android/adbkey" ]]; then
    printf '检测到已保存的 S24U/Termux 无线 ADB 身份；优先复用，不重新配对。\n'
    if manual_connect_port && verify_shell_uid; then
      printf 'ADB_CONNECTION=saved_identity_manual_port\n'
      return 0
    fi
    ADB_SERIAL=""
    printf '已保存身份无法连接，转入一次无线 ADB 配对。\n' >&2
  fi

  open_wireless_pairing_dialog || fail "WIRELESS_DEBUGGING_SETTINGS_OPEN_FAILED"
  printf '\n手机已打开“无线调试/使用配对码配对设备”。脚本先自动发现配对端口。\n'
  pairing_endpoint="$(discover_mdns_endpoint _adb-tls-pairing._tcp 8 || true)"
  if [[ -n "$pairing_endpoint" ]]; then
    printf '请输入系统显示的 6 位配对码：\n> ' >&2
    IFS= read -r -t 300 pairing_code || return 10
    [[ "$pairing_code" =~ ^[0-9]{6}$ ]] || fail "INVALID_PAIRING_CODE"
  else
    printf 'mDNS 未发现配对服务。请输入“弹窗IP:配对端口 六位码”，例如 172.19.0.1:41435 653903：\n> ' >&2
    IFS=' ' read -r -t 300 manual_endpoint pairing_code extra || return 10
    [[ -z "$extra" && "$manual_endpoint" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}:[0-9]{1,5}$ && "$pairing_code" =~ ^[0-9]{6}$ ]] || \
      fail "INVALID_MANUAL_PAIRING_INPUT"
    pairing_endpoint="$manual_endpoint"
  fi
  pair_endpoint "$pairing_endpoint" "$pairing_code" || fail "WIRELESS_ADB_PAIRING_FAILED"
  pairing_code=""

  endpoint="$(discover_mdns_endpoint _adb-tls-connect._tcp 8 || true)"
  if [[ -n "$endpoint" ]] && connect_endpoint "$endpoint" && verify_shell_uid; then
    printf 'ADB_CONNECTION=new_pairing_mdns\n'
    return 0
  fi
  ADB_SERIAL=""
  manual_connect_port || fail "WIRELESS_ADB_CONNECT_FAILED"
  verify_shell_uid || fail "ADB_SHELL_UID_NOT_2000"
  printf 'ADB_CONNECTION=new_pairing_manual_port\n'
}

check_h1_run_as() {
  adb_bounded 5 -s "$ADB_SERIAL" shell pm path "$PKG" 2>/dev/null | grep -q '^package:' || \
    fail "H1_PACKAGE_NOT_INSTALLED"
  adb_bounded 8 -s "$ADB_SERIAL" shell run-as "$PKG" sh -c \
    'test -d files/models && test -n "$(ls -A files/models 2>/dev/null)"' || \
    fail "H1_RUN_AS_OR_MODEL_DIRECTORY_UNAVAILABLE"
}

main() {
  preflight
  progress 1 preflight termux_storage_environment PASS

  ensure_adb_client
  progress 2 adb_client android_tools_and_saved_identity PASS

  progress 3 local_adb acquire_shell_uid_2000 RUN
  acquire_local_adb_shell
  verify_shell_uid || fail "ADB_SHELL_UID_NOT_2000"
  progress 3 local_adb shell_uid_2000 PASS

  check_h1_run_as
  progress 4 h1_access package_debuggable_models PASS

  progress 5 capacity measure_model_and_free_space RUN
  local model_kb free_kb needed_kb
  model_kb="$(adb_bounded 15 -s "$ADB_SERIAL" shell run-as "$PKG" du -sk files/models 2>/dev/null | awk 'NR==1{print $1}' | tr -d '\r')"
  free_kb="$(df -k "$DOWNLOADS_DIR" | awk 'END{print $4}')"
  [[ "$model_kb" =~ ^[0-9]+$ && "$free_kb" =~ ^[0-9]+$ ]] || fail "SIZE_DISCOVERY_FAILED"
  needed_kb=$((model_kb + model_kb / 20 + 65536))
  printf 'MODEL_KB=%s FREE_KB=%s NEEDED_KB=%s\n' "$model_kb" "$free_kb" "$needed_kb"
  ((free_kb >= needed_kb)) || fail "NOT_ENOUGH_SHARED_STORAGE"
  progress 5 capacity space_check PASS

  progress 6 backup adb_exec_out_tar_stream RUN
  rm -f "$TMP"
  if ! HOME="$ADB_HOME" "$ADB_BIN" -s "$ADB_SERIAL" exec-out \
      run-as "$PKG" tar -cf - files/models >"$TMP"; then
    rm -f "$TMP"
    fail "ADB_MODEL_STREAM_FAILED"
  fi
  [[ -s "$TMP" ]] || fail "BACKUP_ARCHIVE_EMPTY"
  progress 6 backup adb_exec_out_tar_stream PASS

  progress 7 archive tar_structure_validation RUN
  tar -tf "$TMP" | grep -q '^files/models/' || {
    rm -f "$TMP"
    fail "BACKUP_TAR_STRUCTURE_INVALID"
  }
  mv -f "$TMP" "$OUT"
  progress 7 archive tar_structure_validation PASS

  progress 8 integrity sha256_write_verify RUN
  sha256sum "$OUT" >"$HASH"
  (cd "$DOWNLOADS_DIR" && sha256sum -c "$(basename "$HASH")") || fail "BACKUP_SHA256_VERIFY_FAILED"
  progress 8 integrity sha256_write_verify PASS

  progress 9 evidence final_counts RUN
  local bytes sha files
  bytes="$(wc -c <"$OUT" | tr -d ' ')"
  sha="$(awk 'NR==1{print $1}' "$HASH")"
  files="$(tar -tf "$OUT" | grep -c '^files/models/.*[^/]$' || true)"
  printf 'BACKUP=%s\nBYTES=%s\nMODEL_FILES=%s\nSHA256=%s\n' "$OUT" "$bytes" "$files" "$sha"
  progress 9 evidence final_counts PASS

  progress 10 complete h1_model_backup PASS
  printf 'RESULT=PASS\nSAFE_TO_PROCEED_WITH_H1_TO_H2_MIGRATION=YES\n'
}

main "$@"
