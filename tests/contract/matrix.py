"""Mutation matrix of the acceptance-contract harness: each entry attacks a reference store and DECLARES, before
anything runs, the contract invariant it breaks and the acceptance assertion(s) that must report it.

Expectations (docs/acceptance-contract.md): `must` = assertions that must all be violated; `accept` = the store must
keep exactly its variant's own outcome (benign changes, legitimate controls). Every REJECT expectation is also
confirmed independently by the oracle (tests/contract/oracle.py). `needs_plan`: the mutation attacks the run plan,
which exists only from schema v5. `files`: the mutation changes the evidence tree (applied to a private copy).
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from tests.contract import refstore as R

RUNNER_CASES_B = [(c, d) for c, per in R.catalog.COMMISSIONING_REQUIRED for d in (R.DEVICES if per else [None])
                  if c not in ("C-GATEWAY", "C-ENVIRONMENT")]
FAULT_CASES = [c.case_id for c in R.catalog.CASES if c.kind == "fault"]
RUNNER_FAULT_CASES = [c for c in FAULT_CASES if not c.startswith("GW-")]


class Ctx:
    """A mutable copy of a reference store: SQL helpers in the reference's own terms (run labels, instances)."""

    def __init__(self, conn, root: Path, ref: R.Ref):
        self.conn, self.root, self.ref = conn, root, ref

    def run(self, label: str) -> int:
        return self.ref.runs[label]

    def rid(self, label: str, case: str, dev: str | None = "dev-a") -> int:
        dev = dev if case != "C-ENVIRONMENT" else None
        r = self.conn.execute("SELECT result_id FROM results WHERE run_id = ? AND case_id = ? AND device_id IS ?",
                              (self.run(label), case, dev)).fetchone()
        assert r is not None, (label, case, dev)
        return r[0]

    def x(self, sql: str, *args):
        return self.conn.execute(sql, args)

    def has(self, table: str) -> bool:
        return self.x("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", table).fetchone() is not None

    def has_column(self, table: str, column: str) -> bool:
        return any(r[1] == column for r in self.x(f"PRAGMA table_info({table})"))

    def fk(self, on: bool):
        self.conn.execute(f"PRAGMA foreign_keys = {'ON' if on else 'OFF'}")

    def delete_result(self, rid: int, *, plan: bool = False) -> None:
        """A result and everything that references it (a cascade an adversary performs with keys enforced)."""
        r = self.x("SELECT run_id, case_id, device_id FROM results WHERE result_id = ?", rid).fetchone()
        self.x("DELETE FROM exchanges WHERE attempt_id IN (SELECT attempt_id FROM attempts WHERE result_id = ?)", rid)
        for t in ("attempts", "capture_flows", "evidence", "checks", "measurements", "fault_events"):
            self.x(f"DELETE FROM {t} WHERE result_id = ?", rid)
        self.x("DELETE FROM results WHERE result_id = ?", rid)
        if plan:
            self.x("DELETE FROM run_plan WHERE run_id = ? AND case_id = ? AND device_id IS ?", *r)

    def evidence_path(self, label: str, rel: str) -> Path:
        return self.root / f"run-{self.run(label)}" / rel

    def reindex(self, path: Path) -> None:
        data = path.read_bytes()
        self.x("UPDATE evidence SET sha256 = ?, bytes = ? WHERE path = ?", hashlib.sha256(data).hexdigest(),
               len(data), str(path.relative_to(self.root)))

    def file_of(self, rid: int, kind: str) -> Path:
        return self.root / self.x("SELECT path FROM evidence WHERE result_id = ? AND kind = ?", rid, kind).fetchone()[0]


@dataclass
class Mutation:
    name: str
    invariant: str                  # docs/acceptance-contract.md id
    apply: Callable[[Ctx], None]
    must: frozenset = frozenset()   # assertions that must all be violated (REJECT)
    accept: bool = False            # benign: the variant's own outcome must stand
    needs_plan: bool = False
    files: bool = False
    base: str = "reference"
    family: str = ""


def M(name, invariant, apply, must=(), **kw) -> Mutation:
    return Mutation(name, invariant, apply, frozenset(must), **kw)


# ---------------------------------------------------------------- primitive attacks (also used by the combinator)

def del_exchanges(label, case, dev="dev-a"):
    return lambda c: c.x("DELETE FROM exchanges WHERE attempt_id IN (SELECT attempt_id FROM attempts "
                         "WHERE result_id = ?)", c.rid(label, case, dev))


def del_attempts(label, case, dev="dev-a"):
    def f(c):
        rid = c.rid(label, case, dev)
        c.x("DELETE FROM exchanges WHERE attempt_id IN (SELECT attempt_id FROM attempts WHERE result_id = ?)", rid)
        c.x("DELETE FROM attempts WHERE result_id = ?", rid)
    return f


def del_capture_index(label, case, dev, kind):
    return lambda c: c.x("DELETE FROM evidence WHERE result_id = ? AND kind = ?", c.rid(label, case, dev), kind)


def set_flow(label, case, cap, sql_set, dev="dev-a"):
    return lambda c: c.x(f"UPDATE capture_flows SET {sql_set} WHERE result_id = ? AND capture = ?",
                         c.rid(label, case, dev), cap)


def unrelated_pcap(label, case, dev, kind):
    def f(c):
        p = c.file_of(c.rid(label, case, dev), kind)
        p.write_bytes(R.pcap([R.tcp_frame("10.77.1.10", "10.77.1.20", 22, 50022, 0x18)] * 4))
        c.reindex(p)
    return f


def dup_result(label, case, dev, first, second):
    """Two results for one instance: the existing row set to `first`, a copy with `second` added after it."""
    def f(c):
        rid = c.rid(label, case, dev)
        c.x("UPDATE results SET verdict = ?, attribution = ? WHERE result_id = ?", first,
            "none" if first == "pass" else "device", rid)
        c.x("INSERT INTO results (run_id, case_id, device_id, fault_id, expected_category, observed_category, "
            "first_attempt_category, attempts, latency_ms, detection_ms, verdict, attribution, detail, preflight, "
            "postflight, evidence_path, observed_at, duration_ms) SELECT run_id, case_id, device_id, fault_id, "
            "expected_category, observed_category, first_attempt_category, attempts, latency_ms, detection_ms, ?, ?, "
            "detail, preflight, postflight, evidence_path, observed_at, duration_ms FROM results WHERE result_id = ?",
            second, "none" if second == "pass" else "device", rid)
    return f


def swap_devices(label, case):
    def f(c):
        a, b = c.rid(label, case, "dev-a"), c.rid(label, case, "dev-b")
        c.fk(False)
        c.x("UPDATE results SET device_id = 'tmp' WHERE result_id = ?", a)
        c.x("UPDATE results SET device_id = 'dev-a' WHERE result_id = ?", b)
        c.x("UPDATE results SET device_id = 'dev-b' WHERE result_id = ?", a)
        c.fk(True)
    return f


def endpoint_port_coordinated(c):
    """F3 rewritten to have dialled the inventoried port 5020: exchange, flow records and counts all agree."""
    rid = c.rid("F", "FT-F3-WRONG-PORT")
    c.x("UPDATE exchanges SET port = 5020 WHERE attempt_id IN (SELECT attempt_id FROM attempts WHERE result_id = ?)",
        rid)
    for cap, kind in (("ctl", "pcap"), ("field", "pcap-field")):
        frames = R.pcap_frames(c.file_of(rid, kind).read_bytes())
        n = sum(1 for fr in frames if R.matches(fr, "10.77.2.11", 5020, None))
        c.x("UPDATE capture_flows SET filter = 'tcp and host 10.77.2.11 and port 5020', packets = ? "
            "WHERE result_id = ? AND capture = ?", n, rid, cap)


