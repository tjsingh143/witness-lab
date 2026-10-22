# Selected release evidence

**Acceptance: 22/24; A14/A15 fail.** These are reports and small excerpts from executed checks, not a substitute
for the complete raw evidence store. The full original databases, packet captures and command archives remain
preserved locally and are not shipped in this repository. The published selection cannot rerun the historical
raw-byte acceptance audit by itself. A new lab run generates its own complete store.

- `acceptance.json` and `reports/`: production audit/report regeneration during release, using the original real-VM
  current campaign database and its actual evidence root. Assertion records were compared and match exactly.
- `live-*-command.log`: original UTC argv/results for the real-VM baseline, faults and Ubuntu focused checks.
  These were executed earlier on `3d7a9f7`; they are not new VM trials during release.
- `F1-stopped-capture.txt`, `F2-hung-capture.txt`: real decoded packet text. Compare the immediate RST for the stopped
  service with the completed handshake but absent application response for SIGSTOP. These cases' original binary
  pcaps remain in the local store; the text excerpts are illustrative evidence, not the complete captures.
- `functional-crosscheck.json`, `baseline-uptime-window-check.json`, `source-verification.json`: preserved native
  SQL/response/hash/packet and installed-source cross-check records from the final functional campaign.
- `release-commands/`: newly executed local release commands, bounded timeouts, UTC start/end and exit statuses.
  The failed first fresh-checkout run and unsupported/unselected Python attempts remain recorded; corrected
  source-only reproduction passed 606 tests, and separate ZIP-dependent tests passed 40. The full synthetic
  adversarial self-test timed out at 900 s with no final verdict; it is not counted as a PASS.
  Acceptance exit 1 is expected for A14/A15. An initial release-check harness compared the report JSON envelope
  to the bare assertion list; the corrected comparison uses `assertions` and passes. Both logs are retained.
- `static-checks.json`: source syntax, byte correspondence, report equality, unchanged authoritative brief,
  overnight seal verification and a small APFS probe. The temporary file probe is not VM commissioning evidence.
- `resource-*.json`: actual host/VM resource inventories. They do not claim a fresh restore or fresh VM ran.
- `native-verification.json`: ten native checks of the sealed portable ZIP, including actual low-memory refusal.
  Recipient installation and end-to-end VM execution remain untested.
- `credential-scan.json`: eight credential-pattern rules over all original reachable history blobs; zero matches.
  It reports no matched values. Pattern matching is not a guarantee against every possible secret.
- `ORIGINAL_COMMITS.txt`: original commit identities/titles at release inspection, without author emails. These
  records describe history preserved locally; those Git objects are not included in the publication snapshot.

`SELECTION_MANIFEST.json` gives the original local reference, original SHA-256 and export SHA-256 for each selected
file. Builder home-directory references are redacted as `<builder-home>` in publication copies only. Publication text normalizes CRLF/trailing whitespace where recorded in the manifest. The original
evidence and hashes remain unchanged. Hashes establish correspondence rather than authenticity.

Historical `results/...` paths in source documents name the preserved local archive. They are not links to a
complete GitHub evidence dataset. See [the final report](../../docs/final-engineering-report.md) for limitations
and [reproduction](../../docs/reproduction.md) to create new independent evidence without an AI subscription.
