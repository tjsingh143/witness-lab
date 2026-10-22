"""Unit tests for scripts/lib/inventory.py (config validation only; no VM involved)."""
import copy
import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("inventory", ROOT / "scripts/lib/inventory.py")
inventory = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inventory)


@pytest.fixture
def inv():
    return yaml.safe_load((ROOT / "inventory.yaml").read_text())


def test_repo_inventory_is_valid_and_matches_brief(inv):
    inventory.validate(inv)
    keys = ("device_id", "hostname", "address", "port", "serial", "fw_version")
    got = [tuple(d[k] for k in keys) for d in inv["devices"]]
    # PROJECT_BRIEF.md section 4.4, verbatim.
    assert got == [("dev-a", "dev-a.lab", "10.77.2.11", 5020, "WIT-0001", "1.0.0"),
                   ("dev-b", "dev-b.lab", "10.77.2.12", 5020, "WIT-0002", "1.0.0")]


def test_shell_vars_are_quoted(inv):
    lines = inventory.shell_vars(inv)
    assert "WIT_DEV_A_ADDR=10.77.2.11" in lines
    assert "WIT_FIELD_L2=10.77.1.20" in lines
    assert "WIT_DEVICE_IDS='dev-a dev-b'" in lines


def _mutate(inv, fn):
    bad = copy.deepcopy(inv)
    fn(bad)
    return bad


@pytest.mark.parametrize("name,fn", [
    ("bool port", lambda i: i["devices"][0].update(port=True)),
    ("port out of range", lambda i: i["devices"][0].update(port=70000)),
    ("address outside device subnet", lambda i: i["devices"][0].update(address="10.77.1.11")),
    ("duplicate serial", lambda i: i["devices"][1].update(serial="WIT-0001")),
    ("duplicate address", lambda i: i["devices"][1].update(address="10.77.2.11")),
    ("bad fw", lambda i: i["devices"][0].update(fw_version="1.0")),
    ("unknown device key", lambda i: i["devices"][0].update(colour="red")),
    ("missing device key", lambda i: i["devices"][0].pop("serial")),
    ("l2 overlaps device subnet", lambda i: i["lab"].update(l2_subnet="10.77.2.0/24")),
    ("mgmt overlaps l2", lambda i: i["lab"].update(mgmt_subnet="10.77.1.0/24")),
    ("same mgmt and lab network", lambda i: i["lab"].update(mgmt_network="witness")),
    ("vm l2 outside subnet", lambda i: i["lab"]["vms"][0].update(l2_address="10.77.3.10")),
    ("vm l2 equals gateway", lambda i: i["lab"]["vms"][0].update(l2_address="10.77.1.2")),
    ("global-unicast mac", lambda i: i["lab"]["vms"][0].update(mac="00:11:22:33:44:55")),
    ("uppercase mac", lambda i: i["lab"]["vms"][0].update(mac="52:55:55:77:01:1A")),
    ("duplicate mac", lambda i: i["lab"]["vms"][1].update(mac=i["lab"]["vms"][0]["mac"])),
    ("wrong vm name", lambda i: i["lab"]["vms"][0].update(name="vigil")),
    ("bad interface name", lambda i: i["lab"].update(device_interface="Field 0")),
    ("schema version bool", lambda i: i.update(schema_version=True)),
])
def test_invalid_inventories_rejected(inv, name, fn):
    with pytest.raises(inventory.InventoryError):
        inventory.validate(_mutate(inv, fn))
