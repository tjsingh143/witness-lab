"""Normalized SQLite results store (PROJECT_BRIEF.md section 8, extended only where needed).

Extensions over the brief's DDL, each for a stated reason:
- case_requirements: many-to-many REQ <-> case (a case may prove several REQs).
- cases.kind: commissioning vs fault, so commissioning status never comes from fault runs.
- runs.kind/git_dirty/finished state: separate clean baseline runs from fault runs.
- results.preflight/postflight/detail: attribution is decided from recorded checks, and
  verdict/attribution are stored independently of the observed category.
- attempts and exchanges: every attempt (retry) and every request/response on it,
  instead of a JSON blob, so first-attempt/flake and per-READ queries are plain SQL.
- checks: each preflight/precheck/postflight line (PASS/FAIL/SKIP) per VM.
- fault_events: when each fault was applied/removed and whether removal was verified.
- evidence: files (pcap, journal, tc/nft/hosts snapshots) referenced by path + sha256.
- measurements (v2): named timings with their bound and clock (REQ-08/09 detection and recovery
  times, restart duration), one row each, because a case can measure more than detection_ms.
- exchanges.local_port (v2): the runner's ephemeral port, so a row can be matched to its packets
  in a capture that also contains the gateway's polls.
- mutants + runs.kind 'mutant' + runs.mutant_id (v3): a suite run against a deliberately broken
  device build (brief 7.4) is its own run kind, so it can never be counted as a clean baseline or
  commission a device, and the mutant report is a plain join.
- attempts.outcome + attempts.predicates (v4, independent audit F-04): each attempt's own assessment
  (ok/device/runner/infra) and predicate values, so "passed only on retry" is a predicate fact, not a
  category change, and a runner/infra attempt stays visible after a retry.
- capture_flows (v4, independent audit F-07): per result and capture, whether the dialled flow was
  expected on the wire and how many of its packets the capture actually holds.
- run_plan (v5, final independent verification FV-01): the run's declared selection of case instances, written
  before its first case (record_plan; the live session also indexes it as session/plan.json), so a missing result is
  "planned, not recorded", never "never part of the run". results.predicates (v5): every predicate the verdict was
  decided on, including the case's own (gateway bounds, timing, F11 shape) that no attempt row holds. Evidence
  tables are append-only from v5 (delete/update
  guards); docs/acceptance-contract.md: the guards stop accidental changes, the verifier does not rely on them.
Foreign keys are enforced (PRAGMA foreign_keys=ON on every connection).

Commissioning (commissioning_gaps, independent audit F-01) is decided against the COMPLETE catalog of
commissioning cases (runner/catalog.py) for every INVENTORY device (never the devices table: FV-02), never against
whichever cases a run happened to execute, against the run's environment record as validated by runner/evidence.py
(second independent audit R-01), and against the evidence contract of its prerequisite results (runner/contract.py).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 5

_V1 = """
CREATE TABLE runs (
  run_id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  kind TEXT NOT NULL CHECK (kind IN ('baseline','fault','mixed')),
  git_sha TEXT,
  git_dirty INTEGER CHECK (git_dirty IN (0,1)),
  clean_env INTEGER NOT NULL CHECK (clean_env IN (0,1)),
  contaminated INTEGER NOT NULL DEFAULT 0 CHECK (contaminated IN (0,1)),
  runner_host TEXT,
  notes TEXT);
CREATE TABLE environment (
  run_id INTEGER NOT NULL REFERENCES runs(run_id),
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  PRIMARY KEY (run_id, key));
CREATE TABLE requirements (req_id TEXT PRIMARY KEY, text TEXT NOT NULL);
CREATE TABLE cases (
  case_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('commissioning','fault')),
  description TEXT NOT NULL);
CREATE TABLE case_requirements (
  case_id TEXT NOT NULL REFERENCES cases(case_id),
  req_id TEXT NOT NULL REFERENCES requirements(req_id),
  PRIMARY KEY (case_id, req_id));
CREATE TABLE devices (
  device_id TEXT PRIMARY KEY, hostname TEXT NOT NULL, expected_addr TEXT NOT NULL,
  port INTEGER NOT NULL, expected_serial TEXT NOT NULL, expected_fw TEXT NOT NULL);
CREATE TABLE faults (
  fault_id TEXT PRIMARY KEY,
  catalog_id TEXT NOT NULL,          -- brief section 6.3 id (F1..F13)
  kind TEXT NOT NULL,
  params TEXT NOT NULL,
  expected_category TEXT NOT NULL,
  description TEXT NOT NULL);
