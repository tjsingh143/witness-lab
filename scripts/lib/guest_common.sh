# shellcheck shell=bash
# Shared helpers for the Witness guest scripts (sourced, not executed).
# Every privileged script calls assert_lab_vm <role> before changing anything:
# Linux + VM + Ubuntu 24.04 arm64 + a lab interface whose MAC matches inventory.yaml.

WIT_REPO="${WIT_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
WIT_LAB_IF=lab0
WIT_STATE_DIR=/var/lib/witness
WIT_NFT_TABLE=witness_isolation   # inet table; lab fault tables use other names

log()  { echo "[$(basename "$0")] $*"; }
warn() { echo "[$(basename "$0")] WARN: $*" >&2; }
die()  { echo "[$(basename "$0")] ERROR: $*" >&2; exit 1; }

need_root() { [[ $EUID -eq 0 ]] || die "must run as root (sudo)"; }

load_inventory() {
  local py=python3
  command -v "$py" >/dev/null || die "python3 missing"
  local vars
  vars="$("$py" "$WIT_REPO/scripts/lib/inventory.py" shell "$WIT_REPO/inventory.yaml")" ||
    die "inventory.yaml failed validation"
  eval "$vars"
}

# assert_lab_vm ctl|field  -> sets WIT_ROLE, WIT_SELF_NAME, WIT_SELF_L2, WIT_PEER_L2
assert_lab_vm() {
  local role="$1" mac want_mac os
  [[ "$(uname -s)" == Linux ]] || die "not Linux; refusing (this never runs on the Mac)"
  [[ "$(systemd-detect-virt --vm 2>/dev/null || echo none)" != none ]] || die "not a VM; refusing"
  [[ "$(uname -m)" == aarch64 ]] || die "expected aarch64 guest"
  os="$(. /etc/os-release && echo "$ID $VERSION_ID")"
  [[ "$os" == "ubuntu 24.04" ]] || die "expected Ubuntu 24.04, got '$os'"
  load_inventory
  case "$role" in
    ctl)   WIT_SELF_NAME="$WIT_CTL_NAME";   want_mac="$WIT_CTL_MAC";   WIT_SELF_L2="$WIT_CTL_L2";   WIT_PEER_L2="$WIT_FIELD_L2" ;;
    field) WIT_SELF_NAME="$WIT_FIELD_NAME"; want_mac="$WIT_FIELD_MAC"; WIT_SELF_L2="$WIT_FIELD_L2"; WIT_PEER_L2="$WIT_CTL_L2" ;;
    *) die "unknown role '$role'" ;;
  esac
  [[ -e "/sys/class/net/$WIT_LAB_IF" ]] || die "lab interface $WIT_LAB_IF missing"
  mac="$(cat "/sys/class/net/$WIT_LAB_IF/address")"
  [[ "$mac" == "$want_mac" ]] || die "$WIT_LAB_IF MAC $mac != inventory $want_mac for $role; wrong VM?"
  # Lima sets the guest hostname to lima-<instance>.
  case "$(hostname)" in
    "$WIT_SELF_NAME"|"lima-$WIT_SELF_NAME") ;;
    *) die "hostname $(hostname) is not $WIT_SELF_NAME" ;;
  esac
  WIT_ROLE="$role"
  export WIT_ROLE WIT_SELF_NAME WIT_SELF_L2 WIT_PEER_L2
}

# Bounded command: run_t SECONDS cmd...
run_t() { local t="$1"; shift; timeout --kill-after=2 "$t" "$@"; }

# ---------------------------------------------------------------- provisioning
WIT_MGMT_IF=eth0                  # Lima's primary NIC (management + SSH fallback)
WIT_NETPLAN=/etc/netplan/60-witness.yaml
WIT_BACKUP_DIR="$WIT_STATE_DIR/backup"
# shellcheck disable=SC2034  # used by the provision scripts that source this file
WIT_PKGS_COMMON=(iproute2 nftables tcpdump curl netcat-openbsd chrony sqlite3 python3 python3-pytest python3-yaml)

# Install $1 to path $2 with mode $3 only if content differs. Prints "changed"/"same".
install_if_changed() {
  local content="$1" path="$2" mode="${3:-0644}"
  if [[ -f "$path" ]] && [[ "$(cat "$path")" == "$content" ]]; then
    chmod "$mode" "$path"; echo same; return 0
  fi
  mkdir -p "$(dirname "$path")"
  printf '%s\n' "$content" >"$path.witness.tmp" && chmod "$mode" "$path.witness.tmp" && mv "$path.witness.tmp" "$path"
  echo changed
}

