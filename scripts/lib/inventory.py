#!/usr/bin/env python3
"""Load and validate inventory.yaml; emit shell variables for the bash scripts.

Usage:
  inventory.py validate [PATH]
  inventory.py shell [PATH]      # prints `KEY=value` lines (shell-quoted)
Exit status: 0 ok, 1 validation error, 2 usage error.
Works on Python >= 3.9 (macOS venv) and 3.12 (Ubuntu 24.04, python3-yaml).
"""
from __future__ import annotations

import ipaddress
import re
import shlex
import sys
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "inventory.yaml"

DEVICE_KEYS = {"device_id", "hostname", "address", "port", "serial", "fw_version", "instance"}
VM_KEYS = {"name", "role", "mac", "l2_address"}
LAB_KEYS = {"hypervisor", "mgmt_network", "mgmt_subnet", "lima_network", "l2_subnet",
            "l2_gateway", "device_subnet", "device_interface", "vms"}
MAC_RE = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
SERIAL_RE = re.compile(r"^WIT-\d{4}$")
HOST_RE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")
IFNAME_RE = re.compile(r"^[a-z][a-z0-9]{0,14}$")


class InventoryError(ValueError):
    pass


def _require_keys(obj, keys, where):
    if not isinstance(obj, dict):
        raise InventoryError(f"{where}: expected a mapping")
    missing = keys - obj.keys()
    extra = obj.keys() - keys
    if missing:
        raise InventoryError(f"{where}: missing keys {sorted(missing)}")
    if extra:
        raise InventoryError(f"{where}: unknown keys {sorted(extra)}")


def _str(v, where):
    if not isinstance(v, str) or not v:
        raise InventoryError(f"{where}: expected non-empty string, got {v!r}")
    return v


def validate(data) -> dict:
    """Return the inventory unchanged if valid, else raise InventoryError."""
    _require_keys(data, {"schema_version", "devices", "lab"}, "inventory")
    if data["schema_version"] != 1 or isinstance(data["schema_version"], bool):
        raise InventoryError("schema_version must be integer 1")

    lab = data["lab"]
    _require_keys(lab, LAB_KEYS, "lab")
    if lab["hypervisor"] not in ("lima", "utm"):
        raise InventoryError("lab.hypervisor must be 'lima' or 'utm'")
    _str(lab["lima_network"], "lab.lima_network")
    if _str(lab["mgmt_network"], "lab.mgmt_network") == lab["lima_network"]:
        raise InventoryError("lab.mgmt_network must differ from lab.lima_network")
    try:
        mgmt = ipaddress.ip_network(_str(lab["mgmt_subnet"], "lab.mgmt_subnet"), strict=True)
        l2 = ipaddress.ip_network(_str(lab["l2_subnet"], "lab.l2_subnet"), strict=True)
        dev_net = ipaddress.ip_network(_str(lab["device_subnet"], "lab.device_subnet"), strict=True)
        gw = ipaddress.ip_address(_str(lab["l2_gateway"], "lab.l2_gateway"))
    except ValueError as e:
        raise InventoryError(f"lab: {e}") from None
    if l2.overlaps(dev_net) or mgmt.overlaps(dev_net) or mgmt.overlaps(l2):
        raise InventoryError("lab mgmt, l2 and device subnets must not overlap")
    if gw not in l2:
        raise InventoryError("lab.l2_gateway not inside lab.l2_subnet")
    if not IFNAME_RE.match(_str(lab["device_interface"], "lab.device_interface")):
        raise InventoryError("lab.device_interface is not a valid interface name")

    vms = lab["vms"]
    if not isinstance(vms, list) or len(vms) != 2:
        raise InventoryError("lab.vms must list exactly two VMs")
    roles, names, macs, addrs = set(), set(), set(), {gw}
    for i, vm in enumerate(vms):
        where = f"lab.vms[{i}]"
        _require_keys(vm, VM_KEYS, where)
        roles.add(vm["role"])
        names.add(_str(vm["name"], f"{where}.name"))
        mac = _str(vm["mac"], f"{where}.mac")
        if not MAC_RE.match(mac):
            raise InventoryError(f"{where}.mac must be lowercase colon-separated")
        if int(mac[:2], 16) & 0b11 != 0b10:
            raise InventoryError(f"{where}.mac must be locally administered unicast")
        macs.add(mac)
        try:
            a = ipaddress.ip_address(_str(vm["l2_address"], f"{where}.l2_address"))
        except ValueError as e:
            raise InventoryError(f"{where}: {e}") from None
        if a not in l2 or a in (l2.network_address, l2.broadcast_address):
            raise InventoryError(f"{where}.l2_address not a host address in lab.l2_subnet")
        if a in addrs:
            raise InventoryError(f"{where}.l2_address duplicates another address")
        addrs.add(a)
    if roles != {"ctl", "field"}:
        raise InventoryError("lab.vms roles must be exactly {ctl, field}")
    if names != {"witness-ctl", "witness-field"}:
        raise InventoryError("lab.vms names must be witness-ctl and witness-field")
    if len(macs) != 2:
        raise InventoryError("lab.vms MAC addresses must differ")

    devices = data["devices"]
    if not isinstance(devices, list) or not devices:
        raise InventoryError("devices must be a non-empty list")
    seen = {k: set() for k in ("device_id", "hostname", "address", "serial", "instance")}
    for i, d in enumerate(devices):
        where = f"devices[{i}]"
        _require_keys(d, DEVICE_KEYS, where)
        for k in ("device_id", "hostname", "address", "serial", "fw_version", "instance"):
            _str(d[k], f"{where}.{k}")
        if not HOST_RE.match(d["hostname"]):
            raise InventoryError(f"{where}.hostname invalid")
        try:
            a = ipaddress.ip_address(d["address"])
        except ValueError as e:
            raise InventoryError(f"{where}: {e}") from None
        if a not in dev_net or a in (dev_net.network_address, dev_net.broadcast_address):
            raise InventoryError(f"{where}.address not a host address in lab.device_subnet")
        port = d["port"]
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise InventoryError(f"{where}.port must be an integer 1..65535")
        if not SERIAL_RE.match(d["serial"]):
            raise InventoryError(f"{where}.serial must look like WIT-0001")
        if not SEMVER_RE.match(d["fw_version"]):
            raise InventoryError(f"{where}.fw_version must be MAJOR.MINOR.PATCH")
        if not re.match(r"^[a-z0-9]+$", d["instance"]):
            raise InventoryError(f"{where}.instance must be [a-z0-9]+")
        for k in seen:
            if d[k] in seen[k]:
                raise InventoryError(f"{where}.{k} duplicates another device")
            seen[k].add(d[k])
    return data


