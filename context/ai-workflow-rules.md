# AI Workflow Rules

## Approach

Build RetailScout incrementally using a spec-driven workflow. The six
`context/` files define what to build, how to build it, and the
current state of progress — always implement against these specs, do
not infer or invent product behavior, scoring logic, or data-source
handling from scratch. Follow the phased delivery plan (Phase 0 data
feasibility → Phase 1 data foundation → Phase 2 scoring engine →
Phase 3 product API/frontend → Phase 4 beta hardening); do not start a
later phase's work before the current phase's deliverables are usable
end to end.

## Scoping Rules

- Work on one feature unit at a time.
- Prefer small, verifiable increments over large speculative changes.
- Do not combine unrelated system boundaries in a single
  implementation step — in particular, never combine a `jobs/` change
  with a `backend/` change in the same unit; they deploy and are
  verified independently.
- A change to scoring weights, catchment radii, or industry mappings
  is a config/data change, not a code change — implement it through
  the versioned config (YAML/table), not by editing formulas inline.

## When to Split Work

Split an implementation step if it combines:

- Ingestion/transformation changes (`jobs/`) and runtime API changes
  (`backend/`) — these have different dependency footprints, deploy
  targets, and failure modes.
- Frontend UI changes and score-methodology changes — a UI unit should
  consume an already-defined API contract, not co-evolve with it.
- Multiple unrelated API routes or multiple unrelated council data
  sources in one pass.
- Behavior not clearly defined in the context files — e.g. a new score
  component, a new business profile, or a new confidence rule needs
  to be specified in `project-overview.md`/`architecture.md` first.

If a change cannot be verified end to end quickly (e.g. re-score a
golden location and check the response), the scope is too broad —
split it.

## Handling Missing Requirements

- Do not invent product behavior, scoring weights, or data-source
  mappings not defined in the context files or the source architecture
  documents.
- If a requirement is ambiguous (e.g. exact hex-grid resolution,
  exact daypart boundaries, exact profile weights), treat documented
  example values as starting hypotheses to validate, not final truth —
  resolve or confirm in the relevant context file before implementing
  against it at scale.
- If a requirement is missing entirely, add it as an open question in
  `progress-tracker.md` before continuing.

## Protected Files

Do not modify the following unless explicitly instructed:

- `frontend/components/ui/*` — generated shadcn/ui components (use the
  CLI to add/update, don't hand-edit generated primitives).
- `contracts/generated/*` — always regenerated from the FastAPI
  OpenAPI schema, never hand-edited.
- `db/migrations/*` — once applied, do not edit in place; create a new
  migration.
- Any third-party library internals.

## Keeping Docs in Sync

Update the relevant context file whenever implementation changes:

- System architecture, boundaries, or the `backend`/`jobs` split →
  `architecture.md`
- Storage model, schema, or retention decisions → `architecture.md`
  and `database-architecture.md` conventions
- Code conventions or standards → `code-standards.md`
- Feature scope, business profiles, or MVP question coverage →
  `project-overview.md`
- Visual language, tokens, or layout patterns → `ui-context.md`

## Before Moving to the Next Unit

1. The current unit works end to end within its defined scope (e.g. a
   score change is verified against at least one golden location).
2. No invariant defined in `architecture.md` was violated — in
   particular: no live council API calls at request time, no partial
   data release exposed, no missing-as-zero coercion.
3. `progress-tracker.md` reflects the completed work, including any
   new open questions.
4. Frontend build (`npm run build`) and backend checks (lint,
   type-check, unit tests) pass for the changed workspace(s).
