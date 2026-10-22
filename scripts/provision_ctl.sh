#!/usr/bin/env bash
# Idempotent provisioning of witness-ctl (VM-A): packages, vsock SSH, lab0 static
# address, static route to the device subnet via witness-field, /etc/hosts device
# names, chrony lab time source, internet isolation. Run as root ON witness-ctl.
# Usage: provision_ctl.sh [--stage base|all]   (base = packages + vsock SSH only)
set -euo pipefail
# shellcheck source=scripts/lib/guest_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/guest_common.sh"

STAGE=all
while [[ $# -gt 0 ]]; do
  case "$1" in
    --stage) STAGE="${2:?}"; shift 2 ;;
    *) die "usage: $0 [--stage base|all]" ;;
  esac
done
[[ "$STAGE" == base || "$STAGE" == all ]] || die "bad --stage $STAGE"
need_root
assert_lab_vm ctl
mkdir -p "$WIT_STATE_DIR"
log "provisioning $WIT_SELF_NAME (stage $STAGE)"

# ShellCheck (repo bash lint) is installed here so the Mac host stays untouched.
ensure_packages "${WIT_PKGS_COMMON[@]}" shellcheck
ensure_vsock_ssh
if [[ "$STAGE" == base ]]; then log "base stage complete"; exit 0; fi

ensure_sysctl
# The device subnet is reachable ONLY through witness-field's lab0 address. Deleting
# this route is fault F5; scripts/reset_lab.sh restores it.
ensure_netplan "$WIT_CTL_L2/$WIT_L2_PREFIX" "
      routes:
        - to: $WIT_DEV_SUBNET
          via: $WIT_FIELD_L2" ""
log "/etc/hosts block: $(ensure_hosts)"

# No driftfile (Phase 3 fix): with -x chronyd cannot adjust the clock but still applies its
# frequency estimate to the time it SERVES. An old drift file (-81 ppm, from before -x) made the
# served time run 81 ppm ahead of ctl's system clock: +1.437 s after 4.9 h, invisible to field's
# SNTP gate (which measures against the served time). With no frequency model it serves the
# system clock itself; preflight check `clock-served` verifies that.
ensure_chrony "# Managed by witness-lab provision_ctl.sh. witness-ctl is the lab time reference: it
# serves its own clock (stepped to the macOS host by lima-guestagent) to witness-field
# over lab0; chronyd runs with -x and never adjusts it. No internet NTP. No driftfile:
# a frequency estimate would be applied to the served time, not to this clock.
local stratum 8
allow $WIT_FIELD_L2/32
logdir /var/log/chrony" "-F 1 -x"
if [[ -e /var/lib/chrony/chrony.drift ]]; then
  log "removing stale chrony drift file ($(cat /var/lib/chrony/chrony.drift)); restarting chronyd"
  rm -f /var/lib/chrony/chrony.drift
  systemctl restart chrony
fi

ensure_isolation
ensure_resolved
ensure_stable_hostkeys

# Runner (Phase 2): SSH key for the fault agent on witness-field (lab_vms.sh link installs the
# public half there and field's host key here), results + evidence directory.
install -d -m 0700 /var/lib/witness/runner
[[ -s /var/lib/witness/runner/id_ed25519 ]] ||
  ssh-keygen -q -t ed25519 -N '' -C "witness-runner@$WIT_CTL_NAME" -f /var/lib/witness/runner/id_ed25519
install -d -m 0755 /var/lib/witness/results /var/lib/witness/results/evidence
log "runner key $(ssh-keygen -lf /var/lib/witness/runner/id_ed25519.pub | awk '{print $2}')"

# Gateway (Phase 3): installed copy of gateway/ plus the runner modules it imports and the
# inventory loader, the inventory itself and the unit. Restarts only when something changed or it
# is not running (like the devices on witness-field), so a repo sync never silently swaps it.
ensure_gateway() {
  local lib=/usr/local/lib/witness-gateway changed=0 f r i
  for f in gateway/__init__.py gateway/gateway.py runner/__init__.py runner/classify.py runner/client.py \
           scripts/lib/inventory.py; do
    [[ "$(install_if_changed "$(cat "$WIT_REPO/$f")" "$lib/$f" 0644)" == changed ]] && changed=1
  done
  [[ "$(install_if_changed "$(cat "$WIT_REPO/inventory.yaml")" /etc/witness/inventory.yaml 0644)" == changed ]] && changed=1
  r="$(install_if_changed "$(cat "$WIT_REPO/gateway/witness-gateway.service")" /etc/systemd/system/witness-gateway.service 0644)"
  if [[ "$r" == changed ]]; then systemctl daemon-reload; changed=1; fi
  systemctl enable witness-gateway.service >/dev/null 2>&1
  if (( changed )) || ! systemctl is-active -q witness-gateway.service; then
    log "restarting witness-gateway (code/unit/inventory changed or not running)"
    run_t 30 systemctl restart witness-gateway.service
  fi
  systemctl is-active -q witness-gateway.service || die "witness-gateway failed to start"
  for i in $(seq 1 20); do
    curl -sf -m 2 -o /dev/null http://127.0.0.1:8080/inventory && break
    sleep 0.25
  done
  curl -sf -m 2 -o /dev/null http://127.0.0.1:8080/inventory || die "witness-gateway API not answering"
  log "witness-gateway active pid $(systemctl show -p MainPID --value witness-gateway.service); GET /inventory OK"
}
mkdir -p /etc/witness
ensure_gateway

mapfile -t hosts < <(device_rows | cut -f2)
log "summary: $(ip -br addr show dev "$WIT_LAB_IF" | tr -s ' ') | $(ip route show "$WIT_DEV_SUBNET") | $(getent hosts "${hosts[@]}" | tr -s ' \n' ' ')"
log "provisioning complete; run scripts/preflight.sh --role ctl"
