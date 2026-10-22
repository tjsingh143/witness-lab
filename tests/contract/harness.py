"""Runs the acceptance-contract matrix: builds the reference variants, applies each declared mutation to a private
copy (in-memory database; evidence tree copied only when a mutation changes files), runs the PRODUCTION verifier
(runner.analysis.audit) and the independent oracle, and compares both with the declared expectation.

Outcome statuses: OK; FALSE_ACCEPT (production accepts where the declaration and the oracle reject); UNDETECTED
(production rejects no more than the unmutated variant already did: the attack went unnoticed); FALSE_REJECT (production rejects beyond the variant's own outcome on a benign
change or a legitimate control); WRONG_INVARIANT (production rejects, but not through the declared assertion);
MATRIX_ERROR (the oracle sees no deviation for a declared attack: the mutation itself is wrong); N/A (the attack
needs the schema-v5 run plan, absent before the repair).
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from tests.contract import matrix as MX, oracle as O, refstore as R


@dataclass
class Built:
    ref: R.Ref
    truth: dict


@dataclass
class Outcome:
    name: str
    status: str
    invariant: str = ""
    declared: list = field(default_factory=list)
    production: list = field(default_factory=list)     # violated assertions
    oracle: str = ""
    why: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


def build_all(workdir: Path, variants=None) -> dict[str, Built]:
    out = {}
    for v in (variants or list(R.VARIANTS)):
        if v == "legacy" and not R.HAS_PLAN:
            continue
        ref = R.build(workdir / v, v)
        conn = sqlite3.connect(ref.db.resolve().as_uri() + "?mode=ro", uri=True)
        out[v] = Built(ref, O.truth(conn, ref.root))
        conn.close()
    return out


def copy_store(b: Built, workdir: Path, files: bool) -> tuple[sqlite3.Connection, Path]:
    src = sqlite3.connect(b.ref.db.resolve().as_uri() + "?mode=ro", uri=True)
    conn = sqlite3.connect(":memory:")
    src.backup(conn)
    src.close()
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall():
        conn.execute(f'DROP TRIGGER "{name}"')            # an adversary first removes the append-only guards
    root = b.ref.root
    if files:
        root = Path(tempfile.mkdtemp(dir=workdir, prefix="ev-"))
        shutil.copytree(b.ref.root, root, dirs_exist_ok=True)
    return conn, root


def production(conn, root) -> tuple[set[str], dict]:
    from runner import analysis as A
    res = A.audit(conn, evidence_root=root, inventory=R.INV)
    bad = {a["id"].split("-")[0]: a["violations"] for a in res if not a["ok"]}
    return set(bad), bad


def run_steps(b: Built, steps, workdir: Path, files: bool = False):
    conn, root = copy_store(b, workdir, files)
    skipped = []
    try:
        for name, fn in steps:
            try:
                fn(MX.Ctx(conn, root, b.ref))
            except AssertionError:
                skipped.append(name)                       # its target was already removed by an earlier step
        failed, bad = production(conn, root)
        verdict, why = O.verdict(conn, root, b.truth, b.ref.expected_failures)
    finally:
        conn.close()
        if files:
            shutil.rmtree(root, ignore_errors=True)
    return failed, bad, verdict, why, skipped


def judge(name, invariant, declared_must: frozenset, accept: bool, base: frozenset, failed: set, bad: dict,
          verdict: str, why: list, skipped=()) -> Outcome:
    o = Outcome(name, "OK", invariant, sorted(declared_must), sorted(failed), verdict, why[:3], list(skipped))
    if accept:
        if verdict == "REJECT" and why and not why[0].startswith("variant expects"):
            o.status = "MATRIX_ERROR"
        elif failed != set(base):
            o.status = "FALSE_REJECT" if failed - set(base) else "FALSE_ACCEPT"
            o.why = [f"{a}: {bad[a][:2]}" for a in sorted(failed - set(base))] or o.why
        return o
    if verdict != "REJECT" or (why and why[0].startswith("variant expects")):
        o.status = "MATRIX_ERROR"
    elif not declared_must <= failed:
        o.status = ("FALSE_ACCEPT" if not failed else "UNDETECTED") if failed <= set(base) else "WRONG_INVARIANT"
        o.why = [f"{a}: {bad[a][:2]}" for a in sorted(failed - set(base))] or ["production: no additional violation"]
    return o


def run_mutation(m: MX.Mutation, built: dict[str, Built], workdir: Path) -> Outcome:
    if m.needs_plan and not R.HAS_PLAN or m.base not in built:
        return Outcome(m.name, "N/A", m.invariant, sorted(m.must))
    b = built[m.base]
    failed, bad, verdict, why, _ = run_steps(b, [(m.name, m.apply)], workdir, m.files)
    return judge(m.name, m.invariant, m.must, m.accept, b.ref.expected_failures, failed, bad, verdict, why)


def run_control(v: str, b: Built, workdir: Path) -> Outcome:
    failed, bad, verdict, why, _ = run_steps(b, [], workdir)
    return judge(f"control {v}", "-", frozenset(), True, b.ref.expected_failures, failed, bad, verdict, why)


def run_combination(seed: int, built: dict[str, Built], workdir: Path, base: str = "reference",
                    steps=None) -> Outcome:
    b = built[base]
    steps = steps if steps is not None else MX.combination(seed)
    failed, bad, verdict, why, skipped = run_steps(b, steps, workdir)
    o = judge(f"seed {seed} [{base}]: " + " + ".join(n for n, _ in steps), "combination", frozenset(), False,
              b.ref.expected_failures, failed, bad, verdict, why, skipped)
    if o.status == "OK" and failed <= set(b.ref.expected_failures):
        o.status = "FALSE_ACCEPT" if not failed else "UNDETECTED"
    return o


def shrink(seed: int, built, workdir: Path, base: str = "reference") -> list[str]:
    """Greedy minimisation of a failing combination: drop each step while the combination still fails."""
    steps = MX.combination(seed)
    i = 0
    while i < len(steps) and len(steps) > 1:
        trial = steps[:i] + steps[i + 1:]
        if run_combination(seed, built, workdir, base, trial).status != "OK":
            steps = trial
        else:
            i += 1
    return [n for n, _ in steps]
