#!/usr/bin/env bash
# Read-only lab preflight/postflight for one Witness VM. Prints one line per check:
#   PASS|FAIL|SKIP <check> <detail>
# and a final "PREFLIGHT GREEN|RED". Exit 0 = green, 1 = red (any FAIL), 2 = usage.
# Never changes state. A red preflight makes any later device result infra-attributed.
# field only: a mutant device build (brief 7.4) is RED unless --allow-mutant (the runner passes it
# only for a declared mutant run; the run is then recorded as kind=mutant, never as a baseline).
# Usage: sudo preflight.sh --role ctl|field [--allow-mutant]
set -uo pipefail
# shellcheck source=scripts/lib/guest_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/guest_common.sh"

ROLE="" ALLOW_MUTANT=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --role) ROLE="${2:-}"; shift 2 ;;
    --allow-mutant) ALLOW_MUTANT=1; shift ;;
    *) echo "usage: $0 --role ctl|field [--allow-mutant]" >&2; exit 2 ;;
  esac
done
[[ "$ROLE" == ctl || "$ROLE" == field ]] || { echo "usage: $0 --role ctl|field" >&2; exit 2; }
need_root
FAILS=0
pass() { echo "PASS $1 ${*:2}"; }
fail() { echo "FAIL $1 ${*:2}"; FAILS=$((FAILS + 1)); }
skip() { echo "SKIP $1 ${*:2}"; }
check() { local name="$1" detail="$2"; shift 2; if "$@" >/dev/null 2>&1; then pass "$name" "$detail"; else fail "$name" "$detail"; fi; }

# Identity first: if this is not the expected lab VM, nothing else is meaningful.
( assert_lab_vm "$ROLE" ) || { echo "FAIL identity not $ROLE lab VM"; echo "PREFLIGHT RED role=$ROLE fails=1"; exit 1; }
assert_lab_vm "$ROLE"
pass identity "$(hostname) $WIT_LAB_IF=$(cat "/sys/class/net/$WIT_LAB_IF/address") kernel=$(uname -r)"

# --- addressing and isolation
got="$(ip -4 -o addr show dev "$WIT_LAB_IF" | awk '{print $4}' | paste -sd' ' -)"
[[ "$got" == "$WIT_SELF_L2/$WIT_L2_PREFIX" ]] && pass lab-address "$WIT_LAB_IF $got" || fail lab-address "$WIT_LAB_IF has '$got', want $WIT_SELF_L2/$WIT_L2_PREFIX"
defr="$(ip -4 route show default; ip -6 route show default 2>/dev/null)"
[[ -z "$defr" ]] && pass no-default-route "isolated" || fail no-default-route "$(echo "$defr" | head -1)"
# Capture first: `nft ... | grep -q` under pipefail fails when grep exits early (SIGPIPE).
iso="$(nft list chain inet "$WIT_NFT_TABLE" output 2>/dev/null)"
if systemctl is-active -q witness-isolation.service && grep -q 'policy drop' <<<"$iso"; then
  if grep -q witness-online-window <<<"$iso"; then
    fail isolation "online window rule still present"
  else
    pass isolation "table inet $WIT_NFT_TABLE output policy drop"
  fi
else
  fail isolation "witness-isolation.service inactive or table missing"
fi
fwd="$(sysctl -n net.ipv4.ip_forward)"; [[ "$fwd" == 0 ]] && pass ip-forward "0" || fail ip-forward "$fwd (want 0)"

# --- no leftover faults
ft="$(fault_tables | paste -sd, -)"
[[ -z "$ft" ]] && pass no-fault-nft "no $WIT_FAULT_TABLE_PREFIX* tables" || fail no-fault-nft "leftover: $ft"
for ifc in $(lab_ifaces); do
  q="$(tc qdisc show dev "$ifc" 2>/dev/null | paste -sd';' -)"
  if [[ -z "$q" ]]; then fail "qdisc-$ifc" "interface missing"
  elif grep -qE "$WIT_FAULT_QDISC_RE" <<<"$q"; then fail "qdisc-$ifc" "fault qdisc: $q"
  else pass "qdisc-$ifc" "$q"; fi
done

