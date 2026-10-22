"""Independent contract verification IC-02 (docs/independent-contract-verification.md): the predicates a verdict was
decided on (results.predicates, schema v5) were checked only as recorded, so deleting a failed C-GATEWAY predicate and
flipping the verdict to pass made a failing case acceptable, and '{}' erased every gateway decision. The names each
case records come from the case contract (runner/contract.py CASE_PREDICATES, anchored below to what tests/live
records) and the final attempt's exchanges, never from the row; the verdict must be the one its recorded basis
yields. Fixture stores (tests/contract/refstore.py); never lab evidence."""
import ast
import inspect
import itertools
import json
from pathlib import Path

import pytest

from runner import analysis as A, catalog, contract as C, db, evidence as EV
from storefix import INV, accepted_store, env_ok, new_store
from tests.contract import refstore as R

LIVE = Path(__file__).resolve().parents[1] / "live"


# ---------------------------------------------------------------- what the live cases record (static, from source)

class Unrenderable(AssertionError):
    """A live code shape the anchor cannot render exactly: it fails rather than guess (independent review)."""


def _eval(node, env: dict):
    return eval(compile(ast.Expression(node), "<tests/live>", "eval"), {"catalog": catalog}, dict(env))


def _render(node, env: dict, parents: dict) -> set[str]:
    """A recorded predicate name: a string, or an f-string evaluated with the helper's literal arguments and, for a
    loop variable, every value of the enclosing `for` loop's sequence."""
    if isinstance(node, ast.Constant):
        return {node.value}
    parts = []
    for v in node.values:
        if isinstance(v, ast.Constant):
            parts.append([v.value])
            continue
        if v.conversion != -1 or v.format_spec is not None:
            raise Unrenderable(f"line {node.lineno}: f-string conversion/format the anchor does not render")
        loop, p = None, parents.get(node)
        while p is not None and loop is None:
            if isinstance(p, ast.For) and isinstance(p.target, ast.Name) and isinstance(v.value, ast.Name) \
                    and p.target.id == v.value.id:
                loop = p
            p = parents.get(p)
        parts.append([str(x) for x in (_eval(loop.iter, env) if loop else [_eval(v.value, env)])])
    return {"".join(c) for c in itertools.product(*parts)}


def _finish_sets(fn, env: dict, fns: dict) -> list[tuple[str, frozenset]]:
    """(kind, predicate names) of every case.finish / case.finish_observed call the live function makes, also inside
    the module helpers it calls (their parameters bound to the literal arguments it passes): `preds` stands for every
    name assigned to it (the dict, `preds[name] = ...`, `preds.update({...})`), recorded unconditionally; a dict
    literal is a set of its own. Any other shape raises Unrenderable."""
    parents = {c: p for p in ast.walk(fn) for c in ast.iter_child_nodes(p)}
    env = dict(env)
    for s in fn.body:                       # helper-level values, e.g. expected = catalog.FAULTS_BY_ID[...].expected_category
        if isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name):
            try:
                env[s.targets[0].id] = _eval(s.value, env)
            except Exception:  # noqa: BLE001 - values of the lab (gateway samples, timings) are not names
                pass
    preds = set()
    for n in ast.walk(fn):
        keys = []
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == "preds" and isinstance(n.value, ast.Dict):
                    keys += n.value.keys
                elif isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == "preds":
                    keys.append(t.slice)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "update" \
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "preds":
            keys += [k for a in n.args if isinstance(a, ast.Dict) for k in a.keys]
        for k in keys:
            q = parents.get(k)
            while q is not None and q is not fn:     # a name recorded on one path only is not "always recorded"
                if isinstance(q, (ast.If, ast.IfExp, ast.Try, ast.While, ast.comprehension)):
                    raise Unrenderable(f"line {k.lineno}: predicate name recorded conditionally")
                q = parents.get(q)
            preds |= _render(k, env, parents)
    out = []
    for n in ast.walk(fn):
        if not isinstance(n, ast.Call):
            continue
        if isinstance(n.func, ast.Attribute) and n.func.attr in ("finish", "finish_observed") \
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "case":
            arg = {k.arg: k.value for k in n.keywords}
            arg = arg.get("extra_predicates", arg.get("predicates"))
            if arg is None:                       # a case without predicates of its own
                out.append(("complete", frozenset()))
            elif isinstance(arg, ast.Name) and arg.id == "preds":
                out.append(("complete", frozenset(preds)))
            elif isinstance(arg, ast.Dict):       # a literal set: the complete one only if it is the only call
                out.append(("literal", frozenset(x for k in arg.keys for x in _render(k, env, parents))))
            else:
                raise Unrenderable(f"line {n.lineno}: predicates passed as {ast.unparse(arg)}")
        elif isinstance(n.func, ast.Name) and n.func.id in fns:
            helper = fns[n.func.id]
            bound = {}
            for prm, a in zip(helper.args.args, n.args):
                try:
                    bound[prm.arg] = ast.literal_eval(a)
                except ValueError:
                    pass
            out += _finish_sets(helper, bound, fns)
    return out