def erase_source_port(label, case, dev):
    """The final verification's gap probe: the connection's local port erased, its flow filter widened to the
    address:port (which the gateway's polls share) and every count made consistent with the capture."""
    def f(c):
        rid = c.rid(label, case, dev)
        c.x("UPDATE exchanges SET local_port = NULL WHERE attempt_id IN (SELECT attempt_id FROM attempts WHERE "
            "result_id = ?)", rid)
        addr, port = R.DEV[dev]["address"], R.DEV[dev]["port"]
        for cap, kind in (("ctl", "pcap"),):
            n = sum(1 for fr in R.pcap_frames(c.file_of(rid, kind).read_bytes()) if R.matches(fr, addr, port, None))
            c.x("UPDATE capture_flows SET filter = ?, packets = ? WHERE result_id = ? AND capture = ?",
                f"tcp and host {addr} and port {port}", n, rid, cap)
    return f


def degrade_to_green(steps: int):
    """On the current-failure variant: rewrite B's failing C-HEALTH/dev-a result into a pass, `steps` layers deep."""
    def f(c):
        rid = c.rid("B", "C-HEALTH")
        c.x("UPDATE results SET verdict = 'pass', attribution = 'none' WHERE result_id = ?", rid)
        if steps >= 2:
            c.x("DELETE FROM exchanges WHERE attempt_id IN (SELECT attempt_id FROM attempts WHERE result_id = ? "
                "AND attempt_no = 2)", rid)
            c.x("DELETE FROM attempts WHERE result_id = ? AND attempt_no = 2", rid)
            c.x("UPDATE results SET attempts = 1 WHERE result_id = ?", rid)
        if steps >= 3:
            c.x("UPDATE attempts SET outcome = 'ok', predicates = ? WHERE result_id = ?",
                json.dumps({"sensor_ok": True, "status_ok": True}, sort_keys=True), rid)
    return f


def flag(sql):
    return lambda c: c.x(f"UPDATE runs SET {sql} WHERE run_id = ?", c.run("B"))


def del_session(kind=None):
    return lambda c: c.x("DELETE FROM evidence WHERE run_id = ? AND result_id IS NULL"
                         + (" AND kind = ?" if kind else ""), c.run("B"), *([kind] if kind else []))


def rm_file(label, rel):
    return lambda c: c.evidence_path(label, rel).unlink()


def rm_case_dir(label, case, dev):
    def f(c):
        import shutil
        shutil.rmtree(c.evidence_path(label, f"{case}__{dev or 'run'}"))
    return f


def damage(label, rel):
    def f(c):
        p = c.evidence_path(label, rel)
        p.write_bytes(p.read_bytes()[:-7])
    return f


def del_run_all(label):
    def f(c):
        run = c.run(label)
        for (rid,) in c.x("SELECT result_id FROM results WHERE run_id = ?", run).fetchall():
            c.delete_result(rid)
        for t in ("evidence", "checks", "fault_events", "environment", "run_plan"):
            if c.has(t):
                c.x(f"DELETE FROM {t} WHERE run_id = ?", run)
        c.x("DELETE FROM runs WHERE run_id = ?", run)
    return f


def del_device(dev):
    def f(c):
        for (rid,) in c.x("SELECT result_id FROM results WHERE device_id = ?", dev).fetchall():
            c.delete_result(rid)
        if c.has("run_plan"):
            c.x("DELETE FROM run_plan WHERE device_id = ?", dev)
        c.x("DELETE FROM devices WHERE device_id = ?", dev)
    return f


def forget_device(dev):
    """Every record of `dev` in the store and its evidence tree removed consistently (results and children, plan
    rows, plan files rewritten and re-indexed, case directories, the devices row): only the inventory, which is not
    in the store, still names it."""
    def f(c):
        import shutil
        del_device(dev)(c)
        for lab in c.ref.runs:
            run_dir = c.evidence_path(lab, "")
            for d in run_dir.glob(f"*__{dev}"):
                shutil.rmtree(d)
            plan = run_dir / "session" / "plan.json"
            if plan.is_file():
                doc = json.loads(plan.read_text())
                doc["instances"] = [i for i in doc["instances"] if i[1] != dev]
                plan.write_text(json.dumps(doc, indent=1) + "\n")
                c.reindex(plan)
    return f


def orphan(table, where, label, case, dev="dev-a"):
    def f(c):
        rid = c.rid(label, case, dev)
        c.fk(False)
        c.x(f"DELETE FROM {table} WHERE {where}", rid)
        c.fk(True)
    return f


# ---------------------------------------------------------------- the declared matrix

