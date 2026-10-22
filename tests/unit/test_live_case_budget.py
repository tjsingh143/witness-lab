"""Per-case setup/body alarm, using real wall time; unit evidence only."""
import signal
import time
from types import SimpleNamespace

import pytest

from runner import contract, db
from runner.cases import Attempt
from tests.live.conftest import Case, CaseBudget, CaseDeadline


def test_cumulative_blocking_steps_cannot_renew_budget():
    budget = CaseBudget(0.12).start()
    t0 = time.monotonic()
    try:
        with pytest.raises(CaseDeadline, match='case deadline'):
            for _ in range(8):
                time.sleep(0.04)  # every operation individually fits; their total does not
    finally:
        budget.stop()
    assert budget.expired and time.monotonic()-t0 < 0.3


def test_budget_includes_elapsed_setup_and_checks_late_decision():
    budget = CaseBudget(0.1, started=time.monotonic()-0.2)
    with pytest.raises(CaseDeadline):
        budget.check()
    assert budget.expired


def test_cleanup_outlives_observation_without_second_alarm():
    old = signal.getsignal(signal.SIGALRM)
    budget = CaseBudget(0.03).start()
    try:
        with pytest.raises(CaseDeadline):
            time.sleep(0.1)
    finally:
        budget.stop()
    time.sleep(0.06)
    budget.stop()  # idempotent; no later case's timer is touched
    assert signal.getsignal(signal.SIGALRM) == old
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


def test_timely_control_keeps_original_alarm_handler():
    old = signal.getsignal(signal.SIGALRM)
    budget = CaseBudget(0.2).start()
    try:
        time.sleep(0.005)
        budget.check()
        assert not budget.expired
    finally:
        budget.stop()
    assert signal.getsignal(signal.SIGALRM) == old


def test_partial_f12_deadline_attempt_uses_the_contract_cut_marker(monkeypatch):
    recorded = []
    monkeypatch.setattr(db, 'insert_attempt', lambda *args, **kw: recorded.append((args, kw)))
    case = SimpleNamespace(spec=SimpleNamespace(fault_id='F12'), budget=SimpleNamespace(expired=True),
                           inflight_attempt=Attempt(attempt_no=1, started_wall=time.time()-1),
                           marks={'first_attempt':time.monotonic()-1}, t0=time.monotonic()-2,
                           lab=SimpleNamespace(conn=object()), result_id=17, _insert=lambda **kw: None)
    Case.record_error(case, 'runner', 'overall live deadline expired')
    args, kw = recorded[0]
    assert args[3] is None and args[5].startswith(contract.DEADLINE)
    assert kw['outcome']=='runner' and case.inflight_attempt.deadline_exhausted
