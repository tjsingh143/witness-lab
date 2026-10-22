#!/usr/bin/env bash
# Repeatable network smoke checks on one Witness VM, with the evidence printed inline
# ("$ cmd" then its real output) and PASS/FAIL per check; final "SMOKE GREEN|RED".
#   --role ctl|field          addressing, routing, names, reachability, isolation probes
#   --route-demo remove|restore   (ctl only) delete / restore the device-subnet route.
#       remove arms a 120 s systemd dead-man timer that restores the route on its own.
# Usage: sudo lab-smoke.sh --role ctl|field [--route-demo remove|restore]
set -uo pipefail
# shellcheck source=scripts/lib/guest_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/guest_common.sh"

ROLE="" DEMO=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --role) ROLE="${2:-}"; shift 2 ;;
    --route-demo) DEMO="${2:-}"; shift 2 ;;
    *) die "usage: $0 --role ctl|field [--route-demo remove|restore]" ;;
  esac
done
[[ "$ROLE" == ctl || "$ROLE" == field ]] || die "usage: $0 --role ctl|field [--route-demo remove|restore]"
need_root
assert_lab_vm "$ROLE"
FAILS=0
ev() { echo "\$ $*"; run_t 8 "$@" 2>&1 | sed 's/^/    /'; return "${PIPESTATUS[0]}"; }
ok()  { echo "PASS $*"; }
bad() { echo "FAIL $*"; FAILS=$((FAILS + 1)); }
expect_ok()   { local n="$1"; shift; if ev "$@"; then ok "$n"; else bad "$n (exit $?)"; fi; }
expect_fail() { local n="$1"; shift; if ev "$@"; then bad "$n (unexpectedly succeeded)"; else ok "$n (failed as required)"; fi; }
route_line() { ip -4 route show "$WIT_DEV_SUBNET"; }
first_dev_addr() { device_rows | head -1 | cut -f1; }
first_dev_host() { device_rows | head -1 | cut -f2; }
finish() {
  if (( FAILS == 0 )); then echo "SMOKE GREEN role=$ROLE ${DEMO:+demo=$DEMO }at=$(date -u +%FT%TZ)"; exit 0; fi
  echo "SMOKE RED role=$ROLE ${DEMO:+demo=$DEMO }fails=$FAILS at=$(date -u +%FT%TZ)"; exit 1
}
echo "# lab-smoke on $(hostname) role=$ROLE at $(date -u +%FT%TZ)"

if [[ -n "$DEMO" ]]; then
  [[ "$ROLE" == ctl ]] || die "--route-demo runs on witness-ctl only"
  case "$DEMO" in
    remove)
      [[ "$(route_line)" == "$WIT_DEV_SUBNET via $WIT_FIELD_L2 dev $WIT_LAB_IF"* ]] || die "route not in the expected state; run reset_lab.sh first"
      systemctl stop witness-route-deadman.timer witness-route-deadman.service 2>/dev/null
      systemctl reset-failed witness-route-deadman.service witness-route-deadman.timer 2>/dev/null
      systemd-run --quiet --unit=witness-route-deadman --on-active=120 --timer-property=AccuracySec=1s \
        /usr/sbin/ip route replace "$WIT_DEV_SUBNET" via "$WIT_FIELD_L2" dev "$WIT_LAB_IF" proto static ||
        die "could not arm dead-man timer; not removing route"
      echo "# dead-man armed: $(systemctl list-timers --no-legend witness-route-deadman.timer | awk '{print $1, $2, $3}')"
      expect_ok "route-delete" ip route del "$WIT_DEV_SUBNET" via "$WIT_FIELD_L2" dev "$WIT_LAB_IF"
      expect_fail "route-get-device-unreachable" ip -4 route get "$(first_dev_addr)"
      expect_fail "ping-device-fails" ping -c1 -W1 -n "$(first_dev_addr)"
      expect_ok "name-still-resolves" getent hosts "$(first_dev_host)"
      expect_ok "l2-peer-still-reachable" ping -c1 -W1 -n "$WIT_FIELD_L2"
      expect_ok "vsock-mgmt-socket-active" systemctl is-active witness-sshd-vsock.socket
      ;;
    restore)
      expect_ok "route-restore" ip route replace "$WIT_DEV_SUBNET" via "$WIT_FIELD_L2" dev "$WIT_LAB_IF" proto static
      systemctl stop witness-route-deadman.timer witness-route-deadman.service 2>/dev/null
      echo "# dead-man disarmed"
      expect_ok "route-present" sh -c "ip -4 route show $WIT_DEV_SUBNET | grep -q 'via $WIT_FIELD_L2 dev $WIT_LAB_IF'"
      expect_ok "route-get-device" ip -4 route get "$(first_dev_addr)"
      expect_ok "ping-device-by-name" ping -c2 -W1 "$(first_dev_host)"
      ;;
    *) die "--route-demo remove|restore" ;;
  esac
  finish
fi

# --- topology evidence
ev ip -br link
ev ip -br addr
ev ip -4 route
ev sysctl net.ipv4.ip_forward
if [[ "$ROLE" == ctl ]]; then
  while IFS=$'\t' read -r addr host; do
    expect_ok "route-get-$addr-via-field" sh -c "ip -4 route get $addr | tee /dev/stderr | grep -q 'via $WIT_FIELD_L2 dev $WIT_LAB_IF'"
    expect_ok "getent-$host" sh -c "getent hosts $host | tee /dev/stderr | grep -q '^$addr '"
    expect_ok "ping-$host" ping -c3 -W1 "$host"
  done < <(device_rows)
  expect_ok "route-get-field-l2-direct" sh -c "ip -4 route get $WIT_FIELD_L2 | tee /dev/stderr | grep -q 'dev $WIT_LAB_IF'"
  expect_ok "ping-field-l2" ping -c3 -W1 -n "$WIT_FIELD_L2"
else
  ev ip -d link show dev "$WIT_DEV_IF"
  expect_ok "device-addrs-local" sh -c "ip -4 route get $(first_dev_addr) | tee /dev/stderr | grep -q '^local '"
  expect_ok "ping-ctl-l2" ping -c3 -W1 -n "$WIT_CTL_L2"
  ev chronyc -n sources
fi

# --- internet isolation (packages are already installed)
mgw="$(mgmt_gateway)"
expect_fail "no-internet-icmp" ping -c1 -W2 -n 1.1.1.1
expect_fail "no-internet-tcp" curl -sS -m 3 -o /dev/null http://1.1.1.1/
expect_fail "no-public-dns" getent hosts archive.ubuntu.com
expect_fail "no-gvproxy-lab-gw" ping -c1 -W1 -n "$WIT_L2_GATEWAY"
expect_fail "no-gvproxy-mgmt-gw" ping -c1 -W1 -n "$mgw"
# Defense in depth: even with a deliberate route to the internet, nft drops egress.
ip route add 1.1.1.1/32 via "$mgw" dev "$WIT_MGMT_IF" 2>/dev/null && trap 'ip route del 1.1.1.1/32 2>/dev/null' EXIT
expect_fail "nft-blocks-even-with-route" curl -sS -m 3 -o /dev/null http://1.1.1.1/
ip route del 1.1.1.1/32 2>/dev/null; trap - EXIT
ev sh -c "nft list chain inet $WIT_NFT_TABLE output | grep -E 'policy|counter'"
finish