CREATE TABLE results (
  result_id INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL REFERENCES runs(run_id),
  case_id TEXT NOT NULL REFERENCES cases(case_id),
  device_id TEXT REFERENCES devices(device_id),
  fault_id TEXT REFERENCES faults(fault_id),
  expected_category TEXT,
  observed_category TEXT,             -- NULL = unclassifiable (verdict error, runner)
  first_attempt_category TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  latency_ms REAL,
  detection_ms REAL,
  verdict TEXT NOT NULL CHECK (verdict IN ('pass','fail','error')),
  attribution TEXT NOT NULL CHECK (attribution IN ('none','runner','infra','device')),
  detail TEXT,
  preflight TEXT NOT NULL CHECK (preflight IN ('green','red')),
  postflight TEXT CHECK (postflight IN ('green','red')),
  evidence_path TEXT,
  observed_at TEXT NOT NULL,
  duration_ms REAL,
  CHECK (verdict <> 'pass' OR attribution = 'none'),
  CHECK (attribution <> 'device' OR preflight = 'green'),
  CHECK (observed_category IS NULL OR observed_category IN
    ('PASS','PASS_SLOW','RESOLVE_FAIL','NO_ROUTE','CONN_REFUSED','CONNECT_TIMEOUT',
     'READ_TIMEOUT','CONN_RESET','MALFORMED','WRONG_IDENTITY','STALE_DATA')));
CREATE TABLE attempts (
  attempt_id INTEGER PRIMARY KEY,
  result_id INTEGER NOT NULL REFERENCES results(result_id),
  attempt_no INTEGER NOT NULL CHECK (attempt_no IN (1,2)),
  category TEXT,
  stage TEXT,
  detail TEXT,
  started_at TEXT,
  duration_ms REAL,
  UNIQUE (result_id, attempt_no));
CREATE TABLE exchanges (
  exchange_id INTEGER PRIMARY KEY,
  attempt_id INTEGER NOT NULL REFERENCES attempts(attempt_id),
  ord INTEGER NOT NULL,
  cmd TEXT NOT NULL,
  req_id INTEGER NOT NULL,
  host TEXT NOT NULL,
  addr TEXT,
  port INTEGER NOT NULL,
  category TEXT,
  stage TEXT,
  detail TEXT,
  stage_failed TEXT,
  os_error TEXT,
  read_end TEXT,
  bytes INTEGER NOT NULL,
  resolve_ms REAL, connect_ms REAL, response_ms REAL, latency_ms REAL, duration_ms REAL,
  t_send TEXT, t_recv TEXT,
  response BLOB,
  UNIQUE (attempt_id, ord));
CREATE TABLE checks (
  check_id INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL REFERENCES runs(run_id),
  result_id INTEGER REFERENCES results(result_id),
  phase TEXT NOT NULL CHECK (phase IN ('preflight','precheck','postflight','session-postflight')),
  vm TEXT NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('PASS','FAIL','SKIP')),
  detail TEXT,
  checked_at TEXT NOT NULL);
CREATE TABLE fault_events (
  event_id INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL REFERENCES runs(run_id),
  result_id INTEGER REFERENCES results(result_id),
  fault_id TEXT NOT NULL REFERENCES faults(fault_id),
  vm TEXT NOT NULL,
  applied_at TEXT,
  removed_at TEXT,
  removal_verified INTEGER CHECK (removal_verified IN (0,1)),
  detail TEXT);
CREATE TABLE evidence (
  evidence_id INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL REFERENCES runs(run_id),
  result_id INTEGER REFERENCES results(result_id),
  kind TEXT NOT NULL,
  path TEXT NOT NULL,                -- relative to the evidence root
  sha256 TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  created_at TEXT NOT NULL);
CREATE INDEX results_run ON results(run_id);
CREATE INDEX results_case ON results(case_id, device_id);
CREATE INDEX checks_run ON checks(run_id, phase);
"""

_V2 = """
CREATE TABLE measurements (
  measurement_id INTEGER PRIMARY KEY,
  result_id INTEGER NOT NULL REFERENCES results(result_id),
  name TEXT NOT NULL,
  value REAL,                        -- NULL = could not be measured (e.g. never detected)
  unit TEXT NOT NULL,
  bound REAL,                        -- requirement bound in the same unit, if any
  clock TEXT NOT NULL,               -- e.g. ctl-monotonic
  detail TEXT,
  UNIQUE (result_id, name));
