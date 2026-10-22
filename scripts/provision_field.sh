#!/usr/bin/env bash
# Idempotent provisioning of witness-field (VM-B): packages, vsock SSH, lab0 static
# address, dummy field0 holding the device addresses, chrony client of witness-ctl,
# no forwarding, internet isolation. Run as root ON witness-field (lab_vms.sh provision).
# Phase 2: the device service (witness-device@<i>) and the fault agent (user witness-fault,
# SSH forced command -> sudo witness-faultctl) that the runner on witness-ctl drives.
# Usage: provision_field.sh [--stage base|all|agent]
#   base  = packages + vsock SSH only;  agent = fault agent + runner key only (lab_vms.sh link)
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
[[ "$STAGE" == base || "$STAGE" == all || "$STAGE" == agent ]] || die "bad --stage $STAGE"
need_root
assert_lab_vm field
mkdir -p "$WIT_STATE_DIR"
log "provisioning $WIT_SELF_NAME (stage $STAGE)"

# Device processes: code + unit + per-instance identity (from inventory.yaml). Restarts an
# instance only when its code, unit or identity changed, or it is not running.
ensure_devices() {
  local c1 c2 c3 changed=0 id k v inst env r
  mkdir -p /usr/local/lib/witness /etc/witness
  c1="$(install_if_changed "$(cat "$WIT_REPO/device/device.py")" /usr/local/lib/witness/device.py 0644)"
  c2="$(install_if_changed "$(cat "$WIT_REPO/device/witness-device@.service")" "$WIT_DEVICE_UNIT" 0644)"
  # mutant builds (brief 7.4) are selected only by a runtime drop-in (witness-faultctl mutant deploy)
  c3="$(install_if_changed "$(cat "$WIT_REPO/device/mutants.py")" /usr/local/lib/witness/mutants.py 0644)"
  [[ "$c2" == changed ]] && systemctl daemon-reload
  [[ "$c1$c2$c3" == *changed* ]] && changed=1
  for id in $WIT_DEVICE_IDS; do
    k="${id^^}"; k="${k//-/_}"
    v="WIT_${k}_INSTANCE"; inst="${!v}"
    env="# Managed by witness-lab provision_field.sh from inventory.yaml (device identity is
# provisioned to match the inventory; the runner checks it, it does not read it from here).
WITNESS_INSTANCE=$inst
WITNESS_DEVICE_ID=$id
WITNESS_SERIAL=$(v="WIT_${k}_SERIAL"; echo "${!v}")
WITNESS_MODEL=WSIM-1
WITNESS_FW_VERSION=$(v="WIT_${k}_FW"; echo "${!v}")
WITNESS_BIND=$(v="WIT_${k}_ADDR"; echo "${!v}")
WITNESS_PORT=$(v="WIT_${k}_PORT"; echo "${!v}")"
    r="$(install_if_changed "$env" "/etc/witness/device-$inst.env" 0644)"
    systemctl enable "witness-device@$inst.service" >/dev/null 2>&1
    if (( changed )) || [[ "$r" == changed ]] || ! systemctl is-active -q "witness-device@$inst.service"; then
      log "restarting witness-device@$inst (code/unit/identity changed or not running)"
      run_t 45 systemctl restart "witness-device@$inst.service"
    fi
    systemctl is-active -q "witness-device@$inst.service" || die "witness-device@$inst failed to start"
    log "witness-device@$inst active pid $(systemctl show -p MainPID --value "witness-device@$inst.service")"
  done
}

# Fault agent: the runner's only privileged path onto this VM.
ensure_fault_agent() {
  local home=/var/lib/witness/fault-agent key sudo_tmp
  install_if_changed "$(cat "$WIT_REPO/scripts/faultctl.py")" /usr/local/sbin/witness-faultctl 0755 >/dev/null
  install_if_changed "$(cat "$WIT_REPO/scripts/witness-fault-ssh")" /usr/local/sbin/witness-fault-ssh 0755 >/dev/null
  if ! id witness-fault >/dev/null 2>&1; then
    useradd --system --home-dir "$home" --create-home --shell /bin/sh witness-fault
    log "created system user witness-fault"
  fi
  sudo_tmp="$(mktemp)"
  printf '%s\n' "# Managed by witness-lab: the runner (via SSH forced command) may run only witness-faultctl." \
    "witness-fault ALL=(root) NOPASSWD: /usr/local/sbin/witness-faultctl" >"$sudo_tmp"
  visudo -cqf "$sudo_tmp" || { rm -f "$sudo_tmp"; die "sudoers fragment failed visudo"; }
  install_if_changed "$(cat "$sudo_tmp")" /etc/sudoers.d/60-witness-fault 0440 >/dev/null; rm -f "$sudo_tmp"
  if [[ -s /etc/witness/runner_key.pub ]]; then
    key="$(head -1 /etc/witness/runner_key.pub)"
    [[ "$key" =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+(\ .*)?$ ]] || die "runner_key.pub is not an ed25519 public key"
    install -d -m 0700 -o witness-fault -g witness-fault "$home/.ssh"
    install_if_changed "restrict,from=\"$WIT_CTL_L2\",command=\"/usr/local/sbin/witness-fault-ssh\" $key" \
      "$home/.ssh/authorized_keys" 0600 >/dev/null
    chown witness-fault:witness-fault "$home/.ssh/authorized_keys"
    log "fault agent: runner key authorized (from=$WIT_CTL_L2, forced command)"
  else
    warn "fault agent: no /etc/witness/runner_key.pub yet (run scripts/lab_vms.sh link)"
  fi
}

if [[ "$STAGE" == agent ]]; then ensure_fault_agent; exit 0; fi
ensure_packages "${WIT_PKGS_COMMON[@]}"
ensure_vsock_ssh
if [[ "$STAGE" == base ]]; then log "base stage complete"; exit 0; fi

ensure_sysctl
dev_addrs="$(device_rows | cut -f1 | sed "s|\$|/$WIT_DEV_PREFIX|" | paste -sd, - | sed 's/,/, /g')"
ensure_netplan "$WIT_FIELD_L2/$WIT_L2_PREFIX" "" "
  dummy-devices:
    $WIT_DEV_IF:
      link-local: []
      addresses: [$dev_addrs]"

ensure_chrony "# Managed by witness-lab provision_field.sh. chronyd is the ONLY clock writer on
# witness-field: it follows witness-ctl over lab0 (no internet NTP) and steps on any
# offset > 0.1 s (ctl itself is stepped to the macOS host by lima-guestagent).
server $WIT_CTL_L2 iburst minpoll 2 maxpoll 4
driftfile /var/lib/chrony/chrony.drift
makestep 0.1 -1
logdir /var/log/chrony" "-F 1"
ensure_guestagent_no_settime

ensure_isolation
ensure_resolved
ensure_stable_hostkeys
ensure_devices
ensure_fault_agent

log "summary: $(ip -br addr show dev "$WIT_LAB_IF" | tr -s ' ') | $(ip -br addr show dev "$WIT_DEV_IF" | tr -s ' ') | ip_forward=$(sysctl -n net.ipv4.ip_forward)"
log "provisioning complete; run scripts/preflight.sh --role field"
