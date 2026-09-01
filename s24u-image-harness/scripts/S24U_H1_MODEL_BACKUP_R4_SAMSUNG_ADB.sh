#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
IFS=$'\n\t'

VERSION="R4-SAMSUNG-ADB"
PKG="io.github.xororz.localdream.s24uharness"
STATE_ROOT="${HOME}/.local/share/s24u-image-harness-migration"
ADB_HOME="${STATE_ROOT}/adb-client"
ADB_SOCKET="/data/data/com.termux/files/s24u_image_harness_adb_socket"
DOWNLOADS_DIR="${HOME}/storage/downloads"
LOG_DIR="${DOWNLOADS_DIR}/S24U_H1_R4_LOGS"
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
  printf 'RESULT=FAIL\nERROR=%s\nLOG_DIR=%s\n' "$1" "$LOG_DIR" >&2
  exit "${2:-20}"
}

preflight() {
  [[ "${PREFIX:-}" == "/data/data/com.termux/files/usr" || -n "${TERMUX_VERSION:-}" ]] || fail "TERMUX_REQUIRED"
  [[ -d "$DOWNLOADS_DIR" && -w "$DOWNLOADS_DIR" ]] || fail "TERMUX_STORAGE_NOT_READY"
  local c
  for c in bash awk grep sed tr head tail sha256sum tar stat df wc timeout find; do
    command -v "$c" >/dev/null 2>&1 || fail "MISSING_COMMAND_${c}"
  done
  mkdir -p "$STATE_ROOT" "$ADB_HOME/.android" "$LOG_DIR"
  chmod 700 "$STATE_ROOT" "$ADB_HOME" "$ADB_HOME/.android"
}

find_existing_adb_keypair() {
  local candidate_dir private_key public_key
  for candidate_dir in \
    "$ADB_HOME/.android" \
    "$HOME/.android" \
    "$HOME/.local/share/s24u-workbuddy/adb-client/.android" \
    "$HOME/.local/share/s24u-toolbox/adb-client/.android" \
    "$HOME/.local/share/mllm-s24u/adb-client/.android" \
    "$HOME/.local/share/m-harness/adb-client/.android"
  do
    private_key="${candidate_dir}/adbkey"
    public_key="${candidate_dir}/adbkey.pub"
    if [[ -f "$private_key" && -f "$public_key" ]]; then
      printf '%s\n' "$candidate_dir"
      return 0
    fi
  done
  while IFS= read -r private_key; do
    [[ -n "$private_key" && -f "${private_key}.pub" ]] || continue
    candidate_dir="$(dirname "$private_key")"
    [[ "$candidate_dir" == *t8u* ]] && continue
    printf '%s\n' "$candidate_dir"
    return 0
  done < <(find "$HOME/.local/share" -maxdepth 6 -type f -name adbkey -path '*/adb-client/.android/adbkey' -print 2>/dev/null || true)
  return 1
}

reuse_existing_adb_identity() {
  [[ -f "$ADB_HOME/.android/adbkey" && -f "$ADB_HOME/.android/adbkey.pub" ]] && return 0
  local src
  src="$(find_existing_adb_keypair || true)"
  [[ -n "$src" ]] || return 0
  cp -f "$src/adbkey" "$ADB_HOME/.android/adbkey"
  cp -f "$src/adbkey.pub" "$ADB_HOME/.android/adbkey.pub"
  chmod 600 "$ADB_HOME/.android/adbkey" "$ADB_HOME/.android/adbkey.pub"
  printf 'ADB_IDENTITY_REUSED_FROM=%s\n' "$src"
}

ensure_tools() {
  command -v pkg >/dev/null 2>&1 || fail "MISSING_PACKAGE_MANAGER_pkg"
  if ! command -v adb >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive pkg install -y android-tools | tee "$LOG_DIR/android-tools-install.log" || fail "ANDROID_TOOLS_INSTALL_FAILED"
    hash -r
  fi
  if ! command -v fakeroot >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive pkg install -y fakeroot | tee "$LOG_DIR/fakeroot-install.log" || fail "FAKEROOT_INSTALL_FAILED"
    hash -r
  fi
  ADB_BIN="$(command -v adb)"
  [[ -n "$ADB_BIN" ]] || fail "ADB_MISSING"
  reuse_existing_adb_identity
}

