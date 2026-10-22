# Witness acceptance contract (evidence model v5)

Authority: [PROJECT_BRIEF.md](../PROJECT_BRIEF.md) §§5–9, 13. This contract states what the acceptance verifier
(`python3 -m runner.analysis`) must prove and from **which independent source each obligation comes**. It is tested
by `scripts/verify_acceptance_contract.py` (reference store + mutation matrix + independent oracle).

**Rule 0.** An obligation is never derived from the rows it constrains. Missing evidence is a violation, never a
reason to skip a check. A legitimately empty observation (nothing sent) must be recorded as such, with the reason
the exchange itself states. The verifier fails closed: a record it cannot evaluate (a wrong stored type, a malformed
value) is a violation, never an exception that skips the check or a pass.

## Sources of obligations

| Source | Fixes | Cannot be changed by editing |
|---|---|---|
| `runner/catalog.py` + `runner/contract.py` (code) | cases, per-device/run-level, observation kind, attempts allowed, command grammar, dialled target, captures, evidence kinds, fault applications, measurements, the names of each case's decision predicates | the results store |
| `inventory.yaml` | devices, addresses, ports, identities, VMs | the results store |
| `docs/requirements.md` | requirements | the results store |
| run plan (`run_plan` rows + indexed `session/plan.json`), written before the first case | declared selection of a run started under schema v5 | results/attempts/exchanges/evidence rows |
| evidence directories `run-N/<case>__<device\|run>/` | which case instances executed (receipts) | the results store |
| indexed `run-N/session/environment.json` (written at session start) | the session's recorded kind, source stamp, mutant/build and environment facts; association to run N by its canonical path | edits confined to database metadata while these bytes are preserved |

"Fair run": finished, `clean_env=1`, not contaminated. "Decided result": verdict pass or fail. "Current result":
every result of the latest fair non-mutant run that **recorded or planned** its instance; every result of the
baseline A18 evaluates, of the A14 trials, and of each mutant's latest valid run.

## Invariants

**I1 Run identity, status, selection, provenance** (A11, A13, A22, A23)
- I1.1 Store integrity: `PRAGMA integrity_check` = ok, `foreign_key_check` empty (no orphaned child of a deleted parent);
  the migration record (when each obligation starts) agrees with the schema and with the rows each migration governs
  (plan rows and plan files, capture-flow records, attempt outcomes never predate their migration).