dm="$WIT_DEADMAN_FIELD"; [[ "$ROLE" == ctl ]] && dm="$WIT_DEADMAN_CTL"
if systemctl is-active -q "$dm.timer"; then fail no-fault-deadman "$dm.timer armed (a fault is applied or was not reverted)"
else pass no-fault-deadman "$dm.timer inactive"; fi
if [[ "$ROLE" == field ]]; then
  # A field capture left by a killed runner (bounded by RuntimeMaxSec=120) would turn the next case's
  # precheck RED; the full preflight must see it too (Phase 4: run 110 started 102 s after a SIGKILL test).
  if systemctl is-active -q witness-field-capture.service; then fail capture-idle "witness-field-capture running (left by a runner?)"
  else pass capture-idle "witness-field-capture inactive"; fi
fi

# --- clocks (REQ-04 precondition): one writer per clock, macOS -> ctl -> field.
if ! systemctl is-active -q chrony; then
  fail chrony "chronyd not active"
elif [[ "$ROLE" == ctl ]]; then
  chrony_is_measure_only && pass clock-source "chronyd -x serving ctl clock (owned by lima-guestagent) to $WIT_FIELD_L2" ||
    fail clock-source "chronyd on ctl must run with -x"
  # Field's gate measures field against the time ctl's chronyd SERVES; that must be ctl's system
  # clock, or both VMs agree with chronyd while disagreeing with each other (Phase 3 finding).
  st="$(chronyc -n tracking 2>/dev/null | sed -n 's/^System time *: //p')"
  sv="$(awk '{print $1}' <<<"$st")"
  if [[ -n "$sv" ]] && awk -v o="$sv" 'BEGIN{exit !(o < 0.01)}'; then
    pass clock-served "ctl chronyd serves the system clock: $st"
  else
    fail clock-served "ctl chronyd served time differs from ctl's system clock: '${st:-no tracking}' (need < 0.01 s)"
  fi
else
  if chrony_is_measure_only; then fail clock-writer "chronyd -x on field: nothing follows ctl"
  elif guestagent_can_settime; then fail clock-writer "lima-guestagent can still set the clock (two writers)"
  else pass clock-writer "chronyd only (lima-guestagent without CAP_SYS_TIME)"; fi
  sel="$(chronyc -n sources 2>/dev/null | awk '$1 ~ /^\^\*/ {print $2}')"
  [[ "$sel" == "$WIT_CTL_L2" ]] && pass clock-source "chrony selected $sel" || fail clock-source "chrony selected '${sel:-none}', want $WIT_CTL_L2"
  off="$(ctl_clock_offset)"
  if [[ -n "$off" ]] && awk -v o="$off" 'BEGIN{exit !(o < 0.1 && o > -0.1)}'; then
    pass clock-sync "SNTP offset of ctl vs field ${off}s (|x|<0.1)"
  else
    fail clock-sync "SNTP offset of ctl vs field '${off:-no reply}' (need |x|<0.1 s)"
  fi
fi

# --- management/rescue path and host health
check vsock-ssh "witness-sshd-vsock.socket active" systemctl is-active -q witness-sshd-vsock.socket
free_kb="$(df -Pk / | awk 'NR==2 {print $4}')"
(( free_kb > 1048576 )) && pass disk "$((free_kb / 1024)) MiB free on /" || fail disk "only $((free_kb / 1024)) MiB free"

