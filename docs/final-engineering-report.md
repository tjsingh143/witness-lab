# Witness final engineering report

**Final project delivery — Linux device commissioning and fault injection.** Original verification report
prepared October 21, 2026; presentation updated October 22, 2026 (Pacific). Recorded command timestamps are UTC.
This is a functional software simulation lab with real Linux VM networking. Detailed verification results and
known limitations are retained below; final delivery does not assert that every acceptance obligation passed.
It is not physical hardware testing, embedded firmware verification, or independent professional certification.

## Delivered behavior

Witness deploys two Ubuntu 24.04 ARM64 VMs, two systemd sensor simulators, a polling gateway and a pytest
commissioning runner. Its explicit protocol and ten requirements cover identity, health, timestamps, sequence
ordering, latency, malformed responses, and detection/recovery bounds. Eleven observed categories distinguish
name resolution, routing, TCP connection/read behavior, framing/schema, identity, freshness, and latency.

The runner preserves observations before deciding verdict and blame. A retry cannot erase its first failure;
partial baselines commission nothing. A normalized SQLite store records environment, plans, attempts, exchanges,
checks, faults, measurements, indexed file hashes and packet-flow records. Reports derive requirement traceability,
commissioning, fault classification, mutant detection and the six specified SQL analyses from this store.

Faults F1–F13 have 21 variants and 24 live instances. Allow-listed, identity-checked fault operations are scoped
to the dedicated guests. Vsock management survives guest route/firewall faults. Finally blocks, contamination
checks, a 90 s dead-man and independent capture expiry provide recovery when the runner fails.

## Verification, with revision and scope

The last live-tested functional source is `3d7a9f74c81f80a1a84f790f7aa01f5254e5aa0f`, with clean guest source stamps.
The release changes documentation, ignore rules and the image URL in the VM template; device, gateway, runner,
fault tools, protocol and acceptance predicates retain their tested bytes. The image's release and SHA-256 are
unchanged. The final template passed native validation, but fresh boot on that template remains unexecuted.

| Evidence | Actual result | Scope / reference |
|---|---|---|
| Stock commissioning, current runs 1 and 9 | **11/11 each**, no retry; both devices commissioned | Real VMs, earlier final functional campaign |
| F1–F13, run 2 | **24/24**, 25/25 verified removals, all 11 observed categories | Real VMs; current fault report |
| M1–M6, runs 3–8 | **6/6 caught**, no runner/infra failures or stock-control false alarms | Real VMs; current mutant report |
| Split-delay F12 and gateway/F5 negatives | **error/runner** near 30.009/30.013 s; A23/A24 hold | Expected diagnostic failures, not commissioning passes |
| TERM/F2, KILL/F2, KILL/F5 | GREEN at +5.659 / +91.880 / +120.906 s | Actual faults and captures observed before exact-PID signals |
| Emergency reset / genuine detector baseline | RED → GREEN / **11/11** | Real VMs; aborted runs corroborated by later recorded sessions |
| Original Mac units / Ubuntu focused checks | **599 / 128 passed** | Historical final functional campaign |
| Initial release source + handoff suite | **646 passed**, 174.06 s | Executed before README polishing; macOS local-socket/synthetic tests |
| Clean snapshot source-only suite | **606 passed**, 188.00 s | New Python 3.14 venv, no historical result store or ZIP dependency |
| Clean snapshot sealed-ZIP tests | **40 passed**, 2.21 s | Explicit `WITNESS_TEST_ZIP`; separate artifact-dependent scope |
| Sealed portable ZIP native checks | **10/10 passed** | Newly executed; extraction, checksums, Lima, configs, real 8 GiB refusal; no VM boot |
| Production acceptance and report regeneration | **22/24**, equal assertion records | Newly executed against complete real retained DB + evidence bytes |
| Original overnight seal | **2,527/2,527 file hashes verified** | Newly checked; original data unchanged |
| Python AST / shell syntax / whitespace | **72 Python / 11 shell files; PASS** | Newly checked; ShellCheck unavailable on host and not rerun in VMs |
| Git object integrity | **PASS** | `git fsck --full`; harmless dangling local commits retained |
| Full synthetic adversarial self-test | **INCOMPLETE — 900 s timeout**, exit 124 | Reached deliberate weakening checks; no final verdict/JSON, no PASS claimed |

The [overnight report](overnight-acceptance-20261021.md) retains exact live timings, source identity, native
cross-checks, failures and recovery evidence. Its independent byte/SQL/packet check covered 914 indexed files,
129 flow records, 96 decoded baseline exchanges and 80 READs. Those counts are historical execution facts,
not new VM trials during release. Selected reports and command records are in [release evidence](../evidence/release/README.md).

**Acceptance gaps:** A14 requires five independent complete, all-pass, retry-free fresh-golden restorations;
A15 requires their stability. Both fail because the current store has none. Existing-VM baselines and successful
older-code clone trials cannot close them. Fresh-image VM reproduction is also mandatory and remains unverified
on the current functional revision. It is an additional obligation beyond the 24-assertion count.
No final independent external sign-off exists. Acceptance criteria were not changed.

### Clean-checkout corrections and retained outcomes

An actual new publication checkout and new venv exposed documentation/setup issues: macOS's default Python
was 3.9 and could not install pinned pytest; its pyenv shim required an explicitly selected installed version.
The instructions now select Python 3.12–3.14 explicitly. A fresh Python 3.14 environment installed the declared
dependencies successfully. The first broad checkout test run recorded **605 passed, one failed, 40 errors**:
the README consistency test required the literal label “21 fault variants,” and all 40 package tests lacked
the deliberately unshipped ZIP. The label was corrected; source-only and ZIP-dependent commands are now separate.
The focused README check passed; all 40 package tests passed with `WITNESS_TEST_ZIP` identifying the sealed ZIP.
The corrected source-only command then passed **606/606** in 188.00 s. The original failing command logs are retained. No runtime implementation or test predicate was changed.