- I1.2 A run's flags agree with its records: env `runs.clean_env` = `runs.clean_env` for every finished run;
  `clean_env=1` ⇔ session preflight rows exist for both inventory VMs and none FAIL; a fair run has no FAIL check
  in any phase; a run without `finished_at` has no session postflight (written just before it finishes);
  `contaminated=1` is corroborated: every `aborted: never finished (detected by run N)` marker names a separate
  recorded run N (never the run itself) with a larger run id and a later recorded start, both times in the runner's
  form, that recorded its session (append-only checks/evidence without a result) and found this run unfinished: no
  finish, or a finish after N's start whose own last session record (its teardown) is later than N's first session
  record (equal times cannot order them) — the runs row's own `finished_at` never proves the overlap; or
  `contaminated: <why>` with a failed
  check, an unverified fault removal or a reset recorded. (A newer run made unfair by a bare edit would otherwise
  hand its instances to an older run; a run naming itself as its detector, or moving its own finish past the next
  run's start, did exactly that: IC-01 and its review. All 15 unfair runs of the master carry these records.)
- I1.3 A run started under v5, or holding plan rows or an indexed plan file, has a plan of ≥ 1 catalog instance
  (per-device case ⇔ inventory device; fault cases on `FAULT_DEVICE`) and exactly one indexed `plan` file, present
  with its recorded hash and listing exactly the rows.
- I1.4 Every planned instance of a finished run has exactly one result; no result is unplanned.
- I1.5 Receipts: every `run-N/<case>__<target>` directory under the evidence root belongs to a result of run N with
  that `evidence_path`; every `run-N` directory belongs to a run row; every decided result has its directory.
- I1.6 Provenance: 40-hex `git_sha`/`git_dirty` recorded and equal to the run row (A13).
- I1.7 Session corroboration (F3): every fair run, regardless of kind or whether current, has exactly one run-level
  `environment` index at `run-N/session/environment.json`. With an evidence root, its length and SHA-256 must match
  the index; its bytes must parse as one JSON object of text values without duplicate names (escaped duplicates
  included). Its complete key/value map equals the environment table, except `runs.clean_env` may be table-only:
  the live writer adds that key through `db.set_clean_env` after collecting the snapshot. A recorded key cannot
  silently disappear from either representation. `runs.kind`, `git_sha`, `git_dirty` are mandatory and equal to the
  run row; recorded `mutant` and `runs.clean_env` also agree with it. Every fair session records the REQ-10 keys
  (apart from the table-only key); v5 sessions and mutant runs additionally require `mutant` and every inventory
  device's build. Historical pre-v5 baseline/fault files may lack mutant/build keys, as the early writer did.
  Any recorded environment of an unfair/interrupted run is checked too. The obligation survives deletion of both
  snapshot and index: environment rows, case results, session postflight or a recorded finish independently require
  it, regardless of run kind, fairness or selection. Only an unfinished run with none of those collection facts and
  no snapshot/index may predate collection; preflight and a plan alone do not require a snapshot. An interruption
  after table persistence but before saving/indexing the snapshot leaves that run unverified, never reconstructed
  or silently excluded to obtain acceptance. No identity is inferred from test outcomes or from a baseline-shaped plan:
  legitimate mutants run commissioning cases too. Acceptance rejects a contradictory store instead of relabelling it.

**I2 Inventory and environment** (A13, A21): reference tables equal their sources; every REQ-10 key of every
inventory VM/device valid (`runner/evidence.check_environment`).

**I3 Required commissioning instances** (A18, standalone commissioning, report): catalog commissioning cases ×
**inventory** devices (run-level once); a device absent from the `devices` table, or whose row differs from the
inventory, is a gap of that device, never a smaller requirement.

**I4 Results, attempts, verdicts, attribution** (A8, A10, A16, A24)
- I4.1 Attempt rows are numbered 1..n with n = `results.attempts`.
- I4.2 Runner-observed cases: a decided result has ≥ 1 attempt (fault cases exactly 1, commissioning ≤ 2).
  Gateway-observed and record cases (C-GATEWAY, GW-*, C-ENVIRONMENT) have none.
- I4.3 `observed_category` = last attempt's category; `first_attempt_category` = attempt 1's (gateway cases: equal).
- I4.4 `expected_category` = catalog expectation (fault prediction; PASS; NULL for C-ENVIRONMENT).
- I4.5 Pass ⇒ preflight and postflight green and their check rows recorded for both VMs without FAIL, one attempt with
  outcome `ok`, observed = expected, and the exchanges of a fault case with a predicted sequence (F11: PASS PASS
  CONN_RESET; F13 repeat-seq: PASS STALE_DATA; F13 skew: STALE_DATA) show exactly it. From schema v5 the predicates the
  verdict was decided on (`results.predicates`: the final attempt's plus the case's own, e.g. gateway bounds, F11
  shape) are recorded for every decided result, include the final attempt's with equal values, and are all true on
  a pass. WHICH predicates a decision holds comes from the case contract (`contract.CASE_PREDICATES`, the names the
  live case records, anchored to tests/live; C-ENVIRONMENT every REQ-10 key) and the final attempt's exchanges,
  never from the row: a missing name is a missing observation (IC-02). A pass holds exactly those names; a fail may
  instead hold the partial set of a case that stopped early (F12 before the restart), and C-ENVIRONMENT adds each
  contradictory other record as false. A name recorded twice is unreadable. The verdict is the one the recorded
  basis yields: a fail over observed = expected, every predicate true (and one attempt with outcome `ok`) is a
  contradiction. Before v5 the case's own predicates were not recorded: the verdict is their only record (stated
  limit).
- I4.6 Attempt outcome `ok` ⇒ recomputed category = expected, every stored predicate true, nothing cut by the deadline.
  Rows of runs before schema v4 have no outcome/predicates: their basis is the category alone, stated as such;
  a v4+ row without an outcome or predicates (an empty set is `{}`) is a violation.

**I5 Protocol operations** (A24)
- I5.1 Every attempt of a decided runner result has exchanges `ord` 1..k, k ≥ 1.
- I5.2 Commands follow the case grammar (I, H, `R×10`, `H R×10 H`, `R×3`, F12 `H R R H+ I (R H)? H+`). An attempt
  ends early only at an exchange that is not PASS/PASS_SLOW, that the deadline cut, or when the deadline left no time.
- I5.3 Each exchange dials the case target: inventory host/port/address, F3 port 5021, F4 10.77.2.13, F7 the other
  device's address, F7-missing no address; an address may be absent only after a failed resolve.
- I5.4 Attempt category = recomputed from its exchanges (first non-pass; F12: one of its first probe run; NULL when cut).
- I5.5 `t_send` does not decrease with `ord`.
- I5.6 A PASS/PASS_SLOW exchange carries its well-formed response (id echoed, the command's fields; IDENTIFY of
  C-IDENTIFY/F12 the inventory identity); an attempt's predicates are exactly those its exchanges and response bytes
  yield (C-HEALTH status/sensor from the payload; `reads_complete` only for a series that ran to its end).

