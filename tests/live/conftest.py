"""Live lab fixtures: run ONLY on witness-ctl as root, against witness-field over lab0.

Session: identity guard -> full preflight on both VMs -> run row (clean_env from
preflight) -> run plan (every collected case instance, before the first case) -> environment
(REQ-10) -> cases -> safety sweep -> full session postflight.
Case:    quick precheck on both VMs -> tcpdump on ctl lab0 (+ witness-field lab0 for fault
         cases) -> [fault applied by `inject`] -> probe -> result row -> [fault reverted by
         `inject.revert()` in the test, or in the fixture's finally] -> quick postflight.
Evidence per case: both captures (pcap + text), device and gateway journals, field and ctl
snapshots taken while the fault is still applied, fault apply/revert JSON, command log,
timing.json (ctl monotonic marks), measurements and gateway API samples (gateway cases).
Captures hold TCP on the inventory's device ports plus the case fault's extra ports (F3: 5021)
and ICMP; after the case, `capture_flows` records for every dialled address:port whether
packets were expected on the wire and how many each capture holds (independent audit F-07).
A red postflight marks the run contaminated and triggers a reset; a red session
preflight makes every case `error/infra` without touching the device. Dead-man timers
on both VMs (90 s) revert faults even if this process is killed.
"""
from __future__ import annotations

import json
import os
import platform
import signal
import sys
import time
import traceback
from pathlib import Path

import pytest

import yaml

from runner import catalog, db, lab as L
from runner.cases import Attempt, case_deadline, decide, decide_observed
from runner.classify import CASE_DEADLINE_S, Identity, classify, parse_frame
from runner.client import single
from scripts.lib import inventory

REPO = Path(__file__).resolve().parents[2]


class Lab:
    def __init__(self, config):
        self.config = config
        self.inv = inventory.load(REPO / "inventory.yaml")
        L.assert_ctl_vm(self.inv)
        self.devices = {d["device_id"]: d for d in self.inv["devices"]}
        self.vms = {v["role"]: v for v in self.inv["lab"]["vms"]}
        self.field = L.FieldCtl(self.vms["field"]["l2_address"])
        self.evidence_root = Path(config.getoption("--evidence-root"))
        self.conn = db.connect(config.getoption("--db"))
        db.sync_reference(self.conn, requirements=db.requirements_from_md(REPO / "docs/requirements.md"),
                          devices=self.inv["devices"], cases=catalog.CASES, faults=catalog.FAULTS,
                          mutants=catalog.MUTANTS)
        self.run_id: int | None = None
        self.preflight_green = False
        self.contaminated = False
        self.gw = L.Gateway()
        self.mutant_id: str | None = config.getoption("--mutant")
        self.builds: dict | None = None     # instance -> build reported by the field at session start

    def identity(self, device_id: str) -> Identity:
        d = self.devices[device_id]
        return Identity(d["device_id"], d["serial"], d["fw_version"])

    @property
    def run_dir(self) -> Path:
        return self.evidence_root / f"run-{self.run_id}"

    def save(self, rel_dir: Path, name: str, text: str, kind: str, result_id: int | None = None) -> Path:
        p = rel_dir / name
        n = 2
        while p.exists():        # never overwrite a file that may already be indexed with its sha256
            p = rel_dir / f"{Path(name).stem}.dup{n}{Path(name).suffix}"
            n += 1
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        db.add_evidence(self.conn, run_id=self.run_id, result_id=result_id, kind=kind, root=self.evidence_root, path=p)
        return p

    def contaminate(self, why: str) -> None:
        self.contaminated = True
        db.mark_contaminated(self.conn, self.run_id, why)

    def quick_checks(self) -> tuple[bool, list[tuple[str, list[dict]]]]:
        out, green = [], True
        try:
            f = self.field("check")
            out.append((self.vms["field"]["name"], f["checks"]))
            green &= f["green"]
        except L.LabError as e:
            out.append((self.vms["field"]["name"], [{"name": "control-channel", "status": "FAIL", "detail": str(e)}]))
            green = False
        c = L.quick_check_local(self.inv)
        out.append((self.vms["ctl"]["name"], c["checks"]))
        return green and c["green"], out

    def reset_both(self) -> str:
        msgs = []
        try:
            msgs.append("field: " + json.dumps(self.field("reset", timeout=150)))
        except L.LabError as e:
            msgs.append(f"field reset FAILED: {e}")
        msgs.append("ctl: " + L.reset_local())
        return "\n".join(msgs)


def _run_kind(items) -> str:
    kinds = {("fault" if "fault" in i.keywords else "commissioning") for i in items}
    return "baseline" if kinds == {"commissioning"} else "fault" if kinds == {"fault"} else "mixed"


