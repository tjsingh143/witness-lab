#!/usr/bin/env python3
"""Verify the acceptance contract (docs/acceptance-contract.md) against its independent oracle, in one command:

    .venv/bin/python scripts/verify_acceptance_contract.py [--seeds 60] [--json out.json] [--no-self-test]

Builds synthetic reference stores in a temporary directory (never touches results/ or the VMs), then checks: every
legitimate control variant has exactly its declared outcome; every declared mutation is rejected through its
declared assertion (benign ones accepted); seeded random combinations of attacks are rejected and, on a genuinely
failing store, never make it acceptable; and (self-test) weakening a critical production check makes this suite
fail. Exit 0 only if every check agrees with the declaration and the oracle; each disagreement is printed with the
contract invariant, the declared and actual violated assertions, and (for combinations) a minimal failing subset.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.contract import harness as H, matrix as MX, refstore as R  # noqa: E402


# Deliberately weakened production checks (in-process patches of a disposable import; no file changes): each
# restores one defect class this repair closes. Every one of them must make the suite fail.
_HEAD_LATEST_FAIR = ("SELECT r2.result_id FROM results r2 WHERE r2.run_id = (SELECT max(r3.run_id) FROM results r3 "
                     "JOIN runs ru USING (run_id) WHERE r3.case_id = r2.case_id AND r3.device_id IS r2.device_id "
                     "AND ru.kind <> 'mutant' AND {fair})")


class _Everything:
    """A set that contains everything: every measurement allowed outside its bound."""
    def __contains__(self, item):
        return True


def _weakenings():
    from runner import analysis as A, contract as C

    @contextmanager
    def patch(*triples):
        old = [(o, n, getattr(o, n)) for o, n, _ in triples]
        for o, n, v in triples:
            setattr(o, n, v)
        try:
            yield
        finally:
            for o, n, v in old:
                setattr(o, n, v)

    flow_plan = A.flow_plan

    def skip_without_exchanges(conn, current, src=None):             # FV-01: the obligation from surviving rows
        return {k: v for k, v in flow_plan(conn, current, src).items() if any(a["exchanges"] for a in v["attempt_rows"])}

    def results_only_baseline(conn, inv=None):                       # RC-4: A18 over executed instances only
        for (run_id,) in conn.execute("SELECT run_id FROM runs ru WHERE ru.kind = 'baseline' AND " + A.FAIR
                                      + " ORDER BY run_id DESC").fetchall():
            if all(n >= 1 for _, _, n in A.commissioning_coverage(conn, run_id, inv)):
                return run_id
        return None

    def abort_within_interval(ru, det, started, sessions):          # IC-01: the pre-repair corroboration
        when = started.get(det)
        ok = when is not None and when >= ru["started_at"] and (ru["finished_at"] is None or ru["finished_at"] >= when)
        return None if ok else "not found unfinished"

    abort_unconfirmed = C._abort_unconfirmed

    def overlap_from_own_finish(ru, det, started, sessions):         # IC-01 review F1: the runs rows alone
        return abort_unconfirmed(ru, det, started, {r: (t, "9999-12-31T23:59:59.999Z") for r, t in started.items()})

    def decision_as_recorded(r, atts, k, exp, outcomes, inv, bad):   # IC-02: the pre-repair decision check
        try:
            preds = json.loads(r.get("predicates") or "null")
        except ValueError:
            preds = "unreadable"
        if not isinstance(preds, dict) or not all(isinstance(v, bool) for v in preds.values()):
            bad("I4.5", "decision predicates not recorded")
            return
        if r["verdict"] == "pass" and not all(preds.values()):
            bad("I4.5", "pass, but a recorded predicate is false")
        if atts and atts[-1]["predicates"]:
            final = json.loads(atts[-1]["predicates"])
            if any(preds.get(n) != v for n, v in final.items()):
                bad("I4.5", "decision predicates disagree with the final attempt's")

    session_environment = C._session_environment

    def session_obligation_from_index(ru, env, files, root, inv, v5, **kw):
        # Restore only the omission bypass, keeping all previous F3 comparison protections intact.
        fair = ru["finished_at"] is not None and ru["clean_env"] == 1 and ru["contaminated"] == 0
        present = root is not None and (Path(root) / f"run-{ru['run_id']}/session/environment.json").exists()
        if not fair and not files and not present:
            return []
        return session_environment(ru, env, files, root, inv, v5, **kw)

    head_latest = _HEAD_LATEST_FAIR.format(fair=A.FAIR)
    a4 = next(x for x in A.ASSERTIONS if x[0].startswith("A4-"))
    head_a4 = (a4[0], a4[1], a4[2].split(" UNION ALL SELECT cr.req_id || ': ' || l.case_id")[0]
               .replace(A.LATEST_CURRENT, head_latest))
    return {
        "A24 evidence-chain check disabled": lambda: patch((C, "result_violations", lambda *a, **k: {})),
        "A23 run selection/receipt check disabled": lambda: patch((C, "_runs", lambda *a, **k: [])),
        "FV-01: flows only for results that kept exchanges": lambda: patch((A, "flow_plan", skip_without_exchanges)),
        "FV-02: required devices from the devices table": lambda: patch(
            (C, "required_devices", lambda conn, inv: [r[0] for r in conn.execute(
                "SELECT device_id FROM devices ORDER BY device_id")] if conn is not None else
             [d["device_id"] for d in inv["devices"]])),
        "RC-4: latest evidence and A18 ignore the run plan": lambda: patch(
            (A, "LATEST_CURRENT", head_latest), (A, "latest_complete_baseline", results_only_baseline),
            (A, "ASSERTIONS", tuple(head_a4 if x is a4 else x for x in A.ASSERTIONS))),
        "I5.6: responses behind PASS and predicates not re-read": lambda: patch(
            (C, "response_violations", lambda *a, **k: [])),
        "I1.2: contamination flag trusted without a corroborating record": lambda: patch(
            (C, "_contamination_cause", lambda *a, **k: None)),
        "I4.5: decision predicates and bounds not checked": lambda: patch((C, "_decision", lambda *a, **k: None),
                                                                          (C, "OUTSIDE_BOUND_ON_PASS", _Everything())),
        "IC-01: an abort corroborated by any run started within it (itself included)": lambda: patch(
            (C, "_abort_unconfirmed", abort_within_interval)),
        "IC-01 review F1: the overlap taken from the runs rows, not the session records": lambda: patch(
            (C, "_abort_unconfirmed", overlap_from_own_finish)),
        "IC-02: decision predicates checked only as recorded (names taken from the row)": lambda: patch(
            (C, "_decision", decision_as_recorded)),
        "IC-02: a predicate name recorded twice read as its last record": lambda: patch(
            (C, "_predicate_record", json.loads)),
        "F3: session environment comparison disabled": lambda: patch(
            (C, "_session_environment", lambda *a, **k: [])),
        "F3 omission: session obligation derived only from surviving index/file": lambda: patch(
            (C, "_session_environment", session_obligation_from_index)),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seeds", type=int, default=60, help="random combinations per base store (reproducible)")
    p.add_argument("--json", help="write every outcome here")
    p.add_argument("--no-self-test", action="store_true")
    p.add_argument("--workdir", help="keep the generated stores here (default: a temporary directory)")
    a = p.parse_args(argv)
    t0 = time.monotonic()
    work = Path(a.workdir or tempfile.mkdtemp(prefix="witness-contract-"))
    work.mkdir(parents=True, exist_ok=True)
    built = H.build_all(work)
    outcomes = [H.run_control(v, b, work) for v, b in built.items()]
    print(f"controls checked: {len(outcomes)}; checking declared mutations", flush=True)
    outcomes += [H.run_mutation(m, built, work) for m in MX.build_matrix()]
    print(f"controls and mutations checked: {len(outcomes)}; checking {2 * a.seeds} seeded combinations", flush=True)
    for seed in range(a.seeds):
        o = H.run_combination(seed, built, work)
        if o.status != "OK":
            o.why.append(f"minimal failing steps: {H.shrink(seed, built, work)}")
        outcomes.append(o)
        f = H.run_combination(seed, built, work, base="current-failure")
        if not f.production:
            f.status = "FALSE_ACCEPT"
            f.why.append("a genuinely failing store became acceptable after evidence was removed")
        else:
            f.status = "OK"
        outcomes.append(f)
    self_test = {}
    if not a.no_self_test:
        try:
            weak = _weakenings()
        except (ImportError, AttributeError) as e:
            self_test["unavailable"] = f"{type(e).__name__}: {e}"
            weak = {}
        for name, ctx in weak.items():
            print(f"checking weakening: {name}", flush=True)
            with ctx():
                caught = [o.name for o in (H.run_mutation(m, built, work) for m in MX.build_matrix())
                          if o.status not in ("OK", "N/A")]
            self_test[name] = {"detected": bool(caught), "mutations_now_failing": len(caught), "e.g.": caught[:3]}
    bad = [o for o in outcomes if o.status not in ("OK", "N/A")]
    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o.status] = counts.get(o.status, 0) + 1
    print(f"acceptance contract: {len(outcomes)} checks in {time.monotonic() - t0:.1f}s; "
          + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + f"; schema v5 plan: {R.HAS_PLAN}")
    for o in bad:
        print(f"  {o.status:15} [{o.invariant}] {o.name}\n      declared {o.declared} production {o.production} "
              f"oracle {o.oracle}; {'; '.join(map(str, o.why))[:400]}")
    undetected_weakenings = [k for k, v in self_test.items() if isinstance(v, dict) and not v["detected"]]
    for k, v in self_test.items():
        print(f"  self-test: {k}: " + (v if isinstance(v, str) else
                                       f"{'DETECTED' if v['detected'] else 'NOT DETECTED'} ({v['mutations_now_failing']} "
                                       f"mutations fail, e.g. {v['e.g.']})"))
    if a.json:
        Path(a.json).write_text(json.dumps({"counts": counts, "plan": R.HAS_PLAN, "outcomes": [asdict(o) for o in outcomes],
                                            "self_test": self_test}, indent=1, default=str))
    ok = not bad and not undetected_weakenings and "unavailable" not in self_test or (a.no_self_test and not bad)
    print("RESULT:", "PASS" if ok else "FAIL")
    if not a.workdir:                        # generated stores (~50 MB) are not kept unless asked for
        shutil.rmtree(work, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