def build_matrix() -> list[Mutation]:
    out: list[Mutation] = []
    add = out.append
    # -- missing evidence: every required instance in turn (B, F, a mutant catch, a fresh trial)
    for case, dev in [(c, d) for c, per in R.catalog.COMMISSIONING_REQUIRED for d in (R.DEVICES if per else [None])]:
        # the planned instance stays current (A4) and B stays A18's run, now with a gap: no fall-back to T5
        add(M(f"del-result B {case}/{dev or 'run'}", "I1.4/I1.5/I10.1",
              (lambda c, case=case, dev=dev: c.delete_result(c.rid("B", case, dev))),
              ["A23", "A4", "A18"] if R.HAS_PLAN else ["A23"], family="del-result"))
    for case in FAULT_CASES:
        add(M(f"del-result F {case}", "I1.4/I1.5/I10.1", (lambda c, case=case: c.delete_result(c.rid("F", case))),
              ["A23", "A4"] if R.HAS_PLAN else ["A23"], family="del-result"))
    add(M("del-result M2 C-IDENTIFY/dev-a (the catch)", "I1.4", lambda c: c.delete_result(c.rid("M2", "C-IDENTIFY")),
          ["A23"], family="del-result"))
    add(M("del-result T3 C-HEALTH/dev-b", "I1.4", lambda c: c.delete_result(c.rid("T3", "C-HEALTH", "dev-b")),
          ["A23", "A14"], family="del-result"))
    # -- missing observation children of every current runner result
    for case, dev in RUNNER_CASES_B:
        add(M(f"del-exchanges B {case}/{dev}", "I5.1", del_exchanges("B", case, dev), ["A24"], family="del-exchanges"))
        add(M(f"del-attempts B {case}/{dev}", "I4.1/I4.2", del_attempts("B", case, dev), ["A24"],
              family="del-attempts"))
    for case in RUNNER_FAULT_CASES:
        add(M(f"del-exchanges F {case}", "I5.1", del_exchanges("F", case), ["A24"], family="del-exchanges"))
        add(M(f"del-attempts F {case}", "I4.1/I4.2", del_attempts("F", case), ["A24"], family="del-attempts"))
    add(M("del-exchanges M6 C-READ-SERIES/dev-a (FLAKE)", "I5.1", del_exchanges("M6", "C-READ-SERIES"), ["A24"]))
    add(M("FV-01 exact: del F3 exchanges + field flow", "I5.1/I8.1",
          lambda c: (del_exchanges("F", "FT-F3-WRONG-PORT")(c),
                     c.x("DELETE FROM capture_flows WHERE result_id = ? AND capture = 'field'",
                         c.rid("F", "FT-F3-WRONG-PORT"))), ["A24", "A17"]))
    add(M("FV-01 variant: del F3 exchanges + packets 999", "I5.1/I9",
          lambda c: (del_exchanges("F", "FT-F3-WRONG-PORT")(c), set_flow("F", "FT-F3-WRONG-PORT", "ctl", "packets=999")(c),
                     set_flow("F", "FT-F3-WRONG-PORT", "field", "packets=999")(c)), ["A24", "A17", "A20"]))
    add(M("FV-01: del F3 exchanges, attempts, flows and evidence index", "I4.2/I7",
          lambda c: (del_attempts("F", "FT-F3-WRONG-PORT")(c),
                     c.x("DELETE FROM capture_flows WHERE result_id = ?", c.rid("F", "FT-F3-WRONG-PORT")),
                     c.x("DELETE FROM evidence WHERE result_id = ?", c.rid("F", "FT-F3-WRONG-PORT"))), ["A24"]))
    add(M("del attempts + results.attempts=0 (B C-IDENTIFY/dev-a)", "I4.2",
          lambda c: (del_attempts("B", "C-IDENTIFY")(c),
                     c.x("UPDATE results SET attempts = 0 WHERE result_id = ?", c.rid("B", "C-IDENTIFY"))), ["A24"]))
    add(M("del one middle exchange (B C-READ-SERIES/dev-a ord 5)", "I5.1",
          lambda c: c.x("DELETE FROM exchanges WHERE ord = 5 AND attempt_id IN (SELECT attempt_id FROM attempts "
                        "WHERE result_id = ?)", c.rid("B", "C-READ-SERIES")), ["A24"]))
    add(M("truncate READ series to its first exchange (B C-READ-SERIES/dev-a)", "I5.2",
          lambda c: c.x("DELETE FROM exchanges WHERE ord > 1 AND attempt_id IN (SELECT attempt_id FROM attempts "
                        "WHERE result_id = ?)", c.rid("B", "C-READ-SERIES")), ["A24"]))
    add(M("truncate READ series after 3 READs (B C-READ-CLOCK/dev-b)", "I5.2",
          lambda c: c.x("DELETE FROM exchanges WHERE ord > 3 AND attempt_id IN (SELECT attempt_id FROM attempts "
                        "WHERE result_id = ?)", c.rid("B", "C-READ-CLOCK", "dev-b")), ["A24"]))
    add(M("del field flow row (F FT-F3)", "I8.1", lambda c: c.x("DELETE FROM capture_flows WHERE result_id = ? AND "
          "capture = 'field'", c.rid("F", "FT-F3-WRONG-PORT")), ["A17"]))
    add(M("del every field flow row of run F", "I8.1", lambda c: c.x("DELETE FROM capture_flows WHERE capture = "
          "'field' AND result_id IN (SELECT result_id FROM results WHERE run_id = ?)", c.run("F")), ["A17"]))
    add(M("del every flow row (B C-IDENTIFY/dev-a)", "I8.1", lambda c: c.x("DELETE FROM capture_flows WHERE "
          "result_id = ?", c.rid("B", "C-IDENTIFY")), ["A17"]))
    for (lab, case, dev, kind) in [("B", "C-IDENTIFY", "dev-a", "pcap"), ("B", "C-GATEWAY", "dev-a", "pcap"),
                                   ("B", "C-ENVIRONMENT", None, "pcap"), ("F", "GW-F1-UNREACHABLE", "dev-a", "pcap-field"),
                                   ("F", "FT-F5-NO-ROUTE", "dev-a", "pcap-field"),
                                   ("F", "FT-F7-NAME-MISSING", "dev-a", "pcap"), ("F", "FT-F3-WRONG-PORT", "dev-a", "pcap"),
                                   ("M4", "C-IDENTIFY", "dev-a", "pcap")]:
        add(M(f"del capture index {lab} {case}/{dev or 'run'} {kind}", "I7", del_capture_index(lab, case, dev, kind),
              ["A24"], family="del-capture-index"))
    add(M("del both capture indexes (F FT-F3)", "I7", lambda c: (del_capture_index("F", "FT-F3-WRONG-PORT", "dev-a",
          "pcap")(c), del_capture_index("F", "FT-F3-WRONG-PORT", "dev-a", "pcap-field")(c)), ["A24", "A20"]))
    add(M("del every evidence row of B's C-GATEWAY results", "I7/I10.3",
          lambda c: c.x("DELETE FROM evidence WHERE result_id IN (SELECT result_id FROM results WHERE run_id = ? AND "
                        "case_id = 'C-GATEWAY')", c.run("B")), ["A24"]))
    add(M("del gateway record index (F GW-F5)", "I10.3", del_capture_index("F", "GW-F5-UNREACHABLE", "dev-a",
                                                                         "gateway"), ["A24"]))
    add(M("del B session evidence index", "I10.4", del_session(), ["A23"]))
    add(M("del B session environment index", "I10.4", del_session("environment"), ["A23"]))
    add(M("damage ctl capture file (F FT-F3)", "I9", damage("F", "FT-F3-WRONG-PORT__dev-a/capture.pcap"), ["A20"],
          files=True))
    add(M("delete ctl capture file (B C-HEALTH/dev-a)", "I9", rm_file("B", "C-HEALTH__dev-a/capture.pcap"), ["A20"],
          files=True))
    add(M("delete session environment.json (B)", "I9", rm_file("B", "session/environment.json"), ["A20"], files=True))
    add(M("delete a case evidence directory (B C-HEALTH/dev-b)", "I1.5/I9", rm_case_dir("B", "C-HEALTH", "dev-b"),
          ["A20", "A23"], files=True))
    add(M("del env key python (B)", "I2", lambda c: c.x("DELETE FROM environment WHERE run_id = ? AND key = 'python'",
                                                      c.run("B")), ["A13"]))
    add(M("del whole run B (rows only, its evidence tree stays)", "I1.5", del_run_all("B"), ["A23"]))
    add(M("orphan: devices row dev-b deleted with keys off", "I1.1/I2",
          lambda c: (c.fk(False), c.x("DELETE FROM devices WHERE device_id = 'dev-b'"), c.fk(True)), ["A21", "A22"]))
    add(M("FV-02: dev-b and all its records deleted", "I3", del_device("dev-b"), ["A21", "A18"]))
    add(M("FV-02 fully coordinated: dev-b gone from rows, plans, re-hashed plan files and directories", "I3",
          forget_device("dev-b"), ["A21", "A18"], files=True))
    add(M("del case->requirement C-READ-SERIES/REQ-05", "I2", lambda c: c.x("DELETE FROM case_requirements WHERE "
          "case_id = 'C-READ-SERIES'"), ["A21"]))
    add(M("del F12's second fault application", "I10.2", lambda c: c.x("DELETE FROM fault_events WHERE event_id = "
          "(SELECT max(event_id) FROM fault_events WHERE result_id = ?)", c.rid("F", "FT-F12-RESTART")), ["A24"]))
    add(M("del F3's fault application", "I10.2", lambda c: c.x("DELETE FROM fault_events WHERE result_id = ?",
                                                               c.rid("F", "FT-F3-WRONG-PORT")), ["A9"]))
    add(M("del GW-F1 measurements", "I10.3", lambda c: c.x("DELETE FROM measurements WHERE result_id = ?",
                                                           c.rid("F", "GW-F1-UNREACHABLE")), ["A24"]))
    add(M("del one F12 measurement", "I10.3", lambda c: c.x("DELETE FROM measurements WHERE result_id = ? AND name = "
          "'gateway_recovery_ms'", c.rid("F", "FT-F12-RESTART")), ["A24"]))
    add(M("del postflight check rows (B C-HEALTH/dev-a)", "I4.5", lambda c: c.x("DELETE FROM checks WHERE result_id = "
          "? AND phase = 'postflight'", c.rid("B", "C-HEALTH")), ["A24"]))
    add(M("del B session preflight check rows", "I1.2", lambda c: c.x("DELETE FROM checks WHERE run_id = ? AND "
          "result_id IS NULL AND phase = 'preflight'", c.run("B")), ["A23"]))
    # -- the run plan (schema v5)
    add(M("del plan row (B C-HEALTH/dev-a)", "I1.3", lambda c: c.x("DELETE FROM run_plan WHERE run_id = ? AND case_id "
          "= 'C-HEALTH' AND device_id = 'dev-a'", c.run("B")), ["A23"], needs_plan=True))
    add(M("del every plan row of B", "I1.3", lambda c: c.x("DELETE FROM run_plan WHERE run_id = ?", c.run("B")),
          ["A23"], needs_plan=True))
    add(M("del B plan rows + plan file index", "I1.3", lambda c: (c.x("DELETE FROM run_plan WHERE run_id = ?",
          c.run("B")), c.x("DELETE FROM evidence WHERE run_id = ? AND kind = 'plan'", c.run("B"))), ["A23"],
          needs_plan=True))
    add(M("del result + its plan row (B C-HEALTH/dev-a)", "I1.3/I1.5",
          lambda c: c.delete_result(c.rid("B", "C-HEALTH"), plan=True), ["A23"], needs_plan=True))
    add(M("del result + plan row + evidence directory (B C-HEALTH/dev-a)", "I1.3",
          lambda c: (c.delete_result(c.rid("B", "C-HEALTH"), plan=True), rm_case_dir("B", "C-HEALTH", "dev-a")(c)),
          ["A23"], needs_plan=True, files=True))
    add(M("v5 migration record moved after every run (plans would look pre-v5)", "I1.1",
          lambda c: c.x("UPDATE schema_migrations SET applied_at = '2999-01-01T00:00:00.000Z' WHERE version = 5"),
          ["A22"], needs_plan=True))
    add(M("v4 migration record deleted (capture-flow records would look unrequired)", "I1.1",
          lambda c: c.x("DELETE FROM schema_migrations WHERE version = 4"), ["A22"]))
    add(M("v5 record moved + a result, its plan row and directory deleted (B C-HEALTH/dev-a)", "I1.1/I1.3",
          lambda c: (c.x("UPDATE schema_migrations SET applied_at = '2999-01-01T00:00:00.000Z' WHERE version = 5"),
                     c.delete_result(c.rid("B", "C-HEALTH"), plan=True), rm_case_dir("B", "C-HEALTH", "dev-a")(c)),
          ["A22", "A23"], needs_plan=True, files=True))
    # -- contradictory evidence
    for first, second in (("pass", "pass"), ("pass", "fail"), ("fail", "pass")):
        add(M(f"duplicate result {first}/{second} (B C-HEALTH/dev-a)", "I1.4", dup_result("B", "C-HEALTH", "dev-a",
              first, second), ["A19"], family="duplicate"))
    add(M("duplicate exchange appended (B C-IDENTIFY/dev-a)", "I5.2",
          lambda c: c.x("INSERT INTO exchanges (attempt_id, ord, cmd, req_id, host, addr, port, category, stage, detail,"
                        " stage_failed, os_error, read_end, bytes, t_send, t_recv, response, local_port) SELECT "
                        "attempt_id, ord + 1, cmd, req_id, host, addr, port, category, stage, detail, stage_failed, "
                        "os_error, read_end, bytes, t_send, t_recv, response, local_port FROM exchanges WHERE "
                        "attempt_id = (SELECT attempt_id FROM attempts WHERE result_id = ?)", c.rid("B", "C-IDENTIFY")),
          ["A24"]))
    add(M("duplicate attempt as attempt 2 (B C-HEALTH/dev-a)", "I4.1",
          lambda c: c.x("INSERT INTO attempts (result_id, attempt_no, category, stage, detail, started_at, duration_ms,"
                        " outcome, predicates) SELECT result_id, 2, category, stage, detail, started_at, duration_ms, "
                        "outcome, predicates FROM attempts WHERE result_id = ?", c.rid("B", "C-HEALTH")), ["A24"]))
    add(M("duplicate fault application (F FT-F3)", "I10.2",
          lambda c: c.x("INSERT INTO fault_events (run_id, result_id, fault_id, vm, applied_at, removed_at, "
                        "removal_verified, detail) SELECT run_id, result_id, fault_id, vm, applied_at, removed_at, "
                        "removal_verified, detail FROM fault_events WHERE result_id = ?", c.rid("F", "FT-F3-WRONG-PORT")),
          ["A24"]))
    add(M("duplicate capture index (B C-IDENTIFY/dev-a)", "I7",
          lambda c: c.x("INSERT INTO evidence (run_id, result_id, kind, path, sha256, bytes, created_at) SELECT run_id,"
                        " result_id, kind, path, sha256, bytes, created_at FROM evidence WHERE result_id = ? AND kind = "
                        "'pcap'", c.rid("B", "C-IDENTIFY")), ["A24", "A20"]))
    add(M("env git_sha contradicts run (B)", "I1.6", lambda c: c.x("UPDATE environment SET value = ? WHERE run_id = ? "
          "AND key = 'git_sha'", "f" * 40, c.run("B")), ["A13"]))
    add(M("flag: B marked unclean (clean_env=0)", "I1.2", flag("clean_env = 0"), ["A23"]))
    add(M("flag: B unclean, env record changed too", "I1.2",
          lambda c: (flag("clean_env = 0")(c), c.x("UPDATE environment SET value = '0' WHERE run_id = ? AND key = "
                                                   "'runs.clean_env'", c.run("B"))), ["A23"]))
    add(M("flag: B marked contaminated without a recorded cause", "I1.2", flag("contaminated = 1"), ["A23"]))
    add(M("endpoint: F3 exchange port 5021 -> 5020", "I5.3", lambda c: c.x(
        "UPDATE exchanges SET port = 5020 WHERE attempt_id IN (SELECT attempt_id FROM attempts WHERE result_id = ?)",
        c.rid("F", "FT-F3-WRONG-PORT")), ["A24", "A17"]))
    add(M("endpoint: F3 rewritten to 5020 with consistent flows and counts", "I5.3", endpoint_port_coordinated,
          ["A24"]))
    add(M("endpoint: B C-IDENTIFY/dev-a address -> dev-b's", "I5.3", lambda c: c.x(
        "UPDATE exchanges SET addr = '10.77.2.12' WHERE attempt_id IN (SELECT attempt_id FROM attempts WHERE "
        "result_id = ?)", c.rid("B", "C-IDENTIFY")), ["A24", "A17"]))
    add(M("device: B C-HEALTH results of dev-a and dev-b swapped", "I5.3", swap_devices("B", "C-HEALTH"), ["A24"]))
    add(M("capture side: F3 field capture relabelled ctl", "I7", lambda c: c.x(
        "UPDATE evidence SET kind = 'pcap' WHERE result_id = ? AND kind = 'pcap-field'",
        c.rid("F", "FT-F3-WRONG-PORT")), ["A24", "A20"]))
    add(M("results.attempts 1 -> 0, rows kept (B C-IDENTIFY/dev-a)", "I4.1", lambda c: c.x(
        "UPDATE results SET attempts = 0 WHERE result_id = ?", c.rid("B", "C-IDENTIFY")), ["A24"]))
    add(M("results.attempts 1 -> 2, one row (B C-IDENTIFY/dev-b)", "I4.1", lambda c: c.x(
        "UPDATE results SET attempts = 2 WHERE result_id = ?", c.rid("B", "C-IDENTIFY", "dev-b")), ["A24"]))
    add(M("attempt renumbered 1 -> 2 (B C-HEALTH/dev-b)", "I4.1", lambda c: c.x(
        "UPDATE attempts SET attempt_no = 2 WHERE result_id = ?", c.rid("B", "C-HEALTH", "dev-b")), ["A24"]))
    add(M("exchange order swapped (B C-READ-CLOCK/dev-a ord 3<->4)", "I5.5", lambda c: (
        c.x("UPDATE exchanges SET ord = -4 WHERE ord = 4 AND attempt_id = (SELECT attempt_id FROM attempts WHERE "
            "result_id = ?)", c.rid("B", "C-READ-CLOCK")),
        c.x("UPDATE exchanges SET ord = 4 WHERE ord = 3 AND attempt_id = (SELECT attempt_id FROM attempts WHERE "
            "result_id = ?)", c.rid("B", "C-READ-CLOCK")),
        c.x("UPDATE exchanges SET ord = 3 WHERE ord = -4 AND attempt_id = (SELECT attempt_id FROM attempts WHERE "
            "result_id = ?)", c.rid("B", "C-READ-CLOCK"))), ["A24"]))
    add(M("orphan: result row deleted with keys off (B C-HEALTH/dev-a)", "I1.1",
          orphan("results", "result_id = ?", "B", "C-HEALTH"), ["A22", "A23"]))
    add(M("orphan: attempt row deleted with keys off (B C-READ-SERIES/dev-a)", "I1.1/I4.1",
          orphan("attempts", "result_id = ?", "B", "C-READ-SERIES"), ["A22", "A24"]))
    add(M("erase the runner's source port + broaden and recount its flow (B C-HEALTH/dev-a)", "I6",
          erase_source_port("B", "C-HEALTH", "dev-a"), ["A24"]))
    add(M("PASS exchange category on a MALFORMED response (M4 C-IDENTIFY/dev-a)", "I5.4/I5.6", lambda c: c.x(
        "UPDATE exchanges SET category = 'PASS' WHERE attempt_id IN (SELECT attempt_id FROM attempts WHERE "
        "result_id = ?)", c.rid("M4", "C-IDENTIFY")), ["A24"]))
    # -- fabricated or manipulated counts
    add(M("packets 0 (F FT-F3 ctl)", "I8.1", set_flow("F", "FT-F3-WRONG-PORT", "ctl", "packets = 0"), ["A17", "A20"]))
    add(M("packets 999 (F FT-F3 ctl)", "I9", set_flow("F", "FT-F3-WRONG-PORT", "ctl", "packets = 999"), ["A20"]))
    add(M("expected 0, packets 0 (F FT-F3 field)", "I8.1", set_flow("F", "FT-F3-WRONG-PORT", "field",
          "expected = 0, packets = 0"), ["A17"]))
    add(M("count +1 without changing the capture (B C-READ-SERIES/dev-a)", "I9", set_flow(
        "B", "C-READ-SERIES", "ctl", "packets = packets + 1"), ["A20"]))
    add(M("unrelated traffic + reindexed hash (F FT-F3 ctl)", "I9", unrelated_pcap("F", "FT-F3-WRONG-PORT", "dev-a",
          "pcap"), ["A20"], files=True))
    add(M("unrelated traffic + reindexed hash (B C-GATEWAY/dev-a)", "I8.2", unrelated_pcap("B", "C-GATEWAY", "dev-a",
          "pcap"), ["A20"], files=True))
    add(M("unrelated traffic + reindexed hash (F GW-F5 field)", "I8.2", unrelated_pcap("F", "GW-F5-UNREACHABLE",
          "dev-a", "pcap-field"), ["A20"], files=True))
    add(M("summary: failing result marked pass", "I4.5", degrade_to_green(1), ["A10"], base="current-failure"))
    add(M("summary: marked pass, retry deleted, attempts=1", "I4.5", degrade_to_green(2), ["A24"],
          base="current-failure"))
    add(M("summary: + attempt outcome ok, predicates true", "I5.6", degrade_to_green(3), ["A24"],
          base="current-failure"))
    add(M("summary: + the decision predicates rewritten true as well (only the response disagrees)", "I5.6",
          lambda c: (degrade_to_green(3)(c), c.x("UPDATE results SET predicates = ? WHERE result_id = ?", json.dumps(
              {"sensor_ok": True, "status_ok": True}, sort_keys=True), c.rid("B", "C-HEALTH"))) if c.has_column(
              "results", "predicates") else degrade_to_green(3)(c), ["A24"], base="current-failure"))
    add(M("type-corrupted records: PASS response stored as text, a pass measurement as text", "I1.1/I5.6/I10.3",
          lambda c: (c.x("UPDATE exchanges SET response = CAST(response AS TEXT) WHERE attempt_id IN (SELECT attempt_id "
                         "FROM attempts WHERE result_id = ?)", c.rid("B", "C-HEALTH", "dev-b")),
                     c.x("UPDATE measurements SET value = 'fast' WHERE result_id = ? AND name = 'fault_apply_call_ms'",
                         c.rid("F", "GW-F1-UNREACHABLE"))), ["A24"]))
    add(M("PASS IDENTIFY whose response bytes name the other device (B C-IDENTIFY/dev-a)", "I5.6", lambda c: c.x(
        "UPDATE exchanges SET response = CAST(replace(replace(CAST(response AS TEXT), 'WIT-0001', 'WIT-0002'), "
        "'\"device_id\":\"dev-a\"', '\"device_id\":\"dev-b\"') AS BLOB) WHERE attempt_id IN (SELECT attempt_id "
        "FROM attempts WHERE result_id = ?)", c.rid("B", "C-IDENTIFY")), ["A24"]))
    # -- benign: no obligation-bearing record changes; the variant's own outcome must stand
    add(M("benign: result details rewritten", "-", lambda c: c.x("UPDATE results SET detail = 'reviewed ' || detail"),
          accept=True, family="benign"))
    add(M("benign: run notes appended", "-", lambda c: c.x("UPDATE runs SET notes = notes || ' | reviewed'"),
          accept=True, family="benign"))
    add(M("benign: exchange latencies rescaled", "-", lambda c: c.x("UPDATE exchanges SET latency_ms = latency_ms * 2, "
          "duration_ms = duration_ms + 1"), accept=True, family="benign"))
    add(M("benign: deadline-cut variant details rewritten", "-", lambda c: c.x("UPDATE results SET detail = 'x'"),
          accept=True, base="deadline-cut", family="benign"))
    # -- runs that predate the plan (schema v4 runs in a v5 store): receipts and trial completeness
    add(M("legacy: del result of a pre-plan trial (T3 C-HEALTH/dev-a)", "I1.5",
          lambda c: c.delete_result(c.rid("T3", "C-HEALTH")), ["A23"], base="legacy", needs_plan=True))
    add(M("legacy: del result + directory of a pre-plan trial (T3 C-HEALTH/dev-a)", "I1.5",
          lambda c: (c.delete_result(c.rid("T3", "C-HEALTH")), rm_case_dir("T3", "C-HEALTH", "dev-a")(c)), ["A14"],
          base="legacy", needs_plan=True, files=True))
    add(M("legacy: del F's exchanges (after the plan)", "I5.1", del_exchanges("F", "FT-F3-WRONG-PORT"), ["A24"],
          base="legacy", needs_plan=True))
    out += review_findings()
    out += contract_verification_findings()
    out += session_environment_findings()
    out += interrupted_environment_findings()
    return out


