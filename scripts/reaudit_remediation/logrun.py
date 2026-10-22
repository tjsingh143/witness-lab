"""Second-audit remediation command recorder: runs one command and writes an exclusively created log under
results/logs/ with UTC start/end, exact argv, combined output, elapsed time and exit code.

    .venv/bin/python scripts/reaudit_remediation/logrun.py NAME TIMEOUT_S CMD...
Never deploys, syncs or touches the lab by itself."""
import datetime
import json
import os
import pathlib
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[2]


def main() -> int:
    name, limit, *cmd = sys.argv[1:]
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = REPO / "results/logs" / f"reaudit-remediation-{name}-{stamp}.log"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    start = time.monotonic()
    with path.open("x") as log:
        def record(s):
            print(s, file=log, flush=True)
            print(s, flush=True)
        record("START_UTC " + datetime.datetime.now(datetime.timezone.utc).isoformat())
        record("CWD " + str(pathlib.Path.cwd()))
        record("ARGV " + json.dumps(cmd))
        try:
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
                               timeout=float(limit))
            record(p.stdout)
            rc = p.returncode
        except subprocess.TimeoutExpired as e:
            record("OUTER_TIMEOUT " + str(e.stdout))
            rc = 124
        record("EXIT_CODE " + str(rc))
        record("ELAPSED_S " + f"{time.monotonic() - start:.3f}")
        record("END_UTC " + datetime.datetime.now(datetime.timezone.utc).isoformat())
        record("LOG " + str(path.relative_to(REPO)))
    return rc


if __name__ == "__main__":
    sys.exit(main())
