# Witness lab record

Everything below was **observed on the running VMs** (captures under `results/logs/`,
mainly `phase1-lab-record-capture-20261017T050052Z.log` and
`phase1-final-verification-20261017T045754Z.log`). If the VMs are rebuilt, re-run
`scripts/lab_vms.sh status` and `scripts/lab_vms.sh smoke`, and update this file from their output.

Scope statement: software simulation over real VM-to-VM network traffic. No physical
hardware, no embedded firmware.

## 1. Host and hypervisor

| Item | Value (observed 2026-10-17 UTC) |
|---|---|
| Host | macOS 26.5.1 (25F80), Apple Silicon arm64, 8 GiB RAM |
| Hypervisor | **Lima 2.2.0**, `vmType: vz` (Apple Virtualization.framework). UTM is not installed; the brief §11 names Lima as the fallback. |
| Lima home | **private** `$REPO/.lima.nosync` (gitignored). The user's `~/.lima` (instance `vigil`, `networks.yaml` sha1 `525600ff…`) was never modified. |
| Guest image | `ubuntu-24.04-server-cloudimg-arm64.img` release-20260705, sha256 `7df02015…c39cc` (Lima template `_images/ubuntu-24.04`) |
| Host-side processes | two `limactl usernet` (gvproxy) processes, one per Lima network, userspace only; **no host routes, interfaces or firewall rules are added** (`netstat -rn` has no 10.77.x entries) |

## 2. VMs

| | VM-A | VM-B |
|---|---|---|
| Lima instance | `witness-ctl` | `witness-field` |
| Guest hostname | `lima-witness-ctl` | `lima-witness-field` |
| OS / kernel | Ubuntu 24.04.4 LTS aarch64, 6.8.0-134-generic | same |
| CPU / RAM / disk | 1 vCPU / 1 GiB / 10 GiB | same |
| Role | gateway, runner, SQLite (Phase 2+) | device processes, faults (Phase 2+) |

## 3. Networks and interfaces

Two Lima **user-v2** networks (gvproxy L2 switches), both created in the private Lima home
by `scripts/lab_vms.sh up` (`limactl network create … --mode user-v2`).

| Lima network | Subnet | Guest NIC | Purpose |
|---|---|---|---|
| `witness-mgmt` | 10.77.0.0/24 | `eth0` (Lima-derived MAC, DHCP) | management only: Lima's SSH **fallback** forwarder. No routes or DNS taken from DHCP. |
| `witness` | 10.77.1.0/24 | `lab0` (pinned MAC, static) | the lab L2 segment: all VM-to-VM lab traffic |
| (none: dummy) | 10.77.2.0/24 | `field0` on witness-field | device addresses, reached from ctl only by routing via witness-field |

**Observed Lima/gvproxy behaviour (why the design looks like this):**
- Lima passes gvproxy only `--subnet`. gvproxy takes **.2** as its own address and
  leases DHCP from **.1**, so the `gateway` you give `limactl network create` is ignored.
  gvproxy's leases API (`curl --unix-socket .lima.nosync/_networks/<net>/<net>_ep.sock http://lima/services/dhcp/leases`)
  showed `10.77.1.2 → 5a:94:ef:e4:0c:dd` (gvproxy itself).
- The **first** user-v2 network in an instance becomes guest `eth0`, with a Lima-derived MAC
  (deterministic per instance name), and `macAddress`/`interface` are ignored for it.
  On the second NIC both are honoured, which is why the lab is on the second NIC.
- With a single NIC, Lima's SSH forwarder targeted the DHCP lease on the lab segment, so
  static lab addresses would have broken management. That approach was tried first and rejected.

| VM | Interface | MAC | IPv4 |
|---|---|---|---|
| witness-ctl | eth0 | 52:55:55:e4:69:79 | 10.77.0.1/24 (DHCP, mgmt) |
| witness-ctl | lab0 | 52:55:55:77:01:10 | **10.77.1.10/24** (static) |
| witness-field | eth0 | 52:55:55:7b:ba:05 | 10.77.0.3/24 (DHCP, mgmt) |
| witness-field | lab0 | 52:55:55:77:01:20 | **10.77.1.20/24** (static) |
| witness-field | field0 (dummy) | 9a:de:6e:f3:8e:ab | **10.77.2.11/24, 10.77.2.12/24** |

The guest scripts check identity before any privileged change: Linux + VM + Ubuntu
24.04 aarch64 + `lab0` MAC equal to `inventory.yaml` + hostname `lima-<instance>`.

## 4. Routing (observed `ip -4 route`)

witness-ctl:
```
10.77.0.0/24 dev eth0 proto kernel scope link src 10.77.0.1 metric 100
10.77.1.0/24 dev lab0 proto kernel scope link src 10.77.1.10
10.77.2.0/24 via 10.77.1.20 dev lab0 proto static
$ ip route get 10.77.2.11
10.77.2.11 via 10.77.1.20 dev lab0 src 10.77.1.10 uid 0
```
witness-field:
```
10.77.0.0/24 dev eth0 proto kernel scope link src 10.77.0.3 metric 100
10.77.1.0/24 dev lab0 proto kernel scope link src 10.77.1.20
10.77.2.0/24 dev field0 proto kernel scope link src 10.77.2.11
```
- **Neither VM has a default route.** `net.ipv4.ip_forward = 0` on both: witness-field does not
  forward, because the device addresses are *local* to it (`ip route get 10.77.2.11` on field
  → `local`). ctl reaches them only because of the static route via 10.77.1.20.