def _repoint(c, rid: int, kind: str, other: Path) -> None:
    """Unlink a result's indexed file of `kind` and point its index row (path, hash, length) at `other`."""
    old = c.file_of(rid, kind)
    old.unlink()
    data = other.read_bytes()
    c.x("UPDATE evidence SET path = ?, sha256 = ?, bytes = ? WHERE result_id = ? AND kind = ?",
        str(other.relative_to(c.root)), hashlib.sha256(data).hexdigest(), len(data), rid, kind)


def _f11_first_read_resets(c):
    """F11's observation rewritten as the device resetting on the FIRST READ (two_reads_then_reset false), pass kept."""
    rid = c.rid("F", "FT-F11-CLOSE-FIN")
    att = "(SELECT attempt_id FROM attempts WHERE result_id = ?)"
    c.x(f"DELETE FROM exchanges WHERE ord > 1 AND attempt_id IN {att}", rid)
    c.x(f"UPDATE exchanges SET category = 'CONN_RESET', read_end = 'reset', response = NULL, bytes = 0 "
        f"WHERE attempt_id IN {att}", rid)


def review_findings() -> list[Mutation]:
    """Attacks the independent review (docs/acceptance-integrity-repair.md section 9) reproduced against the first
    version of the repair; declared here before the corresponding fixes."""
    out = []
    add = out.append
    add(M("review 1: newest baseline made unfinished by a bare edit", "I1.2", flag("finished_at = NULL"), ["A23"],
          base="current-failure"))
    add(M("review 1: current fault run made unfinished by a bare edit", "I1.2", lambda c: c.x(
        "UPDATE runs SET finished_at = NULL WHERE run_id = ?", c.run("F")), ["A23"], base="deadline-cut"))
    add(M("review 1: newest baseline contaminated with a forged contamination note", "I1.2", flag(
        "contaminated = 1, notes = notes || ' | contaminated: forged'"), ["A23"], base="current-failure"))
    add(M("review 2: plan rows deleted, v5 record moved, a result and its directory deleted", "I1.3", lambda c: (
        c.x("DELETE FROM run_plan"),
        c.x("UPDATE schema_migrations SET applied_at = '2999-01-01T00:00:00.000Z' WHERE version = 5"),
        c.delete_result(c.rid("B", "C-HEALTH")), rm_case_dir("B", "C-HEALTH", "dev-a")(c)), ["A23"],
        base="current-failure", needs_plan=True, files=True))
    add(M("review 2: run_plan dropped, v5 record deleted, a result and its directory deleted", "I1.1/I1.3",
          lambda c: (c.x("DROP TABLE run_plan"), c.x("DELETE FROM schema_migrations WHERE version = 5"),
                     c.delete_result(c.rid("B", "C-HEALTH")), rm_case_dir("B", "C-HEALTH", "dev-a")(c)),
          ["A22", "A23"], base="current-failure", needs_plan=True, files=True))
    add(M("review 2: newest run back-dated before v5, its plan rows, a result and directory deleted", "I1.3",
          lambda c: (c.x("UPDATE runs SET started_at = (SELECT started_at FROM runs WHERE run_id = ?) WHERE run_id = ?",
                         c.run("T3"), c.run("B")),
                     c.x("DELETE FROM run_plan WHERE run_id = ?", c.run("B")),
                     c.delete_result(c.rid("B", "C-HEALTH")), rm_case_dir("B", "C-HEALTH", "dev-a")(c)),
          ["A23"], base="legacy", needs_plan=True, files=True))
    add(M("review 3: a failure recorded in a bound and a case predicate flipped to pass", "I4.5/I10.3", lambda c: c.x(
        "UPDATE results SET verdict = 'pass', attribution = 'none' WHERE result_id = ?", c.rid("B", "C-GATEWAY",
                                                                                            "dev-b")),
        ["A24"], base="gateway-failure", needs_plan=True))
    add(M("review 3: F11 resets on the first READ, pass kept", "I4.5/I5.2", _f11_first_read_resets, ["A24"]))
    add(M("review 4: degraded pass with its predicates erased", "I4.6/I5.6", lambda c: (
        degrade_to_green(2)(c),
        c.x("UPDATE attempts SET outcome = 'ok', predicates = NULL WHERE result_id = ?", c.rid("B", "C-HEALTH")),
        c.x("DELETE FROM capture_flows WHERE result_id = ? AND filter NOT IN (SELECT 'tcp and host ' || x.addr || "
            "' and port ' || x.port || ' and port ' || x.local_port FROM exchanges x JOIN attempts a USING "
            "(attempt_id) WHERE a.result_id = ?)", c.rid("B", "C-HEALTH"), c.rid("B", "C-HEALTH"))),
        ["A24"], base="current-failure"))
    add(M("review 5: F3 field capture row re-pointed at the ctl capture", "I7", lambda c: _repoint(
        c, c.rid("F", "FT-F3-WRONG-PORT"), "pcap-field", c.file_of(c.rid("F", "FT-F3-WRONG-PORT"), "pcap")),
        ["A24"], files=True))
    add(M("review 5: C-GATEWAY/dev-a capture row re-pointed at dev-b's capture", "I7", lambda c: _repoint(
        c, c.rid("B", "C-GATEWAY", "dev-a"), "pcap", c.file_of(c.rid("B", "C-GATEWAY", "dev-b"), "pcap")),
        ["A24"], files=True))
    add(M("review 6: flow records deleted; commissioning must not count the result", "I8.1/I10.5", lambda c: c.x(
        "DELETE FROM capture_flows WHERE result_id = ?", c.rid("B", "C-IDENTIFY")), ["A17", "A18"]))
    add(M("review 7: devices row differs from the inventory", "I3", lambda c: c.x(
        "UPDATE devices SET expected_serial = 'WIT-9999', expected_addr = '10.77.2.99' WHERE device_id = 'dev-b'"),
        ["A21", "A18"]))
    add(M("review 10: plan file of a superseded fair run deleted", "I1.3", rm_file("F0", "session/plan.json"), ["A23"],
          needs_plan=True, files=True))
    add(M("review 11: inventory/hosts/counters records of FT-F4 de-indexed", "I10.3", lambda c: c.x(
        "DELETE FROM evidence WHERE result_id = ? AND kind IN ('inventory', 'hosts', 'counters')",
        c.rid("F", "FT-F4-WRONG-ADDR")), ["A24"]))
    return out