def _check_builds(lab: Lab, items) -> str:
    """Run kind from what the field REPORTS (state.json build), not from a flag alone: a run against a
    mutant build is kind=mutant and must be declared with --mutant; an undeclared mutant, a declared
    mutant that is not deployed, or a mutant run with fault cases is refused (exit 3, no run row).
    If the control channel is down the builds stay unknown and the session preflight goes RED."""
    kind = _run_kind(items)
    try:
        lab.builds = lab.field("status")["builds"]
    except L.LabError:
        return "mutant" if lab.mutant_id else kind
    want = {d["instance"]: "stock" for d in lab.devices.values()}
    if lab.mutant_id:
        if lab.mutant_id not in catalog.MUTANTS_BY_ID:
            pytest.exit(f"unknown mutant {lab.mutant_id}; known: {sorted(catalog.MUTANTS_BY_ID)}", returncode=3)
        if kind != "baseline":
            pytest.exit("a mutant run executes the commissioning suite only (-m commissioning)", returncode=3)
        want[lab.devices[catalog.MUTANT_DEVICE]["instance"]] = \
            "mutant:" + catalog.mutant_spec(lab.mutant_id, lab.inv["devices"])
        kind = "mutant"
    if lab.builds != want:
        pytest.exit(f"refusing live run: field reports device builds {lab.builds}, expected {want} "
                    f"(declared mutant: {lab.mutant_id}); deploy/restore with scripts/lab_vms.sh mutant", returncode=3)
    return kind


def plan_instances(items) -> list[tuple[str, str | None]]:
    """(case, device or None) of every collected live case, as Case resolves it."""
    out = []
    for item in items:
        m = item.get_closest_marker("case")
        if m is not None:
            spec = catalog.CASES_BY_ID[m.args[0]]
            dev = item.callspec.params.get("device") if hasattr(item, "callspec") else None
            out.append((spec.case_id, dev if dev is not None else catalog.instance_device(spec)))
    return out


INTERRUPTED: list[str] = []


def _sigterm(signum, frame):
    # One-shot: a second SIGTERM (e.g. forwarded by `timeout`) must not abort the
    # reverts that the first one starts. Faults are also covered by dead-man timers.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    INTERRUPTED.append(f"SIGTERM at {db.utcnow()}")
    raise KeyboardInterrupt(f"signal {signum}")     # unwinds through every fixture finally


