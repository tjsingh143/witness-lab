"""Independent audit F-04: attribution is decided over ALL attempts. A runner error or an invalid (restart) window
on one attempt can never become a device flake or a pass after the retry; a genuine device failure followed by a
pass stays a FLAKE (fail/device). Per-attempt outcomes are persisted so Q5 ("passed only on retry") is a predicate
fact, not a category change. Pure decision logic + fixture store; no VM involved."""
import pytest

from runner import analysis as A, db
from runner.cases import Attempt, decide, with_retry
from runner.classify import Classification, Observation
from storefix import new_store, result


def att(no, cat, preds=None, restart=False, note="", detail=None):
    o = Observation(host="h", port=1, cmd="HEALTH", req_id=1)
    return Attempt(no, [(o, Classification(cat, "x", detail or f"d-{cat}"))], predicates=preds or {},
                   restart_observed=restart, note=note)


RUNNER = att(1, None, detail="unclassifiable_send_error:timeout")
RESTART = att(1, "PASS", restart=True, note="restart observed")
DEGRADED = att(1, "PASS", preds={"status_ok": False, "sensor_ok": True})
DEVICE = att(1, "READ_TIMEOUT")
GOOD = att(2, "PASS", preds={"status_ok": True, "sensor_ok": True})


@pytest.mark.parametrize("first,alone,retried", [
    (RUNNER, ("error", "runner"), ("error", "runner")),       # audit repro 1: was fail/device FLAKE
    (RESTART, ("error", "infra"), ("error", "infra")),         # audit repro 2: was fail/device FLAKE
    (DEGRADED, ("fail", "device"), ("fail", "device")),       # predicate failure with category PASS -> FLAKE
    (DEVICE, ("fail", "device"), ("fail", "device")),         # genuine device failure -> FLAKE
])
def test_attribution_survives_the_retry(first, alone, retried):
    d1 = decide([first], "PASS", preflight_green=True)
    d2 = decide([first, GOOD], "PASS", preflight_green=True)
    assert (d1.verdict, d1.attribution) == alone
    assert (d2.verdict, d2.attribution) == retried
    assert d2.verdict != "pass"
    if retried[1] == "device":
        assert d2.detail.startswith("FLAKE: attempt 1")
    else:
        assert "attempt 1 was not a fair device test" in d2.detail and "never a device flake" in d2.detail


def test_degraded_first_attempt_detail_names_the_failed_predicate():
    d = decide([DEGRADED, GOOD], "PASS", preflight_green=True)
    assert "failed predicates: status_ok" in d.detail and "passed only on retry" in d.detail


def test_unfair_second_attempt_after_a_device_failure_is_an_error_not_a_device_verdict():
    d = decide([DEVICE, att(2, None)], "PASS", preflight_green=True)
    assert (d.verdict, d.attribution) == ("error", "runner") and "attempt 2 was not a fair device test" in d.detail
    d = decide([DEVICE, att(2, "PASS", restart=True, note="restart observed")], "PASS", preflight_green=True)
    assert (d.verdict, d.attribution) == ("error", "infra")


def test_red_preflight_still_dominates():
    assert decide([RUNNER, GOOD], "PASS", preflight_green=False).attribution == "infra"


def test_outcomes_and_retry_policy():
    assert [a.outcome("PASS") for a in (RUNNER, RESTART, DEGRADED, DEVICE, GOOD)] == \
        ["runner", "infra", "device", "device", "ok"]
    seq = iter([DEGRADED, GOOD])          # a degraded HEALTH is not ok, so it is retried
    assert [a.attempt_no for a in with_retry(lambda no: next(seq))] == [1, 2]


@pytest.fixture
def conn(tmp_path):
    c = new_store(tmp_path / "r.db")
    yield c
    c.close()


def persist(conn, run, case, attempts, expected="PASS"):
    d = decide(attempts, expected, preflight_green=True)
    rid = result(conn, run, case, "dev-a", bare=True, verdict=d.verdict, attribution=d.attribution,
                 observed=attempts[-1].category, first=attempts[0].category, attempts=len(attempts))
    for a in attempts:
        db.insert_attempt(conn, rid, a.attempt_no, a.category, "x", a.deciding.detail, db.utcnow(), 1.0, a.exchanges,
                          outcome=a.outcome(expected), predicates=a.predicates)
    return rid


def test_q5_uses_persisted_attempt_outcomes_and_a16_holds(conn):
    run = db.start_run(conn, kind="baseline", git_sha="s", git_dirty=0, clean_env=1, runner_host="unit")
    persist(conn, run, "C-HEALTH", [DEGRADED, GOOD])          # category PASS -> PASS: the old Q5 missed this
    persist(conn, run, "C-IDENTIFY", [RUNNER, att(2, "PASS")])
    persist(conn, run, "C-READ-CLOCK", [DEVICE, att(2, "READ_TIMEOUT")])   # failed twice: not "passed on retry"
    db.finish_run(conn, run)
    q5 = {r[3]: r for r in A.rows(conn, A.Q5_RETRY)[0]}
    assert set(q5) == {"C-HEALTH", "C-IDENTIFY"}
    assert q5["C-HEALTH"][5:11] == ("PASS", "PASS", "fail", "device", "device", "ok")
    assert q5["C-IDENTIFY"][7:11] == ("error", "runner", "runner", "ok") and q5["C-IDENTIFY"][11] == "attempt outcome"
    au = {a["id"]: a for a in A.audit(conn)}
    assert au["A16-retry-attribution"]["ok"] and au["A10-retried-is-never-pass"]["ok"]


def test_a16_flags_a_device_verdict_over_an_unfair_attempt(conn):
    """What the pre-remediation decide() produced for the audit's repro: fail/device over a runner attempt."""
    run = db.start_run(conn, kind="baseline", git_sha="s", git_dirty=0, clean_env=1, runner_host="unit")
    rid = result(conn, run, "C-IDENTIFY", "dev-a", verdict="fail", attribution="device", first=None, attempts=2,
                 bare=True)
    for a in (RUNNER, att(2, "PASS")):
        db.insert_attempt(conn, rid, a.attempt_no, a.category, "x", "", db.utcnow(), 1.0, a.exchanges,
                          outcome=a.outcome("PASS"))
    legacy = result(conn, run, "C-HEALTH", "dev-a", verdict="fail", attribution="device", attempts=2, bare=True)
    db.insert_attempt(conn, legacy, 1, "PASS", "x", "d; restart observed: uptime_s 9 -> 1", db.utcnow(), 1.0, [])
    db.finish_run(conn, run)
    v = {a["id"]: a for a in A.audit(conn)}["A16-retry-attribution"]
    assert not v["ok"] and len(v["violations"]) == 2
    assert any("attempt 1 runner" in x for x in v["violations"])
    assert any("restart observed" in x for x in v["violations"])     # pre-v4 row: detail-based fallback
