# Architectural Design Language

The system's direction is architectural synthesis across building types and styles. Paris Haussmann is the current reference domain, not the definition of architecture or a universal template.

## Contract

Every design carries an `architectural_contract` into the task brief as `design_language`:

- `style`: the requested architectural type and historical or contemporary context.
- `invariants`: source-backed rules that every candidate must satisfy.
- `variation_axes`: independent choices that can produce different coherent designs.
- `relationships`: how site, massing, circulation, structure, envelope and components fit together.
- `uncertainties`: missing or occluded evidence, kept separate from design inference.

Dimensions, roof form, floor hierarchy and topology are decisions to review at the framework stage. Component proportions, placement, repetition and junctions are reviewed in composition and refinement. A specific roof type is mandatory only when the task's rules require it.

Variation means architectural choices within constraints, not random material replacement or copying reference coordinates. Different candidates may express the same rules through different arrangements.

## Capability Growth

A visual or capability failure can trigger source diagnosis. The agent inspects the active dispatch, reads generation functions, proposes exact source edits and validates a task-local version. Editable modules separate structure, facade composition, techniques, assembly and domain-specific profiles. Form, scheme and technique registries may grow while source assets and acceptance gates remain protected.

Each version is bound by hashes. Fresh workers load that version, run trusted regression tests and build deterministic schematics. Independent file, geometry and Minecraft registry validation run before activation. Candidates are rerendered and re-reviewed after rollback to the affected stage. The main checkout is not hot-reloaded or overwritten by model patches.

The source repair operation preserves tool calls, code changes, validation logs and version receipts. A failed validation feeds the next repair attempt. Interruption preserves the last activated version and completed artifacts.

## Current Limits

The installed knowledge catalogue, user-facing planner and production adapter still primarily cover Paris-derived buildings and a finite set of site forms and dimensions. Existing review-layer labels reflect that adapter. The generic contract and source repair mechanism are foundations for broader capability; they do not establish support for every possible building, structural engineering compliance, or arbitrary new topology.

New domains require their own architectural evidence and task-specific component/review schemas. Neither passing tests nor a model's own review grants game or aesthetic acceptance. Final game acceptance remains user-owned.