ALTER TABLE exchanges ADD COLUMN local_port INTEGER;
CREATE INDEX measurements_name ON measurements(name)
"""

_V4 = """
ALTER TABLE attempts ADD COLUMN outcome TEXT CHECK (outcome IS NULL OR outcome IN ('ok','device','runner','infra'));
ALTER TABLE attempts ADD COLUMN predicates TEXT;
CREATE TABLE capture_flows (
  flow_id INTEGER PRIMARY KEY,
  result_id INTEGER NOT NULL REFERENCES results(result_id),
  capture TEXT NOT NULL CHECK (capture IN ('ctl','field')),
  filter TEXT NOT NULL,              -- BPF of the dialled flow, e.g. tcp and host 10.77.2.11 and port 5021
  expected INTEGER NOT NULL CHECK (expected IN (0,1)),
  packets INTEGER,                   -- NULL = capture file missing or unreadable
  detail TEXT NOT NULL,
  UNIQUE (result_id, capture, filter))
"""

RUN_COLS = "run_id, started_at, finished_at, kind, git_sha, git_dirty, clean_env, contaminated, runner_host, notes"


def _v3(conn: sqlite3.Connection, version: int, desc: str) -> None:
    """runs.kind gains 'mutant' (+ runs.mutant_id). SQLite cannot alter a CHECK constraint, so runs is
    rebuilt with the documented procedure (https://www.sqlite.org/lang_altertable.html#otheralter):
    foreign keys off (outside the transaction), new table, copy, drop, rename, foreign_key_check, commit."""
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN")
        conn.execute("""CREATE TABLE mutants (
          mutant_id TEXT PRIMARY KEY,
          spec TEXT NOT NULL,                -- device/mutants.py grammar (template; filled at deploy)
          description TEXT NOT NULL,
          predicted TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE runs_v3 (
          run_id INTEGER PRIMARY KEY,
          started_at TEXT NOT NULL,
          finished_at TEXT,
          kind TEXT NOT NULL CHECK (kind IN ('baseline','fault','mixed','mutant')),
          git_sha TEXT,
          git_dirty INTEGER CHECK (git_dirty IN (0,1)),
          clean_env INTEGER NOT NULL CHECK (clean_env IN (0,1)),
          contaminated INTEGER NOT NULL DEFAULT 0 CHECK (contaminated IN (0,1)),
          runner_host TEXT,
          notes TEXT,
          mutant_id TEXT REFERENCES mutants(mutant_id),
          CHECK ((kind = 'mutant') = (mutant_id IS NOT NULL)))""")
        conn.execute(f"INSERT INTO runs_v3 ({RUN_COLS}) SELECT {RUN_COLS} FROM runs")
        conn.execute("DROP TABLE runs")
        conn.execute("ALTER TABLE runs_v3 RENAME TO runs")
        bad = conn.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            raise RuntimeError(f"v3 migration: foreign key violations {bad[:5]}")
        conn.execute("INSERT INTO schema_migrations VALUES (?,?,?)", (version, desc, utcnow()))   # same transaction
        conn.execute("COMMIT")
        conn.execute(f"PRAGMA user_version = {version}")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


# Evidence is append-only once recorded. Allowed updates are the runner's own: run status (runs), postflight and
# results recorded later in the case (results), environment upserts at session start.
_APPEND_ONLY = ("runs", "environment", "results", "attempts", "exchanges", "checks", "fault_events", "evidence",
                "measurements", "capture_flows", "run_plan")
_IMMUTABLE = ("attempts", "exchanges", "checks", "fault_events", "evidence", "measurements", "capture_flows", "run_plan")


def _v5(conn: sqlite3.Connection, version: int, desc: str) -> None:
    stmts = ["""CREATE TABLE run_plan (
          run_id INTEGER NOT NULL REFERENCES runs(run_id),
          case_id TEXT NOT NULL REFERENCES cases(case_id),
          device_id TEXT REFERENCES devices(device_id),   -- NULL = run-level case
          planned_at TEXT NOT NULL)""",
             "CREATE UNIQUE INDEX run_plan_instance ON run_plan(run_id, case_id, coalesce(device_id, ''))",
             # every predicate the verdict was decided on (final attempt's + the case's own), JSON {name: bool}
             "ALTER TABLE results ADD COLUMN predicates TEXT"]
    stmts += [f"CREATE TRIGGER append_only_{t} BEFORE DELETE ON {t} BEGIN "
              f"SELECT RAISE(ABORT, 'Witness evidence is append-only: {t} rows are never deleted'); END"
              for t in _APPEND_ONLY]
    stmts += [f"CREATE TRIGGER immutable_{t} BEFORE UPDATE ON {t} BEGIN "
              f"SELECT RAISE(ABORT, 'Witness evidence is append-only: {t} rows are never changed'); END"
              for t in _IMMUTABLE]
    with conn:
        for st in stmts:
            conn.execute(st)
        conn.execute("INSERT INTO schema_migrations VALUES (?,?,?)", (version, desc, utcnow()))
        conn.execute(f"PRAGMA user_version = {version}")


MIGRATIONS = [(1, "initial normalized schema (brief section 8 + attempts/exchanges/checks/evidence)", _V1),
              (2, "measurements table (REQ-08/09 timings) and exchanges.local_port", _V2),
              (3, "mutants table, runs.kind 'mutant' and runs.mutant_id (table rebuild)", _v3),
              (4, "attempts.outcome/predicates (retry attribution) and capture_flows (packet evidence)", _V4),
              (5, "run_plan (declared selection), results.predicates (decision basis) and append-only guards on "
                  "evidence tables", _v5)]


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def wall_to_iso(t: float | None) -> str | None:
    if t is None:
        return None
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def connect(path: str | os.PathLike) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise RuntimeError("SQLite foreign keys could not be enabled")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
                 "version INTEGER PRIMARY KEY, description TEXT NOT NULL, applied_at TEXT NOT NULL)")
    have = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    for version, desc, sql in MIGRATIONS:
        if version in have:
            continue
        if callable(sql):      # needs its own transaction control (table rebuild)
            sql(conn, version, desc)
            continue
        with conn:   # one transaction per migration
            for stmt in (s.strip() for s in sql.split(";")):
                if stmt:
                    conn.execute(stmt)
            conn.execute("INSERT INTO schema_migrations VALUES (?,?,?)", (version, desc, utcnow()))
            conn.execute(f"PRAGMA user_version = {version}")
    return max([v for v, _, _ in MIGRATIONS])


# ---------------------------------------------------------------- reference data

_REQ_ROW = re.compile(r"^\|\s*(REQ-\d{2})\s*\|\s*(.+?)\s*\|")


def requirements_from_md(path: str | os.PathLike) -> dict[str, str]:
    """REQ-ID -> requirement text, from the table in docs/requirements.md (single source)."""
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = _REQ_ROW.match(line)
        if m and m.group(1) not in out:
            out[m.group(1)] = m.group(2)
    return out


def sync_reference(conn, *, requirements: dict[str, str], devices: list[dict], cases, faults, mutants=()) -> None:
    """Upsert REQs, inventory devices, the case catalog, fault catalog and mutant catalog."""
    with conn:
        for m in mutants:
            conn.execute("""INSERT INTO mutants VALUES (?,?,?,?) ON CONFLICT(mutant_id) DO UPDATE SET
                spec=excluded.spec, description=excluded.description, predicted=excluded.predicted""",
                         (m.mutant_id, m.spec, m.description, m.predicted))
        for rid, text in requirements.items():
            conn.execute("INSERT INTO requirements VALUES (?,?) ON CONFLICT(req_id) DO UPDATE SET text=excluded.text",
                         (rid, text))
        for d in devices:
            conn.execute("""INSERT INTO devices VALUES (?,?,?,?,?,?) ON CONFLICT(device_id) DO UPDATE SET
                hostname=excluded.hostname, expected_addr=excluded.expected_addr, port=excluded.port,
                expected_serial=excluded.expected_serial, expected_fw=excluded.expected_fw""",
                         (d["device_id"], d["hostname"], d["address"], d["port"], d["serial"], d["fw_version"]))
        for f in faults:
            conn.execute("""INSERT INTO faults VALUES (?,?,?,?,?,?) ON CONFLICT(fault_id) DO UPDATE SET
                catalog_id=excluded.catalog_id, kind=excluded.kind, params=excluded.params,
                expected_category=excluded.expected_category, description=excluded.description""",
                         (f.fault_id, f.catalog_id, f.kind, f.params, f.expected_category, f.description))
        for c in cases:
            conn.execute("""INSERT INTO cases VALUES (?,?,?) ON CONFLICT(case_id) DO UPDATE SET
                kind=excluded.kind, description=excluded.description""", (c.case_id, c.kind, c.description))
            conn.execute("DELETE FROM case_requirements WHERE case_id=?", (c.case_id,))
            for r in c.reqs:
                if r not in requirements:
                    raise ValueError(f"case {c.case_id} traces to unknown requirement {r}")
                conn.execute("INSERT INTO case_requirements VALUES (?,?)", (c.case_id, r))


# ---------------------------------------------------------------- runs

def start_run(conn, *, kind: str, git_sha: str | None, git_dirty: int | None, clean_env: int,
              runner_host: str, notes: str = "", mutant_id: str | None = None) -> int:
    with conn:
        cur = conn.execute("INSERT INTO runs (started_at, kind, git_sha, git_dirty, clean_env, runner_host, notes,"
                           " mutant_id) VALUES (?,?,?,?,?,?,?,?)",
                           (utcnow(), kind, git_sha, git_dirty, clean_env, runner_host, notes, mutant_id))
    return cur.lastrowid


def set_clean_env(conn, run_id: int, clean: bool) -> None:
    with conn:
        conn.execute("UPDATE runs SET clean_env=? WHERE run_id=?", (int(clean), run_id))
        put_env(conn, run_id, {"runs.clean_env": str(int(clean))})


def mark_contaminated(conn, run_id: int, why: str) -> None:
    with conn:
        conn.execute("UPDATE runs SET contaminated=1, notes=trim(coalesce(notes,'') || ' | contaminated: ' || ?)"
                     " WHERE run_id=?", (why, run_id))


def mark_aborted_runs(conn, current_run_id: int) -> list[int]:
    """Earlier runs that never finished (runner killed) are contaminated: their faults
    were reverted by a dead-man timer or a reset, not by the run itself. Only runs that started before this session
    (smaller run id) can have been found unfinished by it, never itself (acceptance contract I1.2)."""
    ids = [r[0] for r in conn.execute("SELECT run_id FROM runs WHERE finished_at IS NULL AND run_id < ?"
                                      " AND coalesce(notes, '') NOT LIKE '%aborted: never finished%'",
                                      (current_run_id,))]
    with conn:
        for rid in ids:
            conn.execute("UPDATE runs SET contaminated=1, notes=trim(coalesce(notes,'') || ?) WHERE run_id=?",
                         (f" | aborted: never finished (detected by run {current_run_id})", rid))
    return ids


def record_plan(conn, run_id: int, instances) -> str:
    """The run's declared selection [(case_id, device_id or None)], written before its first case (acceptance contract
    I1.3). Returns the canonical plan document; the live session indexes it as session/plan.json. A duplicate,
    uncatalogued or non-inventory instance is refused by the schema (unique index, foreign keys)."""
    rows = sorted(((c, d) for c, d in instances), key=lambda x: (x[0], x[1] or ""))
    now = utcnow()
    with conn:
        for c, d in rows:
            conn.execute("INSERT INTO run_plan (run_id, case_id, device_id, planned_at) VALUES (?,?,?,?)",
                         (run_id, c, d, now))
    return json.dumps({"run_id": run_id, "planned_at": now, "instances": [[c, d] for c, d in rows]}, indent=1) + "\n"


def finish_run(conn, run_id: int) -> None:
    with conn:
        conn.execute("UPDATE runs SET finished_at=? WHERE run_id=?", (utcnow(), run_id))


def put_env(conn, run_id: int, kv: dict[str, str]) -> None:
    with conn:
        for k, v in kv.items():
            conn.execute("INSERT INTO environment VALUES (?,?,?) ON CONFLICT(run_id,key) DO UPDATE SET value=excluded.value",
                         (run_id, k, "" if v is None else str(v)))


def add_checks(conn, run_id: int, phase: str, vm: str, checks: list[dict], result_id: int | None = None) -> None:
    now = utcnow()
    with conn:
        for c in checks:
            conn.execute("INSERT INTO checks (run_id,result_id,phase,vm,name,status,detail,checked_at) VALUES (?,?,?,?,?,?,?,?)",
                         (run_id, result_id, phase, vm, c["name"], c["status"], c.get("detail", ""), now))


# ---------------------------------------------------------------- results

def insert_result(conn, *, run_id, case_id, device_id, fault_id, expected, observed, first_attempt,
                  attempts, latency_ms, detection_ms, verdict, attribution, detail, preflight,
                  evidence_path, observed_at, duration_ms, predicates: dict | None = None) -> int:
    """`predicates`: every predicate the verdict was decided on (schema v5; None = no decision was made)."""
    cols = ("run_id, case_id, device_id, fault_id, expected_category, observed_category, first_attempt_category, "
            "attempts, latency_ms, detection_ms, verdict, attribution, detail, preflight, evidence_path, observed_at, "
            "duration_ms")
    vals = [run_id, case_id, device_id, fault_id, expected, observed, first_attempt, attempts, latency_ms,
            detection_ms, verdict, attribution, detail, preflight, evidence_path, observed_at, duration_ms]
    if predicates is not None:
        cols += ", predicates"
        vals.append(json.dumps(predicates, sort_keys=True))
    with conn:
        cur = conn.execute(f"INSERT INTO results ({cols}) VALUES ({','.join('?' * len(vals))})", vals)
    return cur.lastrowid


def insert_attempt(conn, result_id: int, attempt_no: int, category, stage, detail, started_at, duration_ms,
                   exchanges: list[tuple], outcome: str | None = None, predicates: dict | None = None) -> int:
    """exchanges: list of (Observation, Classification). outcome: runner/cases.Attempt.outcome()."""
    with conn:
        cur = conn.execute("INSERT INTO attempts (result_id,attempt_no,category,stage,detail,started_at,duration_ms,"
                           "outcome,predicates) VALUES (?,?,?,?,?,?,?,?,?)",
                           (result_id, attempt_no, category, stage, detail, started_at, duration_ms, outcome,
                            None if predicates is None else json.dumps(predicates, sort_keys=True)))
        aid = cur.lastrowid
        for i, (o, c) in enumerate(exchanges, 1):
            conn.execute(
                """INSERT INTO exchanges (attempt_id, ord, cmd, req_id, host, addr, port, category, stage, detail,
                   stage_failed, os_error, read_end, bytes, resolve_ms, connect_ms, response_ms, latency_ms,
                   duration_ms, t_send, t_recv, response, local_port)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (aid, i, o.cmd, o.req_id, o.host, o.addr, o.port, c.category, c.stage, c.detail, o.stage_failed,
                 o.error, o.end, len(o.data), o.resolve_ms, o.connect_ms, o.response_ms, o.latency_ms,
                 o.duration_ms, wall_to_iso(o.t_send_wall), wall_to_iso(o.t_recv_wall), o.data or None,
                 getattr(o, "local_port", None)))
    return aid