@pytest.fixture(scope="session")
def lab(request):
    try:
        lab = Lab(request.config)
    except L.LabError as e:
        pytest.exit(f"refusing live run: {e}", returncode=3)
    signal.signal(signal.SIGTERM, _sigterm)
    kind = _check_builds(lab, request.session.items)

    pf_ctl = L.preflight_local()
    try:
        pf_field = lab.field("preflight", *(["allow-mutant"] if lab.mutant_id else []), timeout=120)
    except L.LabError as e:
        pf_field = {"green": False, "checks": [{"name": "control-channel", "status": "FAIL", "detail": str(e)}],
                    "output": str(e)}
    lab.preflight_green = bool(pf_ctl["green"] and pf_field["green"])
    src = L.source_info()
    lab.run_id = db.start_run(lab.conn, kind=kind, git_sha=src.get("git_sha"),
                              git_dirty=int(src["git_dirty"]) if src.get("git_dirty") in ("0", "1") else None,
                              clean_env=int(lab.preflight_green), runner_host=platform.node(),
                              notes=request.config.getoption("--run-notes"), mutant_id=lab.mutant_id)
    aborted = db.mark_aborted_runs(lab.conn, lab.run_id)
    sess = lab.run_dir / "session"
    db.add_checks(lab.conn, lab.run_id, "preflight", lab.vms["ctl"]["name"], pf_ctl["checks"])
    db.add_checks(lab.conn, lab.run_id, "preflight", lab.vms["field"]["name"], pf_field["checks"])
    lab.save(sess, "preflight-ctl.txt", pf_ctl["output"], "preflight")
    lab.save(sess, "preflight-field.txt", pf_field.get("output", ""), "preflight")
    # declared selection (docs/acceptance-contract.md I1.3), before the first case: a result that is missing later is
    # "planned, not recorded", never "not part of this run" (final independent verification FV-01 class)
    lab.save(sess, "plan.json", db.record_plan(lab.conn, lab.run_id, plan_instances(request.session.items)), "plan")

    # ---- environment (REQ-10)
    env = {"python": platform.python_version(), "pytest": pytest.__version__,
           "git_sha": src.get("git_sha", ""), "git_dirty": src.get("git_dirty", ""),
           "source.synced_at": src.get("synced_at", ""), "source.lima": src.get("lima", ""),
           "runs.kind": kind, "mutant": lab.mutant_id or "none"}
    for dev_id, d in lab.devices.items():
        env[f"device_build.{dev_id}"] = str((lab.builds or {}).get(d["instance"], "unknown (field status failed)"))
    for k, v in L.local_env().items():
        env[f"{k}.{lab.vms['ctl']['name']}"] = v
    try:
        fe = lab.field("env", timeout=40)
        fe.pop("ok", None)
        env["chrony.offset"] = fe.pop("chrony.offset")
        for k, v in fe.items():
            env[f"{k}.{lab.vms['field']['name']}"] = v
    except L.LabError as e:
        env[f"env_error.{lab.vms['field']['name']}"] = str(e)
    for dev_id, d in lab.devices.items():
        o = single(d["hostname"], d["port"], "IDENTIFY")
        c = classify(o)
        env[f"fw_version.{dev_id}"] = c.payload["fw_version"] if c.payload and "fw_version" in c.payload \
            else f"unavailable ({c.category}: {c.detail})"
    db.put_env(lab.conn, lab.run_id, env)
    db.set_clean_env(lab.conn, lab.run_id, lab.preflight_green)
    lab.save(sess, "environment.json", json.dumps(env, indent=1, sort_keys=True), "environment")
    if aborted:
        print(f"\nwitness: earlier unfinished runs marked contaminated/aborted: {aborted}", file=sys.stderr)
    print(f"\nwitness run_id={lab.run_id} kind={kind}{' mutant=' + lab.mutant_id if lab.mutant_id else ''} "
          f"preflight={'GREEN' if lab.preflight_green else 'RED'} evidence={lab.run_dir}", file=sys.stderr)

    yield lab

    # ---- session teardown: never leave a fault behind
    try:
        st = lab.field("status")
        if lab.builds is not None and st.get("builds") != lab.builds:
            lab.contaminate(f"device build changed during the run: {lab.builds} -> {st.get('builds')}")
        if st["active_faults"] or st["deadman_armed"]:
            lab.contaminate(f"faults left at session end: {st['active_faults']}")
            lab.save(sess, "session-reset.txt", lab.reset_both(), "reset")
    except L.LabError as e:
        lab.contaminate(f"field status unavailable at session end: {e}")
    if not L.quick_check_local(lab.inv)["green"]:
        lab.contaminate("ctl fault state left at session end")
        lab.save(sess, "session-reset-ctl.txt", L.reset_local(), "reset")
    pf_ctl = L.preflight_local()
    try:
        pf_field = lab.field("preflight", *(["allow-mutant"] if lab.mutant_id else []), timeout=120)
    except L.LabError as e:
        pf_field = {"green": False, "checks": [{"name": "control-channel", "status": "FAIL", "detail": str(e)}], "output": str(e)}
    db.add_checks(lab.conn, lab.run_id, "session-postflight", lab.vms["ctl"]["name"], pf_ctl["checks"])
    db.add_checks(lab.conn, lab.run_id, "session-postflight", lab.vms["field"]["name"], pf_field["checks"])
    lab.save(sess, "postflight-ctl.txt", pf_ctl["output"], "postflight")
    lab.save(sess, "postflight-field.txt", pf_field.get("output", ""), "postflight")
    if not (pf_ctl["green"] and pf_field["green"]):
        lab.contaminate("session postflight red")
    lab.save(sess, "field-commands.jsonl", "\n".join(json.dumps(c, default=str) for c in lab.field.calls), "command-log")
    db.finish_run(lab.conn, lab.run_id)
    r = lab.conn.execute("SELECT clean_env, contaminated FROM runs WHERE run_id=?", (lab.run_id,)).fetchone()
    print(f"\nwitness run_id={lab.run_id} finished clean_env={r[0]} contaminated={r[1]}", file=sys.stderr)
    lab.conn.close()


# ---------------------------------------------------------------- per case

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    rep = (yield).get_result()
    setattr(item, f"rep_{rep.when}", rep)
    setattr(item, f"exc_{rep.when}", call.excinfo.value if call.excinfo else None)


class CaseDeadline(Exception):
    pass


class CaseBudget:
    """One real-time alarm over per-case setup and body; cleanup has its own bounded operations.

    The call hook stops the alarm BEFORE dependent fixtures revert faults. A timeout
    must end the observation, never interrupt its safety teardown.
    """

    def __init__(self, seconds=CASE_DEADLINE_S, started=None):
        self.end = (time.monotonic() if started is None else started) + seconds
        self.seconds, self.expired, self.active = seconds, False, False

    def start(self):
        self.old_handler = signal.signal(signal.SIGALRM, self._alarm)
        self.active = True
        signal.setitimer(signal.ITIMER_REAL, max(0.000001, self.end - time.monotonic()))
        return self

    def _alarm(self, signum, frame):
        self.expired = True
        raise CaseDeadline(f"case deadline {self.seconds}s exceeded (per-case setup and body)")

    def check(self):
        if self.expired or time.monotonic() >= self.end:
            self._alarm(None, None)

    def stop(self):
        if self.active:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self.old_handler)
            self.active = False


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    try:
        yield
    finally:
        c = getattr(item, "_witness_case", None)
        if c is not None:
            c.mark("body_end")
            c.budget.stop()
            for conn in c.connections:
                conn.close()
            if c.budget.expired and c.result_id is None:
                c.record_error("runner", f"case deadline {CASE_DEADLINE_S}s exceeded (per-case setup and body)")


