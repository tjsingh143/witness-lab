#!/usr/bin/env bash
# Bounded, idempotent emergency reset of lab FAULT state on one Witness VM, safe on a
# partially provisioned VM. It removes only what the lab may inject:
#   - nft tables named witness_fault* (never witness_isolation, never Lima's tables)
#   - netem/tbf/prio fault qdiscs on the lab interfaces (lab0, and field0 on witness-field)
#   - the fault dead-man timer of this VM (the timer only, never its running service)
#   - ctl: the device-subnet route via witness-field, the /etc/hosts managed block
#   - field: mutant-build drop-ins (/run/systemd/system/witness-device@<i>.service.d/50-witness-mutant.conf:
#     removed, then the device restarts as the stock build), field0 dummy addresses; SIGSTOPped
#     witness-device processes get SIGCONT,
#     inactive witness-device@ units are started, device fault modes are set back to normal,
#     a leftover field-side capture unit is stopped
# Each step is time-bounded and continues on error; exit 1 if any step failed.
# Usage: sudo reset_lab.sh --role ctl|field [--dry-run]
set -uo pipefail
# shellcheck source=scripts/lib/guest_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/guest_common.sh"

ROLE="" DRY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --role) ROLE="${2:-}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    *) die "usage: $0 --role ctl|field [--dry-run]" ;;
  esac
done
[[ "$ROLE" == ctl || "$ROLE" == field ]] || die "usage: $0 --role ctl|field [--dry-run]"
need_root
assert_lab_vm "$ROLE"   # refuses to touch anything on the wrong machine
ERR=0
act() {  # act <description> <cmd...>
  local d="$1"; shift
  if (( DRY )); then log "would: $d"; return 0; fi
  if run_t 10 "$@"; then log "did: $d"; else warn "FAILED: $d"; ERR=1; fi
}

log "reset on $WIT_SELF_NAME (dry-run=$DRY)"
while read -r fam name; do
  [[ -n "${name:-}" ]] && act "delete nft table $fam $name" nft delete table "$fam" "$name"
done < <(fault_tables)

for ifc in $(lab_ifaces); do
  [[ -e "/sys/class/net/$ifc" ]] || { warn "$ifc missing (not provisioned?)"; continue; }
  # Capture before grep: `tc ... | grep -q` under pipefail races SIGPIPE on multi-line output
  # (observed: the prio+netem tree survived one reset-selftest and was removed in another).
  q="$(tc qdisc show dev "$ifc")"
  if grep -qE "^qdisc ($WIT_FAULT_QDISC_RE) " <<<"$q"; then
    act "remove root qdisc $(tc qdisc show dev "$ifc" root | awk '{print $2}') (fault qdisc tree) on $ifc" tc qdisc del dev "$ifc" root
  fi
done

dm="$WIT_DEADMAN_FIELD"; [[ "$ROLE" == ctl ]] && dm="$WIT_DEADMAN_CTL"
systemctl is-active -q "$dm.timer" && act "disarm dead-man $dm.timer" systemctl stop "$dm.timer"

if [[ "$ROLE" == ctl ]]; then
  want="$WIT_DEV_SUBNET via $WIT_FIELD_L2 dev $WIT_LAB_IF"
  if [[ "$(ip -4 route show "$WIT_DEV_SUBNET")" != "$want"* ]]; then
    act "restore route $want" ip route replace "$WIT_DEV_SUBNET" via "$WIT_FIELD_L2" dev "$WIT_LAB_IF" proto static
  fi
  if [[ "$(awk -v b="$WIT_HOSTS_BEGIN" -v e="$WIT_HOSTS_END" '$0==b{s=1} s{print} $0==e{s=0}' /etc/hosts)" != "$(hosts_block)" ]]; then
    if (( DRY )); then log "would: rewrite /etc/hosts managed block"; else log "did: /etc/hosts block $(ensure_hosts)"; fi
  fi
  [[ -n "$(systemctl list-units --all --no-legend 'witness-route-deadman*' 2>/dev/null)" ]] &&
    act "stop route dead-man timer" systemctl stop witness-route-deadman.timer witness-route-deadman.service
else
  # Field-side evidence capture (witness-faultctl capture start) is bounded by RuntimeMaxSec anyway.
  systemctl is-active -q witness-field-capture.service && act "stop field capture" systemctl stop witness-field-capture.service
  if ! ip link show dev "$WIT_DEV_IF" >/dev/null 2>&1; then
    act "recreate dummy $WIT_DEV_IF" ip link add "$WIT_DEV_IF" type dummy
  fi
  act "set $WIT_DEV_IF up" ip link set "$WIT_DEV_IF" up
  while IFS=$'\t' read -r addr _; do
    grep -q " $addr/" <<<"$(ip -4 -o addr show dev "$WIT_DEV_IF")" ||
      act "re-add $addr/$WIT_DEV_PREFIX to $WIT_DEV_IF" ip addr add "$addr/$WIT_DEV_PREFIX" dev "$WIT_DEV_IF"
  done < <(device_rows)
  if [[ -f "$WIT_DEVICE_UNIT" ]]; then
    for i in $(device_instances); do
      u="witness-device@$i.service"
      dropin="/run/systemd/system/witness-device@$i.service.d/50-witness-mutant.conf"
      if [[ -e "$dropin" ]] || ! grep -qs '"build": "stock"' "/run/witness-device-$i/state.json"; then
        if [[ -e "$dropin" ]]; then act "remove mutant drop-in $dropin" rm -f "$dropin"; fi
        act "daemon-reload" systemctl daemon-reload
        if [[ -d "/run/witness-device-$i" ]] && systemctl is-active -q "$u"; then act "restart $u as stock build" systemctl restart "$u"; fi
      fi
      # The cgroup path contains a literal "\x2d" (system-witness\x2ddevice.slice): read it
      # verbatim (an earlier `xargs -I{}` unescaped the backslash and silently found no pids).
      cg="$(systemctl show -p ControlGroup --value "$u")"
      for pid in $([[ -n "$cg" ]] && cat "/sys/fs/cgroup$cg/cgroup.procs" 2>/dev/null); do
        [[ "$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null)" == T ]] && act "SIGCONT stopped pid $pid ($u)" kill -CONT "$pid"
      done
      systemctl is-active -q "$u" || act "start $u" systemctl start "$u"
      # Mode files live in the ROOT-owned /run/witness-fault (never in the device-owned
      # /run/witness-device-$i, where the device user could plant a symlink for root to follow).
      if [[ -d "/run/witness-device-$i" ]] && ! grep -qs '"mode": "normal"' "/run/witness-device-$i/state.json"; then
        act "device $i fault mode -> normal" bash -c "install -d -m 0755 -o root -g root /run/witness-fault &&
          [[ ! -L /run/witness-fault ]] && printf 'normal\n' >/run/witness-fault/device-$i.mode &&
          systemctl kill -s HUP --kill-whom=main $u"
      fi
    done
  fi
fi

(( DRY )) && { log "dry run complete"; exit 0; }
(( ERR == 0 )) && log "reset complete; verify with: sudo scripts/preflight.sh --role $ROLE" || warn "reset had failures"
exit "$ERR"