def live_decisions() -> dict[str, list[frozenset]]:
    """{case_id: [the predicate-name sets a case that stopped early records (FT-F12 before the restart)..., the set
    of its complete observation]}: the complete one is the call recording `preds` (or a case's only call)."""
    out = {}
    for path in sorted(LIVE.glob("test_*.py")):
        mod = ast.parse(path.read_text())
        fns = {f.name: f for f in mod.body if isinstance(f, ast.FunctionDef)}
        for f in fns.values():
            for d in f.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "case":
                    calls = _finish_sets(f, {}, fns)
                    complete = [x for k, x in calls if k == "complete"] or [x for k, x in calls if len(calls) == 1]
                    if len(complete) != 1 and calls:
                        raise Unrenderable(f"{d.args[0].value}: {len(complete)} complete decisions")
                    out[d.args[0].value] = [x for k, x in calls if k == "literal" and len(calls) > 1] + complete
    return out


def instance_devices(case_id: str) -> list:
    c = catalog.CASES_BY_ID[case_id]
    return [catalog.FAULT_DEVICE] if c.kind == "fault" else [d["device_id"] for d in INV["devices"]] \
        if c.per_device else [None]


def test_every_catalog_case_has_a_live_test():
    assert set(live_decisions()) == set(catalog.CASES_BY_ID)


@pytest.mark.parametrize("case_id", sorted(catalog.CASES_BY_ID))
def test_contract_names_exactly_the_predicates_the_live_case_records(case_id):
    live = live_decisions()[case_id]
    for dev in instance_devices(case_id):
        full, partial = C.case_predicates(case_id, dev, INV)
        if case_id == "C-ENVIRONMENT":            # finish_check(preds) over every REQ-10 key (required_env_keys)
            assert not live and full == set(EV.required_env_keys(INV)) and not partial
            continue
        assert full == live[-1], (sorted(full - live[-1]), sorted(live[-1] - full))
        assert set(partial) == set(live[:-1]), (partial, live[:-1])


@pytest.mark.parametrize("case_id", sorted(catalog.CASES_BY_ID))
def test_reference_writer_records_the_predicates_the_live_case_records(case_id):
    """The harness's writer keeps its own copy (independent of the verifier's); both are anchored to tests/live."""
    names = set(R.case_predicates(case_id))
    if case_id == "C-ENVIRONMENT":
        assert names == set(EV.required_env_keys(INV))
    else:
        assert names == live_decisions()[case_id][-1], sorted(names ^ live_decisions()[case_id][-1])


def test_environment_and_attempt_names_come_from_their_writers():
    """C-ENVIRONMENT decides on preds over required_env_keys (the function the contract uses); the attempt-level names
    derived_predicates can yield are exactly those runner/cases.py records on an attempt."""
    env = (LIVE / "test_commissioning.py").read_text()
    assert "want = required_env_keys(INV)" in env and "for k in want}" in env and "case.finish_check(preds" in env
    cases = {t.slice.value for t in ast.walk(ast.parse((Path(C.__file__).parent / "cases.py").read_text()))
             if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Attribute) and t.value.attr == "predicates"
             and isinstance(t.slice, ast.Constant)}
    derived = {k.value for n in ast.walk(ast.parse(inspect.getsource(C.derived_predicates))) if isinstance(n, ast.Dict)
               for k in n.keys if isinstance(k, ast.Constant)}
    assert cases == derived == {"status_ok", "sensor_ok", "health_payload", "reads_complete"}