- **Why `ping 10.77.2.11` / `dev-a.lab` works from ctl:** ctl's longest-prefix match for
  10.77.2.11 is `10.77.2.0/24 via 10.77.1.20 dev lab0`. It ARPs for 10.77.1.20 on lab0 and
  sends the frame to field's pinned MAC. Field accepts it because 10.77.2.11 is a local
  address (on dummy `field0`; Linux's weak host model accepts it on any interface) and replies
  to 10.77.1.10 out of lab0 via its connected route.
- **Route removal (fault F5 preview, observed 2026-10-17T04:59:45Z):** after
  `ip route del 10.77.2.0/24 …` on ctl, `ip route get 10.77.2.11` → `RTNETLINK answers: Network is unreachable`
  and `ping` → `connect: Network is unreachable`. It fails immediately, locally, with ENETUNREACH,
  because ctl has no default route to fall back on. Name resolution and the L2 ping to
  10.77.1.20 still worked, and fresh vsock management sessions to both VMs succeeded. The route was restored and preflight went GREEN.
  Prediction for Phase 3 F5: **NO_ROUTE**, not CONNECT_TIMEOUT, in this topology.

Persistence: netplan `/etc/netplan/60-witness.yaml` (networkd renderer) holds the lab0
address, the ctl route and the `field0` dummy (`dummy-devices:`). cloud-init's
`50-cloud-init.yaml` is backed up to `/var/lib/witness/backup/` and network config is disabled
(`/etc/cloud/cloud.cfg.d/99-witness-disable-network-config.cfg`), because the Lima
instance-id changes on every boot. Verified after full VM stop/start, without re-provisioning.

## 5. Names

`/etc/hosts` on witness-ctl contains a managed block generated from `inventory.yaml`:
```
# BEGIN witness-lab (generated from inventory.yaml; edit there, not here)
10.77.2.11	dev-a.lab
10.77.2.12	dev-b.lab
# END witness-lab
```
Lima's boot script `06-etc-hosts.sh` re-appends `10.77.0.2 host.lima.internal` on every boot.
The block is position-independent, so the two coexist; that address is unreachable because of isolation.
systemd-resolved has **no DNS servers** (`/etc/systemd/resolved.conf.d/60-witness.conf`:
`DNS=`, `FallbackDNS=`, LLMNR and mDNS off), so unknown names fail fast
(`getent hosts ubuntu.com` → exit 2).

## 6. Isolation (internet inaccessible after provisioning)

UTM Host-Only would enforce isolation in the hypervisor. With Lima user-v2, gvproxy provides NAT,
so isolation is enforced **in each guest**, at two layers:
1. no default route, no DNS servers (above);
2. nft table `inet witness_isolation` (`/etc/witness/isolation.nft`, loaded by
   `witness-isolation.service`, which only replaces its own table and never runs `flush ruleset`):
   output **policy drop**, except `lo`, established traffic, lab0 to `{10.77.1.10, 10.77.1.20, 10.77.2.0/24}`
   and DHCP on eth0. Input on eth0 accepts only established traffic, DHCP, and TCP 22 from gvproxy 10.77.0.2.

Observed probes (`lab-smoke.sh`, both VMs, all **failed as required**): `ping 1.1.1.1`,
`curl http://1.1.1.1/`, `getent hosts archive.ubuntu.com`, `ping 10.77.1.2` (gvproxy, lab),
`ping 10.77.0.2` (gvproxy, mgmt), and **`curl http://1.1.1.1/` with a deliberately added
route via gvproxy**, which nft dropped. Packages are installed before isolation. A later
install opens a bounded "online window" (temporary route + nft rule + DNS, all removed on
exit) inside `ensure_packages`.

Other nft content is Lima's own: `table ip nat` (iptables-nft LIMADNS chain from Lima's `09-host-dns-setup.sh`).
Lab fault tables must be named `witness_fault*`. preflight fails on any leftover, and reset deletes them.

## 7. Management / rescue path

- `limactl shell <vm>` is SSH over **AF_VSOCK**, independent of guest IP networking. Ubuntu 24.04's
  systemd 255 has no sshd-vsock generator, so provisioning adds `witness-sshd-vsock.socket`
  (`ListenStream=vsock::22`, `Accept=yes`) plus `witness-sshd-vsock@.service` (`sshd -i`).
  Lima log on every boot: `Detected SSH server is listening on the vsock port`.
- Fallback: Lima's gvproxy forwarder to the eth0 DHCP address on `witness-mgmt`.
- The Lima guest agent also uses vsock (port 2222).
- Faults on lab0/field0 (route, netem, nft) therefore cannot cut management.
  This was demonstrated with route removal, and with netem on lab0 during the reset self-test.

## 8. Clocks

**Observed:** `lima-guestagent` steps each guest clock to the macOS host (`settimeofday`,
checked every 10 s). It tolerated drifts up to 37 ms and corrected 102 ms and larger, and Lima has
no opt-out. The two guest clocks ran **~83 ppm apart** (raw SNTP offset 25 → 35 ms over 2 min). A
chronyd that also steered the clock fought the agent (19 steps in 5 min on field), and `chronyd -x` reports modelled
offsets (~0 while the true offset was 25–35 ms), so it cannot gate REQ-04.

**Design: one writer per clock, macOS → ctl → field.**
- witness-ctl: lima-guestagent owns the clock; `chronyd -x` (`/etc/default/chrony`
  `DAEMON_OPTS="-F 1 -x"`) only serves it (`local stratum 8`, `allow 10.77.1.20/32`).
- witness-field: chronyd owns the clock (`server 10.77.1.10 iburst minpoll 2 maxpoll 4`,
  `makestep 0.1 -1`), and lima-guestagent is denied `CAP_SYS_TIME`
  (`/etc/systemd/system/lima-guestagent.service.d/60-witness-no-settime.conf`; survives reboot).
- Gate: `scripts/lib/ntp_offset.py 10.77.1.10` (raw SNTP four-timestamp offset, min-delay of 4).
  Observed after convergence: |offset| ≤ 0.6 ms (10 samples), and −2.3 ms in the final preflight.

## 9. Services, ports, versions

| Service | VM | State | Notes |
|---|---|---|---|
| `witness-isolation.service` | both | active (exited) | nft isolation table |
| `witness-sshd-vsock.socket` | both | active | management SSH over vsock |
| `chrony.service` | both | active | 4.5-1ubuntu4.2; ctl `-x` server UDP 123 on lab0, field client |
| `lima-guestagent.service` | both | active | field: without CAP_SYS_TIME |
| `witness-device@a`, `@b` | field | active, enabled (Phase 2) | Type=notify, DynamicUser, TCP 5020 bound only to 10.77.2.11 / .12; journald id `witness-device@<i>` |
| `witness-fault-deadman` (transient) | field | only while a fault is applied | `systemd-run` timer, 90 s, runs `witness-faultctl reset deadman` |
| `witness-ctl-fault-deadman` (transient) | ctl | only during F4, F5, F7 | 90 s timer, runs `reset_lab.sh --role ctl` (restores the managed hosts block and the device route) |
| `witness-gateway` | ctl | active, enabled (Phase 3) | Type=notify, DynamicUser, HTTP 127.0.0.1:8080, polls both devices every 2 s; code `/usr/local/lib/witness-gateway`, inventory `/etc/witness/inventory.yaml` |
| `witness-field-capture` (transient) | field | only during a fault case | tcpdump on lab0 started by `witness-faultctl capture start`, RuntimeMaxSec=120, stopped by `capture stop`/reset |