# Back up a system file once (first provisioning) before replacing it.
backup_once() {
  local f="$1" b="$WIT_BACKUP_DIR${1}.orig"
  [[ -e "$f" && ! -e "$b" ]] || return 0
  mkdir -p "$(dirname "$b")"; cp -a "$f" "$b"; log "backed up $f -> $b" >&2
}

pkg_missing() {
  local p out=()
  for p in "$@"; do
    dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'install ok installed' || out+=("$p")
  done
  echo "${out[*]}"
}

mgmt_gateway() {
  # gvproxy's address on the management network, from systemd-networkd's DHCP lease.
  local idx f
  idx="$(cat "/sys/class/net/$WIT_MGMT_IF/ifindex")"
  f="/run/systemd/netif/leases/$idx"
  [[ -r "$f" ]] && sed -n 's/^ROUTER=\([0-9.]*\).*/\1/p' "$f" | head -1
}

# Temporary, bounded internet access for apt after isolation is in place.
_ONLINE_GW=""
online_end() {
  local h
  for h in $(nft -a list chain inet "$WIT_NFT_TABLE" output 2>/dev/null | sed -n 's/.*comment "witness-online-window" # handle \([0-9]*\)$/\1/p'); do
    nft delete rule inet "$WIT_NFT_TABLE" output handle "$h" || warn "could not delete online rule $h"
  done
  [[ -z "$_ONLINE_GW" ]] || ip route del default via "$_ONLINE_GW" dev "$WIT_MGMT_IF" metric 900 2>/dev/null || true
  resolvectl revert "$WIT_MGMT_IF" 2>/dev/null || true
  _ONLINE_GW=""
}
online_begin() {
  if ip route show default | grep -q .; then return 0; fi   # pre-isolation first run
  _ONLINE_GW="$(mgmt_gateway)"; [[ -n "$_ONLINE_GW" ]] || die "no DHCP router on $WIT_MGMT_IF; cannot open online window"
  trap online_end EXIT
  log "opening temporary online window via $_ONLINE_GW dev $WIT_MGMT_IF (removed on exit)"
  if nft list table inet "$WIT_NFT_TABLE" >/dev/null 2>&1; then
    nft insert rule inet "$WIT_NFT_TABLE" output oifname "$WIT_MGMT_IF" accept comment '"witness-online-window"'
  fi
  ip route add default via "$_ONLINE_GW" dev "$WIT_MGMT_IF" proto static metric 900
  resolvectl dns "$WIT_MGMT_IF" "$_ONLINE_GW"
}

ensure_packages() {
  local missing; missing="$(pkg_missing "$@")"
  if [[ -z "$missing" ]]; then log "packages present: $*"; return 0; fi
  log "installing: $missing"
  online_begin
  export DEBIAN_FRONTEND=noninteractive
  run_t 600 apt-get -o Acquire::http::Timeout=20 -o Acquire::Retries=2 update -q
  # shellcheck disable=SC2086
  run_t 900 apt-get -o Acquire::http::Timeout=20 install -y -q --no-install-recommends $missing
  online_end; trap - EXIT
  missing="$(pkg_missing "$@")"; [[ -z "$missing" ]] || die "still missing after install: $missing"
}

# OpenSSH on AF_VSOCK port 22, so `limactl shell` (Lima 2.x: SSH over vsock on vz)
# does not depend on guest IP networking. systemd 255 has no sshd-vsock generator.
ensure_vsock_ssh() {
  local a b
  a="$(install_if_changed '# Managed by witness-lab: SSH over AF_VSOCK (Lima management path)
[Unit]
Description=OpenSSH over AF_VSOCK port 22 (witness-lab rescue/management path)
[Socket]
ListenStream=vsock::22
Accept=yes
[Install]
WantedBy=sockets.target' /etc/systemd/system/witness-sshd-vsock.socket)"
  b="$(install_if_changed '# Managed by witness-lab
[Unit]
Description=OpenSSH per-connection server over AF_VSOCK
[Service]
ExecStart=-/usr/sbin/sshd -i
StandardInput=socket
StandardError=journal
RuntimeDirectory=sshd
RuntimeDirectoryPreserve=yes' /etc/systemd/system/witness-sshd-vsock@.service)"
  if [[ "$a$b" == *changed* ]]; then systemctl daemon-reload; fi
  systemctl enable --now witness-sshd-vsock.socket >/dev/null 2>&1 || die "cannot enable vsock ssh socket"
  log "vsock ssh socket: $(systemctl is-active witness-sshd-vsock.socket)"
}

