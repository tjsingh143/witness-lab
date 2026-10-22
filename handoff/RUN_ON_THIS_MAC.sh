#!/bin/bash
# Portable entry point. macOS ships bash 3.2; keep this file compatible with it.
set -euo pipefail
cd "$(dirname "$0")"
PACKAGE="$PWD"
fail() { echo "Witness: $*" >&2; exit 2; }
[[ -f SHA256SUMS && -f SOURCE_MANIFEST.json ]] || fail 'Incomplete package. Extract the ZIP again.'
[[ -z "$(find . -type l -print -quit)" ]] || fail 'Package contains a symlink; refusing.'
/usr/bin/shasum -a 256 -c SHA256SUMS > /dev/null || fail 'Package integrity failed. Extract the original ZIP again.'
if [[ "${1:-}" == --verify ]]; then echo 'Package checksums verified (no host changes).'; exit 0; fi
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || fail 'Requires native Apple Silicon macOS; Rosetta/x86 is unsupported.'
MAC_MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
[[ "$MAC_MAJOR" -ge 13 ]] || fail 'Requires macOS 13 or later for Apple Virtualization.'
WORK="$HOME/Wit-f09aa63.nosync"
[[ ! -L "$WORK" ]] || fail 'Work directory is a symlink; refusing.'
find_python() {
  local candidate
  for candidate in /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if [[ -x "$candidate" ]] && "$candidate" -c 'import sys;sys.exit(not ((3,12)<=sys.version_info[:2]<(3,15)))' 2>/dev/null; then
      PY="$candidate"; return 0
    fi
  done
  # /usr/bin/python3 may launch a CLT install dialog on an unprepared machine.
  if xcode-select -p >/dev/null 2>&1 && [[ -x /usr/bin/python3 ]] && /usr/bin/python3 -c 'import sys;sys.exit(not ((3,12)<=sys.version_info[:2]<(3,15)))' 2>/dev/null; then
    PY=/usr/bin/python3; return 0
  fi
  return 1
}
if [[ "${1:-}" == --return || "${1:-}" == --report ]]; then
  find_python || fail 'Python 3.12–3.14 is needed to read the checkpoint.'
  exec "$PY" "$PACKAGE/launcher.py" "${1}" --work "$WORK"
