# Evidence-First v2 Architecture Baseline Audit

审计日期：2026-10-19

## 结论先行

本次升级应从 `codex/evidence-first-v2` 分支继续；候选热修复的基本证据保真补丁可运行，但不能直接视为 Phase 1 完成。候选分支的全量测试为 `494 passed`，全仓库 Ruff 为 `77 findings`（主要是历史 `scripts/_verify_*.py`），候选自身仍有 3 个 Ruff 问题。

德清县真实 snapshot C 回放显示：四个目标事实在 RawDoc、ProcessedData、EvidenceStore 和 15,000 字符 LLM context 中都存在，但最终报告只出现两个增长率，C 组旁的 `sources.json` 仍是仅含 `report_path` 和 `sections` 的元数据对象。第一个可定位的信息断点是 `report/source archive` 边界；离线 Claim 评分因此不能从 C 的归档中取得正文证据，并将 5 条 snapshot Claim 判为无支持/数值不匹配。候选补丁只修复了新的 smoke 写出路径，尚未覆盖所有实验写出路径，也没有完整 Source Contract。

## Git and environment freeze

| Item | Observed value |
| --- | --- |
| Legacy baseline branch | `codex/experiment-superiority` |
| Legacy baseline commit | `52a6ed0f5164721cece221ffb9e7f67f73ac3dd7` |
| Candidate remote ref | `origin/fix/evidence-preservation-20261019` |
| Candidate commit | `b32470a40c1a042a8d386d15c248fb5e765bc60c` |
| Development branch | `codex/evidence-first-v2` |
| Python | `3.13.7` |
| Pydantic | `2.13.4` |
| pytest | `9.1.1` |
| Ruff | `0.16.10` |
| Initial worktree | clean on the legacy branch |

The candidate branch was fetched from the remote and branched locally. The old baseline branch remains unchanged. Existing experiment files were read only; no experiment result was overwritten or deleted.

## Regression corpus inventory

The replay uses committed, real experiment artifacts rather than generated mock data:

- Deqing snapshot C raw/processed/report/source artifacts under `experiments/independent_comparison/runs/continuation_natural_stage_b_deepseek_flash_20261019/...region_01_snapshot_r1_C/` — 8 files, 115,751 bytes.
- Frozen continuation claims: `experiments/independent_comparison/ground_truth/continuation_ground_truth_20261019.jsonl` — 142,849 bytes.
- Offline claim observations: `experiments/independent_comparison/claim_scores/continuation_natural_stage_b_deepseek_flash_20261019_v3/claim_observations.jsonl` — 498,680 bytes.
- Matched-budget run corpus: `experiments/independent_comparison/runs/continuation_matched_budget_deepseek_flash_20261019/` — 380 files, 7,809,659 bytes.

## Deqing data-flow replay

Replay target:

`continuation_natural_stage_b_deepseek_flash_20261019_region_01_snapshot_r1_C`

Required facts:

- 2024 GDP `722.5` 亿元.
- GDP growth `5.8%`.
- Scale-above industrial added value `300.6` 亿元.
- Its growth `7.7%`.

Observed counts from the replay:

| Stage | Result |
| --- | --- |
| RawDoc | 2 docs; each required value occurs in at least one doc; value occurrence counts `[1, 1, 2, 2]` |
| ProcessedData | 2 docs; same required facts retained; counts `[1, 1, 2, 2]` |
| EvidenceStore | 231 evidence items; required facts occur in `[2, 2, 4, 4]` item fields |
| LLM context | 15,000 chars; all four required values present |
| Report | 3,507 chars; `722.5` and `300.6` absent, `5.8%` and `7.7%` present |
| Source archive | JSON object with keys `report_path`, `sections`; no source content |
| Offline scoring | C snapshot observation is `VALID` but all 5 task claims are `CONTRADICTED`, `ground_truth_recall=0`, `evidence_support_rate=0`, `factual_error_rate=1` |