class Case:
    def __init__(self, lab: Lab, request):
        m = request.node.get_closest_marker("case")
        if m is None:
            raise RuntimeError(f"{request.node.nodeid} has no @pytest.mark.case")
        self.lab, self.node = lab, request.node
        self.spec = catalog.CASES_BY_ID[m.args[0]]
        self.device_id = request.node.callspec.params.get("device") if hasattr(request.node, "callspec") else None
        if self.device_id is None:
            self.device_id = catalog.instance_device(self.spec)     # fault cases target FAULT_DEVICE (instance a)
        self.dir = lab.run_dir / f"{self.spec.case_id}__{self.device_id or 'run'}"
        self.t0_wall, self.t0 = time.time(), time.monotonic()
        self.calls0 = len(lab.field.calls)
        self.precheck_green = True
        self.pending_checks: list[tuple[str, str, list[dict]]] = []
        self.pending_files: list[tuple[str, str, str]] = []
        self.fault_events: list[dict] = []
        self.result_id: int | None = None
        self.t_apply_start: float | None = None   # ctl monotonic: just before the fault command
        self.t_applied: float | None = None       # ctl monotonic: fault confirmed applied
        self.capture: L.Capture | None = None
        self.field_capture: L.FieldCapture | None = None
        self.decision = None
        self.target = dict(lab.devices[self.device_id]) if self.device_id else None   # row the probe dials
        self.pending_measurements: list[tuple] = []
        self.marks: dict[str, float] = {"case_start": self.t0}
        self.counters_before: dict | None = None
        self.budget = CaseBudget(started=self.t0)
        self.inflight_attempt: Attempt | None = None
        self.connections: list = []

    @property
    def device(self) -> dict:
        return self.lab.devices[self.device_id]

    @property
    def is_fault(self) -> bool:
        return self.spec.kind == "fault"

    def mark(self, name: str) -> float:
        t = time.monotonic()
        self.marks[name] = t
        return t

    def measure(self, name: str, value, *, unit: str = "ms", bound=None, clock: str = "ctl-monotonic",
                detail: str = "") -> None:
        row = (name, None if value is None else float(value), unit, bound, clock, detail)
        if self.result_id is None:
            self.pending_measurements.append(row)
        else:
            db.add_measurement(self.lab.conn, self.result_id, name, row[1], unit=unit, bound=bound, clock=clock,
                               detail=detail)

    def file(self, name: str, text: str, kind: str) -> None:
        if self.result_id is None:
            self.pending_files.append((name, text, kind))
        else:
            self.lab.save(self.dir, name, text, kind, self.result_id)

    def _insert(self, *, expected, observed, first, attempts_n, latency, detection, verdict, attribution, detail,
                predicates=None):
        self.result_id = db.insert_result(
            self.lab.conn, run_id=self.lab.run_id, case_id=self.spec.case_id, device_id=self.device_id,
            fault_id=self.spec.fault_id, expected=expected, observed=observed, first_attempt=first,
            attempts=attempts_n, latency_ms=latency, detection_ms=detection, verdict=verdict,
            attribution=attribution, detail=detail,
            preflight="green" if (self.lab.preflight_green and self.precheck_green) else "red",
            evidence_path=str(self.dir.relative_to(self.lab.evidence_root)),
            observed_at=db.wall_to_iso(time.time()), duration_ms=(time.monotonic() - self.t0) * 1000,
            predicates=predicates)
        for phase, vm, checks in self.pending_checks:
            db.add_checks(self.lab.conn, self.lab.run_id, phase, vm, checks, self.result_id)
        for name, text, kind in self.pending_files:
            self.lab.save(self.dir, name, text, kind, self.result_id)
        for name, value, unit, bound, clock, detail in self.pending_measurements:
            db.add_measurement(self.lab.conn, self.result_id, name, value, unit=unit, bound=bound, clock=clock,
                               detail=detail)
        self.pending_checks.clear()
        self.pending_files.clear()
        self.pending_measurements.clear()

    def finish(self, attempts: list[Attempt], expected: str, *, extra_predicates=None, detection_ms=None):
        """Record the case (result + attempts + exchanges), then assert the verdict."""
        self.budget.check()
        d = decide(attempts, expected, preflight_green=self.lab.preflight_green and self.precheck_green,
                   extra_predicates=extra_predicates)
        self._insert(expected=expected, observed=attempts[-1].category, first=attempts[0].category,
                     attempts_n=len(attempts), latency=attempts[-1].first_latency_ms, detection=detection_ms,
                     verdict=d.verdict, attribution=d.attribution, detail=d.detail,
                     predicates={**attempts[-1].predicates, **(extra_predicates or {})})
        for a in attempts:
            dc = a.deciding
            db.insert_attempt(self.lab.conn, self.result_id, a.attempt_no, a.category, dc.stage if dc else None,
                              (dc.detail if dc else "") + (f"; {a.note}" if a.note else ""),
                              a.started_at, a.duration_ms, a.exchanges, outcome=a.outcome(expected),
                              predicates=a.predicates)
        self.decision = d
        assert d.verdict == "pass", f"{self.spec.case_id}/{self.device_id}: {d.verdict}/{d.attribution}: {d.detail}"
        return d

    def finish_observed(self, observed: str | None, expected: str, *, predicates: dict[str, bool],
                        detection_ms=None, latency_ms=None, what: str = ""):
        """Record a case whose observation is the gateway's poll (no runner attempt: attempts=0)."""
        self.budget.check()
        d = decide_observed(observed, expected, preflight_green=self.lab.preflight_green and self.precheck_green,
                            predicates=predicates, what=what)
        self._insert(expected=expected, observed=observed, first=observed, attempts_n=0, latency=latency_ms,
                     detection=detection_ms, verdict=d.verdict, attribution=d.attribution, detail=d.detail,
                     predicates=predicates)
        self.decision = d
        assert d.verdict == "pass", f"{self.spec.case_id}/{self.device_id}: {d.verdict}/{d.attribution}: {d.detail}"
        return d

    def finish_check(self, predicates: dict[str, bool], detail: str, device_caused: frozenset = frozenset()):
        """A non-network case (REQ-10): no observed category. A failure is the harness's (runner), except
        when every failed predicate is in `device_caused` (the device itself withheld the value, e.g. its
        IDENTIFY was MALFORMED so no firmware version could be recorded): then it is the device's."""
        self.budget.check()
        bad = sorted(k for k, v in predicates.items() if not v)
        if not (self.lab.preflight_green and self.precheck_green):
            verdict, attr = "error", "infra"
        elif not bad:
            verdict, attr = "pass", "none"
        else:
            verdict, attr = "fail", ("device" if set(bad) <= set(device_caused) else "runner")
        self._insert(expected=None, observed=None, first=None, attempts_n=0, latency=None, detection=None,
                     verdict=verdict, attribution=attr, detail=detail + (f"; failed: {','.join(bad)}" if bad else ""),
                     predicates=None if verdict == "error" else predicates)
        assert verdict == "pass", f"{self.spec.case_id}: {verdict}/{attr}: missing {bad}"

    def record_error(self, attribution: str, detail: str):
        if self.spec.fault_id:
            expected = catalog.FAULTS_BY_ID[self.spec.fault_id].expected_category
        else:
            expected = "PASS" if self.spec.per_device else None
        a = self.inflight_attempt if self.budget.expired else None
        if a is not None:
            a.deadline_exhausted = True
            a.note = "case_deadline_exhausted:overall live case; partial F12 observations retained"
            a.duration_ms = (time.monotonic() - self.marks.get("first_attempt", self.t0)) * 1000
        self._insert(expected=expected, observed=None, first=None, attempts_n=int(a is not None), latency=None, detection=None,
                     verdict="error", attribution=attribution, detail=detail[:2000])
        if a is not None:
            db.insert_attempt(self.lab.conn, self.result_id, a.attempt_no, None, "deadline", a.note,
                              a.started_at, a.duration_ms, a.exchanges, outcome="runner", predicates=a.predicates)

    def ensure_result(self) -> None:
        """If the test body or a fixture raised before recording, record error with the cause:
        infra when the lab control channel failed, runner for any other harness exception."""
        if self.result_id is not None:
            return
        if self.budget.expired:
            self.record_error("runner", f"case deadline {CASE_DEADLINE_S}s exceeded (per-case setup and body)")
            return
        exc = getattr(self.node, "exc_call", None) or getattr(self.node, "exc_setup", None)
        rep = getattr(self.node, "rep_call", None) or getattr(self.node, "rep_setup", None)
        if exc is None and (rep is None or not rep.failed):
            # pytest re-raises KeyboardInterrupt without a report
            why = f"runner interrupted ({', '.join(INTERRUPTED) or 'KeyboardInterrupt'}) before recording"
            self.record_error("runner", why)
            return
        text = rep.longreprtext[-1500:] if rep is not None and rep.failed else repr(exc)
        infra = isinstance(exc, L.LabError) and exc.infra
        self.record_error("infra" if infra else "runner", f"harness exception {type(exc).__name__}: {text}")

    def detection_ms(self) -> float | None:
        return None if self.t_applied is None else (time.monotonic() - self.t_applied) * 1000