Packages (both): iproute2 6.1.0-1ubuntu6.4, nftables 1.0.9-1ubuntu0.1, tcpdump
4.99.4-3ubuntu4.24.04.1, curl 8.5.0-2ubuntu10.10, netcat-openbsd 1.226-1ubuntu2, chrony
4.5-1ubuntu4.2, sqlite3 3.45.1-1ubuntu2.8, python3 3.12.3-0ubuntu2.1, python3-pytest 7.4.4-1,
python3-yaml. ctl also: shellcheck 0.9.0. `sch_netem` is in the base kernel
(`modprobe -n -v sch_netem` → `…/kernel/net/sched/sch_netem.ko.zst`), so
`linux-modules-extra` is not needed.

## 10. Commands (run from the repo root on the Mac)

| Purpose | Command |
|---|---|
| Create/start both VMs + networks | `scripts/lab_vms.sh up` |
| Status (incl. SSH transport) | `scripts/lab_vms.sh status` |
| Copy repo to `/opt/witness-lab` in both guests | `scripts/lab_vms.sh sync` |
| Provision (idempotent; field first) | `scripts/lab_vms.sh provision` |
| Preflight both (read-only) | `scripts/lab_vms.sh preflight` |
| Network smoke + isolation probes | `scripts/lab_vms.sh smoke` |
| Route-removal demo (auto-restores) | `scripts/lab_vms.sh route-demo` |
| Emergency reset of lab fault state | `scripts/lab_vms.sh reset` (`reset --dry-run` to preview) |
| Prove reset works | `scripts/lab_vms.sh reset-selftest` |
| Stop both / delete both | `scripts/lab_vms.sh stop` / `scripts/lab_vms.sh destroy --yes` |
| Shell into a VM | `LIMA_HOME=$PWD/.lima.nosync limactl shell witness-ctl` |
| In-guest equivalents | `sudo /opt/witness-lab/scripts/{preflight.sh,reset_lab.sh,lab-smoke.sh} --role ctl\|field` |
| Clock check (on field) | `python3 /opt/witness-lab/scripts/lib/ntp_offset.py 10.77.1.10`, `chronyc -n sources` |
| Diagnostics | `ip -br addr`, `ip route get 10.77.2.11`, `getent hosts dev-a.lab`, `nft list table inet witness_isolation`, `tc qdisc show dev lab0`, `journalctl -u lima-guestagent` |

If a guest's networking is broken beyond `reset`, the rescue console is still
`limactl shell` (vsock). The original cloud-init netplan, hosts and chrony files are in
`/var/lib/witness/backup/`.

## 11. Phase 2: devices, runner, fault agent (observed 2026-10-17)

### Components and paths