def add_measurement(conn, result_id: int, name: str, value: float | None, *, unit: str = "ms",
                    bound: float | None = None, clock: str = "ctl-monotonic", detail: str = "") -> None:
    with conn:
        conn.execute("INSERT INTO measurements (result_id,name,value,unit,bound,clock,detail) VALUES (?,?,?,?,?,?,?)",
                     (result_id, name, value, unit, bound, clock, detail))


def set_postflight(conn, result_id: int, green: bool) -> None:
    with conn:
        conn.execute("UPDATE results SET postflight=? WHERE result_id=?", ("green" if green else "red", result_id))


def add_fault_event(conn, *, run_id, result_id, fault_id, vm, applied_at, removed_at, removal_verified, detail) -> None:
    with conn:
        conn.execute("INSERT INTO fault_events (run_id,result_id,fault_id,vm,applied_at,removed_at,removal_verified,detail)"
                     " VALUES (?,?,?,?,?,?,?,?)",
                     (run_id, result_id, fault_id, vm, applied_at, removed_at,
                      None if removal_verified is None else int(removal_verified), detail))


def add_evidence(conn, *, run_id: int, result_id: int | None, kind: str, root: str | os.PathLike,
                 path: str | os.PathLike) -> None:
    p = Path(path)
    data = p.read_bytes()
    with conn:
        conn.execute("INSERT INTO evidence (run_id,result_id,kind,path,sha256,bytes,created_at) VALUES (?,?,?,?,?,?,?)",
                     (run_id, result_id, kind, str(p.relative_to(root)), hashlib.sha256(data).hexdigest(),
                      len(data), utcnow()))