SELF_ABORT = "contaminated = 1, notes = notes || ' | aborted: never finished (detected by run ' || run_id || ')'"
# 1 ms after the start of the run bound to the parameter, in the runner's time form
_JUST_AFTER = ("strftime('%Y-%m-%dT%H:%M:%fZ', julianday((SELECT started_at FROM runs WHERE run_id = ?)) + 0.001 / "
               "86400.0)")


def _reorder_predicates(c):
    """The same decision recorded with its names in reverse order (JSON object order carries no obligation)."""
    rid = c.rid("B", "C-GATEWAY", "dev-a")
    preds = json.loads(c.x("SELECT predicates FROM results WHERE result_id = ?", rid).fetchone()[0])
    c.x("UPDATE results SET predicates = ? WHERE result_id = ?", json.dumps(dict(reversed(list(preds.items())))), rid)


def contract_verification_findings() -> list[Mutation]:
    """Attacks of the independent contract verification (docs/independent-contract-verification.md IC-01, IC-02),
    declared before their fixes: a run that certifies its own abort, and a decision whose predicates are deleted,
    shadowed or renamed. Their legitimate controls are the variants aborted-detected and gateway-api-failure."""
    out = []
    add = out.append
    # IC-01: an abort is corroborated only by a separate run that started after it while it was unfinished
    add(M("IC-01: newest baseline certifies its own abort (auditor's SQL)", "I1.2", flag(SELF_ABORT), ["A23"],
          base="current-failure", family="IC-01"))
    add(M("IC-01: current fault run certifies its own abort", "I1.2", lambda c: c.x(
        f"UPDATE runs SET {SELF_ABORT} WHERE run_id = ?", c.run("F")), ["A23"], base="deadline-cut", family="IC-01"))
    add(M("IC-01: newest baseline's abort credited to a run that does not exist", "I1.2", flag(
        "contaminated = 1, notes = notes || ' | aborted: never finished (detected by run 9999)'"), ["A23"],
        base="current-failure", family="IC-01"))
    add(M("IC-01: newest baseline's abort credited to an earlier run", "I1.2", lambda c: flag(
        f"contaminated = 1, notes = notes || ' | aborted: never finished (detected by run {c.run('T5')})'")(c),
        ["A23"], base="current-failure", family="IC-01"))
    add(M("IC-01: killed run's marker rewritten to cite itself", "I1.2", lambda c: c.x(
        "UPDATE runs SET notes = replace(notes, 'detected by run ' || ?, 'detected by run ' || run_id) WHERE run_id = ?",
        c.run("N"), c.run("K")), ["A23"], base="aborted-detected", family="IC-01"))
    add(M("IC-01: a self-citing marker added beside the genuine one", "I1.2", lambda c: c.x(
        "UPDATE runs SET notes = notes || ' | aborted: never finished (detected by run ' || run_id || ')' WHERE "
        "run_id = ?", c.run("K")), ["A23"], base="aborted-detected", family="IC-01"))
    add(M("IC-01: killed run given a finish before its detector started", "I1.2", lambda c: c.x(
        "UPDATE runs SET finished_at = started_at WHERE run_id = ?", c.run("K")), ["A23"], base="aborted-detected",
        family="IC-01"))
    add(M("IC-01: detector's start moved before the killed run's", "I1.2", lambda c: c.x(
        "UPDATE runs SET started_at = (SELECT started_at FROM runs WHERE run_id = ?) WHERE run_id = ?", c.run("B"),
        c.run("N")), ["A23"], base="aborted-detected", family="IC-01"))
    # the independent review of this repair (F1, F1c, F2): the overlap claimed by the runs rows alone
    add(M("IC-01 review F1: current fault run's finish moved 1 ms after the next run's start, abort credited to it",
          "I1.2", lambda c: c.x(f"UPDATE runs SET contaminated = 1, notes = notes || ' | aborted: never finished "
                                f"(detected by run {c.run('M1')})', finished_at = {_JUST_AFTER} WHERE run_id = ?",
                                c.run("M1"), c.run("F")), ["A23"], base="deadline-cut", family="IC-01"))
    add(M("IC-01 review F1c: next run's start moved 1 ms after the current fault run's, abort credited to it", "I1.2",
          lambda c: (c.x(f"UPDATE runs SET started_at = {_JUST_AFTER} WHERE run_id = ?", c.run("F"), c.run("M1")),
                     c.x(f"UPDATE runs SET {SELF_ABORT.replace('run_id', str(c.run('M1')))} WHERE run_id = ?",
                         c.run("F"))), ["A23"], base="deadline-cut", family="IC-01"))
    add(M("IC-01 review F2: a bare runs row inside the newest baseline credited with its abort", "I1.2", lambda c: (
        c.x(f"INSERT INTO runs (started_at, kind, git_sha, git_dirty, clean_env, runner_host, notes) VALUES "
            f"({_JUST_AFTER}, 'baseline', ?, 0, 1, 'fixture', 'fabricated detector')", c.run("B"), R.SHA),
        c.x("UPDATE runs SET contaminated = 1, notes = notes || ' | aborted: never finished (detected by run ' || "
            "(SELECT max(run_id) FROM runs) || ')' WHERE run_id = ?", c.run("B"))), ["A23"], base="current-failure",
        family="IC-01"))
    # IC-02: the names a decision holds come from the case contract, never from the row
    add(M("IC-02: C-GATEWAY/dev-b decision predicates erased, pass kept", "I4.5", lambda c: c.x(
        "UPDATE results SET predicates = '{}' WHERE result_id = ?", c.rid("B", "C-GATEWAY", "dev-b")),
        ["A24", "A18"], needs_plan=True, family="IC-02"))
    add(M("IC-02: every C-GATEWAY and C-ENVIRONMENT decision erased (auditor's SQL)", "I4.5", lambda c: c.x(
        "UPDATE results SET predicates = '{}' WHERE case_id IN ('C-GATEWAY', 'C-ENVIRONMENT')"), ["A24", "A18"],
        needs_plan=True, family="IC-02"))
    add(M("IC-02: failing API predicate deleted, verdict flipped to pass (auditor's SQL)", "I4.5", lambda c: c.x(
        "UPDATE results SET verdict = 'pass', attribution = 'none', predicates = json_remove(predicates, "
        "'$.api_unknown_device_404') WHERE result_id = ?", c.rid("B", "C-GATEWAY", "dev-b")), ["A24", "A18"],
        base="gateway-api-failure", needs_plan=True, family="IC-02"))
    add(M("IC-02: failing API predicate shadowed by a later true record of the same name, verdict pass", "I4.5",
          lambda c: c.x("UPDATE results SET verdict = 'pass', attribution = 'none', predicates = substr(predicates, 1, "
                        "length(predicates) - 1) || ', \"api_unknown_device_404\": true}' WHERE result_id = ?",
                        c.rid("B", "C-GATEWAY", "dev-b")), ["A24", "A18"], base="gateway-api-failure",
          needs_plan=True, family="IC-02"))
    add(M("IC-02: failing API predicate renamed true, verdict pass", "I4.5", lambda c: c.x(
        "UPDATE results SET verdict = 'pass', attribution = 'none', predicates = json_set(json_remove(predicates, "
        "'$.api_unknown_device_404'), '$.api_unknown_device_ok', json('true')) WHERE result_id = ?",
        c.rid("B", "C-GATEWAY", "dev-b")), ["A24", "A18"], base="gateway-api-failure", needs_plan=True,
        family="IC-02"))
    add(M("IC-02: FT-F3's own predicate deleted (pass)", "I4.5", lambda c: c.x(
        "UPDATE results SET predicates = json_remove(predicates, '$.gateway_once_agrees_CONN_REFUSED') WHERE "
        "result_id = ?", c.rid("F", "FT-F3-WRONG-PORT")), ["A24"], needs_plan=True, family="IC-02"))
    add(M("IC-02: GW-F5's predicates of dev-b deleted (pass)", "I4.5", lambda c: c.x(
        "UPDATE results SET predicates = json_remove(predicates, '$.\"dev-b_unreachable_within_3P\"', "
        "'$.\"dev-b_category_NO_ROUTE\"', '$.\"dev-b_recovered_within_2P_of_revert\"') WHERE result_id = ?",
        c.rid("F", "GW-F5-UNREACHABLE")), ["A24"], needs_plan=True, family="IC-02"))
    add(M("IC-02: FT-F12 recorded as its partial pre-restart set, pass kept", "I4.5", lambda c: c.x(
        "UPDATE results SET predicates = '{\"pre_restart_connection\": true}' WHERE result_id = ?",
        c.rid("F", "FT-F12-RESTART")), ["A24"], needs_plan=True, family="IC-02"))
    add(M("IC-02: a REQ-10 key deleted from B's C-ENVIRONMENT decision (pass)", "I4.5", lambda c: c.x(
        "UPDATE results SET predicates = json_remove(predicates, '$.\"chrony.offset\"') WHERE result_id = ?",
        c.rid("B", "C-ENVIRONMENT", None)), ["A24", "A18"], needs_plan=True, family="IC-02"))
    add(M("IC-02: fail recorded over an all-true decision basis (B C-GATEWAY/dev-a)", "I4.5", lambda c: c.x(
        "UPDATE results SET verdict = 'fail', attribution = 'device' WHERE result_id = ?",
        c.rid("B", "C-GATEWAY", "dev-a")), ["A4", "A24"], needs_plan=True, family="IC-02"))
    add(M("benign: decision predicate names stored in reverse order (B C-GATEWAY/dev-a)", "-", _reorder_predicates,
          accept=True, needs_plan=True, family="benign"))
    return out


