# Project status and engineering notes

This document records the boundary between what this repository is intended to demonstrate, what has been verified in the repository, and what still needs evidence. It is deliberately more specific than a feature list.

## Current stage

**Deep Research Multi-Agent Architecture (Refactored Prototype)**

## Why this exists

I built this to make the first pass of county-level industry desk research reproducible: collect public material, preserve evidence links, and turn the material into a reviewable, traceable Markdown research report.

The architecture was upgraded from a linear single-pass retrieval pipeline to a deep, evidence-driven multi-agent research loop inspired by BettaFish and modern agentic research practices.

## Core Capabilities Added in Refactoring

1. **Dynamic Question Tree & Intent Planning**:
   - `QueryEngine` constructs mode-specific inquiry trees (formation, statistics, enterprise/chain, policy, bottlenecks, outlook).
   - Dynamic search query generation covering official gazettes, statistical yearbooks, and sector policies.
   - Administrative disambiguation (`disambiguate_region`) for counties, county-level cities, and prefecture-level cities.

2. **Reflection & Gap-Driven Supplemental Search**:
   - `ResearchCritic` evaluates initial evidence coverage against the question tree.
   - Generates targeted supplemental queries to close coverage, metric, or temporal gaps.

3. **Structured Evidence Store & Fact Verification**:
   - `EvidenceStore` ingests raw documents, extracts fine-grained numerical, policy, and historical claims with `(num, unit, indicator, period, scope)` attribution.
   - Detects metric conflicts and scope divergences across years and administrative boundaries.
   - `FactVerifier` performs bidirectional Claim → Evidence → Source checks with strict confidence thresholds to prevent LLM hallucinations.

4. **Specialized Multi-Agent Synthesis Matrix**:
   - `EconomicResearchAgent`, `PolicyResearchAgent`, `IndustryResearchAgent`, and `ResearchSynthesizer` collaborate under `DeepResearchCoordinator`.
   - Appends verifiable audit logs and conflict investigation records to every generated report.

5. **Objective Benchmark Suite**:
   - Covers Case A (Anji Bamboo), Case B (Xinfeng Navel Orange), Case C (Hegang Industrial Transition).
   - Metrics include Precision@K, Recall@K, Official Source Ratio, Evidence Support Rate, and Conflict Detection.

## Scope and known limitations

The generated report is an in-depth research draft, not an official policy determination.
- Public search coverage depends on the availability of indexed local government and statistical resources.
- In offline/mock test environments, deterministic golden datasets are used to evaluate retrieval recall and verification logic.
- When running in an environment without LLM API keys, the system safely falls back to rule-based heuristic analysis.

## Verification Record

- **Test Suite**: 299/299 tests passing (`pytest`).
- **Static Analysis**: 0 lint or complexity errors (`ruff check`).
- **Benchmark Evaluation**:
  - Case A (Anji): Recall@K improved from 40% to 100%, evidence support rate at 100%.
  - Case B (Xinfeng): Recall@K improved from 20% to 100%, successfully detected 1 scope divergence.
  - Case C (Hegang): Recall@K improved from 20% to 80%, core facts 4/4 covered.
