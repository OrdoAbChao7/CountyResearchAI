# Evidence-First v2 Migration Guide

## Existing integrations

Callers may continue to provide `RawDoc` collections through `ProcessedData`; the adapter `build_evidence_ledger(processed_data)` builds canonical sources, chunks, and extractable claims without requiring an immediate rewrite of existing collectors. Existing CLI commands and legacy report modes remain the compatibility boundary.

To use evidence-bound research in an application path:

1. Build or obtain a `ProcessedData` value.
2. Construct a `ResearchSpec` with the region, mode, architecture version, budget, and required `QuestionSlot` values.
3. Build the `EvidenceLedger` and select an `EvidencePack` for each slot.
4. Attach the ledger/pack to the research context or `ProcessedData` path consumed by the analyzer.
5. Preserve the resulting source/chunk map and pack audit data with the report.

Use the canonical architecture value `evidence_first_v2` for new experiment manifests. `workflow_legacy` and `deep_legacy` remain explicit options where supported; unknown versions should fail validation rather than silently selecting a path.

## Budget and evidence handling

`QuestionSlot.budget_chars` and `ProcessedData.render_for_llm(max_chars=...)` are character limits, not tokenizer token limits. Inspect `EvidencePack.excluded_evidence_reasons`, `missing_requirements`, and `status`; a non-empty pack does not imply all requested facts were found. Keep source offsets and hashes from the adapter—do not synthesize offsets for source material without reliable positions.

For long-history mode, period packs and task checkpoints are optional additions. Pass `analysis_checkpoint_path` only when resumability is wanted and the path is unique to that analysis. A matching checkpoint resumes completed tasks; input, prompt, provider/model, or county drift must start a distinct analysis rather than reusing results.

## Validation before rollout

Run the test suite and scoped Ruff checks. Compare reports and archived source contracts on representative local inputs before enabling the architecture for production workloads. Existing offline evidence does not show a quality lift: adaptive ranking was tied on its small replay, exact excerpt retention drops at EvidencePack selection, and current independent C-group metrics are below baselines. Do not interpret character reduction as token/cost reduction. New Provider/Judge experiments require their own current authorization and resource gate.
