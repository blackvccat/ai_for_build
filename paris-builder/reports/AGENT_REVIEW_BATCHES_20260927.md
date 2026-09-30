# Runtime limits and review refresh correction

## Changes

- Removed the service-wide DSH 60-turn ceiling, SDK request deadline and application token budget. User interruption remains enabled. Removed the obsolete connection-dialog budget hint.
- Review now collects framework geometry or each detail layer and each individual storey in separate schema groups, then requests the final summary. Explicit object templates and field-specific retry diagnostics preserve all architectural gates.
- Visual review no longer has a total call/token quota. Per-response provider parameters still apply.
- Background refreshes and delayed build completion no longer activate preview. The four-second preview timer stops refreshing after the user leaves preview.

## Verification

- 154 Python tests and five Node tests passed; UTF-8 checks passed.
- Browser: opened running ATELIER-A9B3C7EE preview, switched to trace, and remained on trace throughout task events and completion. Connection dialog no longer shows a fixed service budget.
- Live schema verification of ATELIER-C56E0ED3 facade-1 reused actual prior image observations only after verifying the image receipt hashes and complete view coverage. Twelve actual model calls returned five detail layers, six individual storeys and the final verdict, all validated.
- Verification operation: a64e3a4047fc44e4a87df5bf6d7c141f. Verdict: reject. This independent verification did not advance or approve the original workflow.
- The active task was interrupted for the server restart and resumed from its preserved framework stage. It finished its review and stopped on unresolved architectural defects because supported generator parameters could not repair them. This is distinct from malformed review JSON.

## Evidence

- runs/LEARNING-WORKBENCH-v1/operations/a64e3a4047fc44e4a87df5bf6d7c141f/verified-review.json
- runs/AGENT-REVIEW-FIX-20260927/trace-stays-selected.png
- Reproduction: PYTHONPATH=src python tools/verify_review_batches.py --run ATELIER-C56E0ED3 --candidate facade-1 --prior-operation ece238eae482427f816b9454aaff6706

Architectural appearance and game acceptance remain separate from schema correctness.
