#!/usr/bin/env bash
# Mac-side lifecycle for the two Witness Lima VMs. Uses a PRIVATE Lima home
# ($REPO/.lima.nosync, gitignored; ".nosync" keeps iCloud from uploading disks),
# so the user's ~/.lima instances and networks.yaml are never read or changed.
# Touches ONLY the instances named in inventory.yaml. Never changes host routes,
# host firewall or other VMs.
#
# Usage: scripts/lab_vms.sh up|status|sync|provision|link|preflight|smoke|route-demo|reset|reset-selftest|stop|destroy --yes
#        scripts/lab_vms.sh unit                        # compileall + unit tests inside witness-ctl
#        scripts/lab_vms.sh suite baseline|fault|all [pytest args]   # live suite ON witness-ctl
#        scripts/lab_vms.sh report | fetch              # Markdown report on ctl; copy results/ to the Mac
#        scripts/lab_vms.sh interrupt-selftest TERM|KILL [f2|f5] # kill the runner mid-fault (field SIGSTOP or
#                                                           # ctl route delete); prove the lab recovers
#        scripts/lab_vms.sh gw [inventory|devices/<id>]   # read the gateway API on witness-ctl (GET only)
#        scripts/lab_vms.sh mutant deploy M1..M6 | restore | run M1..M6 [reps]   # brief 7.4 mutant builds on dev-a
#                                                  (run notes prefixed with $WIT_RUN_TAG, default phase4)
#        scripts/lab_vms.sh golden-restore --yes        # fresh lab from the golden clones (deletes current lab VMs)
#        scripts/lab_vms.sh results-push                # Mac results/witness.db (+ evidence) -> ctl (fresh clones)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${WIT_PY:-$REPO/.venv/bin/python}"
export LIMA_HOME="${WIT_LIMA_HOME:-$REPO/.lima.nosync}"
LIMA_CFG="$LIMA_HOME/_config/networks.yaml"
GUEST_REPO=/opt/witness-lab
TIMEOUT_START=600

die() { echo "lab_vms: ERROR: $*" >&2; exit 1; }
log() { echo "lab_vms: $*"; }

[[ "$(uname -s)" == Darwin ]] || die "run on the macOS host"
command -v limactl >/dev/null || die "limactl not found (brew install lima)"
[[ -x "$PY" ]] || die "missing $PY; run: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt"
eval "$("$PY" "$REPO/scripts/lib/inventory.py" shell "$REPO/inventory.yaml")"

VMS=("$WIT_CTL_NAME" "$WIT_FIELD_NAME")
WIT_DEADMAN_CTL_UNIT=witness-ctl-fault-deadman

is_lab_vm() { [[ "$1" == "$WIT_CTL_NAME" || "$1" == "$WIT_FIELD_NAME" ]]; }
vm_status() { limactl list --format '{{.Status}}' "$1" 2>/dev/null || echo Absent; }
mac_of() { [[ "$1" == "$WIT_CTL_NAME" ]] && echo "$WIT_CTL_MAC" || echo "$WIT_FIELD_MAC"; }
gsh() { local vm="$1"; shift; is_lab_vm "$vm" || die "refusing non-lab VM $vm"; limactl shell --workdir / "$vm" -- "$@"; }

ensure_network() {
  # ensure_network NAME SUBNET: additive, via `limactl network create` (Lima >= 2.0) in
  # the private LIMA_HOME. Lima hands gvproxy only the derived --subnet (gvproxy then
  # takes .2 and leases from .1), so an existing entry is compared by subnet only.
  local name="$1" subnet="$2" got first
  got="$(limactl network list --json | "$PY" -c '
import ipaddress, json, sys
for line in sys.stdin:
    n = json.loads(line)
    if n["name"] == sys.argv[1]:
        print(n.get("mode"), ipaddress.ip_network("%s/%s" % (n.get("gateway"), n.get("netmask")), strict=False))' "$name")"
  first="$("$PY" -c "import ipaddress,sys;n=ipaddress.ip_network(sys.argv[1]);print(f'{n[1]}/{n.prefixlen}')" "$subnet")"
  if [[ -z "$got" ]]; then
    limactl network create "$name" --mode user-v2 --gateway "$first"
    log "created network '$name' ($subnet) in $LIMA_CFG"
  elif [[ "$got" == "user-v2 $subnet" ]]; then
    log "network '$name' present ($got)"
  else
    die "network '$name' exists but differs: '$got' != 'user-v2 $subnet'"
  fi
}