adb_samsung() {
  env \
    HOME="$ADB_HOME" \
    ANDROID_NO_USE_FWMARK_CLIENT=1 \
    ADB_SERVER_SOCKET="localfilesystem:${ADB_SOCKET}" \
    fakeroot "$ADB_BIN" "$@"
}

adb_bounded() {
  local seconds="$1"; shift
  timeout "$seconds" env \
    HOME="$ADB_HOME" \
    ANDROID_NO_USE_FWMARK_CLIENT=1 \
    ADB_SERVER_SOCKET="localfilesystem:${ADB_SOCKET}" \
    fakeroot "$ADB_BIN" "$@"
}

cleanup_adb() {
  if [[ -n "$ADB_BIN" ]]; then
    adb_samsung kill-server >>"$LOG_DIR/adb-server.log" 2>&1 || true
  fi
  rm -f "$ADB_SOCKET" 2>/dev/null || true
}
trap cleanup_adb EXIT

start_private_adb_server() {
  rm -f "$ADB_SOCKET" 2>/dev/null || true
  adb_samsung kill-server >>"$LOG_DIR/adb-server.log" 2>&1 || true
  rm -f "$ADB_SOCKET" 2>/dev/null || true
  adb_bounded 10 start-server 2>&1 | tee -a "$LOG_DIR/adb-server.log"
  adb_samsung version 2>&1 | tee "$LOG_DIR/adb-version.log"
}

open_wireless_settings() {
  local am_bin=""
  if command -v am >/dev/null 2>&1; then
    am_bin="$(command -v am)"
  elif [[ -x /system/bin/am ]]; then
    am_bin="/system/bin/am"
  else
    return 10
  fi
  "$am_bin" start -a android.settings.WIRELESS_DEBUGGING_SETTINGS >/dev/null 2>&1 && return 0
  "$am_bin" start -a android.settings.APPLICATION_DEVELOPMENT_SETTINGS >/dev/null 2>&1 && return 0
  return 10
}

open_pairing_dialog() {
  local am_bin=""
  if command -v am >/dev/null 2>&1; then
    am_bin="$(command -v am)"
  elif [[ -x /system/bin/am ]]; then
    am_bin="/system/bin/am"
  else
    return 10
  fi
  "$am_bin" start -a android.settings.WIRELESS_DEBUGGING_PAIRING_DIALOG >/dev/null 2>&1 && return 0
  open_wireless_settings
}