@pytest.mark.parametrize("shape", [
    "def t(case):\n    preds = {'a': True}\n    if case:\n        preds['b'] = True\n    case.finish([], 'PASS', extra_predicates=preds)",
    "def t(case):\n    p = {'a': True}\n    case.finish([], 'PASS', extra_predicates=p)",
    "def t(case, x='y'):\n    preds = {f'{x!r}_ok': True}\n    case.finish([], 'PASS', extra_predicates=preds)",
    "def t(case):\n    case.finish([], 'PASS', extra_predicates={'a': True})\n    case.finish([], 'PASS', extra_predicates={'b': False})",
], ids=["conditional-name", "other-dict-name", "fstring-conversion", "two-literal-decisions"])
def test_anchor_fails_on_a_shape_it_cannot_render(shape):
    """Independent review: shapes tests/live does not use today must make the anchor fail, never misrender."""
    mod = ast.parse("@pytest.mark.case('X')\n" + shape)
    fns = {f.name: f for f in mod.body if isinstance(f, ast.FunctionDef)}
    with pytest.raises(Unrenderable):
        calls = _finish_sets(fns["t"], {}, fns)
        complete = [x for k, x in calls if k == "complete"] or [x for k, x in calls if len(calls) == 1]
        if len(complete) != 1:
            raise Unrenderable("not one complete decision")


def test_anchor_renders_what_the_live_helpers_record():
    """The anchor itself (independent review F4: templates matched any text): a gateway case's category is its
    fault's prediction, GW-F5 names both devices and leaves none to stay healthy, F11 FIN and RST record their own
    ends, F12's early stop records only its own set."""
    live = live_decisions()
    assert {"dev-a_category_CONNECT_TIMEOUT", "dev-b_stayed_healthy"} <= live["GW-F8-UNREACHABLE"][-1]
    assert {"dev-a_category_NO_ROUTE", "dev-b_category_NO_ROUTE"} <= live["GW-F5-UNREACHABLE"][-1]
    assert not any("stayed_healthy" in n for n in live["GW-F5-UNREACHABLE"][-1])
    assert "read_end_eof" in live["FT-F11-CLOSE-FIN"][-1] and "read_end_reset" in live["FT-F11-CLOSE-RST"][-1]
    assert live["FT-F12-RESTART"][:-1] == [frozenset({"pre_restart_connection"})]
    assert "pre_restart_connection" not in live["FT-F12-RESTART"][-1]


# ---------------------------------------------------------------- the store

GATEWAY = sorted(live_decisions()["C-GATEWAY"][-1])
F3 = sorted(live_decisions()["FT-F3-WRONG-PORT"][-1])


@pytest.fixture
def store(tmp_path):
    conn = new_store(tmp_path / "d.db")
    b = R.Builder(conn=conn, root=tmp_path / "evidence")
    runs = {"B": b.run("B", "baseline", R.commissioning_set(), env=env_ok()),
            "F": b.run("F", "fault", R.fault_set(), env=env_ok(kind="fault"))}
    yield conn, runs, b
    conn.close()


def rid(conn, run, case, dev="dev-a") -> int:
    return conn.execute("SELECT result_id FROM results WHERE run_id = ? AND case_id = ? AND device_id IS ?",
                        (run, case, dev)).fetchone()[0]


def record(conn, r: int, preds, verdict: str | None = None) -> None:
    text = preds if isinstance(preds, str) else json.dumps(preds, sort_keys=True)
    conn.execute("UPDATE results SET predicates = ? WHERE result_id = ?", (text, r))
    if verdict:
        conn.execute("UPDATE results SET verdict = ?, attribution = ? WHERE result_id = ?",
                     (verdict, "none" if verdict == "pass" else "device", r))


def decision(conn, r: int) -> list[str]:
    """The I4.5 (decision basis) violations of one result."""
    return [v for v in C.result_violations(conn, [r], INV)[r] if "[I4.5]" in v]


def test_live_gateway_decision_is_accepted(store):
    conn, runs, _ = store
    r = rid(conn, runs["B"], "C-GATEWAY", "dev-b")
    record(conn, r, dict.fromkeys(GATEWAY, True))
    assert decision(conn, r) == []


def test_gateway_pass_without_its_predicates_is_rejected(store):
    conn, runs, _ = store
    r = rid(conn, runs["B"], "C-GATEWAY", "dev-b")
    record(conn, r, {})
    assert any("missing" in v and "api_unknown_device_404" in v for v in decision(conn, r)), decision(conn, r)


def test_erased_failing_gateway_predicate_with_its_verdict_flipped_is_rejected(store):
    """The auditor's counterexample: a genuine API failure (observed PASS, every bound met) is a valid fail; deleting
    the false predicate and flipping the verdict must not make it a pass."""
    conn, runs, _ = store
    r = rid(conn, runs["B"], "C-GATEWAY", "dev-b")
    record(conn, r, {**dict.fromkeys(GATEWAY, True), "api_unknown_device_404": False}, "fail")
    assert decision(conn, r) == []
    record(conn, r, dict.fromkeys(set(GATEWAY) - {"api_unknown_device_404"}, True), "pass")
    assert any("missing" in v and "api_unknown_device_404" in v for v in decision(conn, r)), decision(conn, r)


