# ADR-002 — Deterministic verification before any semantic judge

Status: accepted (2026-10-26)

## Context

Legacy verification could treat a credible source or a matching number as proof.
That is not proposition support and it made unsupported report statements look
verified.

## Decision

A claim may be `SUPPORTED` only when all deterministic checks pass:

1. snapshot hash and span hash match;
2. the quote resolves at the recorded offsets (or is an exact substring when
   offsets are unknown);
3. the claimed value and unit appear in the quote;
4. region/period/scope/caliber/version are compatible;
5. the claim period falls inside the requested `date_window`.

Statuses are disjoint. `NOT_COMPARABLE` covers differing years, scopes, calibers,
and incompatible units. `OUTDATED` is reserved for a newer series version.
Conflicting claims are `NEEDS_REVIEW` only when both sides independently pass the
objective support test; a baseless contradiction cannot override a supported
claim.

A model-assisted judge, if added later, must write `judge_assessment` and remain
distinguishable from deterministic checks. It must never silently promote a
claim to `SUPPORTED`.

## Consequences

- Conservative behavior: paraphrases and unextracted aliases stay
  `INSUFFICIENT`. This is intentional; recall is a future metric, not a reason to
  loosen proof.
- The 2027 planning target in the mock corpus is now `NOT_COMPARABLE` for a 2024
  window instead of a false `SUPPORTED`.
- Briefs withhold unsupported statement text rather than restating it.