# ---------------------------------------------------------------- F3: recorded session environment versus mutable metadata

def relabel_run(kind, label="B"):
    """The auditor's three-row F3 edit, generalized to the other non-baseline kinds."""
    def f(c):
        mutant = "M5" if kind == "mutant" else None
        c.x("UPDATE runs SET kind = ?, mutant_id = ? WHERE run_id = ?", kind, mutant, c.run(label))
        values = {"runs.kind": kind, "mutant": mutant or "none", "device_build.dev-a":
                  "mutant:" + R.catalog.mutant_spec(mutant, R.INV["devices"]) if mutant else "stock"}
        for key, value in values.items():
            c.x("UPDATE environment SET value = ? WHERE run_id = ? AND key = ?", value, c.run(label), key)
    return f


def session_edit(edit, label="B", *, rehash=True):
    def f(c):
        p = c.evidence_path(label, "session/environment.json")
        p.write_text(edit(p.read_text()))
        if rehash:
            c.reindex(p)
    return f


def _erase_session_key(key, *, table=False):
    def f(c):
        def edit(text):
            doc = json.loads(text)
            doc.pop(key)
            return json.dumps(doc)
        session_edit(edit)(c)
        if table:
            c.x("DELETE FROM environment WHERE run_id = ? AND key = ?", c.run("B"), key)
    return f


