# Builder verification — 2026-10-21

**Packaging checks PASS; recipient execution UNTESTED.** This report covers a portable source/launcher release. It does not claim another full local VM campaign or execution on a second Mac. No existing VM was started, provisioned, stopped, cloned or deleted while building this package. No source-runtime or acceptance-contract change was made.

## Source reconciliation and export

Builder started at `f09aa6322e5b8d923b9219b5f90ba32f50b17c0a`. `git diff --name-only 3d7a9f7 f09aa63 -- device gateway runner scripts tests inventory.yaml config requirements-dev.txt` is empty: the last tested runtime is unchanged. Historical report/checkpoint/source manifests confirm 11/11 commissioning, 24/24 faults, 6/6 mutants and 22/24 acceptance, with five current fresh restorations and independent fresh-VM reproduction still open.

The builder read the authoritative brief, repository instructions, protocol, requirements, lab record, commissioning SOP, acceptance contract, implementation ledger, interrupted-evidence repair and final overnight execution report/checkpoint/scripts. The original first specification commit is `38e51d5`; full commit IDs/titles through the included revision are in `RELEVANT_COMMITS.txt`.

Export is 109 Git-tracked source/specification/documentation files at f09aa63, plus the launcher, support scripts and release documents. The original Git blob SHA, original SHA-256 and export SHA-256 are listed per source file. Runtime/tests/provisioning bytes equal the original revision. An absolute home path in historical review documentation is redacted only in the distribution. The authoritative brief retains SHA-256 `07a33a088939c9cc59ef4dbbfb12706ad17431d9eb4d8b5353feafdcea555baf`.

The clean snapshot excludes all historical results, databases, pcaps, ignored/untracked files, VM images, credentials, caches and environments. All **453** tracked historical evidence symlinks are excluded. An automated scan of **13,988** reachable original-history blobs found **494** blobs containing absolute home paths and **zero matches** for the credential patterns tested. These are pattern-scan results, not a guarantee against every possible secret. Full history is deliberately not distributed; personal author metadata and evidence paths are not necessary to run the source. The builder records ignored/untracked inventories and exports neither category. The archive contains no symlinks, sockets, VM disks, databases, pcaps, recognized private keys or original absolute username paths. `EXPORT_AUDIT.json` records the final scan counts (which may also include new packaging commits).

ZIP member order, permissions and timestamps are normalized. Two successive builds from identical source/builder inputs produced the same ZIP SHA-256 (`reproducible-zip-first.sha256` and `build-seal-1.log`/`build-seal-2.log`). Mutable local ignored/untracked inventory counts stay outside the payload, in `dist/BUILDER_INPUT_INVENTORY.json`.

## Executed local checks

All commands ran from the repository root. Local evidence is retained under `results/handoff-build-20261021/`; it is not imported into recipient acceptance.

| Actual command / check | Outcome | Local record |
|---|---|---|
| `python3 handoff/build_package.py --out dist` | PASS: fresh snapshot, Git blob manifest, export scan, ZIP creation, content SHA-256 seal | `build-candidate-final.log`, final release metadata |
| `python3 -m unittest discover -s handoff/tests -p test_portable.py -v` | **40 passed**, 6.153 s | `portable-tests-release.log` |
| `.venv/bin/python -B -m pytest -q -p no:cacheprovider handoff/tests/test_guest_verify.py` | **7 passed**, 7.00 s; explicit synthetic contract fixtures, never real VM evidence | `guest-verifier-fixtures-release.log` |
| `.venv/bin/python -B -m pytest -q -p no:cacheprovider tests/unit/test_live_case_budget.py tests/unit/test_case_deadline.py tests/unit/test_decision_predicates.py tests/unit/test_interrupted_environment.py tests/test_inventory.py` | **149 passed**, 34.30 s | `source-focused-tests.log` |
| `.venv/bin/python -B handoff/verify_build.py --zip dist/Witness-Reproduction-f09aa63-v1.zip --lima-archive /tmp/witness-lima-2.2.0.tar.gz --out results/handoff-build-20261021/native-release` | **10/10 native checks PASS** | `native-release.log`, per-command JSON/stdout/stderr in `native-release/` |
| `python3 -m py_compile handoff/*.py`; `bash -n handoff/RUN_ON_THIS_MAC.sh handoff/RETURN_RESULTS.sh`; extracted source shell syntax; `git diff --check` | PASS | packaging tests and builder execution record |
| Official Lima 2.2.0 archive SHA-256, extracted `limactl --version`; signed Python.org 3.13.9 package SHA-256 and `pkgutil --check-signature` | PASS; Python installer **not executed** | native logs, `python-installer-signature.log`, pinned dependency hashes |
| Ubuntu original URL / archive / archive S3 TLS endpoint HEAD and SHA256SUMS | Original URL now redirects to HTTP; direct archive HTTPS timed out; **S3 HTTPS 200**, 615,630,848-byte image and published SHA match the original pin | `ubuntu-image-head.log`, `ubuntu-archive-head.log`, `ubuntu-archive-s3-head.log`, `ubuntu-archive-SHA256SUMS.txt` |
| Original checkout/evidence preservation manifest re-read | **15,880** original entries preserved, apart from declared `.gitignore`/implementation-ledger updates; brief unchanged | `preservation-before.json`, `preservation-current.json` and final preservation record |

