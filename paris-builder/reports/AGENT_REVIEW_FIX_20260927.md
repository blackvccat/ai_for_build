# Agent execution and architectural review correction

## Observed failures

- Session `e1b69b5d76884293` repeatedly acknowledged prompt-writing requests without delivering the text.
- Session `972b9d39e82741cf` failed while replacing its JSON file with WinError 5.
- The layered review contract allowed a generic roof observation to substitute for a roof-form assessment. Tier2 scope omitted much of the facade detail review.

## Changes

- Resolve short confirmations using recent conversation context. A prompt-drafting action must deliver the actual draft. Retry an incomplete draft once; never report an acknowledgement as task completion.
- Retry atomic replacement on Windows errors 5/32/33, with a bounded delay. Preserve the previous JSON on persistent failure and remove the temporary file.
- Framework reviews require nine explicit geometry checks, including style typology, floor hierarchy, roof section, slope break, roof/body ratio and attic volume. Structural checks cannot be marked not applicable.
- Facade and refinement reviews require eight detail categories for each architectural layer and each individual storey. A failed window/detail check prevents approval.
- Existing layered-v1 autonomous runs restart at frameworks when resumed. Old reviews cannot substitute for the new evidence.
- Reference street-house roofs now retain a measured steep lower slope and shallow upper slope. Roof sections are recorded for both street and corner forms. This is generated geometry, not historical measurement or aesthetic acceptance.

## Verification

- Full suite: 144 tests passed. JavaScript syntax and UTF-8 I/O checks passed.
- A real Windows CreateFileW reader denied file replacement during the test; retry succeeded after the reader released the file, preserving both events.
- Live DSH execution in the original prompt session: submitting `请开始` returned a complete multi-section prompt; session increased from 35 to 42 events. Verified both saved JSON and browser-rendered text. No building was queued for that prompt-only task.
- Browser screenshot: `runs/AGENT-REVIEW-FIX-20260927/prompt-reply.png`.
- Rendered seven fixed views of the revised framework: `runs/AGENT-REVIEW-FIX-20260927/previews/`. Roof heights 5..9 verified against actual roof blocks and measured slopes.

## Limits

- The newly strengthened visual review chain has not yet completed a live end-to-end building run. Contract tests and framework rendering do not establish reliable architectural judgment by the model.
- The old tier2 building is not declared architecturally accepted. The verification framework preserves its dimensions to isolate the roof change; it is not a final widened-facade design.
- Game acceptance remains user-only and PENDING.