def _record_capture_flows(lab: Lab, c: Case, pcaps: dict) -> None:
    """For every address:port the case's exchanges dialled (runner/lab.dialled_flows): was traffic expected on the
    wire, and how many packets of that flow does each capture hold? Rows go to capture_flows; an expected flow with
    0 packets is an evidence defect that the acceptance assertions and the report surface (it says nothing about
    the device, so the verdict is not changed)."""
    rows = lab.conn.execute("SELECT x.addr, x.port, x.local_port, x.stage_failed, x.os_error FROM attempts a "
                            "JOIN exchanges x USING (attempt_id) WHERE a.result_id = ?", (c.result_id,)).fetchall()
    for f in L.dialled_flows(rows):
        for cap, path in pcaps.items():
            bpf = L.flow_record_filter(f)
            n = L.count_packets(path, bpf) if path is not None and f["addr"] is not None else None
            missing = path is not None and f["addr"] is not None and not Path(path).exists()
            db.add_capture_flow(lab.conn, c.result_id, capture=cap, bpf=bpf, expected=f["expected"], packets=n,
                                detail=f["why"] + ("; capture file missing" if missing else ""))
            if f["expected"] and not n:
                print(f"\nwitness: EVIDENCE GAP {c.spec.case_id}/{c.device_id}: {cap} capture holds {n} packets of "
                      f"{bpf}", file=sys.stderr)