valid_endpoint() {
  local ep="$1" host port octet
  local -a octets=()
  [[ "$ep" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}:[0-9]{1,5}$ ]] || return 1
  host="${ep%:*}"
  port="${ep##*:}"
  ((10#$port >= 1 && 10#$port <= 65535)) || return 1
  IFS='.' read -r -a octets <<<"$host"
  for octet in "${octets[@]}"; do
    ((10#$octet >= 0 && 10#$octet <= 255)) || return 1
  done
  [[ "$host" != "127.0.0.1" ]]
}

discover_real_mdns_endpoint() {
  local service="$1" attempts="$2" attempt output endpoint
  for ((attempt=1; attempt<=attempts; attempt++)); do
    output="$(adb_bounded 5 mdns services 2>&1 || true)"
    printf '%s\n' "$output" >>"$LOG_DIR/adb-mdns.log"
    endpoint="$(awk -v wanted="$service" '
      index($0, wanted) {
        for (i = NF; i >= 1; i--) {
          if ($i ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+$/) { print $i; exit }
        }
      }' <<<"$output")"
    if [[ -n "$endpoint" ]] && valid_endpoint "$endpoint"; then
      printf '%s\n' "$endpoint"
      return 0
    fi
    sleep 1
  done
  return 10
}

connect_real_endpoint() {
  local ep="$1" output rc=0
  valid_endpoint "$ep" || return 10
  set +e
  output="$(adb_bounded 12 connect "$ep" 2>&1)"
  rc=$?
  set -e
  printf '%s\n' "$output" | tee -a "$LOG_DIR/adb-connect.log"
  if ((rc == 0)) && grep -Eq '(^| )(connected to|already connected to) ' <<<"$output"; then
    ADB_SERIAL="$ep"
    return 0
  fi
  return 10
}

verify_shell_uid() {
  [[ -n "$ADB_SERIAL" ]] || return 10
  local output uid
  output="$(adb_bounded 8 -s "$ADB_SERIAL" shell id -u 2>&1 || true)"
  printf '%s\n' "$output" >>"$LOG_DIR/adb-shell-uid.log"
  uid="$(printf '%s\n' "$output" | tr -dc '0-9' | head -c 8)"
  [[ "$uid" == "2000" ]]
}

try_saved_identity() {
  [[ -f "$ADB_HOME/.android/adbkey" ]] || return 10
  local ep=""
  ep="$(discover_real_mdns_endpoint _adb-tls-connect._tcp 3 || true)"
  if [[ -n "$ep" ]] && connect_real_endpoint "$ep" && verify_shell_uid; then
    printf 'ADB_CONNECTION=saved_identity_mdns\n'
    return 0
  fi
  ADB_SERIAL=""
  open_wireless_settings || true
  printf '\n已套用 Samsung fwmark/fakeroot 修正。若无线调试页仍打开，请输入“IP 地址和端口”完整值，例如 172.19.0.1:35653：\n> ' >&2
  IFS= read -r -t 300 ep || return 10
  valid_endpoint "$ep" || return 10
  if connect_real_endpoint "$ep" && verify_shell_uid; then
    printf 'ADB_CONNECTION=saved_identity_samsung_fixed\n'
    return 0
  fi
  ADB_SERIAL=""
  return 10
}

pair_once() {
  local pair_ep="" pair_code="" output="" rc=0 host connect_ep="" connect_port=""
  open_pairing_dialog || fail "WIRELESS_DEBUGGING_PAIRING_DIALOG_OPEN_FAILED"
  printf '\n已打开“使用配对码配对设备”。R4 只使用弹窗显示的真实 IP，不再使用 loopback。\n'
  pair_ep="$(discover_real_mdns_endpoint _adb-tls-pairing._tcp 5 || true)"
  if [[ -n "$pair_ep" ]]; then
    printf '自动发现配对地址：%s\n请输入弹窗中的 6 位配对码：\n> ' "$pair_ep" >&2
    IFS= read -r -t 300 pair_code || fail "PAIRING_INPUT_TIMEOUT"
  else
    printf '请输入弹窗中的“IP:配对端口 六位码”，例如 172.19.0.1:35767 530602：\n> ' >&2
    IFS=' ' read -r -t 300 pair_ep pair_code || fail "PAIRING_INPUT_TIMEOUT"
  fi
  valid_endpoint "$pair_ep" || fail "INVALID_PAIRING_ENDPOINT"
  [[ "$pair_code" =~ ^[0-9]{6}$ ]] || fail "INVALID_PAIRING_CODE"

  set +e
  output="$(adb_bounded 20 pair "$pair_ep" "$pair_code" 2>&1)"
  rc=$?
  set -e
  printf '%s\n' "$output" | tee "$LOG_DIR/adb-pair.log"
  pair_code=""
  if ((rc != 0)) || ! grep -Fq 'Successfully paired' <<<"$output"; then
    fail "WIRELESS_ADB_PAIRING_FAILED_WITH_LOG"
  fi

  chmod 600 "$ADB_HOME/.android/adbkey" "$ADB_HOME/.android/adbkey.pub" 2>/dev/null || true
  host="${pair_ep%:*}"

  connect_ep="$(discover_real_mdns_endpoint _adb-tls-connect._tcp 5 || true)"
  if [[ -z "$connect_ep" ]]; then
    printf '\n配对已成功。回到无线调试主页面，只输入“IP 地址和端口”冒号后的连接端口，例如 35653：\n> ' >&2
    IFS= read -r -t 300 connect_port || fail "CONNECT_PORT_INPUT_TIMEOUT"
    [[ "$connect_port" =~ ^[0-9]{1,5}$ ]] || fail "INVALID_CONNECT_PORT"
    ((10#$connect_port >= 1 && 10#$connect_port <= 65535)) || fail "INVALID_CONNECT_PORT"
    connect_ep="${host}:${connect_port}"
  fi

  connect_real_endpoint "$connect_ep" || fail "WIRELESS_ADB_CONNECT_FAILED_WITH_LOG"
  verify_shell_uid || fail "ADB_SHELL_UID_NOT_2000"
  printf 'ADB_CONNECTION=new_pairing_samsung_fixed\n'
}

check_h1_access() {
  adb_bounded 8 -s "$ADB_SERIAL" shell pm path "$PKG" 2>&1 | tee "$LOG_DIR/h1-package.log" | grep -q '^package:' || \
    fail "H1_PACKAGE_NOT_INSTALLED"
  adb_bounded 10 -s "$ADB_SERIAL" shell run-as "$PKG" sh -c \
    'test -d files/models && test -n "$(ls -A files/models 2>/dev/null)"' \
    >"$LOG_DIR/h1-run-as.log" 2>&1 || fail "H1_RUN_AS_OR_MODEL_DIRECTORY_UNAVAILABLE"
}

backup_models() {
  local model_kb free_kb needed_kb bytes sha files
  model_kb="$(adb_bounded 20 -s "$ADB_SERIAL" shell run-as "$PKG" du -sk files/models 2>/dev/null | awk 'NR==1{print $1}' | tr -d '\r')"
  free_kb="$(df -k "$DOWNLOADS_DIR" | awk 'END{print $4}')"
  [[ "$model_kb" =~ ^[0-9]+$ && "$free_kb" =~ ^[0-9]+$ ]] || fail "SIZE_DISCOVERY_FAILED"
  needed_kb=$((model_kb + model_kb / 20 + 65536))
  printf 'MODEL_KB=%s FREE_KB=%s NEEDED_KB=%s\n' "$model_kb" "$free_kb" "$needed_kb"
  ((free_kb >= needed_kb)) || fail "NOT_ENOUGH_SHARED_STORAGE"

  rm -f "$TMP"
  if ! adb_samsung -s "$ADB_SERIAL" exec-out run-as "$PKG" tar -cf - files/models >"$TMP"; then
    rm -f "$TMP"
    fail "ADB_MODEL_STREAM_FAILED"
  fi
  [[ -s "$TMP" ]] || fail "BACKUP_ARCHIVE_EMPTY"
  tar -tf "$TMP" | grep -q '^files/models/' || {
    rm -f "$TMP"
    fail "BACKUP_TAR_STRUCTURE_INVALID"
  }
  mv -f "$TMP" "$OUT"

  sha256sum "$OUT" >"$HASH"
  (cd "$DOWNLOADS_DIR" && sha256sum -c "$(basename "$HASH")") || fail "BACKUP_SHA256_VERIFY_FAILED"

  bytes="$(wc -c <"$OUT" | tr -d ' ')"
  sha="$(awk 'NR==1{print $1}' "$HASH")"
  files="$(tar -tf "$OUT" | grep -c '^files/models/.*[^/]$' || true)"
  printf 'BACKUP=%s\nBYTES=%s\nMODEL_FILES=%s\nSHA256=%s\n' "$OUT" "$bytes" "$files" "$sha"
}

main() {
  preflight
  progress 1 preflight termux_storage PASS

  ensure_tools
  progress 2 samsung_compat android_tools_fakeroot PASS

  start_private_adb_server
  progress 3 adb_server unix_socket_fwmark_bypass PASS

  progress 4 adb_identity reuse_existing_key RUN
  if try_saved_identity; then
    progress 4 adb_identity saved_key_reused PASS
  else
    progress 4 adb_identity saved_key_not_authorized PAIR_REQUIRED
    pair_once
  fi

  verify_shell_uid || fail "ADB_SHELL_UID_NOT_2000"
  progress 5 adb_shell uid_2000 PASS

  check_h1_access
  progress 6 h1_access run_as_models PASS

  progress 7 backup model_stream RUN
  backup_models
  progress 7 backup model_stream PASS

  progress 8 integrity tar_and_sha256 PASS
  progress 9 evidence logs_and_counts PASS
  progress 10 complete h1_model_backup PASS

  printf 'RESULT=PASS\nSAFE_TO_PROCEED_WITH_H1_TO_H2_MIGRATION=YES\n'
}

main "$@"
