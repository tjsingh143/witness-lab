@AGENTS.md

# Claude Code conventions for Witness

- The authoritative source is PROJECT_BRIEF.md. Read it in full at the beginning of Phase 1, and consult relevant sections each later phase. It must remain byte-for-byte unchanged.
- This published snapshot intentionally omits the original `prompts/phaseN.md` kit. Start with `README.md`, `docs/final-engineering-report.md` and the latest entries in `docs/implementation-state.md`. Follow the user's current task; do not resume an obsolete phase or infer an unrequested implementation campaign from the historical ledger.
- Use Claude Code's built-in Read/Edit/Bash/Web tools as needed. Look up *current* UTM, Lima, Ubuntu or Linux documentation when a decision depends on a specific version or uncertain behavior; web search needs no CLI flag.
- Default to direct tool use within this session; do not launch subagents or agent teams. Maintain a compact on-disk handoff rather than relying on chat history across sessions.
- Before altering Linux networking, routing, nftables, process state, or traffic control, verify you are on `witness-ctl` or `witness-field`; keep a rescue console and scoped undo. Never perform disruptive fault injection on macOS.
- Do not exceed the current phase's scope in order to use extra tokens. Prefer implementation and real tests to lengthy planning, repeated summaries, or speculative enhancements.
- Return a concise milestone summary: actual files changed, tests run with PASS/FAIL/BLOCKED, real VM evidence, safety restoration, and the next actionable step. Never say a missing test passed.
- For context compaction: preserve any failed tests, known blockers, destructive state left active, decisions, paths and command evidence. Update `docs/implementation-state.md` before restarting a session.
