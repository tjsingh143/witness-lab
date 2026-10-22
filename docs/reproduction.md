# Reproducing Witness

Run from the repository root. No AI account is required. These are three different verification scopes;
source tests do not stand in for VM traffic, and a passing demonstration does not grant full acceptance.
The final release status and executed checks are in [the engineering report](final-engineering-report.md).

## Source tests

Python 3.12–3.14, Git, and internet access to install the two pinned Python dependencies.
Select a supported interpreter explicitly: these commands use `python3.14`; substitute `python3.13` or
`python3.12` as appropriate. The macOS bundled `python3` can be 3.9 and cannot install the pinned pytest. With pyenv, first select the installed supported version; the shim alone does not select it.

```sh
git clone https://github.com/tjsingh143/witness-lab.git
cd witness-lab
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit tests/test_inventory.py handoff/tests/test_guest_verify.py
```

The initial GitHub repository is private; clone access requires the owner's authorization. Once downloaded,
source tests need no GitHub or AI service. `requirements-dev.txt` pins PyYAML 6.0.3 and pytest 9.1.1. Source and
handoff fixture tests are CPU/local-socket/synthetic-store checks; the source-only command covers 606.
The additional 40 portable-package tests need the sealed release ZIP. After saving that ZIP under `dist/`, run:

```sh
.venv/bin/python -m pytest -q -p no:cacheprovider handoff/tests/test_portable.py
```

Alternatively set `WITNESS_TEST_ZIP` to its downloaded path. These artifact-dependent tests are deliberately
separate from a fresh Git clone's source-only checks. Linux guest provisioning uses
Ubuntu's signed package repositories and records installed versions; it is not a frozen OS build.

For the independent-oracle acceptance test harness:

```sh
.venv/bin/python scripts/verify_acceptance_contract.py --json contract-check.json
```

This creates disposable synthetic stores and tests controls, mutations, seeded combinations, and deliberately
weakened checks. It does not create real commissioning evidence. Remove the generated JSON when finished or keep
it outside source control.

## Two-VM demonstration

Validated host/hypervisor family: Apple Silicon macOS, Lima 2.2.0, Apple Virtualization.framework; Ubuntu 24.04 ARM64
with 1 vCPU, 1 GiB RAM and 10 GiB logical disk per guest. Other host architectures and hypervisors are unqualified.
Use AC power. A recommended entry budget is 16 GiB RAM and 40 GiB free, followed by actual resource checks.
Maintain at least 10 GiB free for ordinary operations plus peak dirty writes, swap, evidence, and recovery needs.
The original 8 GiB Mac ran the historical functional campaign but is not qualified for the full campaign.

1. Install Lima (`brew install lima` if Homebrew is already your chosen package manager). Check
   `limactl --version`: 2.2.0 is the tested version; a newer Homebrew version has not been qualified here.
   The sealed portable package below supplies a private, pinned 2.2.0 instead.
2. Check `df -h .`, `sysctl hw.memsize vm.swapusage`, and `memory_pressure`. Do not start under critical pressure,
   rapidly growing swap, or a reserve that cannot cover the peak. The full launcher applies stricter automatic gates.
3. Complete the source-test setup above. In a **new checkout without existing VM instances**, execute:

```sh
scripts/lab_vms.sh up
scripts/lab_vms.sh provision
scripts/lab_vms.sh provision
scripts/lab_vms.sh preflight
caffeinate -i scripts/lab_vms.sh suite baseline
caffeinate -i scripts/lab_vms.sh suite fault
scripts/lab_vms.sh report
scripts/lab_vms.sh fetch
scripts/lab_vms.sh preflight
scripts/lab_vms.sh stop
```

`provision` must be checked twice for idempotence. Preflight must be GREEN for both guests. Baseline selects all
11 commissioning instances; faults select 24 tests. `report` writes Markdown/JSON and runs acceptance; its exit
1 before five independent restorations is expected. Run `fetch` even after that expected nonzero audit, retaining
`results/witness.db`, `results/evidence/`, and `results/reports/`. Unexpected suite failures are failures.

Read `results/reports/commissioning-report.md`, `fault-report.md`, `traceability.md`, and `acceptance-audit.md`.
For an interactive example, while the lab is running:

```sh
scripts/lab_vms.sh gw devices/dev-a
export LIMA_HOME="$PWD/.lima.nosync"
limactl shell --workdir / witness-ctl -- ip route get 10.77.2.11
```

The devices answer IDENTIFY/HEALTH/READ on TCP 5020; see the [SOP](commissioning-sop.md) for packet and service
inspection. `scripts/lab_vms.sh reset`, then `preflight`, is the scoped recovery path. Vsock management survives
lab network faults. No host network changes are needed. Do not start a golden alongside a lab VM sharing its MAC.

The standard template now explicitly pins the original image through HTTPS, avoiding the retired dated URL's
HTTP redirect. This final configuration passed native Lima validation and an endpoint HEAD check. A full boot,
image download/hash, and provisioning sequence on this revised template was not executed during release.
The original fresh-VM test on older code does not close the current fresh-VM obligation.

## Full acceptance and portable handoff

Use the sealed `Witness-Reproduction-f09aa63-v1.zip` attached to
[the v0.9.0-partial prerelease](https://github.com/tjsingh143/witness-lab/releases/tag/v0.9.0-partial).
It contains the tested runtime source and a deterministic coordinator; no original results database is imported.
Its runtime is unchanged from `3d7a9f7`, even though the source snapshot identity is `f09aa63`.

Verify the downloaded ZIP before extraction:

```sh
shasum -a 256 Witness-Reproduction-f09aa63-v1.zip
```

Expected SHA-256: `32d2b7e00cb49f80861910b739cd1db3b1fc6ff645df767b363c5b5155157293`.
Extract it and read its `HANDOFF.md`; from the extracted package directory:

```sh
/bin/bash RUN_ON_THIS_MAC.sh --verify
/bin/bash RUN_ON_THIS_MAC.sh
```

The package requires native Apple Silicon macOS 13+, at least 16 GiB RAM and 40 GiB free at entry. Restore gates
add the measured logical pair size (at least 20 GiB), 4 GiB overhead/evidence and 10 GiB reserve; extra space can
be required. It stops under critical pressure, swap above 4 GiB or growth above 1 GiB, or disk below 12 GiB,
leaving reaction headroom above the 10 GiB floor. It never removes unrelated files to satisfy these gates.

The coordinator owns a separate private workspace, downloads pinned dependencies, provisions twice, verifies
preflight and source stamps, runs units/contract controls/faults/mutants/deadline and recovery probes, performs
five distinct golden restorations, then reconstructs from the pinned image. Positive experiments continue one
new main evidence store; expected negatives use separately attributed stores. A successful ordinary restart
cannot count as a restoration. The final production acceptance command needs the **real** DB and capture bytes:

```sh
.venv/bin/python -m runner.analysis --db results/witness.db --evidence-root results/evidence --json acceptance.json
```

All 24 assertions plus the separate mandatory experiments and cleanup are required for full project acceptance.
A14/A15 alone do not establish fresh-image reproduction. Use the launcher's completion report, not pytest's
summary alone. Retain failed attempts and all provenance.

**What is verified:** package hashes, source correspondence, 40 coordinator unit tests, seven guest-verifier
fixture tests, and ten native smoke checks including configuration validation and actual low-RAM refusal.
**What remains unverified:** recipient installation/permissions/downloads and the complete end-to-end VM campaign
on a recipient Mac. Local packaging success is not an external execution result.

`handoff/build_package.py` is an archival maintainer tool tied to original commit `f09aa63`. Rebuilding that exact
ZIP requires the preserved original development repository; the sanitized GitHub snapshot does not contain its
Git objects. The sealed ZIP remains independently runnable and checksum-verifiable. The published repository's
normal source tests and manual two-VM route do not depend on those old objects. See [builder verification](../handoff/BUILDER_VERIFICATION.md).

## Evidence custody

Raw DBs/pcaps and the original evidence seal remain local. The small [release evidence selection](../evidence/release/README.md)
preserves interpretable reports, command outcomes, and source provenance; it is deliberately incomplete for raw
historical acceptance recomputation. A new run creates a complete independent store. Review generated logs for
machine-specific information before sharing them. Do not commit VM disks, keys, venvs, caches, or raw databases.