def test_duplicated_predicate_name_is_rejected(store):
    """JSON keeps the LAST of two equal names: a false record followed by a true one would read as true."""
    conn, runs, _ = store
    r = rid(conn, runs["B"], "C-GATEWAY", "dev-b")
    text = json.dumps(dict.fromkeys(GATEWAY, True))[:-1] + ', "api_unknown_device_404": false, ' \
        '"api_unknown_device_404": true}'
    record(conn, r, text, "pass")
    assert any("api_unknown_device_404" in v and "twice" in v for v in decision(conn, r)), decision(conn, r)


def test_renamed_predicate_is_rejected(store):
    conn, runs, _ = store
    r = rid(conn, runs["B"], "C-GATEWAY", "dev-b")
    record(conn, r, {**dict.fromkeys(set(GATEWAY) - {"api_unknown_device_404"}, True), "api_unknown_device_ok": True})
    v = decision(conn, r)
    assert any("api_unknown_device_404" in x and "api_unknown_device_ok" in x for x in v), v


def test_reordered_predicates_are_the_same_record(store):
    conn, runs, _ = store
    r = rid(conn, runs["B"], "C-GATEWAY", "dev-b")
    record(conn, r, "{" + ", ".join(f'"{k}": true' for k in reversed(GATEWAY)) + "}")
    assert decision(conn, r) == []


def test_non_boolean_predicate_value_is_rejected(store):
    conn, runs, _ = store
    r = rid(conn, runs["B"], "C-GATEWAY", "dev-b")
    record(conn, r, {**dict.fromkeys(GATEWAY, True), "api_bad_id_400": "true"})
    assert decision(conn, r)


def test_fault_case_own_predicate_is_required(store):
    conn, runs, _ = store
    r = rid(conn, runs["F"], "FT-F3-WRONG-PORT")
    record(conn, r, dict.fromkeys(F3, True))
    assert decision(conn, r) == []
    record(conn, r, dict.fromkeys(set(F3) - {"gateway_once_agrees_CONN_REFUSED"}, True))
    assert any("gateway_once_agrees_CONN_REFUSED" in v for v in decision(conn, r)), decision(conn, r)


def test_gateway_fault_case_names_every_observed_device(store):
    conn, runs, _ = store
    r = rid(conn, runs["F"], "GW-F5-UNREACHABLE")
    full, _ = C.case_predicates("GW-F5-UNREACHABLE", "dev-a", INV)
    assert {"dev-a_unreachable_within_3P", "dev-b_unreachable_within_3P", "dev-b_category_NO_ROUTE"} <= full
    record(conn, r, dict.fromkeys(full - {"dev-b_unreachable_within_3P"}, True))
    assert any("dev-b_unreachable_within_3P" in v for v in decision(conn, r)), decision(conn, r)


# -- partial observations: a case that stopped early records only what it observed (fail), never on a pass

@pytest.mark.parametrize("inst", [
    R.Inst("C-HEALTH", "dev-a", [[R.X("HEALTH", "refused")]], verdict="fail", attribution="device"),
    R.Inst("C-READ-SERIES", "dev-a", [[R.X("HEALTH"), R.X("READ"), R.X("READ", "rtimeout")]], verdict="fail",
           attribution="device"),
    R.Inst("FT-F12-RESTART", "dev-a", [[R.X("HEALTH", "refused")]], verdict="fail", attribution="device",
           case_predicates={"pre_restart_connection": False}),
], ids=["health-refused", "series-stopped-early", "f12-old-process-unreachable"])
def test_partial_observation_is_a_complete_record_of_a_fail(store, inst):
    conn, runs, b = store
    kind = "fault" if inst.case_id.startswith("FT-") else "baseline"
    run = b.run("partial", kind, [inst], env=env_ok(kind=kind))
    r = rid(conn, run, inst.case_id)
    assert decision(conn, r) == []


def test_partial_f12_record_never_supports_a_pass(store):
    conn, runs, _ = store
    r = rid(conn, runs["F"], "FT-F12-RESTART")
    record(conn, r, {"pre_restart_connection": True})
    assert any("missing" in v for v in decision(conn, r)), decision(conn, r)