def add_capture_flow(conn, result_id: int, *, capture: str, bpf: str, expected: bool, packets: int | None,
                     detail: str) -> None:
    with conn:
        conn.execute("INSERT INTO capture_flows (result_id,capture,filter,expected,packets,detail) VALUES (?,?,?,?,?,?)",
                     (result_id, capture, bpf, int(expected), packets, detail))


# ---------------------------------------------------------------- commissioning (independent audit F-01)

def _required_values() -> str:
    from runner.catalog import COMMISSIONING_REQUIRED
    return ", ".join(f"('{case_id}', {int(per_device)})" for case_id, per_device in COMMISSIONING_REQUIRED)


def _inventory_values(inv: dict | None, conn=None) -> tuple[str, dict]:
    """(device_id, expected firmware) of every INVENTORY device: the required set (FV-02), never the devices table.
    Returns the VALUES list of named placeholders and their bound values."""
    from runner import contract, evidence
    inv = inv or evidence.repo_inventory()
    fw = {d["device_id"]: d["fw_version"] for d in inv["devices"]}
    devs = contract.required_devices(conn, inv)
    params = {k: v for i, d in enumerate(devs) for k, v in ((f"inv_dev_{i}", d), (f"inv_fw_{i}", fw.get(d, "")))}
    return ", ".join(f"(:inv_dev_{i}, :inv_fw_{i})" for i in range(len(devs))), params