# render_netplan "<lab0 addr/prefix>" "<extra lab0 yaml (routes)>" "<extra top-level yaml>"
ensure_netplan() {
  local lab_cidr="$1" lab_extra="$2" top_extra="$3" mgmt_mac lab_mac content r
  mgmt_mac="$(cat "/sys/class/net/$WIT_MGMT_IF/address")"
  lab_mac="$(cat "/sys/class/net/$WIT_LAB_IF/address")"
  [[ "$mgmt_mac" != "$lab_mac" ]] || die "mgmt and lab MAC identical"
  content="# Managed by witness-lab (scripts/lib/guest_common.sh). Replaces cloud-init's
# 50-cloud-init.yaml (backed up under $WIT_BACKUP_DIR). eth0 = management only:
# DHCP address kept for Lima's SSH fallback, but no routes/DNS/NTP from it.
network:
  version: 2
  renderer: networkd
  ethernets:
    $WIT_MGMT_IF:
      match: {macaddress: \"$mgmt_mac\"}
      set-name: $WIT_MGMT_IF
      dhcp4: true
      dhcp6: false
      accept-ra: false
      link-local: []
      dhcp-identifier: mac
      dhcp4-overrides: {use-routes: false, use-dns: false, use-ntp: false, use-domains: false}
    $WIT_LAB_IF:
      match: {macaddress: \"$lab_mac\"}
      set-name: $WIT_LAB_IF
      dhcp4: false
      dhcp6: false
      accept-ra: false
      link-local: []
      addresses: [$lab_cidr]${lab_extra}${top_extra}"
  backup_once /etc/netplan/50-cloud-init.yaml
  r="$(install_if_changed 'network: {config: disabled}' /etc/cloud/cloud.cfg.d/99-witness-disable-network-config.cfg)"
  [[ -e /etc/netplan/50-cloud-init.yaml ]] && { rm -f /etc/netplan/50-cloud-init.yaml; r=changed; }
  [[ "$(install_if_changed "$content" "$WIT_NETPLAN" 0600)" == changed ]] && r=changed
  if [[ "$r" == changed ]]; then
    run_t 30 netplan generate || die "netplan generate failed"
    log "applying netplan (management SSH may blip)"
    run_t 60 netplan apply || die "netplan apply failed"
  else
    log "netplan unchanged"
  fi
}

# Keep SSH host keys across reboots. OBSERVED (Phase 2): Lima presents a new cloud-init
# instance-id on every boot, so cloud-init's per-instance ssh module (ssh_deletekeys: true by
# default) regenerated the host keys at each boot and the runner's pinned known_hosts for
# witness-field failed closed ("REMOTE HOST IDENTIFICATION HAS CHANGED").
ensure_stable_hostkeys() {
  local r
  r="$(install_if_changed '# Managed by witness-lab: keep SSH host keys across Lima boots (new instance-id each boot).
ssh_deletekeys: false' /etc/cloud/cloud.cfg.d/99-witness-keep-ssh-hostkeys.cfg)"
  log "ssh host keys pinned across boots ($r): $(ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub | awk '{print $2}')"
}

ensure_resolved() {
  # No upstream DNS at all: lab names come only from /etc/hosts; unknown names fail fast.
  local r
  r="$(install_if_changed '# Managed by witness-lab: no DNS servers, no fallback, no LLMNR/mDNS.
[Resolve]
DNS=
FallbackDNS=
LLMNR=no
MulticastDNS=no' /etc/systemd/resolved.conf.d/60-witness.conf)"
  [[ "$r" == same ]] || systemctl restart systemd-resolved
}

ensure_sysctl() {
  local r
  r="$(install_if_changed "# Managed by witness-lab. Neither VM routes between interfaces: the device
# addresses are local to witness-field (dummy $WIT_DEV_IF), so forwarding is not needed.
# IPv6 is not disabled globally (ssh.socket listens on [::]:22); the NICs get no
# IPv6 addresses (netplan link-local: [], accept-ra: false) and nft drops v6 egress.
net.ipv4.ip_forward = 0" /etc/sysctl.d/60-witness.conf)"
  [[ "$r" == same ]] || sysctl -q -p /etc/sysctl.d/60-witness.conf
  sysctl -q net.ipv4.ip_forward=0 >/dev/null
}

# Egress isolation: only lab peers on lab0, DHCP on eth0, inbound SSH from gvproxy.
ensure_isolation() {
  local gw rules r
  gw="$(mgmt_gateway)"; [[ -n "$gw" ]] || die "no DHCP router on $WIT_MGMT_IF"
  rules="#!/usr/sbin/nft -f
# Managed by witness-lab. Replaces ONLY table inet $WIT_NFT_TABLE (never flush ruleset:
# Lima's own iptables-nft LIMADNS chain lives in table ip nat). Fail-closed egress.
table inet $WIT_NFT_TABLE {}
delete table inet $WIT_NFT_TABLE
table inet $WIT_NFT_TABLE {
  set lab_peers {
    type ipv4_addr; flags interval
    elements = { $WIT_CTL_L2, $WIT_FIELD_L2, $WIT_DEV_SUBNET }
  }
  chain output {
    type filter hook output priority filter; policy drop;
    oifname \"lo\" accept
    ct state established,related accept
    oifname \"$WIT_LAB_IF\" ip daddr @lab_peers accept
    oifname \"$WIT_MGMT_IF\" udp sport 68 udp dport 67 accept
    counter comment \"witness-isolation-egress-drop\"
  }
  chain input {
    type filter hook input priority filter; policy accept;
    iifname \"$WIT_MGMT_IF\" ct state established,related accept
    iifname \"$WIT_MGMT_IF\" ip saddr $gw tcp dport 22 accept
    iifname \"$WIT_MGMT_IF\" udp sport 67 udp dport 68 accept
    iifname \"$WIT_MGMT_IF\" counter drop comment \"witness-isolation-mgmt-ingress-drop\"
  }
}"
  r="$(install_if_changed "$rules" /etc/witness/isolation.nft 0644)"
  install_if_changed "# Managed by witness-lab
[Unit]
Description=Witness lab internet isolation (nft table inet $WIT_NFT_TABLE)
DefaultDependencies=no
Before=network-pre.target
Wants=network-pre.target
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f /etc/witness/isolation.nft
[Install]
WantedBy=multi-user.target" /etc/systemd/system/witness-isolation.service >/dev/null
  systemctl daemon-reload
  systemctl enable witness-isolation.service >/dev/null 2>&1
  nft -c -f /etc/witness/isolation.nft || die "isolation ruleset failed nft -c"
  if [[ "$r" == changed ]] || ! nft list table inet "$WIT_NFT_TABLE" >/dev/null 2>&1; then
    systemctl restart witness-isolation.service
  fi
  systemctl is-active -q witness-isolation.service || die "witness-isolation.service not active"
  log "isolation table inet $WIT_NFT_TABLE active (mgmt gw $gw)"
}

# "addr<TAB>hostname" per inventory device, in inventory order.
device_rows() {
  local id k a h
  for id in $WIT_DEVICE_IDS; do
    k="${id^^}"; k="${k//-/_}"; a="WIT_${k}_ADDR"; h="WIT_${k}_HOST"
    printf '%s\t%s\n' "${!a}" "${!h}"
  done
}

WIT_HOSTS_BEGIN="# BEGIN witness-lab (generated from inventory.yaml; edit there, not here)"
WIT_HOSTS_END="# END witness-lab"
hosts_block() { printf '%s\n%s\n%s\n' "$WIT_HOSTS_BEGIN" "$(device_rows)" "$WIT_HOSTS_END"; }

# Rewrite only the managed block of /etc/hosts (Lima's 06-etc-hosts.sh edits only
# its host.lima.internal line, so both coexist). Prints changed/same.
ensure_hosts() {
  local rest new
  # An exact, single managed block anywhere in the file is "same": Lima re-appends its
  # host.lima.internal line after it at every boot, so position must not matter.
  if [[ "$(grep -cxF "$WIT_HOSTS_BEGIN" /etc/hosts)" == 1 ]] &&
     [[ "$(awk -v b="$WIT_HOSTS_BEGIN" -v e="$WIT_HOSTS_END" '$0==b{s=1} s{print} $0==e{s=0}' /etc/hosts)" == "$(hosts_block)" ]]; then
    echo same; return 0
  fi
  rest="$(awk -v b="$WIT_HOSTS_BEGIN" -v e="$WIT_HOSTS_END" '$0==b{s=1;next} $0==e{s=0;next} !s' /etc/hosts)"
  new="$(printf '%s\n%s' "$rest" "$(hosts_block)")"
  backup_once /etc/hosts
  install_if_changed "$new" /etc/hosts 0644
}

# ---------------------------------------------------------------- lab state
WIT_FAULT_TABLE_PREFIX=witness_fault   # every lab fault nft table must use this prefix
# shellcheck disable=SC2034  # used by preflight.sh and reset_lab.sh
WIT_DEVICE_UNIT=/etc/systemd/system/witness-device@.service   # installed in Phase 2
# Transient dead-man timers armed while a fault is applied (field: witness-faultctl; ctl: runner F7).
# shellcheck disable=SC2034  # used by preflight.sh and reset_lab.sh
WIT_DEADMAN_FIELD=witness-fault-deadman
# shellcheck disable=SC2034
WIT_DEADMAN_CTL=witness-ctl-fault-deadman
# Fault qdiscs: netem/tbf (also as a child of the prio root the F6 fixture builds).
# shellcheck disable=SC2034  # used by preflight.sh and reset_lab.sh
WIT_FAULT_QDISC_RE='netem|tbf|prio'

# "family name" of every nft table named witness_fault*
fault_tables() { nft list tables 2>/dev/null | awk -v p="$WIT_FAULT_TABLE_PREFIX" '$1=="table" && index($3,p)==1 {print $2, $3}'; }

# Interfaces whose qdiscs the lab may change.
lab_ifaces() { if [[ "$WIT_ROLE" == field ]]; then echo "$WIT_LAB_IF $WIT_DEV_IF"; else echo "$WIT_LAB_IF"; fi; }

device_instances() {
  local id k i
  for id in $WIT_DEVICE_IDS; do k="${id^^}"; k="${k//-/_}"; i="WIT_${k}_INSTANCE"; echo "${!i}"; done
}

# Clock discipline: exactly ONE writer per clock, hierarchy macOS -> ctl -> field.
# OBSERVED (Lima 2.2.0, vz): lima-guestagent steps each guest clock to the macOS host
# (settimeofday, 10 s loop, only after ~100 ms drift; no Lima opt-out), and the two
# guest clocks run ~83 ppm apart. A chronyd that also steers fights it (19 steps in
# 5 min on witness-field), and chronyd -x offsets are modelled, not raw (~0 while the
# true offset was 25-35 ms). Therefore:
#   ctl:   lima-guestagent owns the clock; chronyd -x only SERVES it on lab0.
#   field: chronyd owns the clock, following ctl; lima-guestagent loses CAP_SYS_TIME.
# REQ-04's preflight gate uses scripts/lib/ntp_offset.py (raw SNTP), not chronyc.
WIT_GA_DROPIN=/etc/systemd/system/lima-guestagent.service.d/60-witness-no-settime.conf

# ensure_chrony CONF DAEMON_OPTS
ensure_chrony() {
  local conf="$1" opts="$2" r1 r2
  backup_once /etc/chrony/chrony.conf
  backup_once /etc/default/chrony
  r1="$(install_if_changed "$conf" /etc/chrony/chrony.conf)"
  r2="$(install_if_changed "# Managed by witness-lab (see Clock discipline in scripts/lib/guest_common.sh).
DAEMON_OPTS=\"$opts\"
SYNC_IN_CONTAINER=\"no\"" /etc/default/chrony)"
  systemctl enable chrony >/dev/null 2>&1
  if [[ "$r1$r2" == *changed* ]] || ! systemctl is-active -q chrony; then systemctl restart chrony; fi
  systemctl is-active -q chrony || die "chronyd failed to start"
}

# field only: lima-guestagent keeps running (Lima needs it) but cannot set the clock.
ensure_guestagent_no_settime() {
  local r
  r="$(install_if_changed "# Managed by witness-lab: chronyd (following witness-ctl) is the only clock writer
# on witness-field, so the Lima guest agent may not step the clock.
[Service]
CapabilityBoundingSet=~CAP_SYS_TIME" "$WIT_GA_DROPIN")"
  if [[ "$r" == changed ]] || guestagent_can_settime; then
    systemctl daemon-reload && systemctl restart lima-guestagent
  fi
  ! guestagent_can_settime || die "lima-guestagent still has CAP_SYS_TIME"
}

guestagent_can_settime() {
  local pid; pid="$(systemctl show -p MainPID --value lima-guestagent)"
  [[ -n "$pid" && "$pid" != 0 ]] || return 1
  # CapBnd bit 25 = CAP_SYS_TIME
  (( (0x$(awk '/^CapBnd/ {print $2}' "/proc/$pid/status") >> 25) & 1 ))
}

chrony_is_measure_only() {
  local pid; pid="$(systemctl show -p MainPID --value chrony 2>/dev/null)"
  [[ -n "$pid" && "$pid" != 0 ]] && tr '\0' ' ' <"/proc/$pid/cmdline" | grep -q -- ' -x'
}

# Raw SNTP offset (s) of witness-ctl's clock relative to this one; empty if no reply.
ctl_clock_offset() {
  python3 "$WIT_REPO/scripts/lib/ntp_offset.py" "$WIT_CTL_L2" --samples 4 --timeout 1 2>/dev/null |
    sed -n 's/^offset_s=\([-+0-9.]*\) .*/\1/p'
}