def test_environment_decision_names_every_req10_key(store):
    conn, runs, _ = store
    r = rid(conn, runs["B"], "C-ENVIRONMENT", None)
    keys = EV.required_env_keys(INV)
    record(conn, r, dict.fromkeys(keys, True))
    assert decision(conn, r) == []
    record(conn, r, dict.fromkeys(keys[1:], True))
    assert any(keys[0] in v for v in decision(conn, r)), decision(conn, r)
    # the live case adds each contradictory other record as a failed predicate (a fail)
    record(conn, r, {**dict.fromkeys(keys, True), "fw_version.dev-a": False, "fw_version_dev-a": False}, "fail")
    assert decision(conn, r) == []
    record(conn, r, {**dict.fromkeys(keys, True), "provenance.witness-ctl": True}, "pass")
    assert any("provenance.witness-ctl" in v for v in decision(conn, r)), decision(conn, r)


# -- the verdict is the one its recorded basis yields

def test_fail_over_an_all_true_gateway_basis_is_rejected(store):
    conn, runs, _ = store
    r = rid(conn, runs["B"], "C-GATEWAY", "dev-a")
    record(conn, r, dict.fromkeys(GATEWAY, True), "fail")
    assert any("yields pass" in v for v in decision(conn, r)), decision(conn, r)


def test_fail_over_a_passing_runner_attempt_is_rejected(store):
    conn, runs, _ = store
    r = rid(conn, runs["B"], "C-IDENTIFY")
    conn.execute("UPDATE results SET verdict = 'fail', attribution = 'device' WHERE result_id = ?", (r,))
    assert any("yields pass" in v for v in decision(conn, r)), decision(conn, r)


def test_genuine_runner_failures_keep_their_basis(store):
    """A degraded HEALTH on both attempts and a pass only on retry (FLAKE) are fails by their basis."""
    conn, runs, b = store
    flake = next(i for i in R.mutant_insts("M6")[0] if (i.case_id, i.device_id) == ("C-READ-SERIES", "dev-a"))
    run = b.run("fails", "baseline", [R.degraded_health("dev-a"), flake], env=env_ok())
    for case in ("C-HEALTH", "C-READ-SERIES"):
        assert decision(conn, rid(conn, run, case)) == [], case


# ---------------------------------------------------------------- acceptance: the auditor's counterexamples

@pytest.fixture
def accepted(tmp_path):
    conn = new_store(tmp_path / "a.db")
    runs = accepted_store(conn)
    yield conn, runs, tmp_path / "evidence"
    conn.close()


def audit(conn, root) -> dict:
    return {a["id"].split("-")[0]: a for a in A.audit(conn, evidence_root=root)}


def test_accepted_store_records_the_live_decision_basis(accepted):
    conn, runs, root = accepted
    assert all(a["ok"] for a in audit(conn, root).values())
    assert set(json.loads(conn.execute("SELECT predicates FROM results WHERE run_id = ? AND case_id = 'C-GATEWAY' "
                                       "AND device_id = 'dev-b'", (runs["final"],)).fetchone()[0])) == set(GATEWAY)


def test_erased_gateway_decision_neither_accepts_nor_commissions(accepted):
    conn, runs, root = accepted
    conn.execute("UPDATE results SET predicates = '{}' WHERE run_id = ? AND case_id = 'C-GATEWAY' AND device_id = "
                 "'dev-b'", (runs["final"],))
    au = audit(conn, root)
    assert not au["A24"]["ok"] and not au["A18"]["ok"], {k: a["violations"][:2] for k, a in au.items() if not a["ok"]}
    assert db.commissioned_devices(conn, runs["final"], evidence_root=root) == ["dev-a"]


def test_failing_gateway_case_with_its_false_predicate_erased_is_rejected(accepted):
    conn, runs, root = accepted
    r = rid(conn, runs["final"], "C-GATEWAY", "dev-b")
    conn.execute("UPDATE results SET verdict = 'fail', attribution = 'device', predicates = json_set(predicates, "
                 "'$.api_unknown_device_404', json('false')) WHERE result_id = ?", (r,))
    assert {k for k, a in audit(conn, root).items() if not a["ok"]} == {"A4", "A18"}
    conn.execute("UPDATE results SET verdict = 'pass', attribution = 'none', predicates = json_remove(predicates, "
                 "'$.api_unknown_device_404') WHERE result_id = ?", (r,))
    au = audit(conn, root)
    assert not au["A24"]["ok"] and not au["A18"]["ok"]
    assert "dev-b" not in db.commissioned_devices(conn, runs["final"], evidence_root=root)