The permanent regression test is `tests/test_evidence_preservation_regression.py::test_saved_deqing_c_archive_regression_generates_scorable_source_contract`. It reads the real RawDoc and ProcessedData artifacts, records the legacy metadata-only archive, and verifies that the new serializer produces content, hashes, status, timestamps, and chunk mappings. The historical archive itself is intentionally not rewritten.

## Root-cause findings

### 1. Source archive contract mismatch — P0

The old C output writer in the saved run stores only report metadata. The scoring path in `scripts/score_independent_claims.py` reads `sources.json` as source material, so the evidence graph is empty even when the processing pipeline retained the facts. A/B and C therefore do not have equivalent evidence inputs.

The current branch now has `src/county_research_ai/evidence/source_contract.py::serialize_source_documents`, and the smoke/experiment writers use it for new runs. This is an initial Phase 1 repair, not yet the final Pydantic Source Contract required by Phase 3.

### 2. Long-document extraction — candidate repair partially valid

The candidate replaces line-only extraction with punctuation/paragraph segmentation and overlapping 300-character windows. This removes the old behavior that skipped a long one-line bulletin solely because it exceeded 300 characters. It still lacks explicit chunk provenance, headings, offsets, and metric-aware selection.

### 3. Context allocation — candidate repair is a bounded stopgap

The candidate reserves source labels and distributes the remaining budget across all documents, preventing an early national document from completely hiding a later county document. It still takes prefixes rather than selecting task-relevant chunks and does not return structured exclusion reasons. Phase 3 must replace this with EvidencePack selection.

### 4. Text cleaning — candidate repair preserves newlines but not full structure

The candidate keeps newline boundaries while collapsing spaces and repeated blank lines. It does not yet preserve table rows as typed structure, record content truncation causes, or guarantee the metric–value–unit association across every cleaning path.

## Candidate patch review

Candidate files:

- `src/county_research_ai/processor.py`: newline-preserving cleaner.
- `src/county_research_ai/evidence/store.py`: long-segment extraction.
- `src/county_research_ai/models.py`: bounded multi-source context.
- `scripts/run_independent_smoke.py`: C source content persistence for that path.
- `tests/test_evidence_preservation_regression.py`: three synthetic regression tests, plus the real-artifact replay test added in this branch.

Candidate-specific Ruff findings before the new serializer integration were:

- `store.py`: loop variable `paragraph` overwritten.
- `models.py`: two `zip()` calls without explicit `strict=`.

The new regression test initially added one import-order finding; it is tracked with the scoped Ruff result and will be cleaned as part of the Phase 1 test gate. Historical verification scripts account for most full-scope findings and are not silently treated as caused by this Goal.

## Commands and results

- `pytest --no-cov -q` at candidate freeze: `494 passed`, one Windows `.pytest_cache` permission warning; after the real replay test and serializer integration: `495 passed`, same warning.
- Focused red replay before serializer: import failed because `county_research_ai.evidence.source_contract` did not exist; after implementation, evidence preservation and source-writer tests: `15 passed`, one Windows `.pytest_cache` permission warning.
- `ruff check src tests scripts` at candidate freeze: `77 findings`; after the scoped cleanup: `73 historical findings`; no claim of repository-wide Ruff cleanliness.
- Scoped Ruff for all changed production and test files: clean. The implementation gate currently has no new Ruff findings.
- `git diff --check`: no whitespace errors in tracked candidate diff.

## Phase 0 status

`COMPLETE`: baseline SHA, branch, candidate ref, artifact inventory, real Deqing loss boundary, replay test, audit documents, green full test suite, and scoped Ruff result are recorded. Phase 1 remains open because the source serializer is only the initial contract layer; truncation reasons, complete A/B/C coverage, and downstream EvidencePack integration are still required. Existing experiment artifacts remain immutable.

## Phase 1 update

The initial Phase 1 gate is now reproducible in `PHASE1_EVIDENCE_PRESERVATION_REPORT.md`. The real C replay retains all four required values through the bounded context and emits 2 source documents with 24 deterministic chunks. The current branch has `502 passed` with one Windows `.pytest_cache` permission warning and clean scoped Ruff for changed files. This does not close Phase 1: the serializer is still a legacy adapter, and historical artifacts are intentionally not rewritten.