render() {
  local vm="$1" out="$2"
  sed -e "s/@NAME@/$vm/g" -e "s/@MAC@/$(mac_of "$vm")/g" -e "s/@NETWORK@/$WIT_LIMA_NETWORK/g" \
    -e "s/@MGMT_NETWORK@/$WIT_MGMT_NETWORK/g" "$REPO/config/lima/witness-vm.yaml.tmpl" >"$out"
}

cmd_up() {
  ensure_network "$WIT_MGMT_NETWORK" "$WIT_MGMT_SUBNET"
  ensure_network "$WIT_LIMA_NETWORK" "$WIT_L2_SUBNET"
  # the RETURN trap must clear itself: otherwise it stays set and fires (with $tmp unbound) when the CALLER
  # returns (observed: golden-restore exited 1 after a successful restore)
  local tmp; tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"; trap - RETURN' RETURN
  for vm in "${VMS[@]}"; do
    case "$(vm_status "$vm")" in
      Running) log "$vm already running" ;;
      Stopped) log "starting $vm"; limactl start --timeout "${TIMEOUT_START}s" "$vm" ;;
      Absent|"")
        render "$vm" "$tmp/$vm.yaml"
        limactl validate "$tmp/$vm.yaml"
        log "creating $vm"
        limactl create --name "$vm" --tty=false "$tmp/$vm.yaml"
        limactl start --timeout "${TIMEOUT_START}s" "$vm" ;;
      *) die "$vm in unexpected state $(vm_status "$vm")" ;;
    esac
  done
  cmd_status
}

cmd_status() {
  for vm in "${VMS[@]}"; do
    printf '%-14s %s ssh=%s\n' "$vm" "$(vm_status "$vm")" "$(ssh_mode "$vm")"
    if [[ "$(vm_status "$vm")" == Running ]]; then
      # shellcheck disable=SC2016  # expanded in the guest
      gsh "$vm" sh -c 'echo "  host=$(hostname) kernel=$(uname -r)"; ip -br addr 2>/dev/null | grep -v "^lo " | sed "s/^/  /"'
    fi
  done
}

cmd_sync() {
  # Copy the working tree (no .git, .venv, results, VM disks) to /opt/witness-lab.
  for vm in "${VMS[@]}"; do
    [[ "$(vm_status "$vm")" == Running ]] || die "$vm not running"
    COPYFILE_DISABLE=1 tar -C "$REPO" --exclude .git --exclude .venv --exclude results --exclude .lima.nosync --exclude .claude \
      --exclude '__pycache__' --exclude '*.qcow2' --exclude '*.img' -cf - . |
      gsh "$vm" sudo sh -c "rm -rf $GUEST_REPO.new && mkdir -p $GUEST_REPO.new && tar -xf - -C $GUEST_REPO.new --no-same-owner 2>/dev/null; rm -rf $GUEST_REPO && mv $GUEST_REPO.new $GUEST_REPO"
    # Provenance for REQ-10 (the guest copy has no .git): commit, dirty flag, Lima version.
    # results/ is excluded from the dirty check because it is never synced to the guests.
    printf 'git_sha=%s\ngit_dirty=%s\nsynced_at=%s\nlima=%s\n' \
      "$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo unknown)" \
      "$([[ -n "$(git -C "$REPO" status --porcelain -- . ':!results' 2>/dev/null)" ]] && echo 1 || echo 0)" \
      "$(date -u +%FT%TZ)" "$(limactl --version 2>/dev/null)" |
      gsh "$vm" sudo sh -c "cat > $GUEST_REPO/.witness-source"
    log "synced repo to $vm:$GUEST_REPO ($(gsh "$vm" sh -c "find $GUEST_REPO -type f | wc -l") files)"
  done
}