def load(path=DEFAULT_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return validate(yaml.safe_load(f))


def shell_vars(inv: dict) -> list[str]:
    lab = inv["lab"]
    out = {
        "WIT_MGMT_NETWORK": lab["mgmt_network"],
        "WIT_MGMT_SUBNET": lab["mgmt_subnet"],
        "WIT_LIMA_NETWORK": lab["lima_network"],
        "WIT_L2_SUBNET": lab["l2_subnet"],
        "WIT_L2_PREFIX": lab["l2_subnet"].split("/")[1],
        "WIT_L2_GATEWAY": lab["l2_gateway"],
        "WIT_DEV_SUBNET": lab["device_subnet"],
        "WIT_DEV_PREFIX": lab["device_subnet"].split("/")[1],
        "WIT_DEV_IF": lab["device_interface"],
        "WIT_DEVICE_IDS": " ".join(d["device_id"] for d in inv["devices"]),
    }
    for vm in lab["vms"]:
        r = vm["role"].upper()
        out[f"WIT_{r}_NAME"] = vm["name"]
        out[f"WIT_{r}_MAC"] = vm["mac"]
        out[f"WIT_{r}_L2"] = vm["l2_address"]
    for d in inv["devices"]:
        k = d["device_id"].upper().replace("-", "_")
        out[f"WIT_{k}_HOST"] = d["hostname"]
        out[f"WIT_{k}_ADDR"] = d["address"]
        out[f"WIT_{k}_PORT"] = str(d["port"])
        out[f"WIT_{k}_SERIAL"] = d["serial"]
        out[f"WIT_{k}_FW"] = d["fw_version"]
        out[f"WIT_{k}_INSTANCE"] = d["instance"]
    return [f"{k}={shlex.quote(v)}" for k, v in out.items()]


def main(argv):
    if len(argv) not in (2, 3) or argv[1] not in ("validate", "shell"):
        print(__doc__, file=sys.stderr)
        return 2
    path = argv[2] if len(argv) == 3 else DEFAULT_PATH
    try:
        inv = load(path)
    except (InventoryError, OSError, yaml.YAMLError) as e:
        print(f"inventory INVALID: {e}", file=sys.stderr)
        return 1
    if argv[1] == "validate":
        print(f"inventory OK: {len(inv['devices'])} devices, VMs "
              f"{', '.join(v['name'] for v in inv['lab']['vms'])}")
    else:
        print("\n".join(shell_vars(inv)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