The full synthetic adversarial self-test was bounded at 900 s and not retried. It reached its controls/mutations,
seeded combinations and several weakening checks but produced no final verdict, so it is **not a release PASS**.
Its exact generated synthetic temporary directory was identified by creation time and command prefix, recorded,
and removed after timeout; no real evidence was removed. This is separate from the completed real-store
acceptance checker and its 22/24 result.

## Bounded final experiment decision

One measured resource preflight was performed; neither blocked VM branch was started or retried. At
2026-10-22T02:47:04Z the 8 GiB Mac had **14.090 GiB free**, **3893.38 MiB swap used**, raw memory pressure **2**,
with all six Witness instances stopped and protected. A later sample had **13.307 GiB free**, **3975.25 MiB swap**,
and pressure 2, still with the VMs stopped. This leaves inadequate stable memory/swap margin for two more guests.

Each guest disk is 10 GiB logical. Current working disks allocate approximately 2.84/2.86 GiB; the current golden
pair allocates **4.513 GiB combined**. APFS `st_blocks` includes shared extents and cannot be added to predict
unique physical storage. A temporary 16 MiB `cp -c` probe consumed zero additional reported bytes at clone time;
a 1 MiB write consumed about 1 MiB and preserved the source hash. This proves small-file COW here, not VM peak space.
[Lima 2.2.0's implementation](https://github.com/lima-vm/lima/blob/v2.2.0/pkg/instance/clone.go) attempts COW through
its copy helper; it does not impose a hard storage cap. Its rename path also nullifies virtualization identity
and skips clone-excluded files, so an unverified rename was not treated as byte-preserving protection.

The historical **20 GiB gate was evaluated rather than blindly reused**. Even giving clone-time COW full credit,
a planning budget of 10 GiB ordinary reserve + 4.513 GiB for rewriting the currently allocated golden blocks +
2 GiB swap growth + 0.5 GiB evidence + 1 GiB recovery is **18.013 GiB**. This is a conservative allowance, not a
measured worst-case bound: new guest allocations or fallback copying could require more (up to the logical sizes).
Five serial restores release disposable divergence between trials, but do not remove the peak of one live pair.
Fresh-image provisioning additionally allocates new disks and can require image conversion/package writes.

Safe cache candidates were inventoried: an unused September Lima image/conversion cache, **2.479 GiB**, and
Homebrew downloads, **0.896 GiB**. Even their theoretical complete reclamation raises the initial free space only
to **17.465 GiB**, below the planning budget, without fixing RAM pressure. The required July image/cache was kept
so fresh reproduction would not require downloading it again (approximately 587 MiB compressed plus conversion).
No cache cleanup, VM rename, restore, deletion, start, host-network edit or unrelated-service change was performed.
All six VM disk inode/size/allocation/mtime records and stopped/protected states matched the before/after inventory.
Both branches terminate **BLOCKED — HOST RESOURCES**; no experimental success is inferred from this preflight.

## Release and evidence decisions

The original checkout began at `c3d27b8` on `main`, with no remote. The GitHub account was verified as `tjsingh143`;
no existing Witness repository was returned by the connected search or authenticated CLI owner inventory.
The original 48-commit reachable history contains 14,083 blobs, 508 with absolute home paths, and 453 tracked
absolute evidence symlinks. No credential matches were found by the recorded pattern scans; no raw DB/pcap or VM
image was tracked. Patterns are limited checks, not a proof that every possible secret is absent.

A separate **sanitized publication snapshot** preserves source, tests, specifications, meaningful reports and
historical audit FAIL records. It excludes original Git history, prompts from the obsolete agent kit, raw results,
absolute symlinks, personal paths, images, dependencies and caches. An initial unpublished export also treated a path-matching regex literal as a personal path; the export rule was
restricted to documentation and executable bytes were compared with the original Git objects. The initial
candidate is retained locally and is not the published history. The source manifest records original Git blob
identities and content hashes, any documented redactions, and the original source revision. The immutable brief's
SHA-256 remains `07a33a088939c9cc59ef4dbbfb12706ad17431d9eb4d8b5353feafdcea555baf`.
The original repository/evidence is preserved; no history was reset or force-pushed.

The GitHub evidence selection is intentionally insufficient to rerun the historical raw-byte acceptance audit.
That audit was actually rerun locally against its complete store; publication contains interpretable reports and
provenance instead of private raw archives. Historical `results/...` paths in retained audit/ledger documents
refer to that preserved archive, not files promised in the snapshot. Home-path redactions are identified in the
publication manifest; audit findings and FAIL verdicts remain intact.

The sealed portable ZIP retains its original source identity and checksum, with deterministic scripts and no AI
subscription requirement. Local packaging and native checks passed; recipient installation and full end-to-end
execution remain **UNTESTED**. Its archival builder needs the original Git objects, which the sanitized snapshot
does not contain. The normal source and manual demo routes do not need those objects.

GitHub publication is private. The project is presented as a final delivery with documented verification
limits. The existing `v0.9.0-partial` tag is retained as the historical identifier of the sealed assets;
changing presentation does not rewrite that tag, its source identity or the original evidence. Only measured
runs on a suitable host can close the remaining verification obligations.