# Runner key: public half of ctl's key -> field's fault agent (forced command), and
# field's host key -> ctl's known_hosts. Only public keys pass through the Mac.
cmd_link() {
  local pub hk
  pub="$(gsh "$WIT_CTL_NAME" sudo cat /var/lib/witness/runner/id_ed25519.pub)"
  [[ "$pub" == "ssh-ed25519 "* ]] || die "ctl runner key missing; run provision first"
  printf '%s\n' "$pub" | gsh "$WIT_FIELD_NAME" sudo sh -c "umask 022; cat > /etc/witness/runner_key.pub"
  gsh "$WIT_FIELD_NAME" sudo bash "$GUEST_REPO/scripts/provision_field.sh" --stage agent
  hk="$(gsh "$WIT_FIELD_NAME" sudo cat /etc/ssh/ssh_host_ed25519_key.pub | awk '{print $1, $2}')"
  printf '%s %s\n' "$WIT_FIELD_L2" "$hk" |
    gsh "$WIT_CTL_NAME" sudo sh -c "umask 022; cat > /var/lib/witness/runner/known_hosts"
  gsh "$WIT_CTL_NAME" sudo ssh -i /var/lib/witness/runner/id_ed25519 -o BatchMode=yes -o ConnectTimeout=3 \
    -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/var/lib/witness/runner/known_hosts \
    "witness-fault@$WIT_FIELD_L2" status || die "runner -> fault agent check failed"
  echo
  log "runner on $WIT_CTL_NAME reaches witness-faultctl on $WIT_FIELD_NAME over lab0"
}

cmd_unit() {
  gsh "$WIT_CTL_NAME" sh -c "cd $GUEST_REPO && export PYTHONPYCACHEPREFIX=/tmp/witness-pyc-\$(id -u) && python3 -m compileall -q device gateway runner scripts tests &&
    python3 -m pytest -q -p no:cacheprovider tests/unit tests/test_inventory.py"
}