def session_environment_findings() -> list[Mutation]:
    out = []
    def add(name, apply, *, files=False, base="reference", must=("A23",), **kw):
        out.append(M("F3: " + name, "I1.7", apply, must, files=files, base=base, family="F3", **kw))

    for kind in ("mutant", "fault", "mixed"):
        add(f"failed baseline relabelled {kind}, environment rows agree", relabel_run(kind), base="current-failure")
    add("mutant relabelled baseline, environment rows agree", relabel_run("baseline", "M5"))
    add("run kind alone contradicts session", lambda c: c.x(
        "UPDATE runs SET kind = 'fault' WHERE run_id = ?", c.run("B")))
    add("superseded run's kind rewritten", relabel_run("mixed", "T1"))
    add("pre-v5 run's kind rewritten", relabel_run("mixed", "T1"), base="legacy")
    for key, value in (("runs.kind", "fault"), ("mutant", "M5"), ("device_build.dev-a", "mutant:temp-string"),
                       ("python", "3.12.4"), ("fw_version.dev-a", "2.0.0"),
                       ("provenance.witness-ctl", "golden-restore id=forged boot_id=forged")):
        add(f"table {key} changed with session preserved", lambda c, k=key, v=value: c.x(
            "INSERT INTO environment VALUES (?,?,?) ON CONFLICT(run_id,key) DO UPDATE SET value=excluded.value",
            c.run("B"), k, v))
    for col, value in (("git_sha", "b" * 40), ("git_dirty", 1)):
        def provenance(c, col=col, value=value):
            c.x(f"UPDATE runs SET {col} = ? WHERE run_id = ?", value, c.run("B"))
            c.x("UPDATE environment SET value = ? WHERE run_id = ? AND key = ?", str(value), c.run("B"), col)
        add(f"run and table {col} agree but session differs", provenance)
    for key in ("runs.kind", "mutant", "git_sha", "git_dirty", "device_build.dev-a", "python"):
        add(f"session missing {key}", _erase_session_key(key), files=True)
        add(f"session and table missing {key}", _erase_session_key(key, table=True), files=True, needs_plan=True)
    add("table missing recorded run kind", lambda c: c.x(
        "DELETE FROM environment WHERE run_id = ? AND key = 'runs.kind'", c.run("B")))
    add("session kind contradicts database", session_edit(lambda t: t.replace('"baseline"', '"fault"')),
        files=True)
    for name, text in (("invalid JSON", "{"), ("not an object", "[]")):
        add(name, session_edit(lambda t, text=text: text), files=True)
    add("non-text value", session_edit(lambda t: json.dumps({**json.loads(t), "python": 1})), files=True)
    # Keep every required key and a last value that agrees with the table: duplicate-name rejection must be the
    # sole reason these fail, rather than an incidental missing-key or value mismatch.
    for name, key in (("duplicate kind", "runs.kind"), ("escaped duplicate kind", r"\u0072uns.kind")):
        add(name, session_edit(lambda t, key=key: '{"' + key + '":"mutant",' + t.lstrip()[1:]), files=True)
    add("unhashed byte edit", session_edit(lambda t: t.replace('"baseline"', '"fault"'), rehash=False), files=True)
    add("missing session bytes", lambda c: c.evidence_path("B", "session/environment.json").unlink(), files=True)
    add("missing environment index", lambda c: c.x(
        "DELETE FROM evidence WHERE run_id = ? AND kind = 'environment'", c.run("B")))
    add("duplicate environment index", lambda c: c.x(
        "INSERT INTO evidence (run_id,result_id,kind,path,sha256,bytes,created_at) "
        "SELECT run_id,result_id,kind,path,sha256,bytes,created_at FROM evidence "
        "WHERE run_id = ? AND kind = 'environment'", c.run("B")))
    add("environment index relabelled", lambda c: c.x(
        "UPDATE evidence SET kind = 'other' WHERE run_id = ? AND kind = 'environment'", c.run("B")))
    add("environment index attached to a result", lambda c: c.x(
        "UPDATE evidence SET result_id = ? WHERE run_id = ? AND kind = 'environment'",
        c.rid("B", "C-HEALTH"), c.run("B")))
    add("environment path points at another run", lambda c: c.x(
        "UPDATE evidence SET path = ? WHERE run_id = ? AND kind = 'environment'",
        f"run-{c.run('T5')}/session/environment.json", c.run("B")))
    add("preserved session contradicts an unfair relabelled run", lambda c: (
        relabel_run("mutant")(c), c.x("UPDATE runs SET contaminated = 1 WHERE run_id = ?", c.run("B"))),
        base="current-failure")
    return out


