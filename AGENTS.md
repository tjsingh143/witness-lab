# Witness implementation invariants (shared across coding tools)

- PROJECT_BRIEF.md is the immutable authoritative scope. Do not edit or replace it. Use docs/implementation-state.md for progress and decisions.
- Work in this repo, and only operate on two explicitly identified, dedicated Witness lab VMs. Do not change the Mac home network, unrelated VMs, credentials, other projects, or unscoped host firewall/routing.
- Never report VM test results without actually executing them and retaining the commands, logs, timestamps, and evidence references. Tests on Mac loopback or mocked sockets are useful unit tests, not evidence of VM-to-VM commissioning.
- Do not silently remove any mandatory feature, use mock data in a final report, or label an expected injected failure as successful commissioning.
- Implement, run focused tests, debug, and repair. Preserve bounded timeouts, fault rollback, preflight/postflight safety, and explicit results attribution.
- If a GUI action, sudo password, account entitlement, hardware operation, or VM console intervention is necessary, provide an exact action and verification command. Never claim it occurred automatically.
- Read PROJECT_BRIEF.md and docs/implementation-state.md at the start of each phase; update state with completion, test commands/results, evidence, blockers, and next actions at the end of the phase.
- Prefer docs/protocol.md, docs/requirements.md, docs/lab-record.md, docs/implementation-state.md and the reporting scripts to multiple redundant summaries.
- Keep all fault injection on explicitly confirmed lab interfaces/processes and ensure teardown plus emergency reset. Never apply blanket network disruption to the Mac or other hosts.
- Project is software simulation with real VM network traffic; never misrepresent as physical hardware or embedded firmware testing. C port is optional.

- Work primarily in one Claude Code conversation per phase. Do not spawn subagents, agent teams, or parallel autonomous agents for this workflow.
- Prioritize the phase's verified exit criteria over context-window consumption. Before heavy work, identify the evidence needed; preserve enough working capacity to test, clean up, and record state.
- Do not guess terminal output, installation state, account permissions, addresses, clock synchronization or any real VM facts. If blocked on a manual prerequisite, report an actionable single step and preserve remaining state; never pretend it was completed.
- The run must not modify host network routes, host firewall or unrelated service configurations. Dangerous network faults are allowed only after positive identification of dedicated VM, interface, destination and a reachable recovery console.

## Published snapshot and presentation

- The original phase-prompt kit is preserved locally and is intentionally absent from this publication. Read the current README and final engineering report before interpreting historical phase entries. The current release remains a partial-acceptance preview; documentation work does not close missing VM experiments.
- Current explanations describe the implementation, observations, results and limitations directly. Add no personal or AI creator byline, ownership boast, or first-person implementation claim. This convention does not remove required third-party credits, original evidence, historical process records, Git metadata or the immutable original brief.
- Keep review-package work bounded to the requested presentation and evidence selection. Preserve runtime code, acceptance criteria, original measurements, historical FAIL results, protected VMs and full local archives unless a separate task authorizes their modification.
- When maintaining published documentation, update its export hashes and declare the edit in `PUBLICATION_PROVENANCE.json`. Preserve the original source object IDs and original hashes; never describe edited prose as an unchanged original record.
