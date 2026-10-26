# Evidence-First v2 Architecture

Status: `ENGINEERING_COMPLETE_RESEARCH_PENDING` (2026-10-19)

Evidence-First v2 adds a structured evidence path to CountyResearchAI while retaining the existing `RawDoc`, `ProcessedData`, CLI, and legacy research modes. It makes source lineage, evidence selection, missing requirements, and budget exclusions inspectable. It does not establish that generated research is more accurate than the existing baselines.

## Data path

```text
RawDoc / ProcessedData
        │ adapter
        ▼
SourceDocument ── EvidenceChunk ── AtomicClaim
        │                               │
        └──────── EvidenceLedger ───────┘
                         │ QuestionSlot + character budget
                         ▼
                    EvidencePack
                         │
          analysis / verification / report appendix
```

`SourceDocument` records canonical source identity and content metadata. `EvidenceChunk` carries its source relationship and offsets; unknown offsets stay unknown rather than being fabricated. `AtomicClaim` represents a comparable fact with region, metric, period, scope, unit, caliber/version, and evidence links. `QuestionSlot` defines the requested question and constraints. The `EvidenceLedger` selects chunks deterministically and exposes selected material, excluded material, and unmet requirements through `EvidencePack`.

The legacy application attaches the ledger and pack on cache-hit and fresh-processing paths. Existing report modes consume the selected pack and append a traceability section. The long-history analyzer derives sentence-level children from original source text, preserving parent chunk IDs and source offsets, then selects per-period packs. Decimal points between digits are not sentence boundaries.

## Retrieval and analysis

Adaptive retrieval builds mode-specific plans from `ResearchSpec`/`QuestionSlot`, ranks candidates using task relevance, locality, period, metric, source reliability and novelty, and can issue gap-linked follow-ups. Its result reports observed retrieval usage and stop reasons. The legacy Collector path remains available.

Evidence-bound verification links supported statements to `Claim → Chunk → Source`. Numeric comparison is conservative about region, metric, period, administrative scope, unit, statistical caliber and series version. Unsupported or ambiguous statements remain unverified; deterministic string/number matching is not semantic entailment.

Long-history analysis routes six topic/period packs and can optionally checkpoint task results. Checkpoints bind to input and prompt/configuration identity and resume only matching analyses. Checkpointing is opt-in; fixed-input experiment recovery still rejects runs left in `RUNNING` state to avoid silent artifact overwrite or unresolved resource leases.

## Compatibility and limits

- Supported experiment architecture labels are manifest-visible; legacy labels remain accepted where defined.
- Existing report and input models remain usable through adapters and compatibility fields.
- Character budgets are not token budgets. Current long-history replay measured fewer prompt characters but lacks matched per-call token traces.
- The six-document adaptive retrieval replay showed no top-3 recall lift.
- The frozen C-group exact-evidence replay found 17/60 matching excerpts in RawDocs/ProcessedData/Ledger and 13/60 in both 6k and 18k EvidencePacks. This is exact excerpt retention, not semantic recall or research quality.
- Historical matched-budget aggregate metrics currently trail baselines for C; the sample is small and not statistically conclusive. No fresh Provider or Judge calls were made for this implementation.

See [Phase 3 architecture](../../PHASE3_EVIDENCE_ARCHITECTURE.md), [Phase 4 retrieval evaluation](../../PHASE4_ADAPTIVE_RETRIEVAL_REPORT.md), [Phase 5 synthesis evaluation](../../PHASE5_EVIDENCE_BOUND_SYNTHESIS_REPORT.md), [Phase 6 efficiency evaluation](../../PHASE6_EFFICIENCY_OPTIMIZATION_REPORT.md), and [Phase 7 replay evaluation](../../PHASE7_EXPERIMENTAL_EVALUATION.md).