# ---------------------------------------------------------------- F3: interrupted-session evidence omissions

def omit_session_environment(label, *, snapshot=True, index=True):
    """Delete only the chosen session representations; keep run/check/result/environment facts intact."""
    def f(c):
        if snapshot:
            c.evidence_path(label, "session/environment.json").unlink()
        if index:
            c.x("DELETE FROM evidence WHERE run_id = ? AND kind = 'environment'", c.run(label))
    return f


def interrupted_environment_findings() -> list[Mutation]:
    out = []
    for base, label in (("aborted-detected", "K"), ("current-failure", "B")):
        for name, snapshot, index in (("snapshot", True, False), ("index", False, True),
                                      ("snapshot and index", True, True)):
            out.append(M(f"F3 omission: {base} missing {name}", "I1.7",
                         omit_session_environment(label, snapshot=snapshot, index=index), ["A23"],
                         base=base, files=snapshot, family="F3-omission"))
    return out


# ---------------------------------------------------------------- randomized combinations (seeded, bounded)

def primitive_pool() -> list[tuple[str, Callable[[Ctx], None]]]:
    """Single attacks each of which the contract must detect alone, drawn from every table of the evidence chain."""
    pool = []
    for case, dev in RUNNER_CASES_B:
        pool += [(f"del-exchanges B {case}/{dev}", del_exchanges("B", case, dev)),
                 (f"del-attempts B {case}/{dev}", del_attempts("B", case, dev)),
                 (f"del-flows B {case}/{dev}", lambda c, case=case, dev=dev: c.x(
                     "DELETE FROM capture_flows WHERE result_id = ?", c.rid("B", case, dev))),
                 (f"del-ctl-index B {case}/{dev}", del_capture_index("B", case, dev, "pcap")),
                 (f"count999 B {case}/{dev}", set_flow("B", case, "ctl", "packets = 999", dev))]
    for case in RUNNER_FAULT_CASES:
        pool += [(f"del-exchanges F {case}", del_exchanges("F", case)),
                 (f"del-field-index F {case}", del_capture_index("F", case, "dev-a", "pcap-field"))]
    for case in FAULT_CASES:
        pool.append((f"del-result F {case}", lambda c, case=case: c.delete_result(c.rid("F", case))))
    for case, dev in [(c, d) for c, per in R.catalog.COMMISSIONING_REQUIRED for d in (R.DEVICES if per else [None])]:
        pool.append((f"del-result B {case}/{dev or 'run'}", lambda c, case=case, dev=dev: c.delete_result(
            c.rid("B", case, dev))))
    for m in ("M1", "M2", "M3", "M4", "M5", "M6"):
        pool.append((f"del-result {m} catch", lambda c, m=m: c.delete_result(c.rid(
            m, "C-READ-SERIES" if m == "M6" else "C-IDENTIFY"))))
    for g in ("GW-F1-UNREACHABLE", "GW-F5-UNREACHABLE", "GW-F8-UNREACHABLE"):
        pool += [(f"del-measurements F {g}", lambda c, g=g: c.x("DELETE FROM measurements WHERE result_id = ?",
                                                                c.rid("F", g))),
                 (f"del-gateway-index F {g}", del_capture_index("F", g, "dev-a", "gateway"))]
    pool += [("del-session-index B", del_session()), ("flag-unclean B", flag("clean_env = 0")),
             ("flag-contaminated B", flag("contaminated = 1")),
             ("del-fault-event F12", lambda c: c.x("DELETE FROM fault_events WHERE event_id = (SELECT max(event_id) "
                                                  "FROM fault_events WHERE result_id = ?)", c.rid("F", "FT-F12-RESTART"))),
             ("dup-result B C-HEALTH/dev-b", dup_result("B", "C-HEALTH", "dev-b", "pass", "fail"))]
    return pool


BENIGN = [("benign-detail", lambda c: c.x("UPDATE results SET detail = detail || ' (r)'")),
          ("benign-notes", lambda c: c.x("UPDATE runs SET notes = notes || ' (r)'"))]


def combination(seed: int) -> list[tuple[str, Callable]]:
    """2-5 distinct primitives (+ maybe a benign edit), reproducible from the seed."""
    rng = random.Random(seed)
    pool = primitive_pool()
    picks = rng.sample(pool, rng.randint(2, 5))
    if rng.random() < 0.3:
        picks.append(rng.choice(BENIGN))
    rng.shuffle(picks)
    return picks