# Live suite on witness-ctl (root: tcpdump, /etc/hosts for F7). Syncs first so the code
# under test is the working tree recorded in .witness-source.
cmd_suite() {
  local kind="${1:-}" sel=""
  shift || true
  case "$kind" in
    baseline) sel="-m commissioning" ;;
    fault) sel="-m fault" ;;
    all) sel="" ;;
    *) die "usage: lab_vms.sh suite baseline|fault|all [pytest args]" ;;
  esac
  local extra=""
  [[ $# -gt 0 ]] && extra="$(printf '%q ' "$@")"   # keep "--run-notes 'a b'" one argument
  cmd_sync >/dev/null
  gsh "$WIT_CTL_NAME" sudo sh -c "cd $GUEST_REPO && timeout --kill-after=10 1200 python3 -m pytest tests/live --live \
    -p no:cacheprovider -rA $sel $extra"
}

cmd_report() {
  cmd_sync >/dev/null
  gsh "$WIT_CTL_NAME" sudo sh -c "cd $GUEST_REPO && python3 -m runner.report --db /var/lib/witness/results/witness.db \
    --out-dir /var/lib/witness/results/reports && python3 -m runner.analysis --db /var/lib/witness/results/witness.db"
}

# Start the F2 (SIGSTOP) fault case, wait until witness-faultctl reports the fault active,
# then signal the runner. TERM: the fixtures' finally must revert. KILL: no Python cleanup
# runs, so the field dead-man timer (90 s) must revert. Either way preflight must end GREEN.
# f5: same proof for a witness-ctl fault: the runner is killed while the device route is deleted
# (GW-F5 case); the in-guest watcher signals within 50 ms of the deletion, and either the fixture
# (TERM) or the ctl dead-man timer running reset_lab.sh --role ctl (KILL) must restore the route.
interrupt_selftest_f5() {
  local sig="$1" rc=0 i r limit=10
  cmd_sync >/dev/null
  gsh "$WIT_CTL_NAME" sudo bash -c "cd $GUEST_REPO && (timeout 300 python3 -m pytest tests/live --live -p no:cacheprovider -m fault \
      -k test_gateway_detects_route_loss --run-notes 'interrupt-selftest $sig f5' > /tmp/witness-interrupt.log 2>&1 &)
    for i in \$(seq 1 1200); do [[ -z \"\$(ip -4 route show $WIT_DEV_SUBNET)\" ]] && break; sleep 0.05; done
    [[ -z \"\$(ip -4 route show $WIT_DEV_SUBNET)\" ]] || { echo 'route never deleted'; exit 1; }
    echo \"\$(date -u +%FT%T.%3NZ) route deleted; ip route get: \$(ip -4 route get $WIT_DEV_A_ADDR 2>&1); dead-man \$(systemctl is-active $WIT_DEADMAN_CTL_UNIT.timer)\"
    pkill -$sig -f '^python3 -m pytest tests/live'
    echo \"\$(date -u +%FT%T.%3NZ) sent SIG$sig to the runner\"" || return 1
  if [[ "$sig" == KILL ]]; then limit=120; fi
  # a TERMed runner is still unwinding (revert, postflight): never start checks or a next run under it
  # shellcheck disable=SC2016  # expanded in the guest
  gsh "$WIT_CTL_NAME" sh -c 'for i in $(seq 1 120); do pgrep -f "^python3 -m pytest tests/live" >/dev/null || exit 0; sleep 0.5; done; exit 1' ||
    log "runner still running after 60 s"
  for i in $(seq 1 "$limit"); do
    # `systemctl is-active` exits 3/4 for an inactive/collected unit: not an error here
    r="$(gsh "$WIT_CTL_NAME" sh -c "ip -4 route show $WIT_DEV_SUBNET; systemctl is-active $WIT_DEADMAN_CTL_UNIT.timer || true" 2>/dev/null | paste -sd'|' -)"
    [[ "$r" == "$WIT_DEV_SUBNET via $WIT_FIELD_L2 dev lab0"*"|inactive" ]] && break
    sleep 1
  done
  log "$(date -u +%FT%TZ) after ~${i}s: route+dead-man = $r"
  [[ "$r" == "$WIT_DEV_SUBNET via $WIT_FIELD_L2 dev lab0"*"|inactive" ]] || { log "route NOT restored"; rc=1; }
  gsh "$WIT_CTL_NAME" sudo sh -c "tail -n 8 /tmp/witness-interrupt.log; journalctl -u $WIT_DEADMAN_CTL_UNIT --since -5min --no-pager -o short-iso-precise | tail -8"
  # the killed runner's field-side capture expires by RuntimeMaxSec (120 s from its start): wait for full GREEN
  for i in $(seq 1 60); do cmd_preflight >/dev/null && break; sleep 2; done
  cmd_preflight >/dev/null && log "$(date -u +%FT%TZ) preflight GREEN after SIG$sig (f5)" || { log "preflight RED after SIG$sig (f5)"; rc=1; }
  return "$rc"
}

cmd_interrupt_selftest() {
  local sig="${1:-}" st i rc=0 limit
  [[ "$sig" == TERM || "$sig" == KILL ]] || die "usage: lab_vms.sh interrupt-selftest TERM|KILL [f2|f5]"
  [[ "${2:-f2}" == f5 ]] && { interrupt_selftest_f5 "$sig"; return; }
  [[ "${2:-f2}" == f2 ]] || die "usage: lab_vms.sh interrupt-selftest TERM|KILL [f2|f5]"
  local fc=(ssh -i /var/lib/witness/runner/id_ed25519 -o BatchMode=yes
            -o UserKnownHostsFile=/var/lib/witness/runner/known_hosts "witness-fault@$WIT_FIELD_L2")
  cmd_sync >/dev/null
  gsh "$WIT_CTL_NAME" sudo sh -c "cd $GUEST_REPO && timeout 300 python3 -m pytest tests/live --live -p no:cacheprovider -m fault \
    -k f2_sigstop --run-notes 'interrupt-selftest $sig' > /tmp/witness-interrupt.log 2>&1" &
  local bg=$!
  for i in $(seq 1 120); do
    st="$(gsh "$WIT_CTL_NAME" sudo "${fc[@]}" status 2>/dev/null || true)"
    [[ "$st" == *'"sigstop:'* ]] && break
    sleep 0.5
  done
  [[ "$st" == *'"sigstop:'* ]] || { wait "$bg"; die "fault never became active: $st"; }
  log "$(date -u +%FT%T.%3NZ 2>/dev/null || date -u +%FT%TZ) fault active on $WIT_FIELD_NAME: $st"
  gsh "$WIT_CTL_NAME" sudo pkill "-$sig" -f "^python3 -m pytest tests/live" || true   # the runner only
  log "$(date -u +%FT%TZ) sent SIG$sig to the runner on $WIT_CTL_NAME"
  wait "$bg" || true
  gsh "$WIT_CTL_NAME" sudo tail -n 15 /tmp/witness-interrupt.log || true
  limit=10; [[ "$sig" == KILL ]] && limit=120
  for i in $(seq 1 "$limit"); do
    st="$(gsh "$WIT_CTL_NAME" sudo "${fc[@]}" status 2>/dev/null || true)"
    [[ "$st" == *'"active_faults": []'*'"deadman_armed": false'* ]] && break
    sleep 1
  done
  log "$(date -u +%FT%TZ) after ${i}s: $st"
  [[ "$st" == *'"active_faults": []'*'"deadman_armed": false'* ]] || { log "lab NOT recovered"; rc=1; }
  gsh "$WIT_FIELD_NAME" sudo tail -n 6 /var/lib/witness/faultctl.log
  cmd_preflight >/dev/null && log "preflight GREEN after SIG$sig" || { log "preflight RED after SIG$sig"; rc=1; }
  return "$rc"
}

cmd_gw() {
  local path="${1:-inventory}"
  [[ "$path" =~ ^(inventory|devices/[a-z0-9-]{1,32})$ ]] || die "usage: lab_vms.sh gw [inventory|devices/<id>]"
  gsh "$WIT_CTL_NAME" curl -s -m 3 "http://127.0.0.1:8080/$path"
  echo
}

db_max_run() {   # db_max_run mac|ctl -> highest run_id in that copy of the results DB (0 if none)
  if [[ "$1" == mac ]]; then
    [[ -f "$REPO/results/witness.db" ]] && sqlite3 "$REPO/results/witness.db" 'SELECT coalesce(max(run_id),0) FROM runs' || echo 0
  else
    gsh "$WIT_CTL_NAME" sudo sh -c "test -f /var/lib/witness/results/witness.db && sqlite3 /var/lib/witness/results/witness.db 'SELECT coalesce(max(run_id),0) FROM runs' || echo 0"
  fi
}

cmd_fetch() {
  mkdir -p "$REPO/results"
  local mac ctl
  mac="$(db_max_run mac)"; ctl="$(db_max_run ctl)"
  # A freshly restored golden clone carries an OLD results DB: never let it overwrite the master copy.
  (( ctl >= mac )) || die "ctl results DB is older (max run $ctl) than the Mac copy (max run $mac); run results-push first"
  [[ -f "$REPO/results/witness.db" ]] && cp -p "$REPO/results/witness.db" "$REPO/results/witness-backup-before-fetch.db"
  gsh "$WIT_CTL_NAME" sudo tar -C /var/lib/witness/results -cf - . | tar -C "$REPO/results" -xf -
  log "fetched witness-ctl:/var/lib/witness/results -> $REPO/results ($(du -sh "$REPO/results" | cut -f1))"
}

# Copy the Mac's master results DB and evidence into ctl (after a golden restore the clone holds an old
# DB, and new run ids must continue the master sequence). Refuses to replace a NEWER ctl DB; the ctl
# copy it replaces is kept as witness.db.replaced-<UTC>.
cmd_results_push() {
  local mac ctl ts
  mac="$(db_max_run mac)"; ctl="$(db_max_run ctl)"
  (( mac > 0 )) || die "no Mac results DB to push"
  (( mac >= ctl )) || die "ctl DB has newer runs (max $ctl) than the Mac copy (max $mac); fetch first"
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  gsh "$WIT_CTL_NAME" sudo sh -c "mkdir -p /var/lib/witness/results/evidence && cd /var/lib/witness/results &&
    { [ ! -f witness.db ] || mv witness.db witness.db.replaced-$ts; }"
  COPYFILE_DISABLE=1 tar --no-xattrs --no-mac-metadata -C "$REPO/results" -cf - witness.db evidence |
    gsh "$WIT_CTL_NAME" sudo tar -C /var/lib/witness/results -xf - --no-same-owner
  log "pushed Mac results (max run $mac) to $WIT_CTL_NAME (its old DB, max run $ctl, kept as witness.db.replaced-$ts)"
}

# Mutants (brief 7.4): witness-faultctl deploys the build on the inventory's mutant device (catalog
# MUTANT_DEVICE) as a runtime systemd drop-in; `run` = deploy -> commissioning suite declared as that
# mutant (run kind=mutant) -> restore stock -> verify (preflight GREEN), restoring even on failure.
mutant_info() {   # mutant_info ID -> "<instance> <spec>"
  (cd "$REPO" && "$PY" -c 'import sys
from runner import catalog
from scripts.lib import inventory
inv = inventory.load("inventory.yaml")
d = next(x for x in inv["devices"] if x["device_id"] == catalog.MUTANT_DEVICE)
print(d["instance"], catalog.mutant_spec(sys.argv[1], inv["devices"]))' "$1") || die "unknown mutant '$1' (M1..M6)"
}

cmd_mutant() {
  local action="${1:-}" id="${2:-}" reps="${3:-1}" inst spec rc=0 k
  inst="$(mutant_info M2 | cut -d' ' -f1)"
  case "$action" in
    deploy)
      read -r inst spec <<<"$(mutant_info "$id")"
      gsh "$WIT_FIELD_NAME" sudo witness-faultctl mutant deploy "$inst" "$spec"; echo ;;
    restore)
      gsh "$WIT_FIELD_NAME" sudo witness-faultctl mutant restore "$inst"; echo ;;
    run)
      read -r inst spec <<<"$(mutant_info "$id")"
      [[ "$reps" =~ ^[1-9]$ ]] || die "reps must be 1-9"
      for k in $(seq 1 "$reps"); do
        # never deploy into a dirty lab: a RED precheck mid-run triggers a reset, which removes the mutant
        # under test (run 110: a field capture left by a SIGKILL self-test)
        cmd_preflight >/dev/null || { log "preflight RED before deploying mutant $id: refusing (fix the lab first)"; rc=1; break; }
        trap 'gsh "$WIT_FIELD_NAME" sudo witness-faultctl mutant restore "$inst" >/dev/null 2>&1 || true' EXIT
        log "$(date -u +%FT%TZ) mutant $id ($spec) on instance $inst: deploy (rep $k/$reps)"
        gsh "$WIT_FIELD_NAME" sudo witness-faultctl mutant deploy "$inst" "$spec" || { rc=1; break; }
        echo
        cmd_suite baseline --mutant "$id" --run-notes "${WIT_RUN_TAG:-phase4} mutant $id ($spec) rep $k/$reps" || log "suite rc=$? (non-zero = some case failed: expected when the mutant is caught)"
        log "$(date -u +%FT%TZ) mutant $id: restore stock build"
        gsh "$WIT_FIELD_NAME" sudo witness-faultctl mutant restore "$inst" || rc=1
        echo
        trap - EXIT
        cmd_preflight >/dev/null && log "preflight GREEN after restoring stock (mutant $id rep $k)" ||
          { log "preflight RED after restoring stock (mutant $id rep $k)"; rc=1; break; }
      done
      return "$rc" ;;
    *) die "usage: lab_vms.sh mutant deploy M1..M6 | restore | run M1..M6 [reps]" ;;
  esac
}

# Fresh lab from the golden clones (brief 7.3): stop and DELETE the current lab instances (limactl refuses a
# protected one), clone each <name>-golden to <name>, start, and write a provenance record in both guests
# (the runner stores it per run as provenance.<vm>, so SQL can tell fresh-clone runs from long-lived VMs).
# Afterwards: `provision` (current code), `results-push`, then preflight/suites.
cmd_golden_restore() {
  [[ "${1:-}" == --yes ]] || die "golden-restore deletes the current lab VMs; rerun with --yes"
  local vm id src
  for vm in "${VMS[@]}"; do [[ "$(vm_status "$vm-golden")" == Stopped ]] || die "$vm-golden missing or not stopped"; done
  for vm in "${VMS[@]}"; do
    [[ "$(vm_status "$vm")" == Running ]] && limactl stop "$vm"
    [[ "$(vm_status "$vm")" == Absent ]] || limactl delete "$vm" || die "could not delete $vm (protected?)"
  done
  for vm in "${VMS[@]}"; do limactl clone "$vm-golden" "$vm" --tty=false >/dev/null; log "cloned $vm-golden -> $vm"; done
  cmd_up >/dev/null
  id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
  for vm in "${VMS[@]}"; do
    src="$(gsh "$vm" sh -c "grep -h '^git_sha=' $GUEST_REPO/.witness-source 2>/dev/null | cut -d= -f2" || true)"
    printf 'golden-restore id=%s from=%s-golden golden_code=%s restored_at=%s\n' "$id" "$vm" "${src:-unknown}" "$(date -u +%FT%TZ)" |
      gsh "$vm" sudo sh -c "umask 022; mkdir -p /var/lib/witness && cat > /var/lib/witness/provenance"
    log "$vm: $(gsh "$vm" cat /var/lib/witness/provenance)"
  done
  cmd_status
}

# vsock = Lima reported SSH over AF_VSOCK at the latest start; usernet = gvproxy forwarder.
ssh_mode() {
  local f="$LIMA_HOME/$1/ha.stderr.log"
  grep -o 'Detected SSH server is listening on the vsock port\|SSH server does not seem to be running on vsock port' "$f" 2>/dev/null |
    tail -1 | grep -q Detected && echo vsock || echo usernet
}

restart_vm() { limactl stop "$1" >/dev/null && limactl start --timeout "${TIMEOUT_START}s" "$1" >/dev/null; }

cmd_provision() {
  cmd_sync
  # Stage base (packages + vsock sshd) touches no network config. Restart any VM still
  # using the gvproxy SSH forwarder so management moves to vsock BEFORE lab networking
  # and isolation change. Field first: ctl's route and chrony checks depend on it.
  local vm role
  for vm in "$WIT_FIELD_NAME" "$WIT_CTL_NAME"; do
    role=field; [[ "$vm" == "$WIT_CTL_NAME" ]] && role=ctl
    gsh "$vm" sudo bash "$GUEST_REPO/scripts/provision_$role.sh" --stage base
    if [[ "$(ssh_mode "$vm")" != vsock ]]; then
      log "$vm: restarting so Lima detects SSH over vsock"
      restart_vm "$vm"
      [[ "$(ssh_mode "$vm")" == vsock ]] || die "$vm: Lima still not using vsock SSH; refusing to change networking"
    fi
    log "$vm: management SSH over $(ssh_mode "$vm")"
  done
  for vm in "$WIT_FIELD_NAME" "$WIT_CTL_NAME"; do
    role=field; [[ "$vm" == "$WIT_CTL_NAME" ]] && role=ctl
    gsh "$vm" sudo bash "$GUEST_REPO/scripts/provision_$role.sh" --stage all
  done
  cmd_link
}

cmd_preflight() {
  local rc=0
  gsh "$WIT_FIELD_NAME" sudo bash "$GUEST_REPO/scripts/preflight.sh" --role field || rc=1
  gsh "$WIT_CTL_NAME" sudo bash "$GUEST_REPO/scripts/preflight.sh" --role ctl || rc=1
  return "$rc"
}

cmd_smoke() {
  local rc=0
  cmd_sync
  cmd_preflight || rc=1
  gsh "$WIT_FIELD_NAME" sudo bash "$GUEST_REPO/scripts/lab-smoke.sh" --role field || rc=1
  gsh "$WIT_CTL_NAME" sudo bash "$GUEST_REPO/scripts/lab-smoke.sh" --role ctl || rc=1
  return "$rc"
}

cmd_reset() {
  local rc=0
  gsh "$WIT_FIELD_NAME" sudo bash "$GUEST_REPO/scripts/reset_lab.sh" --role field "$@" || rc=1
  gsh "$WIT_CTL_NAME" sudo bash "$GUEST_REPO/scripts/reset_lab.sh" --role ctl "$@" || rc=1
  return "$rc"
}

# Prove reset_lab.sh reverts injected lab state: inject small faults on the
# identity-checked lab VMs only, require preflight RED, reset, require preflight GREEN.
cmd_reset_selftest() {
  local rc=0 fld ctl
  fld="source $GUEST_REPO/scripts/lib/guest_common.sh && assert_lab_vm field && set -x &&
    nft add table ip witness_fault_selftest &&
    tc qdisc add dev field0 root netem delay 5ms &&
    tc qdisc add dev lab0 root handle 1: prio bands 4 && tc qdisc add dev lab0 parent 1:4 netem delay 5ms &&
    systemctl kill -s STOP --kill-whom=main witness-device@${WIT_DEV_A_INSTANCE} &&
    install -d -m 0755 /run/witness-fault && printf 'malformed\\n' > /run/witness-fault/device-${WIT_DEV_B_INSTANCE}.mode &&
    systemctl kill -s HUP --kill-whom=main witness-device@${WIT_DEV_B_INSTANCE} &&
    ip addr del ${WIT_DEV_B_ADDR}/$WIT_DEV_PREFIX dev field0"
  ctl="source $GUEST_REPO/scripts/lib/guest_common.sh && assert_lab_vm ctl && set -x &&
    nft add table inet witness_fault_selftest &&
    tc qdisc add dev lab0 root netem delay 5ms &&
    ip route del $WIT_DEV_SUBNET &&
    sed -i 's/^${WIT_DEV_A_ADDR}\t${WIT_DEV_A_HOST}$/${WIT_DEV_B_ADDR}\t${WIT_DEV_A_HOST}/' /etc/hosts"
  trap 'cmd_reset >/dev/null 2>&1 || true' EXIT
  log "inject on $WIT_FIELD_NAME"; gsh "$WIT_FIELD_NAME" sudo bash -c "$fld" || rc=1
  log "inject on $WIT_CTL_NAME"; gsh "$WIT_CTL_NAME" sudo bash -c "$ctl" || rc=1
  if cmd_preflight; then log "UNEXPECTED: preflight GREEN with faults injected"; rc=1; else log "preflight RED with faults injected (required)"; fi
  cmd_reset || rc=1
  trap - EXIT
  if cmd_preflight; then log "preflight GREEN after reset (required)"; else log "preflight still RED after reset"; rc=1; fi
  return "$rc"
}

# Remove the ctl device route, prove management (fresh vsock SSH sessions to both VMs)
# still works while devices are unreachable, then restore. The guest also arms a
# 120 s dead-man timer, and the trap restores the route if this script fails.
cmd_route_demo() {
  local rc=0
  trap 'gsh "$WIT_CTL_NAME" sudo bash "$GUEST_REPO/scripts/lab-smoke.sh" --role ctl --route-demo restore >/dev/null 2>&1 || true' EXIT
  gsh "$WIT_CTL_NAME" sudo bash "$GUEST_REPO/scripts/lab-smoke.sh" --role ctl --route-demo remove || rc=1
  for vm in "${VMS[@]}"; do
    # shellcheck disable=SC2016  # expanded in the guest
    if out="$(gsh "$vm" sh -c 'echo "$(hostname) up=$(cut -d. -f1 /proc/uptime)s"; ip -4 route show '"$WIT_DEV_SUBNET")"; then
      log "management session to $vm OK during route removal (ssh=$(ssh_mode "$vm")): $(echo "$out" | paste -sd' ' -)"
    else
      log "management session to $vm FAILED during route removal"; rc=1
    fi
  done
  gsh "$WIT_CTL_NAME" sudo bash "$GUEST_REPO/scripts/lab-smoke.sh" --role ctl --route-demo restore || rc=1
  trap - EXIT
  gsh "$WIT_CTL_NAME" sudo bash "$GUEST_REPO/scripts/preflight.sh" --role ctl >/dev/null && log "ctl preflight GREEN after restore" || { log "ctl preflight RED after restore"; rc=1; }
  return "$rc"
}

cmd_stop() { for vm in "${VMS[@]}"; do [[ "$(vm_status "$vm")" == Running ]] && limactl stop "$vm"; done; cmd_status; }

cmd_destroy() {
  [[ "${1:-}" == --yes ]] || die "destroy deletes both lab VM disks; rerun with --yes"
  for vm in "${VMS[@]}"; do
    is_lab_vm "$vm" || die "refusing $vm"
    [[ "$(vm_status "$vm")" == Absent ]] || limactl delete --force "$vm"
  done
}

case "${1:-}" in
  up) cmd_up ;;
  status) cmd_status ;;
  sync) cmd_sync ;;
  provision) shift; cmd_provision "$@" ;;
  link) cmd_link ;;
  unit) cmd_unit ;;
  suite) shift; cmd_suite "$@" ;;
  report) shift; cmd_report "$@" ;;
  fetch) cmd_fetch ;;
  gw) shift; cmd_gw "$@" ;;
  mutant) shift; cmd_mutant "$@" ;;
  golden-restore) shift; cmd_golden_restore "$@" ;;
  results-push) cmd_results_push ;;
  interrupt-selftest) shift; cmd_interrupt_selftest "$@" ;;
  preflight) cmd_preflight ;;
  smoke) cmd_smoke ;;
  route-demo) cmd_route_demo ;;
  reset) shift; cmd_reset "$@" ;;
  reset-selftest) cmd_reset_selftest ;;
  stop) cmd_stop ;;
  destroy) shift; cmd_destroy "$@" ;;
  *) sed -n '2,17p' "$0"; exit 2 ;;
esac