@pytest.fixture
def case(lab, request):
    c = Case(lab, request)
    request.node._witness_case = c
    c.budget.start()
    try:
        if not lab.preflight_green:
            c.precheck_green = False
            c.record_error("infra", "session preflight RED: case not executed (device never fairly tested)")
            pytest.fail("infra: session preflight red")
        green, checks = lab.quick_checks()
        c.pending_checks += [("precheck", vm, ch) for vm, ch in checks]
        if not green:
            lab.contaminate(f"precheck red before {c.spec.case_id}")
            c.file("precheck-reset.txt", lab.reset_both(), "reset")
            green, checks = lab.quick_checks()
            c.pending_checks += [("precheck", vm, ch) for vm, ch in checks]
            if not green:
                c.precheck_green = False
                c.record_error("infra", "precheck red and reset did not restore the lab; case not executed")
                pytest.fail("infra: precheck red after reset")
        extra_ports = catalog.FAULTS_BY_ID[c.spec.fault_id].capture_ports if c.spec.fault_id else ()
        c.capture = L.Capture(c.dir / "capture.pcap",
                              bpf=L.capture_filter([d["port"] for d in lab.devices.values()] + list(extra_ports))).start()
        if c.is_fault:
            c.field_capture = L.FieldCapture(lab.field, f"run{lab.run_id}-{c.spec.case_id}-{c.device_id or 'run'}",
                                             c.dir / "capture-field.pcap", extra_ports=extra_ports)
            c.field_capture.start()
        # Probe/retry contexts reuse the time already spent on setup. The real-time
        # alarm also bounds direct GW HTTP, fault commands, reconnects and sleeps.
        with case_deadline(max(0.0, c.budget.end - time.monotonic())):
            yield c
    finally:
        c.budget.stop()
        c.mark("cleanup_start")
        for conn in c.connections:
            conn.close()
        txt = c.capture.stop() if c.capture else None
        ftxt = fpcap = None
        if c.field_capture is not None:
            try:
                fpcap, ftxt = c.field_capture.stop()
            except L.LabError as e:
                c.file("capture-field-error.txt", str(e), "pcap-text")
        c.ensure_result()
        pcap = c.dir / "capture.pcap"
        if pcap.exists():
            db.add_evidence(lab.conn, run_id=lab.run_id, result_id=c.result_id, kind="pcap", root=lab.evidence_root, path=pcap)
        if txt and txt.exists():
            db.add_evidence(lab.conn, run_id=lab.run_id, result_id=c.result_id, kind="pcap-text", root=lab.evidence_root, path=txt)
        if fpcap and fpcap.exists():
            db.add_evidence(lab.conn, run_id=lab.run_id, result_id=c.result_id, kind="pcap-field", root=lab.evidence_root,
                            path=fpcap)
        if ftxt and ftxt.exists():
            db.add_evidence(lab.conn, run_id=lab.run_id, result_id=c.result_id, kind="pcap-field-text",
                            root=lab.evidence_root, path=ftxt)
        try:
            _record_capture_flows(lab, c, {"ctl": pcap, **({"field": fpcap or c.dir / "capture-field.pcap"}
                                                         if c.is_fault else {})})
        except Exception as e:  # noqa: BLE001 - evidence bookkeeping must not skip the postflight below
            c.file("capture-flows-error.txt", f"{type(e).__name__}: {e}", "pcap-flow")
        green, checks = lab.quick_checks()
        for vm, ch in checks:
            db.add_checks(lab.conn, lab.run_id, "postflight", vm, ch, c.result_id)
        db.set_postflight(lab.conn, c.result_id, green)
        if not green:
            lab.contaminate(f"postflight red after {c.spec.case_id}")
            c.file("postflight-reset.txt", lab.reset_both(), "reset")
        inst = c.device.get("instance") if c.device_id else None
        if inst:
            try:
                j = lab.field("journal", inst, f"{c.t0_wall - 1:.3f}")["journal"]
                c.file(f"journal-witness-device@{inst}.txt", j, "journal")
            except L.LabError as e:
                c.file("journal-error.txt", str(e), "journal")
        try:
            c.file("journal-witness-gateway.txt", L.gateway_journal(c.t0_wall - 1), "journal")
        except (OSError, L.LabError) as e:
            c.file("journal-gateway-error.txt", str(e), "journal")
        c.file("field-commands.jsonl", "\n".join(json.dumps(x, default=str) for x in lab.field.calls[c.calls0:]),
               "command-log")
        c.file("timing.json", json.dumps({"clock": "ctl CLOCK_MONOTONIC seconds", "t0_wall": db.wall_to_iso(c.t0_wall),
                                          "marks": {k: round(v, 6) for k, v in c.marks.items()},
                                          "offsets_ms": {k: round((v - c.t0) * 1000, 1) for k, v in c.marks.items()}},
                                         indent=1), "timing")