# One row per INVENTORY device with every unmet commissioning prerequisite of run :run (NULL = commissioned).
# The required set is the WHOLE catalog of commissioning cases: per-device cases for every inventory device (FV-02: a
# device deleted from the devices table is a gap, never a smaller requirement), run-level cases once (they gate every
# device). Every required instance needs exactly ONE result in the run, with verdict pass,
# preflight green and postflight green; the run must be a finished, clean, uncontaminated baseline; no result in
# the run may have observed WRONG_IDENTITY for the device (REQ-02) and no other result on it may be non-pass; the
# firmware version the run recorded must equal the inventory's and the device build must be stock.
COMMISSIONING_GAPS = """
WITH req(case_id, per_device) AS (VALUES {required}),
devices_inv(device_id, expected_fw) AS (VALUES {inventory}),
need AS (SELECT d.device_id AS dev, q.case_id, CASE WHEN q.per_device = 1 THEN d.device_id END AS target
         FROM devices_inv d CROSS JOIN req q),
ru AS (SELECT * FROM runs WHERE run_id = :run),
gap(dev, why) AS (
  SELECT d.device_id, 'run ' || :run || ' does not exist' FROM devices_inv d WHERE NOT EXISTS (SELECT 1 FROM ru)
  UNION ALL SELECT d.device_id, 'run kind ' || ru.kind || ' (only a baseline run commissions)'
    FROM devices_inv d, ru WHERE ru.kind <> 'baseline'
  UNION ALL SELECT d.device_id, 'run not finished (aborted or still running)' FROM devices_inv d, ru
    WHERE ru.finished_at IS NULL
  UNION ALL SELECT d.device_id, 'run started with a red preflight (clean_env=0)' FROM devices_inv d, ru
    WHERE ru.clean_env <> 1
  UNION ALL SELECT d.device_id, 'run contaminated' FROM devices_inv d, ru WHERE ru.contaminated <> 0
  UNION ALL SELECT n.dev, 'missing ' || n.case_id || coalesce('/' || n.target, ' (run-level)') FROM need n
    WHERE NOT EXISTS (SELECT 1 FROM results r WHERE r.run_id = :run AND r.case_id = n.case_id
                        AND r.device_id IS n.target)
  UNION ALL SELECT n.dev, 'duplicate ' || n.case_id || coalesce('/' || n.target, ' (run-level)')
                   || ' (' || count(*) || ' results)'
    FROM need n JOIN results r ON r.run_id = :run AND r.case_id = n.case_id AND r.device_id IS n.target
    GROUP BY n.dev, n.case_id, n.target HAVING count(*) > 1
  UNION ALL SELECT n.dev, n.case_id || coalesce('/' || n.target, ' (run-level)') || ' ' || r.verdict || '/'
                   || r.attribution || CASE WHEN r.preflight <> 'green' THEN ', preflight red' ELSE '' END
                   || CASE WHEN coalesce(r.postflight, '') <> 'green'
                           THEN ', postflight ' || coalesce(r.postflight, 'not recorded') ELSE '' END
    FROM need n JOIN results r ON r.run_id = :run AND r.case_id = n.case_id AND r.device_id IS n.target
    WHERE r.verdict <> 'pass' OR r.preflight <> 'green' OR coalesce(r.postflight, '') <> 'green'
  UNION ALL SELECT DISTINCT x.device_id, 'WRONG_IDENTITY observed (' || x.case_id || ')' FROM results x
    WHERE x.run_id = :run AND x.device_id IS NOT NULL AND x.observed_category = 'WRONG_IDENTITY'
  UNION ALL SELECT x.device_id, 'non-pass result ' || x.case_id || ' ' || x.verdict || '/' || x.attribution
    FROM results x WHERE x.run_id = :run AND x.device_id IS NOT NULL AND x.verdict <> 'pass'
      AND x.case_id NOT IN (SELECT case_id FROM req)
  UNION ALL SELECT d.device_id, 'recorded firmware '
                   || CASE WHEN e.value IS NULL THEN 'missing' ELSE quote(e.value) END
                   || ' <> inventory ' || quote(d.expected_fw)
    FROM devices_inv d LEFT JOIN environment e ON e.run_id = :run AND e.key = 'fw_version.' || d.device_id
    WHERE e.value IS NOT d.expected_fw
  UNION ALL SELECT d.device_id, 'device build '
                   || CASE WHEN e.value IS NULL THEN 'not recorded' ELSE quote(e.value) END || ' (stock required)'
    FROM devices_inv d LEFT JOIN environment e ON e.run_id = :run AND e.key = 'device_build.' || d.device_id
    WHERE e.value IS NOT 'stock'
  UNION ALL SELECT d.device_id, 'inventory device absent from the devices table' FROM devices_inv d
    WHERE NOT EXISTS (SELECT 1 FROM devices x WHERE x.device_id = d.device_id))
SELECT d.device_id, (SELECT group_concat(g.why, '; ') FROM gap g WHERE g.dev = d.device_id) AS gaps
FROM devices_inv d ORDER BY d.device_id"""