fi
[[ $# -eq 0 ]] || fail 'Options: --verify (read only), --report, --return; no flags for normal run/resume.'
RAM="$(sysctl -n hw.memsize)"
FREE_K="$(df -Pk "$HOME" | awk 'END {print $4}')"
PRESSURE="$(sysctl -n kern.memorystatus_vm_pressure_level)"
echo "RAM: $((RAM / 1073741824)) GiB; free disk: $((FREE_K / 1048576)) GiB; pressure level: $PRESSURE"
[[ "$RAM" -ge 17179869184 ]] || fail 'BLOCKED: at least 16 GiB RAM required; this workload is not qualified on smaller hosts.'
if [[ -f "$WORK/.witness-owner.json" ]]; then
  [[ "$FREE_K" -ge 12582912 ]] || fail 'BLOCKED: resumption requires at least 12 GiB free; restore phases will recheck their full-copy reserve.'
else
  [[ "$FREE_K" -ge 41943040 ]] || fail 'BLOCKED: at least 40 GiB free required. No files or VMs were removed.'
fi
[[ "$PRESSURE" -le 2 ]] || fail 'BLOCKED: critical memory pressure. Close workloads and rerun this command.'
cat <<EOF

Witness will create/resume ONLY $WORK
and its private Lima home. It will download Lima 2.2.0 and an Ubuntu ARM64 image,
create two 1 GiB/10 GiB VMs, provision them, run real network fault experiments,
six mutants, deadline/crash recovery, five independent restorations and fresh VMs.
Allow several hours on AC power. Disk/RAM are monitored; unsafe work stops.
All VM deletion is limited to this launcher's disposable pair. Golden copies stay
stopped. No host routing/firewall changes, Docker cleanup or AI account is needed.
Homebrew and Git are detected but are optional for this source snapshot.
If supported Python is absent, a checksum-pinned, signed Python.org 3.13.9 package
will be installed system-wide. That one operation needs your Mac admin password.
macOS may require approval of downloaded software/network access. Protections stay on.
Logs contain lab traffic and may contain your username/hostname; review before sharing.
Rerun the same command after interruption. Completed experiments are retained.
EOF
[[ -r /dev/tty ]] || fail 'Run in an interactive Terminal to give informed consent.'
printf '\nType WITNESS to consent (5 minute limit): ' > /dev/tty
IFS= read -r -t 300 CONSENT < /dev/tty || fail 'Consent timed out; no installation or VM changes made.'
[[ "$CONSENT" == WITNESS ]] || fail 'Consent declined; no installation or VM changes made.'
BOOTSTRAP_LOG="$(mktemp -t witness-bootstrap-f09aa63)"
printf '%s consent=WITNESS ram_bytes=%s free_KiB=%s pressure=%s\n' "$(date -u +%FT%TZ)" "$RAM" "$FREE_K" "$PRESSURE" >> "$BOOTSTRAP_LOG"
echo "Bootstrap log: $BOOTSTRAP_LOG"
if ! find_python; then
  TMP="$(mktemp -d -t witness-python)"
  trap 'rm -f "$TMP/python.pkg" "$TMP/signature.txt"; rmdir "$TMP" 2>/dev/null || true' EXIT
  echo 'Downloading the signed Python 3.13.9 installer (bounded to 10 minutes).'
  printf '%s download https://www.python.org/ftp/python/3.13.9/python-3.13.9-macos11.pkg\n' "$(date -u +%FT%TZ)" >> "$BOOTSTRAP_LOG"
  if curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 --connect-timeout 20 --max-time 600 \
    -o "$TMP/python.pkg" https://www.python.org/ftp/python/3.13.9/python-3.13.9-macos11.pkg >> "$BOOTSTRAP_LOG" 2>&1; then
    echo 'download_exit=0' >> "$BOOTSTRAP_LOG"
  else
    echo "download_exit=$?" >> "$BOOTSTRAP_LOG"; fail "Python download failed. See $BOOTSTRAP_LOG"
  fi
  printf '%s  %s\n' dafebf62b8737f341f6b7eca2d6d1153a50a6b1bfbfa4b8aaf0e62adc73e5017 "$TMP/python.pkg" | shasum -a 256 -c -
  pkgutil --check-signature "$TMP/python.pkg" > "$TMP/signature.txt"
  cat "$TMP/signature.txt"
  cat "$TMP/signature.txt" >> "$BOOTSTRAP_LOG"
  grep -Fq 'Python Software Foundation (BMM5U3QVKW)' "$TMP/signature.txt" || fail 'Unexpected Python signer.'
  echo 'Enter your Mac administrator password for the signed Python installer. Input is hidden.'
  # sudo has a bounded password prompt; installer is supervised separately.
  sudo -v & AUTH_PID=$!
  ( sleep 180; kill -TERM "$AUTH_PID" 2>/dev/null || true ) & AUTH_WATCH_PID=$!
  if wait "$AUTH_PID"; then AUTH_RC=0; else AUTH_RC=$?; fi
  kill "$AUTH_WATCH_PID" 2>/dev/null || true
  [[ "$AUTH_RC" -eq 0 ]] || fail "Administrator authentication failed or timed out (3 minutes). See $BOOTSTRAP_LOG"
  printf '%s sudo -n /usr/sbin/installer -pkg [hash-verified-python.pkg] -target /\n' "$(date -u +%FT%TZ)" >> "$BOOTSTRAP_LOG"
  sudo -n /usr/sbin/installer -pkg "$TMP/python.pkg" -target / >> "$BOOTSTRAP_LOG" 2>&1 &
  INSTALL_PID=$!
  ( sleep 600; kill -TERM "$INSTALL_PID" 2>/dev/null || true ) & WATCH_PID=$!
  if wait "$INSTALL_PID"; then RC=0; else RC=$?; fi
  kill "$WATCH_PID" 2>/dev/null || true
  printf '%s installer_exit=%s\n' "$(date -u +%FT%TZ)" "$RC" >> "$BOOTSTRAP_LOG"
  [[ "$RC" -eq 0 ]] || fail 'Python installation failed/timed out; rerun after resolving installer output.'
  find_python || fail 'Installer finished but supported Python is not available.'
fi
if [[ -n "${TMP:-}" ]]; then
  rm -f "$TMP/python.pkg" "$TMP/signature.txt"
  rmdir "$TMP" 2>/dev/null || true
  trap - EXIT
fi
printf '%s controller_python=%s\n' "$(date -u +%FT%TZ)" "$PY" >> "$BOOTSTRAP_LOG"
exec caffeinate -i "$PY" "$PACKAGE/launcher.py" --work "$WORK" --consented --bootstrap-log "$BOOTSTRAP_LOG"