| Item | VM | Path / name |
|---|---|---|
| Device code (installed copy) | field | `/usr/local/lib/witness/device.py` (repo `device/device.py`) |
| Device unit | field | `/etc/systemd/system/witness-device@.service` (repo `device/witness-device@.service`) |
| Device identity (from inventory) | field | `/etc/witness/device-a.env`, `/etc/witness/device-b.env` |
| Device runtime state | field | `/run/witness-device-<i>/state.json` (pid, mode; written by the device, read by root) |
| Device fault-mode control | field | `/run/witness-fault/device-<i>.mode` (root-owned dir, device read-only; deleted by `ExecStartPre=+` on every start, so restart = `normal`). Moved out of the device-owned run dir after a security review: root must not write where the device user could plant a symlink. |
| Fault agent | field | `/usr/local/sbin/witness-faultctl` (repo `scripts/faultctl.py`), audit log `/var/lib/witness/faultctl.log` |
| Forced-command wrapper | field | `/usr/local/sbin/witness-fault-ssh`; user `witness-fault` (system, `/var/lib/witness/fault-agent`); sudoers `/etc/sudoers.d/60-witness-fault` |
| Runner key | ctl | `/var/lib/witness/runner/id_ed25519` (+ `known_hosts` holding field's host key) |
| Runner / pytest | ctl | `/opt/witness-lab` (`runner/`, `tests/`), run as root (tcpdump, F7 `/etc/hosts`) |
| Results | ctl | `/var/lib/witness/results/witness.db`, `.../evidence/run-<N>/<case>__<device>/`, `.../reports/` |

Control channel: the runner on witness-ctl runs `ssh witness-fault@10.77.1.20 <words>` over lab0.
`authorized_keys` is `restrict,from="10.77.1.10",command="/usr/local/sbin/witness-fault-ssh"`, and the
wrapper runs `sudo -n witness-faultctl <words>`. faultctl re-checks the VM identity and validates every
word (`id`, `apply netem 300 all;reboot`, `apply mode a explode`, `journal a $(id)` and unknown
instances were all refused, see `results/logs/phase2-device-smoke-*.log`).

### Commands

| Purpose | Command |
|---|---|
| Device status / logs | `systemctl status witness-device@a` ; `journalctl -u witness-device@a --since -10min` |
| Restart / stop / start | `sudo systemctl restart\|stop\|start witness-device@a` (restart returns after the new process bound: Type=notify) |
| Talk to a device by hand (ctl) | `printf '{"id":1,"cmd":"IDENTIFY"}\n' \| nc -q1 -w2 dev-a.lab 5020` |
| Listening sockets (field) | `ss -ltnp 'sport = :5020'` |
| Fault agent status (ctl, root) | `ssh -i /var/lib/witness/runner/id_ed25519 -o UserKnownHostsFile=/var/lib/witness/runner/known_hosts witness-fault@10.77.1.20 status` |
| Unit tests in ctl | `scripts/lab_vms.sh unit` |
| Live suites (run ON ctl) | `scripts/lab_vms.sh suite baseline` / `suite fault` |
| Report / copy results to Mac | `scripts/lab_vms.sh report` ; `scripts/lab_vms.sh fetch` |
| Prove interrupt recovery | `scripts/lab_vms.sh interrupt-selftest TERM` / `KILL` (field F2), `... TERM f5` / `KILL f5` (ctl route) |
| Gateway API (GET only) | `scripts/lab_vms.sh gw inventory` ; `scripts/lab_vms.sh gw devices/dev-a` (on ctl: `curl -s http://127.0.0.1:8080/inventory`) |
| Gateway status / logs / one-shot poll | `systemctl status witness-gateway` ; `journalctl -u witness-gateway --since -10min` ; `cd /opt/witness-lab && python3 -m gateway.gateway --inventory inventory.yaml --once` |
| Field fault agent, new verbs | `apply nft drop\|reject\|reject-data a`, `revert nft`, `apply\|revert restart a`, `apply mode a close-after:2\|reset-after:2\|clock-skew:+30s\|repeat-seq`, `capture start\|stop NAME`, `counters` |

### Observed behaviour worth knowing (each with evidence)

- **Stopped vs hung process (F1 vs F2).** `systemctl stop`: SYN answered by RST within ~1 ms
  (CONN_REFUSED). `SIGSTOP`: the kernel still completes SYN/SYN-ACK/ACK and ACKs the request; the
  listener's Recv-Q shows 1 queued connection (`ss` snapshot), no application byte for 2.0 s
  (READ_TIMEOUT). After SIGCONT the device answers the already-closed socket and ctl replies RST.
  (`run-3/FT-F1-STOPPED__dev-a`, `run-3/FT-F2-HUNG__dev-a`.)
- **netem scope.** A plain root netem on field `lab0` would also delay SSH and chrony; an
  asymmetric delay would make chrony (`makestep 0.1 -1`) step field's clock. The fixture therefore
  delays only device-source TCP 5020 (prio band 4 + flower). netem counters during F6-300: 3 packets
  through netem while the prio root carried 25 (SSH etc. unaffected).
- **Half-open leftovers after a delayed SYN-ACK.** After F6-3000 the runner had given up, but field
  kept the connection in SYN-RECV and retransmitted the SYN-ACK once the qdisc was gone; it landed in
  the next case's capture (run 3). Fix: `revert netem` waits (≤ 8 s) until no SYN-RECV remains, and the
  field quick check fails on any (verified in run 4).
- **tcpdump needs `--immediate-mode`.** Without it, sub-second cases captured 0 packets
  ("10 packets received by filter, 0 packets captured"): libpcap TPACKET_V3 hands packets over only
  when a ring block fills or times out. Run 1's pcaps are empty for this reason (kept as a record).
- **RST instead of FIN when closing with unread data.** The device's `frame_too_long` close sent RST
  and the client could lose the error reply; fixed with a bounded lingering close (half-close, drain ≤ 1 s).
- **EOF vs RST (loopback on ctl's kernel, `results/logs/phase2-eof-vs-rst-loopback-*.log`):**
  0 bytes + FIN and 0 bytes + RST are both CONN_RESET; 20 bytes + FIN and 20 bytes + RST are both
  MALFORMED (truncated). Linux returns the queued 20 bytes before reporting ECONNRESET. Live:
  F10-truncated shows 43 bytes then FIN.
- **Device restart:** `systemctl restart witness-device@a` returned in 0.16 s; SIGTERM → "stopped" in
  95 ms (graceful: listener closed, open connections FIN); new PID, `uptime_s` ≈ 0.07, READ `seq` restarts at 1.
- **Reboot:** after a full stop/start of both VMs, both device units were active 4–5 s after boot with
  `NRestarts=0`, and preflight was GREEN on the first attempt (`results/logs/phase2-reboot-*.log`).
- **SSH host keys regenerated on every boot (fixed).** Lima presents a new cloud-init instance-id
  at each boot (`iid-1792216378` → `iid-1792216503` across one reboot), and cloud-init's ssh module
  (`ssh_deletekeys: true` by default) regenerated field's host keys. The runner's pinned
  `known_hosts` then failed closed ("REMOTE HOST IDENTIFICATION HAS CHANGED"): run 18's session
  preflight was RED and all 9 cases were recorded `error/infra` without touching a device. The new key
  was confirmed identical via the independent vsock path before re-pinning. Provisioning now installs
  `/etc/cloud/cloud.cfg.d/99-witness-keep-ssh-hostkeys.cfg` (`ssh_deletekeys: false`); after the next
  reboot the key was unchanged and run 19 passed without re-linking (`results/logs/phase2-reboot2-hostkeys-*.log`).
- **Fail-closed process control** (`results/logs/phase2-failclosed-pid-*.log`): with SIGSTOP active, a
  second fault, a wrong PID, a right PID with a wrong start time, and dev-b's PID against instance a
  were all refused; only the exact recorded PID + start time was continued.

### Golden clones (brief §7.3)

`witness-ctl-golden` and `witness-field-golden` were created with `limactl clone` (VMs stopped) from the
final Phase 2 state (commit `06c92aa`, after the host-key fix). On APFS the clone is copy-on-write:
free space changed by ~0 (17,595,544 → 17,706,956 KiB free, the old clones' divergent blocks were freed),
although `du` shows ~2.2 GiB each (shared blocks). They grow only as the live disks diverge.

**Never start a golden instance while the originals run**: it has the same pinned `lab0` MAC (and
Lima SSH port). Restore procedure as written in Phase 2 (superseded: Phase 4 executed and automated it as
`scripts/lab_vms.sh golden-restore --yes`, five times plus once from refreshed clones; see section 14):
```
scripts/lab_vms.sh stop
LIMA_HOME=$PWD/.lima.nosync limactl delete witness-field
LIMA_HOME=$PWD/.lima.nosync limactl clone witness-field-golden witness-field --tty=false
scripts/lab_vms.sh up && scripts/lab_vms.sh preflight     # then: scripts/lab_vms.sh link if the field host key differs
```

## 12. Phase 3 pre-run predictions (written 2026-10-17T06:19Z, BEFORE any F4/F5 run)

These predictions are committed to git before the F4/F5 fixtures exist, so the history shows
they were not fitted to the observations. Inputs used (configuration only, no fault applied):
read-only probes at 06:12Z on witness-field: `net.ipv4.ip_forward = 0`,
`net.ipv4.conf.lab0.forwarding = 0`, `rp_filter = 2` (loose), `Ip InAddrErrors = 0`,
field0 holds only 10.77.2.11/24 and 10.77.2.12/24; ctl routes 10.77.2.0/24 via 10.77.1.20.

### F4: inventory points dev-a at 10.77.2.13 (unused)

Fault as it will be applied: the inventory row for dev-a carries address 10.77.2.13, and the
managed `/etc/hosts` block on witness-ctl is regenerated from that faulted inventory, so
`dev-a.lab` resolves to 10.77.2.13. The runner and the gateway both dial `dev-a.lab:5020`.

**Prediction: CONNECT_TIMEOUT** (detail `no_handshake_within_timeout`), not NO_ROUTE, not CONN_REFUSED.

Reasoning, hop by hop:
1. ctl: 10.77.2.13 matches `10.77.2.0/24 via 10.77.1.20 dev lab0`, so the SYN leaves lab0 addressed to
   witness-field's MAC (ARP is for the next hop 10.77.1.20, which answers). No local error on ctl.
2. field: 10.77.2.13 is not a local address (only .11/.12 are; the /24 on dummy `field0` is a connected
   *unicast* route, not a local route). The packet would have to be forwarded, and forwarding is off on
   the ingress device (`conf.lab0.forwarding = 0`). In the kernel's input route lookup that is
   `-EHOSTUNREACH` → `ip_error()`, and `ip_error()` does **not** send ICMP when forwarding is disabled on
   the ingress device; it only increments `IpInAddrErrors` and drops the packet.
3. So ctl receives nothing: no SYN-ACK, no RST, no ICMP. `connect()` gives up at the 1.0 s connect timeout.

Expected evidence: ctl lab0 capture shows SYN(s) to 10.77.2.13:5020 (possibly the 1 s retransmission
right as the runner gives up) and no reply of any kind; a witness-field lab0 capture shows the same SYN
arriving; field `Ip InAddrErrors` rises by about the number of SYNs (runner + gateway polls), and
`Icmp OutDestUnreachs` does not change. The gateway marks dev-a unreachable with CONNECT_TIMEOUT while
dev-b stays healthy. Even if forwarding were enabled, the dummy (NOARP) interface would silently
discard the packet, so I expect a silent drop either way; an ICMP host-unreachable would mean this
reasoning is wrong.

Alternatives rejected before running: NO_ROUTE (ctl has a covering route, and field sends no ICMP);
CONN_REFUSED (needs field to treat .13 as local and answer RST). Residual uncertainty: gvproxy (the
user-v2 L2 switch between the VMs) forwards by MAC, so it should pass the frame unchanged. If the
field-side capture shows no SYN, gvproxy dropped it and the explanation moves from field's kernel to the switch.

### F5: device-subnet route deleted on witness-ctl

The Phase 1 prediction in section 4 stays as written: **NO_ROUTE**, not CONNECT_TIMEOUT.
Pre-run detail added now: `connect()` fails synchronously inside ctl (route lookup in
`tcp_v4_connect` → `ENETUNREACH`, since ctl has no default route to fall back on), in microseconds. **No
SYN leaves ctl**, so the ctl lab0 capture has no TCP/5020 packet for the probe, and there is no ICMP
(this is a local errno, not an ICMP message). Both devices become unreachable (they share the route);
the gateway marks both NO_ROUTE at its next poll (≤ P = 2 s). Management (vsock) and the ctl→field SSH
control channel (connected route on lab0) keep working.

### Other Phase 3 faults (brief §6.3 expectations, mechanism stated in advance)

| Fault | Expected | Mechanism expected |
|---|---|---|
| F3 port 5021 | CONN_REFUSED | field kernel answers SYN to 10.77.2.11:5021 with RST (no listener) |
| F8 nft drop (dev-a, tcp/5020) | CONNECT_TIMEOUT | SYN dropped in field's input hook; capture: SYN (+1 s retransmit), no reply; nft counter > 0 |
| F9 nft reject with tcp reset (all segments) | CONN_REFUSED | nft answers the SYN with RST; looks like F1 on the wire, but the device is still LISTENing (ss) and the nft counter rises |
| F9 nft reject, request data only | CONN_RESET | handshake completes, the PSH request segment is rejected with RST → recv ECONNRESET with 0 bytes |
| F11 close-after:2 (FIN) / reset-after:2 (RST) | CONN_RESET / CONN_RESET | two exchanges PASS, third request gets FIN (EOF) or RST before any response byte; protocol §2.6 maps both to CONN_RESET, detail tells them apart |
| F12 restart during polls | PASS within 10 s (REQ-08) | Type=notify: `systemctl restart` returns only after the new process bound, so I expect the **first** HEALTH probe after it returns to PASS; gateway sees the restart (uptime drops) at its next poll (≤ P) |
| F13 clock-skew:+30s / repeat-seq | STALE_DATA / STALE_DATA | ts 30 s ahead of the window / seq not increasing on the second READ |

## 13. Phase 3 observations (2026-10-17; after section 12 was committed in `fe85e80`)

All on the real VMs; final evidence runs are listed in docs/implementation-state.md, per-case evidence in
`results/evidence/run-N/<case>__<device>/` (ctl `capture.txt`, field `capture-field.txt`, snapshots taken
while the fault was applied, journals, `timing.json`), timings in the `measurements` table.

### F4 and F5 against the predictions

**F4 (predicted CONNECT_TIMEOUT, silent drop at witness-field): matched.** First run: run 32. connect gave up at
1009.9 ms with `no_handshake_within_timeout`. The ctl capture shows SYNs to 10.77.2.13:5020 (runner port 38802
and its retransmission 1.009 s later, plus one gateway poll) and nothing coming back. The **field** capture shows
the same three SYNs (same sequence numbers) arriving on witness-field's lab0, so gvproxy delivered them.
Field counters across the case: `Ip.InAddrErrors` 0 → 3 (exactly the SYNs), `Icmp.OutDestUnreachs` 3 → 3,
`Tcp.OutRsts` 6 → 6. The packet reached field and the kernel discarded it as an address error without ICMP,
as `ip_error()` does when forwarding is off. The gateway marked dev-a unreachable (CONNECT_TIMEOUT) at its next
poll. Final runs repeat it: 1002–1012 ms, `InAddrErrors` +2 per case (the runner's SYN and its retransmit).

**F5 (predicted NO_ROUTE, no SYN on the wire): matched.** connect failed with ENETUNREACH in < 1 ms; the ctl
lab0 capture has **zero** packets for the case (neither runner nor gateway could emit one); `ip route get
10.77.2.11` → `RTNETLINK answers: Network is unreachable`. The gateway marked both devices NO_ROUTE
(they share the route). SSH to field and vsock management kept working (the case's own field calls succeeded).

### Other faults (final runs; all observed = expected)

| Fault | Observed | Timing | Wire / system evidence |
|---|---|---|---|
| F3 port 5021 | CONN_REFUSED | 1.0–1.4 ms | kernel RST for the SYN; control probe on 5020 PASS; `gateway --once` with the faulted inventory also says CONN_REFUSED |
| F8 nft drop | CONNECT_TIMEOUT | connect 1002–1005 ms | SYN seen on field's lab0, nothing back; nft counter `packets 1`; no RST/ICMP from field |
| F9 reject (incl. SYN) | CONN_REFUSED | 0.7–0.8 ms connect | `[S]` → `[R.] seq 0` from nft while `ss` shows dev-a LISTEN; nft counter 1. Same category as F1, different cause: process up, firewall answering |
| F9 reject, data only | CONN_RESET (`reset_before_response`) | 1.3–1.7 ms | handshake completes, request `[P.] 1:27` reaches field, nft answers `[R]`; the orphaned device socket is aborted by the revert (`[R.]` ~1.6 s later) |
| F11 close-after:2 | CONN_RESET (`eof_before_response`) | 3.6–3.8 ms | 2 responses, then `[F.]` instead of the 3rd |
| F11 reset-after:2 | CONN_RESET (`reset_before_response`) | 3.6–5.6 ms | 2 responses, then `[R.]` instead of the 3rd |
| F12 restart | PASS (first probe) | restart 184–189 ms on field; first PASS HEALTH 2.3–3.6 ms after the call returned | Type=notify held: the new pid was listening when `systemctl restart` returned, so the **first** HEALTH probe passed (as predicted in section 12); the connection held open across the restart got EOF → CONN_RESET |
| F13 clock-skew:+30s | STALE_DATA (`ts_outside_window:+29.999..+30.0s`) | 2.7–4.3 ms | |
| F13 repeat-seq | STALE_DATA (`seq_not_increasing:184<=184`) | 3.3–4.0 ms | first READ PASS, second repeats seq |

Gateway (REQ-09, fault command sent → gateway state `unreachable`, bound 6000 ms; 18 measurements per
case across runs 28–67, from `measurements`): F1 372–2322 ms, F5 309–1617 ms (both devices), F8 1979–2374 ms
(includes the poll's 1 s connect timeout). No value exceeded the bound. dev-b stayed healthy during F1/F8.
Recovery after the revert: 110–2288 ms (bound 4000; runs 28–47 measured it from the revert call returning,
runs 48+ from the revert command being sent, see run 47 below; the reference is in each row's `detail`).
F7: the gateway flagged `wrong_identity` (`device_id`, `serial`) 410–1717 ms after the hosts-swap command
(runs 62, 63, 66, 67; checked since run 62). REQ-08 (F12, 12 runs 31–67): first PASS HEALTH 1.7–9.6 ms after the restart returned,
`systemctl restart` 162–296 ms on field, gateway saw the new process 842–1111 ms after the first PASS (bound 4000).
Non-pass gateway results, all explained: run 47 GW-F8 (my recovery reference, below), run 54 GW-F1 (stop
window, finding 3), runs 38/39/42/43 GW-F5 (deliberately interrupted self-tests).

### Findings that were not predicted

1. **ctl's chronyd served a drifting time (Phase 1 defect, fixed).** The F4 captures on ctl and field
   differed by a constant +1.427 s for the same packets (0.4 ms RTT), and the gateway's READ skew was +1.435 s,
   yet field's SNTP gate read +0.1 ms. `chronyc tracking` on ctl: `System time: 1.437340140 seconds slow of NTP
   time`, `Frequency: 80.993 ppm slow`. Its drift file (−80.993 ppm, from before `-x`) was being applied to the
   **served** time while `-x` kept the system clock untouched: 81 ppm × 4.9 h since chronyd started = 1.43 s.
   Field followed the served time, and the gate compared field with that same served time, so it could not
   see the error. It grows ~0.29 s/h and would have broken REQ-04's ±2 s window after ~7 h with a GREEN
   preflight, as device-attributed STALE_DATA. Phase 2 data shows it was already there: +5 ms (run 20) and
   +36 ms (run 25). Fix: no driftfile on ctl (provision_ctl.sh removes it), and a new ctl preflight check
   `clock-served` (served time must equal ctl's system clock within 10 ms). Before: ctl preflight RED with
   `clock-served` 1.4445 s; after: frequency 0.000 ppm, field stepped −1.36 s in five steps, skew −1 ms,
   preflight GREEN. Logs: `results/logs/phase3-clock-*`, `phase3-chrony-*`.
2. **Mac sleep stalls both VMs.** After host sleep both guest clocks were ~16 min behind; lima-guestagent
   stepped ctl within seconds, field's chronyd only after ~20 s ("no selectable sources", then "System clock
   wrong by 986 s"). In that window the gateway (started at 09:37:25Z) classified both devices STALE_DATA
   (`ts_outside_window:-985.055s`) for two polls: a true positive. Live runs are now wrapped in `caffeinate -i`
   (blocks idle sleep only while the command runs); session preflight still gates the clocks.
3. **Graceful stop window → CONN_RESET instead of CONN_REFUSED** (protocol.md section 5 note): run 54 GW-F1.
   The case asserted the transition poll's category, which was conditional on timing. It now asserts the
   category of a poll that started after the fault was confirmed applied (steady state, CONN_REFUSED in every
   run since) and keeps the transition poll's category in the result detail. Run 54 stays recorded as fail.
6. **Harness defects found by live runs (fixed; failing rows kept):** (a) run 33: `revert nft` checked once for
   the orphaned F9-data socket while it was only 0.7 s idle; the postflight caught it 1 s later and contaminated
   the run → the revert now waits (≤ 2.5 s) for it. (b) run 47: GW-F8 recovery was measured from the revert call
   *returning*; the gateway had recovered 13 ms earlier → measured from the command being sent. (c) F3/F4/F8/F9
   runner detection times included post-probe evidence calls (F9 398/308 ms in runs 33/37) → taken right
   after the probe from run 44 on (F9 1.0–8.3 ms in runs 45–63).
4. **F6 netem is subnet-wide**: the flower filter matches `src 10.77.2.0/24`, so the gateway sees dev-b
   PASS_SLOW/READ_TIMEOUT during F6 as well (it was scoped that way in Phase 2; recorded, not changed).
5. **lima-guestagent steps ctl by about ±100 ms** whenever ctl drifts past ~100 ms (seen at 10:42:53Z, 10:57:35Z, 10:57:43Z),
   and field follows a few seconds later; in that window field↔ctl differ by up to ~0.12 s (run 33 F13 read +30.123 s).
   That is far inside ±2 s, but it is why the preflight gate stays at < 100 ms.

### Recovery recipe (the brief's "UTM console" equivalent on Lima)

Management never uses lab networking: `limactl shell <vm>` is SSH over vsock (section 7). If a fault is left:
(1) `scripts/lab_vms.sh reset` (both VMs: nft fault tables, qdiscs, route, hosts block, device modes, SIGCONT,
field capture, stale connections); (2) per VM, `LIMA_HOME=$PWD/.lima.nosync limactl shell witness-ctl sudo
/opt/witness-lab/scripts/reset_lab.sh --role ctl` (or `--role field`); (3) if vsock SSH itself fails,
`limactl stop <vm> && limactl start <vm>`: runtime faults vanish at boot (nft fault tables, qdiscs, device
modes are not persistent; netplan restores the route). Only the ctl `/etc/hosts` block (F4/F7) persists across
a reboot, so run `reset_lab.sh --role ctl` and then preflight; (4) last resort: golden clone restore (section 11).
The dead-man timers cover a killed runner: shown for field (F2, +91 s) and ctl (F5, +90.1 s, route restored by
`reset_lab.sh --role ctl`; `results/logs/phase3-interrupt2-KILL-f5-*`).

## 14. Phase 4 (observed 2026-10-17 12:24–13:20Z)

### Current VM facts (`results/logs/phase4-lab-facts-20261017T131620Z.log`)

| | witness-ctl | witness-field |
|---|---|---|
| Hostname | `lima-witness-ctl` | `lima-witness-field` |
| OS / kernel | Ubuntu 24.04.4 LTS, Linux 6.8.0-134-generic aarch64 | same |
| Interfaces | `eth0` 10.77.0.1/24 (mgmt, Lima user-v2 `witness-mgmt`), `lab0` 10.77.1.10/24 MAC 52:55:55:77:01:10 | `eth0` 10.77.0.3/24, `lab0` 10.77.1.20/24 MAC 52:55:55:77:01:20, `field0` (dummy, NOARP) 10.77.2.11/24 + 10.77.2.12/24 |
| Routes (`ip -4 route`) | 10.77.0.0/24 dev eth0; 10.77.1.0/24 dev lab0; **10.77.2.0/24 via 10.77.1.20 dev lab0 proto static**; no default | 10.77.0.0/24 dev eth0; 10.77.1.0/24 dev lab0; 10.77.2.0/24 dev field0; no default; ip_forward 0 |
| Listening | 127.0.0.1:8080 (gateway), :22 (sshd; vsock socket for management) | 10.77.2.11:5020, 10.77.2.12:5020 (devices), :22 |
| witness units | `witness-gateway`, `witness-isolation`, `witness-sshd-vsock.socket` | `witness-device@a`, `witness-device@b`, `witness-isolation`, `witness-sshd-vsock.socket` |
| Packages (both) | python3 3.12.3, systemd 255.4-1ubuntu8.16, chrony 4.5-1ubuntu4.2, nftables 1.0.9-1ubuntu0.1, iproute2 6.1.0-1ubuntu6.4, tcpdump 4.99.4-3ubuntu4.24.04.1, netcat-openbsd 1.226-1ubuntu2, sqlite3 3.45.1-1ubuntu2.8, python3-pytest 7.4.4-1, python3-yaml 6.0.1-2build2, curl 8.5.0-2ubuntu10.10, openssh-server 9.6p1-3ubuntu13.16 | same |
| Clock | lima-guestagent owns the clock; chronyd `-x` serves it, **no driftfile** | chronyd follows 10.77.1.10 (`^* 10.77.1.10 ... -498us`) |

Host: macOS 26.5.1 (25F80), Lima 2.2.0. Free disk 10–11 GiB throughout Phase 4 (`df -h /System/Volumes/Data`).

### Service, capture and status commands (every component)

| Component | Status | Logs | Restart / stop / start |
|---|---|---|---|
| Device a/b (field) | `systemctl status witness-device@a`; `cat /run/witness-device-a/state.json` (pid, mode, build) | `journalctl -u witness-device@a --since -10min` | `sudo systemctl restart\|stop\|start witness-device@a` |
| Gateway (ctl) | `systemctl status witness-gateway`; `curl -s 127.0.0.1:8080/inventory` | `journalctl -u witness-gateway --since -10min` | `sudo systemctl restart witness-gateway` |
| Fault agent (field) | `sudo witness-faultctl status` (faults, dead-man, pids, modes, builds) | `/var/lib/witness/faultctl.log` | stateless CLI; `sudo witness-faultctl reset` |
| Isolation (both) | `systemctl status witness-isolation`; `sudo nft list table inet witness_isolation` | journal | `sudo systemctl restart witness-isolation` |
| Clocks | ctl `chronyc tracking` (System time must be 0), field `chronyc -n sources` | `journalctl -u chrony` | `sudo systemctl restart chrony` |
| Captures | ctl: `sudo tcpdump -nn -i lab0 --immediate-mode -c 200 'tcp port 5020 or icmp'`; field: `sudo witness-faultctl capture start NAME` / `capture stop NAME` (transient unit, RuntimeMaxSec 120) | per case: `results/evidence/run-N/<case>__<device>/capture*.txt` | bounded by `-c`/RuntimeMaxSec |
| Whole lab (Mac) | `scripts/lab_vms.sh status`, `preflight` | `results/logs/` | `scripts/lab_vms.sh reset`, `stop`, `up`, `golden-restore --yes` |

### Mutant builds (brief 7.4)

`device/mutants.py` (installed as `/usr/local/lib/witness/mutants.py`) defines six broken builds selected at
process start by `WITNESS_MUTANT`. `witness-faultctl mutant deploy a SPEC` writes the runtime drop-in
`/run/systemd/system/witness-device@a.service.d/50-witness-mutant.conf`, reloads systemd and restarts the device;
`mutant restore a` removes it. Deploy refuses while a fault or another mutant is active. The device reports
`build` in state.json and logs `WARNING MUTANT BUILD <spec>`. Field preflight `device-build-<i>` is RED for a
mutant unless the runner declared it (`--mutant Mn` → `preflight allow-mutant`); a run against a mutant is
recorded as `kind=mutant` and the runner refuses (exit 3, no run row) when the reported build differs from the
declaration (`results/logs/phase4-refuse-*`). `reset_lab.sh` removes mutant drop-ins (verified:
`phase4-mutant-tooling-selftest-*`). Results: `results/reports/mutant-report.md`.

### Golden clones and VM inventory after Phase 4

| Instance | State | Content |
|---|---|---|
| `witness-ctl`, `witness-field` | Running, **protected** | the original lab VMs (Phase 1–4 history, master results DB on ctl) |
| `witness-ctl-golden`, `witness-field-golden` | Stopped, protected | **Phase 4 state** (code `87d322b`, gateway, no chrony drift file): the VMs of fresh trial 5 after its baseline, fault suite and reset self-test |
| `witness-ctl-golden-p2`, `witness-field-golden-p2` | Stopped, protected | the original Phase 2 golden clones (code `06c92aa`), kept unchanged |

Restore = `scripts/lab_vms.sh golden-restore --yes` (stops/deletes the current `witness-ctl`/`witness-field`;
protected instances are refused, so the originals must be renamed away or unprotected first), then
`provision` and `results-push`. The restore writes `/var/lib/witness/provenance` in both guests; the runner
stores it per run (`provenance.<vm>`), which is how SQL identifies fresh-clone runs.

### Observations in Phase 4 (each with evidence)

1. **RESOLVE_FAIL observed live for the first time** (new F7 naming variant, `dev-a.lab` removed from the
   managed `/etc/hosts` block): getaddrinfo `EAI_AGAIN` in ~4 ms (no DNS server on the isolated lab), no packet
   on the wire, the gateway also reported RESOLVE_FAIL (run 70; again in run 104 on a fresh clone).
2. **Mutant M3 (no newline) was masked by the stale-connection check** (runs 77–79). Prediction committed in
   `9de9813` (12:42Z, before the first mutant run at 12:43Z): every dev-a case MALFORMED. Observed: 10/11 cases PASS
   (runs 77, 78; 9/11 in run 79), only C-ENVIRONMENT failed, all three runs contaminated. First hypothesis: the mutant was not active. Refuted by the
   run's own environment row, recorded at session start: `fw_version.dev-a = unavailable (MALFORMED: incomplete:86B)`,
   and by the field status `builds={'a': 'mutant:no-newline'}`. The checks table showed the cause:
   precheck `no-stale-conn` FAIL `10.77.2.11:5020 10.77.1.10:47808`. The device journal shows that
   connection opened at a gateway poll slot (12:46:09.975Z, `IDENTIFY id=1 ... build=mutant:no-newline bytes=86`)
   and closed by the peer 2.0 s later: a **live gateway poll** waiting for the missing frame end, idle longer than
   the 1500 ms "stale" threshold. RED precheck → reset → `reset_lab.sh` removed the mutant drop-in
   (`precheck-reset.txt`) → the remaining cases tested the stock build. The harness stayed safe (run
   contaminated, build change detected at session end, runs excluded), but an infra check mistook device
   slowness for leftover lab state. Fix `8002e08`: threshold 5000 ms (>
   the gateway's 4.0 s poll deadline). After the fix M3 runs 80–82 and 92–94 were clean and caught.
3. **C-ENVIRONMENT blamed the runner for a device failure** (M3/M6 runs 80–82, 89–91): the session IDENTIFY of
   the mutant returned MALFORMED/READ_TIMEOUT, so `fw_version.dev-a` was recorded as `unavailable (...)`; the case
   correctly failed but with attribution `runner`. Fixed (`51cfe5a`): a firmware version withheld by the device is
   attributed `device` (verdict unchanged). Runs 92–97 show the corrected attribution. The earlier rows are kept.
4. **The single retry fired on the VMs for the first time** (M6 slow-7th): C-READ-CLOCK and C-READ-SERIES on dev-a
   have `attempts = 2` with READ_TIMEOUT on both attempts (runs 89–91, 95–97, 115, 125). **A live FLAKE occurred in
   run 125** (final code `633df97`): C-IDENTIFY/dev-a attempt 1 READ_TIMEOUT (`no_bytes_by_deadline`, the device's
   7th request slept 2.5 s), attempt 2 PASS 8.2 ms; recorded `fail/device` "FLAKE: ... passed only on retry"
   (report Q5). The retry path is therefore verified live, not only on loopback.
5. **M6 is timing-dependent**: in runs 89–97 the gateway's 3 requests per 2 s poll and the session's fixed request
   order made the session's environment IDENTIFY the device's 7th request every time; in run 125 the 7th request
   fell on the C-IDENTIFY probe instead. Every valid M6 run was still caught (C-READ-* and C-GATEWAY).
6. **Golden clones carried the Phase 3 clock defect**: every restore from the Phase 2 golden clones re-ran
   `removing stale chrony drift file (-80.993317 ...)` during provisioning (RCA-001); the refreshed clones do not.
7. Harness: `cmd_up`'s RETURN trap leaked into its caller (golden-restore exited 1 after a successful restore,
   `phase4-trial1-golden-restore-*`); fixed. macOS tar added `LIBARCHIVE.xattr` headers to results-push
   (cosmetic warnings in the guest); now `--no-xattrs --no-mac-metadata`.
8. **A SIGKILLed runner's field capture outlived the dead-man recovery** (run 110, M1, contaminated, excluded):
   the `interrupt-selftest KILL f5` runner (run 109) had started a field-side capture (`witness-field-capture`,
   bounded by `RuntimeMaxSec=120`); the ctl dead-man restored the route at +90 s and the self-test's full preflight
   reported GREEN, but `preflight.sh` did not check `capture-idle` (only the per-case quick check did). The next
   run (mutant M1, 102 s after run 109 started) failed its first precheck on `capture-idle`, the reset removed the
   mutant, and the remaining cases tested the stock build (11/11 pass, run contaminated by design). Fixed in
   `633df97`: field preflight checks `capture-idle`; `lab_vms.sh mutant run` refuses to deploy unless preflight is
   GREEN; the f5 self-test waits (bounded) for full GREEN. Re-verified: `phase4-final2-interrupt-KILL-f5-*`
   (GREEN at 14:15:14Z once the capture expired), then M1 run 120 caught.

## 15. Independent-audit remediation (2026-10-18): what changed for an operator

- **Code deployed** `0943fd5` (from `7e255ed`): device request parser (section 2 rules on requests), gateway restart
  inference, runner/acceptance changes; `scripts/lab_vms.sh provision` restarted `witness-device@a/b` and
  `witness-gateway` once (code changed); no package installs, no online window, no network change.
- **Results DB schema v4** (migrated in place on first use): `attempts.outcome/predicates`, `capture_flows`.
- **Field capture** accepts extra validated ports: `witness-faultctl capture start NAME [PORT...]` (max 4; the inventory
  device ports are always included; the runner passes F3's 5021). Filter returned in the reply as `filter`.
- **Evidence** names are per fault application (`fault-apply-F12.json`, `fault-apply-F12.2.json`); an existing evidence
  file is never overwritten; the report re-hashes every indexed file (`--evidence-root`, default `<db dir>/evidence`).
- **Remediation-only locations** on witness-ctl: `/var/lib/witness/remediation/` (separate test DB of the HEALTH-only
  partial run, F-03 netem capture) and `/tmp/witness-remediation-*` (F-05 probe captures); copied to
  `~/Desktop/Witness/remediation-evidence-20261018/`. Helper: `scripts/remediation/ctl.sh CMD...` runs one command in
  witness-ctl under the private Lima home (`/opt/witness-lab` working directory).
- **Mutant run notes** take a prefix from `WIT_RUN_TAG` (default `phase4`): `WIT_RUN_TAG=remediation scripts/lab_vms.sh mutant run M1 1`.
- **Host caveat seen during the remediation**: with other desktop applications swapping (13.7 of 15.0 GiB swap on this
  8 GiB Mac) the field VM stalled long enough for the runner's SSH control channel to time out (run 132: preflight RED,
  all `error/infra`); free disk fell to 1.8 GiB because macOS swap shares the APFS container. Check `sysctl vm.swapusage`
  and `df -h /` before long runs.