# Every REQUIRED commissioning instance (case, inventory device or NULL for run-level) with its number of results in
# run :run. A run is complete when every count is exactly 1.
COMMISSIONING_COVERAGE = """
WITH req(case_id, per_device) AS (VALUES {required}),
devices_inv(device_id, expected_fw) AS (VALUES {inventory}),
need AS (SELECT DISTINCT q.case_id, CASE WHEN q.per_device = 1 THEN d.device_id END AS target
         FROM devices_inv d CROSS JOIN req q)
SELECT n.case_id, n.target, (SELECT count(*) FROM results r WHERE r.run_id = :run AND r.case_id = n.case_id
                               AND r.device_id IS n.target) AS n
FROM need n ORDER BY n.case_id, n.target"""


def commissioning_gaps(conn, run_id: int, inv: dict | None = None, evidence_root=None) -> dict[str, str | None]:
    """{inventory device_id: unmet prerequisites ('; '-joined) or None if run `run_id` commissions it}:
    COMMISSIONING_GAPS, plus the run's environment record validated by runner/evidence.check_environment (second
    independent audit R-01: a recorded C-ENVIRONMENT pass alone was trusted over a whitespace-only or contradictory
    value), plus the evidence contract of the run and of its prerequisite results (runner/contract.py, acceptance
    contract I10.5: a pass verdict whose attempts, exchanges, captures or session evidence are missing or
    contradictory commissions nothing). With `evidence_root` the files are verified too (hashes, packet recounts,
    plan file, case directories)."""
    from runner import contract, evidence
    inv = inv or evidence.repo_inventory()
    values, params = _inventory_values(inv, conn)
    sql = COMMISSIONING_GAPS.format(required=_required_values(), inventory=values)
    gaps = {r[0]: r[1] for r in conn.execute(sql, {"run": run_id, **params}).fetchall()}
    cur = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    row = cur.fetchone()
    if row is not None:
        run = dict(zip([d[0] for d in cur.description], row))
        env = {k: v for k, v in conn.execute("SELECT key, value FROM environment WHERE run_id = ?", (run_id,))}
        bad = evidence.check_environment(env, run, inv).problems
        if bad:
            why = "environment record invalid: " + "; ".join(f"{k} {v}" for k, v in sorted(bad.items()))
            gaps = {d: f"{g}; {why}" if g else why for d, g in gaps.items()}
        table = {r[0]: tuple(r[1:]) for r in conn.execute(
            "SELECT device_id, hostname, expected_addr, port, expected_serial, expected_fw FROM devices")}
        for d in inv["devices"]:              # the reference row every result joins must be the inventory's (I3)
            want = (d["hostname"], d["address"], d["port"], d["serial"], d["fw_version"])
            if d["device_id"] in table and table[d["device_id"]] != want and d["device_id"] in gaps:
                why = f"devices table row {table[d['device_id']]} differs from the inventory {want}"
                gaps[d["device_id"]] = f"{gaps[d['device_id']]}; {why}" if gaps[d["device_id"]] else why
        for d, vs in contract.commissioning_contract_gaps(conn, run_id, inv, evidence_root).items():
            if vs:
                why = "evidence contract: " + "; ".join(vs[:5]) + (f"; (+{len(vs) - 5} more)" if len(vs) > 5 else "")
                gaps[d] = f"{gaps[d]}; {why}" if gaps.get(d) else why
    return gaps


def commissioned_devices(conn, run_id: int, inv: dict | None = None, evidence_root=None) -> list[str]:
    """Devices that run `run_id` commissions: every prerequisite of commissioning_gaps holds."""
    return [dev for dev, gaps in commissioning_gaps(conn, run_id, inv, evidence_root).items() if gaps is None]