**I6 Exchange lifecycle and bounded failures** (A24): "nothing sent" only with its reason — no address ⇒ failed
resolve (RESOLVE_FAIL or deadline); `not_started` ⇒ deadline cut; connect ENETUNREACH ⇒ NO_ROUTE. An exchange that
got past connect records its local port (schema v2+), the key that separates the runner's connection from the
gateway's polls to the same address:port. A cut attempt is `runner`, its result `error/runner`. Error results may
lack observations; they never satisfy a pass claim.

**I7 Required captures** (A24 index, A20 bytes): every decided result has exactly one indexed ctl capture
(`<case dir>/capture.pcap`) and every decided fault-case result exactly one field capture
(`<case dir>/capture-field.pcap`); every file indexed for a result lies in that result's case directory; no file is
indexed twice.

**I8 Capture flows** (A17, A20)
- I8.1 Runner results recorded under v4+: each dialled flow (from its I5-validated exchanges) × required capture has
  exactly one `capture_flows` record with the matching expectation; no record is unaccounted; an expected record
  never holds 0 packets.
- I8.2 Gateway-observed results: the observed device's address:port has packets in each required capture (the
  gateway's polls), recounted from the bytes (no record exists for them).

**I9 Bytes** (A20): every indexed file of a current result and its run's session files exists with its recorded
length and SHA-256; each expected flow recounted from the hash-verified capture is > 0 and equals its record;
runner results predating capture_flows are recounted from their derived flows. No evidence root ⇒ violated.

**I10 Run, device and project acceptance** (A4, A5, A9, A12, A14, A18, A24)
- I10.1 The latest fair run that recorded or planned an instance is its current evidence; a planned instance
  without its result is a violation (no fallback to an older run).
- I10.2 Decided fault results have exactly the catalog's applications (F12: 2), each removal verified.
- I10.3 Pass results hold every measurement their case records, each within its bound (FT-F13-SKEW's skew lies outside
  REQ-04's window by design); the evidence files each case writes are indexed in their exact number, including the
  fault injector's records per fault kind (counters, hosts, inventory).
- I10.4 Every fair run has its session evidence indexed (preflight ctl/field, environment, postflight ctl/field,
  field command log; plan under v5).
- I10.5 Commissioning (`commissioning_gaps`) applies I3–I9, including the I8.1 flow records, to the run's prerequisite
  results (bytes when an evidence root is given); A14 and A18 use it. A5/A6 existential claims are witnessed by current
  results through A4.

**I11 Report consistency**: the report uses the same selection (I10.1) in traceability and the fault table, the same
commissioning function (I3, I10.5), names the run A18 evaluates, and embeds the same audit; a planned-but-missing
instance is shown as MISSING, never as an older pass.

## Boundaries (not claimed)

The session snapshot records kind/source/build/environment facts, not a signed run id, start time, runner hostname
or contamination cause. Its canonical path/index associates it with a run. Comparing preserved bytes closes F3;
hash agreement with an index in the same mutable database establishes correspondence, not authenticity. Rewriting
the file, its hash and all corresponding metadata consistently remains outside this contract. Without an evidence
root, standalone commissioning performs structural checks only; full acceptance rejects the missing byte checks.

Not claimed: resistance to a coordinated rewrite of a parent and all its corroborating records (e.g. result row + plan
rows + plan file + its index hash; a whole run plus its evidence directory; renumbering a failed attempt away together
with the result summary; a contamination flag plus a fabricated failed check; an abort marker plus a fabricated
session record — inserted session checks of the detector, or a later teardown check of the aborted run, corroborate it
whatever their status), forged values that are self-consistent with every record (a measurement value inside its
bound, a latency, rewritten response bytes, a false case predicate rewritten true under its own name: the verifier
does not recompute a case's own predicates — the gateway's API and state checks are recorded nowhere else; some runner
fault predicates, e.g. `zero_response_bytes` or `detail_*`, could be recomputed from the exchanges but are not), or
authenticity of the source stamp. Fail-closed limit of I1.2: an abort whose overlap no session record shows is
rejected even when genuine — a detecting session killed between marking the run and recording its preflight, or a run
that finished in the milliseconds between its last session record and `finish_run` while the next session started
(both only with concurrent sessions); such a store needs review by hand. The case's own predicates of runs before
schema v5 were never recorded: a pass there rests on its verdict for them. The oracle of the test harness judges only
the attacks its matrix lists. No cryptographic protection. The append-only triggers of v5 stop accidental deletion
through SQLite; they are not proof and are not relied on by the verifier.
