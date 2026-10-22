"""Shared pytest options. Live tests are deselected unless --live is given (and then
they refuse to run anywhere except witness-ctl, see tests/live/conftest.py)."""
import pytest


def pytest_addoption(parser):
    g = parser.getgroup("witness")
    g.addoption("--live", action="store_true", help="run live VM tests (only on witness-ctl, as root)")
    g.addoption("--db", default="/var/lib/witness/results/witness.db", help="SQLite results database")
    g.addoption("--evidence-root", default="/var/lib/witness/results/evidence", help="evidence directory root")
    g.addoption("--run-notes", default="", help="free-text note stored on the run row")
    g.addoption("--mutant", default=None, help="declare a mutant run (M1..M6, runner/catalog.py MUTANTS): the field "
                "must report exactly that build on the mutant device; the run is recorded as kind=mutant")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="live VM test: run on witness-ctl with --live (scripts/lab_vms.sh suite)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