# --- role-specific network
if [[ "$ROLE" == ctl ]]; then
  r="$(ip -4 route show "$WIT_DEV_SUBNET")"
  [[ "$r" == "$WIT_DEV_SUBNET via $WIT_FIELD_L2 dev $WIT_LAB_IF"* ]] && pass device-route "$r" || fail device-route "'$r'"
  [[ "$(awk -v b="$WIT_HOSTS_BEGIN" -v e="$WIT_HOSTS_END" '$0==b{s=1} s{print} $0==e{s=0}' /etc/hosts)" == "$(hosts_block)" ]] &&
    pass hosts-block "/etc/hosts matches inventory" || fail hosts-block "/etc/hosts block differs from inventory"
  check ping-field-l2 "$WIT_FIELD_L2 via $WIT_LAB_IF" ping -c1 -W1 -n "$WIT_FIELD_L2"
  if [[ -f /etc/systemd/system/witness-gateway.service ]]; then
    gi="$(curl -s -m 2 http://127.0.0.1:8080/inventory 2>/dev/null)"
    gids="$(python3 -c 'import json,sys; print(" ".join(sorted(d["device_id"] for d in json.load(sys.stdin)["devices"])))' <<<"$gi" 2>/dev/null)"
    gwant="$(tr ' ' '\n' <<<"$WIT_DEVICE_IDS" | sort | paste -sd' ' -)"
    if systemctl is-active -q witness-gateway.service && [[ "$gids" == "$gwant" ]]; then
      pass gateway "witness-gateway active; GET /inventory lists $gids"
    else
      fail gateway "witness-gateway $(systemctl is-active witness-gateway.service); GET /inventory devices '${gids:-none}' want '$gwant'"
    fi
  else
    skip gateway "witness-gateway not installed yet (Phase 3)"
  fi
  while IFS=$'\t' read -r addr host; do
    got="$(getent ahostsv4 "$host" | awk 'NR==1 {print $1}')"
    [[ "$got" == "$addr" ]] && pass "resolve-$host" "$got" || fail "resolve-$host" "'$got' want $addr"
    rg="$(ip -4 route get "$addr" 2>&1 | head -1)"
    [[ "$rg" == "$addr via $WIT_FIELD_L2 dev $WIT_LAB_IF "* ]] && pass "route-get-$addr" "$rg" || fail "route-get-$addr" "$rg"
    check "ping-$host" "$addr" ping -c1 -W1 -n "$addr"
  done < <(device_rows)
else
  if grep -q dummy <<<"$(ip -d link show dev "$WIT_DEV_IF" 2>/dev/null)"; then
    want="$(device_rows | cut -f1 | sed "s|\$|/$WIT_DEV_PREFIX|" | sort | paste -sd' ' -)"
    got="$(ip -4 -o addr show dev "$WIT_DEV_IF" | awk '{print $4}' | sort | paste -sd' ' -)"
    [[ "$got" == "$want" ]] && pass device-addrs "$WIT_DEV_IF dummy: $got" || fail device-addrs "$WIT_DEV_IF has '$got', want '$want'"
  else
    fail device-addrs "$WIT_DEV_IF missing or not a dummy interface"
  fi
  check ping-ctl-l2 "$WIT_CTL_L2 via $WIT_LAB_IF" ping -c1 -W1 -n "$WIT_CTL_L2"
  if [[ -f "$WIT_DEVICE_UNIT" ]]; then
    for i in $(device_instances); do
      u="witness-device@$i.service"; pid="$(systemctl show -p MainPID --value "$u")"
      if systemctl is-active -q "$u" && [[ "$pid" != 0 ]] && [[ "$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null)" != T ]]; then
        pass "service-$i" "$u active pid $pid"
      else
        fail "service-$i" "$u not active/running (pid $pid)"
      fi
      mode="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["mode"])' "/run/witness-device-$i/state.json" 2>/dev/null)"
      [[ "$mode" == normal ]] && pass "device-mode-$i" "normal" || fail "device-mode-$i" "fault mode '${mode:-unknown}'"
      build="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("build","stock"))' "/run/witness-device-$i/state.json" 2>/dev/null)"
      dropin="/run/systemd/system/witness-device@$i.service.d/50-witness-mutant.conf"
      if [[ "$build" == stock && ! -e "$dropin" ]]; then pass "device-build-$i" "stock"
      elif [[ "$build" == mutant:* ]] && (( ALLOW_MUTANT )); then pass "device-build-$i" "$build (declared mutant run)"
      else fail "device-build-$i" "build '${build:-unknown}'$([[ -e "$dropin" ]] && echo " + mutant drop-in $dropin")"; fi
    done
    while IFS=$'\t' read -r addr host; do
      if [[ -n "$(ss -Hltn "src $addr:5020")" ]]; then pass "listen-$addr" "$host $addr:5020"
      else fail "listen-$addr" "nothing listening on $addr:5020 ($host)"; fi
    done < <(device_rows)
  else
    skip device-services "$WIT_DEVICE_UNIT not installed yet (Phase 2)"
  fi
fi

if (( FAILS == 0 )); then echo "PREFLIGHT GREEN role=$ROLE host=$(hostname) at=$(date -u +%FT%TZ)"; exit 0; fi
echo "PREFLIGHT RED role=$ROLE host=$(hostname) fails=$FAILS at=$(date -u +%FT%TZ)"; exit 1