The 40 packaging tests cover checksums/tampering/missing files, archive permissions, extraction into a different directory, relative paths, unowned directories, work/VM symlinks, unrelated or unclaimed Lima names, inherited environment isolation, low RAM/disk, full-copy restore reserve, pressure/swap stop, route conflicts, process timeout/termination, resource-red safety cleanup, atomic checkpoint/resume, replacement transactions, continuation-store preservation, incomplete/failed report verdicts and scoped return archives/credential guards. These are unit/control tests with explicit fixtures; they do not prove VM behavior.

The seven guest-verifier integration tests call the actual commissioning/audit/report APIs on labeled synthetic stores: complete/partial baselines, wrong source revision, full fault/removal shape, all 24 assertions/report generation, repeated-restoration rejection and missing-evidence rejection. They exposed and prevented an incorrect commissioning API keyword during development.

Native checks extract the real ZIP into a new temporary directory containing spaces, verify ZIP CRCs/checksums and executable modes, run the packaged `--verify` and CLI help, extract/run the pinned official Lima binary, inventory an empty private Lima home, create only its two private network configuration entries, and validate both generated VZ configurations. No VM is created or started. The **exact recipient command** from the message is executed twice with a temporary Downloads/home path: this actual 8 GiB host returns BLOCKED before consent/installation/VM creation, and repeat execution safely reuses the extraction.

## Retained failures and corrections

The first native configuration validation failed because the **smoke harness** had not created its empty private home's network entries. That failure remains in `native-smoke/`; the fixed harness creates only those private configuration entries, and all ten checks pass in `native-smoke-fixed/` and `native-release/`. The distribution coordinator already created the networks before validation.

Review corrected the commissioning verifier's keyword, an unsupported Lima cache environment variable, the Ubuntu archived-image endpoint, loss of newer guest records after an interrupted fetch, and cleanup commands being gated by the same resource condition they must recover from. Final source remains unchanged. The coordinator uses a verified local image to avoid Lima's shared user cache, atomic transfers and retained prior DB snapshots, and bounded safety commands even under resource pressure.

## Explicitly UNTESTED here

Fresh-machine administrator authentication/Python installation, macOS GUI/security approvals, full image download/hash on the recipient, VZ boot on another Mac, actual recipient apt provisioning, clock convergence, live faults/mutants, golden clone/restore disk allocation, interruption/power-loss behavior, five real independent restorations, fresh-VM reproduction and full external acceptance are **UNTESTED** in this packaging assignment. The launcher implements and records these operations; this report does not predict that they pass. Lower-resource hosts are not qualified. An unavailable pinned dependency blocks execution without a latest-version substitution.

Recipient output is generated independently from new traffic and stores. Full acceptance requires all wrapper steps, the actual production 24-assertion audit and clean shutdown. This package is ready to send for that execution; it has not been end-to-end validated on a second Mac and is not an external professional certification.
