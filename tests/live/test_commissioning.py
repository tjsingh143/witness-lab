"""Clean-baseline commissioning cases (no faults). Run on witness-ctl:
    sudo python3 -m pytest tests/live --live -m commissioning
Each case may retry once (new connection, 250 ms later); a pass on retry is a FLAKE (fail)."""
from pathlib import Path

import pytest

from runner import cases as K
from runner.evidence import check_environment, required_env_keys
from scripts.lib import inventory

pytestmark = [pytest.mark.live, pytest.mark.commissioning]
INV = inventory.load(Path(__file__).resolve().parents[2] / "inventory.yaml")
DEVICES = [d["device_id"] for d in INV["devices"]]


@pytest.mark.case("C-IDENTIFY")
@pytest.mark.parametrize("device", DEVICES)
def test_identify(case, lab, device):
    d = case.device
    attempts = K.with_retry(lambda no: K.identify(d["hostname"], d["port"], lab.identity(device), no=no))
    case.finish(attempts, "PASS")


@pytest.mark.case("C-HEALTH")
@pytest.mark.parametrize("device", DEVICES)
def test_health(case, lab, device):
    d = case.device
    attempts = K.with_retry(lambda no: K.health(d["hostname"], d["port"], no=no))
    case.finish(attempts, "PASS")


@pytest.mark.case("C-READ-CLOCK")
@pytest.mark.parametrize("device", DEVICES)
def test_read_clock_window(case, lab, device):
    d = case.device
    attempts = K.with_retry(lambda no: K.read_series(d["hostname"], d["port"], 10, bracket_health=False, no=no))
    case.finish(attempts, "PASS")


@pytest.mark.case("C-READ-SERIES")
@pytest.mark.parametrize("device", DEVICES)
def test_read_series_monotonic(case, lab, device):
    d = case.device
    attempts = K.with_retry(lambda no: K.read_series(d["hostname"], d["port"], 10, bracket_health=True, no=no))
    case.finish(attempts, "PASS")


@pytest.mark.case("C-ENVIRONMENT")
def test_environment_recorded(case, lab):
    rows = dict(lab.conn.execute("SELECT key, value FROM environment WHERE run_id=?", (lab.run_id,)).fetchall())
    run = dict(lab.conn.execute("SELECT * FROM runs WHERE run_id=?", (lab.run_id,)).fetchone())
    # the same validation acceptance (A13) and commissioning apply: every required key in its valid representation,
    # consistent with the run row (second independent audit R-01: "   \t" passed acceptance but not this case)
    chk = check_environment(rows, run, INV)
    want = required_env_keys(INV)
    preds = {k: k not in chk.problems and k not in chk.withheld for k in want}
    preds.update({k: False for k in chk.problems if k not in preds})       # contradictory or ambiguous other records
    # fw_version.<dev> = "unavailable (<category>: ...)" means the session's IDENTIFY of that device was
    # classified as a failure while preflight was green: the device withheld its firmware version, the
    # harness recorded exactly that (attribution device, verdict still fail). Any other gap is the runner's.
    device_caused = frozenset(chk.withheld)
    case.finish_check(preds, f"{sum(preds[k] for k in want)}/{len(want)} required environment keys valid"
                      + (f"; withheld by the device: {','.join(sorted(device_caused))}" if device_caused else "")
                      + "".join(f"; {k}: {why}" for k, why in sorted(chk.problems.items())),
                      device_caused=device_caused)
