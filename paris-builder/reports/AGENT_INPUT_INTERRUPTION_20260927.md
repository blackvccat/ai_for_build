# Composer, interruption and actual reference-image input

## Implemented

- Image chooser, drop and clipboard paste share PNG/JPEG validation, previews and removal. Maximum two images, 2 MB each.
- Enter submits; Shift+Enter inserts a newline. IME confirmation does not submit.
- Session tasks expose queued, running, stopping, interrupted, failed and done states. Interrupt closes DSH and waits for worker exit before allowing continuation.
- Continuation preserves original inputs and completed workflow artifacts without repeating the original user event.
- Uploaded references are resolved within their session and passed as actual image pixels to the vision provider. Observations and matching image hashes are recorded and cached.
- Application-level worker errors mark the task failed. Invalid vision output cannot be reported as completion; response and receipt are saved for diagnosis.
- Draft instructions assign roof form and proportions to framework review and individual storey details to refinement review.

## Verification

- 151 Python tests passed, including failed-result propagation and actual image-path forwarding.
- Three Node composer tests passed. JavaScript syntax and UTF-8 checks passed.
- Browser: Enter submitted, Shift+Enter preserved the draft, attachment chooser preview/removal worked.
- Session d0af595e4cb44558: interrupt reached interrupted; continuation reached done with one original user event.
- Session e507b24d1f14410b: existing photo was read with matching SHA256 receipt; corrected reference observations and full prompt displayed. No building was started.
- Screenshots: task-interrupted.png, attachment-preview.png and photo-analysis-reply.png in runs/AGENT-REVIEW-FIX-20260927.

## Limits

- Native operating-system file dragging was not exercised; drop handling is covered by the composer tests.
- Synchronous render/vision calls stop at the next checkpoint after the current call returns.
- The strengthened architectural review chain has not completed a new live building run. Architectural and game acceptance remain pending.