# ---------------------------------------------------------------- faults

class Injector:
    """inject(fault_id) applies one catalogued fault; inject.revert() removes it early (so a test
    can measure recovery); the fixture's finally reverts whatever is still applied. Every revert
    first snapshots the faulted state (field + ctl), records a fault_event, verifies the removal,
    and marks the run contaminated + resets the lab when it cannot verify it."""

    def __init__(self, case: Case, lab: Lab):
        self.case, self.lab = case, lab
        self.applied: list[dict] = []
        self.applications: dict[str, int] = {}     # fault_id -> times applied in this case (F12 restarts twice)

    def __call__(self, fault_id: str) -> dict:
        return self.apply(fault_id)

    def apply(self, fault_id: str) -> dict:
        case, lab = self.case, self.lab
        spec = catalog.FAULTS_BY_ID[fault_id]
        if spec.fault_id != case.spec.fault_id:
            raise RuntimeError(f"case {case.spec.case_id} is catalogued with {case.spec.fault_id}, not {fault_id}")
        inst = case.device["instance"]
        field_vm, ctl_vm = lab.vms["field"]["name"], lab.vms["ctl"]["name"]
        if spec.kind in ("inventory-addr", "nft"):
            case.counters_before = lab.field("counters")["counters"]
            case.file("counters-before.json", json.dumps(case.counters_before, indent=1, sort_keys=True), "counters")
        # evidence names and marks per APPLICATION: F12 applies its fault twice, and an unnumbered second
        # application overwrote the first one's indexed files (runs 133-138, found by the evidence-hash check)
        n = self.applications[fault_id] = self.applications.get(fault_id, 0) + 1
        tag = fault_id if n == 1 else f"{fault_id}.{n}"
        case.t_apply_start = case.mark(f"apply_start:{tag}")
        vm = field_vm
        if spec.kind == "service-stop":
            r = lab.field("apply", "service-stop", inst)
            revert = lambda: lab.field("revert", "service-stop", inst)  # noqa: E731
        elif spec.kind == "sigstop":
            r = lab.field("apply", "sigstop", inst)
            pid, st = str(r["pid"]), str(r["starttime"])
            revert = lambda: lab.field("revert", "sigstop", inst, pid, st)  # noqa: E731
        elif spec.kind == "netem":
            delay = fault_id.split("-")[1]
            r = lab.field("apply", "netem", delay, "data" if fault_id.endswith("-data") else "all")
            revert = lambda: lab.field("revert", "netem")  # noqa: E731
        elif spec.kind == "device-mode":
            r = lab.field("apply", "mode", inst, catalog.DEVICE_MODES[fault_id])
            revert = lambda: lab.field("revert", "mode", inst)  # noqa: E731
        elif spec.kind == "nft":
            r = lab.field("apply", "nft", catalog.NFT_KINDS[fault_id], inst)
            revert = lambda: lab.field("revert", "nft")  # noqa: E731
        elif spec.kind == "service-restart":
            r = lab.field("apply", "restart", inst)
            revert = lambda: lab.field("revert", "restart", inst)  # noqa: E731
        elif spec.kind == "route-delete":
            vm = ctl_vm
            rd = L.RouteDelete(lab.inv)
            line = rd.apply()
            r = {"applied_at": db.utcnow(), "verified": rd.applied(), "detail": line}

            def revert():
                ok = rd.revert()
                return {"removed_at": db.utcnow(), "verified": ok, "detail": f"route restored: {rd.route()}"}
        elif spec.kind in ("hosts-swap", "hosts-remove", "inventory-addr"):
            vm = ctl_vm
            if spec.kind == "hosts-swap":
                to = next(d for d in lab.inv["devices"] if d["device_id"] != case.device_id)["address"]
            elif spec.kind == "hosts-remove":
                to = None
            else:
                to = catalog.UNUSED_ADDR
                if to in {d["address"] for d in lab.inv["devices"]}:
                    raise RuntimeError(f"F4 address {to} is in the inventory: not unused")
                case.target = {**case.device, "address": to}
                self._save_faulted_inventory()
            sw = L.HostsSwap(lab.inv, case.device["hostname"], to)
            line = sw.apply()

            def revert():
                ok = sw.revert()
                case.target = dict(case.device)
                return {"removed_at": db.utcnow(), "verified": ok, "detail": "restored original /etc/hosts bytes"}
            r = {"applied_at": db.utcnow(), "verified": True, "detail": f"/etc/hosts now has {line!r}"}
            case.file(f"hosts-during-{tag}.txt", Path("/etc/hosts").read_text(), "hosts")
        elif spec.kind == "inventory-port":
            vm = f"{ctl_vm} (runner inventory copy only)"
            case.target = {**case.device, "port": catalog.WRONG_PORT}
            self._save_faulted_inventory()

            def revert():
                case.target = dict(case.device)
                return {"removed_at": db.utcnow(), "verified": True, "detail": "runner inventory copy discarded"}
            r = {"applied_at": db.utcnow(), "verified": True,
                 "detail": f"runner dials {case.target['hostname']}:{catalog.WRONG_PORT}; no VM state changed"}
        else:
            raise RuntimeError(f"unknown fault kind {spec.kind}")
        self.applied.append({"fault_id": fault_id, "tag": tag, "vm": vm, "revert": revert,
                             "applied_at": r.get("applied_at")})
        case.file(f"fault-apply-{tag}.json", json.dumps(r, indent=1), "fault-apply")
        if not r.get("verified"):
            raise L.LabError(f"fault {fault_id} could not be verified as applied: {r.get('detail')}")
        case.t_applied = case.mark(f"applied:{tag}")
        return r

    def _save_faulted_inventory(self) -> None:
        inv = {**self.lab.inv, "devices": [self.case.target if d["device_id"] == self.case.device_id else d
                                           for d in self.lab.inv["devices"]]}
        self.case.file("inventory-faulted.yaml", yaml.safe_dump(inv, sort_keys=False), "inventory")

    def revert(self, fault_id: str | None = None) -> dict | None:
        """Revert one applied fault now (the latest, or `fault_id`); returns the revert reply."""
        case, lab = self.case, self.lab
        idx = next((i for i in range(len(self.applied) - 1, -1, -1)
                    if fault_id is None or self.applied[i]["fault_id"] == fault_id), None)
        if idx is None:
            return None
        a = self.applied.pop(idx)
        fid, tag = a["fault_id"], a["tag"]
        try:
            snap = lab.field("snapshot")
            case.file(f"snapshot-during-{tag}.txt", "\n".join(f"== {k}\n{v}" for k, v in snap.items() if k != "ok"),
                      "snapshot")
        except L.LabError as e:
            case.file(f"snapshot-during-{tag}.txt", f"snapshot failed: {e}", "snapshot")
        try:
            case.file(f"snapshot-ctl-during-{tag}.txt", L.ctl_snapshot(lab.inv), "snapshot")
        except Exception as e:  # noqa: BLE001 - evidence must not block the revert
            case.file(f"snapshot-ctl-during-{tag}.txt", f"ctl snapshot failed: {e}", "snapshot")
        case.mark(f"revert_start:{tag}")
        removed, verified, detail, rr = None, False, "", None
        try:
            rr = a["revert"]()
            removed, verified, detail = rr.get("removed_at"), bool(rr.get("verified")), rr.get("detail", "")
        except Exception as e:  # noqa: BLE001 - every failure must still be recorded and reset
            detail = f"revert raised {type(e).__name__}: {e}"
        case.mark(f"reverted:{tag}")
        if rr is not None:
            case.file(f"fault-revert-{tag}.json", json.dumps(rr, indent=1), "fault-revert")
        if not verified:
            lab.contaminate(f"revert of {fid} not verified: {detail}")
            case.file(f"revert-reset-{tag}.txt", lab.reset_both(), "reset")
        case.fault_events.append(dict(fault_id=fid, vm=a["vm"], applied_at=a["applied_at"], removed_at=removed,
                                      removal_verified=verified, detail=detail))
        return rr

    def revert_all(self) -> None:
        while self.applied:
            self.revert()


@pytest.fixture
def inject(case, lab):
    inj = Injector(case, lab)
    try:
        yield inj
    finally:
        inj.revert_all()
        # fault events reference the result row (recorded by the test body, or as an error now)
        case.ensure_result()
        for ev in case.fault_events:
            db.add_fault_event(lab.conn, run_id=lab.run_id, result_id=case.result_id, **ev)
