"""Deterministic QuestionSlot-driven retrieval planning and coverage feedback."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum

from ..domain.research_contracts import EvidencePack, ResearchSpec
from ..models import RawDoc
from .content_extractor import calculate_content_fingerprint, normalize_url
from .query_engine import GeneratedQuery, QueryEngine


class RetrievalStopReason(StrEnum):
    QUALITY_MET = "quality_met"
    BUDGET_EXHAUSTED = "budget_exhausted"
    ZERO_MARGINAL_EVIDENCE = "zero_marginal_evidence"
    NO_GAP_QUERY = "no_gap_query"
    MAX_ROUNDS = "max_rounds_reached"


@dataclass
class RetrievalBudget:
    max_queries: int = 12
    max_fetches: int = 120
    used_queries: int = 0
    used_fetches: int = 0

    @property
    def remaining_queries(self) -> int:
        return max(0, self.max_queries - self.used_queries)

    @property
    def remaining_fetches(self) -> int:
        return max(0, self.max_fetches - self.used_fetches)

    def reserve_queries(self, count: int) -> int:
        reserved = min(max(0, count), self.remaining_queries)
        self.used_queries += reserved
        return reserved

    def record_fetches(self, count: int) -> int:
        actual = max(0, count)
        self.used_fetches += actual
        return actual


@dataclass(frozen=True)
class AdaptiveQueryPlan:
    spec: ResearchSpec
    queries: tuple[GeneratedQuery, ...]
    round_number: int = 1


@dataclass(frozen=True)
class AdaptiveCollectionResult:
    documents: tuple[RawDoc, ...]
    usage: dict[str, int]
    stop_reason: RetrievalStopReason | None = None


@dataclass(frozen=True)
class RankedDocument:
    document: RawDoc
    score: float
    components: dict[str, float]
    matched_metrics: tuple[str, ...] = ()
    fingerprint: str = ""
    duplicate_of: str = ""


@dataclass(frozen=True)
class SlotCoverage:
    slot_id: str
    matched_metrics: tuple[str, ...]
    missing_metrics: tuple[str, ...]
    selected_claim_count: int
    selected_source_count: int
    status: str


@dataclass(frozen=True)
class CoverageSnapshot:
    slots: tuple[SlotCoverage, ...]
    new_evidence_count: int
    independent_source_count: int
    conflict_count: int = 0

    @property
    def satisfied_slot_ids(self) -> tuple[str, ...]:
        return tuple(slot.slot_id for slot in self.slots if slot.status == "complete")

    @property
    def missing_slot_ids(self) -> tuple[str, ...]:
        return tuple(slot.slot_id for slot in self.slots if slot.status != "complete")

    @property
    def missing_metrics(self) -> tuple[str, ...]:
        return tuple(
            metric
            for slot in self.slots
            for metric in slot.missing_metrics
        )

    @property
    def quality_met(self) -> bool:
        core = [slot for slot in self.slots if self._is_core(slot)]
        return bool(core) and all(slot.status == "complete" for slot in core)

    @staticmethod
    def _is_core(slot: SlotCoverage) -> bool:
        return slot.slot_id.rsplit(":", 1)[-1] in {
            "economic_scale", "industry_structure", "origin", "growth",
            "administration", "geography", "traditional",
        }


@dataclass(frozen=True)
class RetrievalDecision:
    coverage: CoverageSnapshot
    queries: tuple[GeneratedQuery, ...] = ()
    stop_reason: RetrievalStopReason | None = None
    usage: dict[str, int] = field(default_factory=dict)


def build_adaptive_query_plan(
    spec: ResearchSpec,
    query_engine: QueryEngine | None = None,
    *,
    max_queries: int = 12,
    round_number: int = 1,
) -> AdaptiveQueryPlan:
    engine = query_engine or QueryEngine()
    queries = engine.generate_research_queries(
        spec.region_name,
        focus=spec.research_focus,
        mode=spec.mode,
        max_queries=max_queries,
    )
    return AdaptiveQueryPlan(spec=spec, queries=tuple(queries), round_number=round_number)


def score_document_for_slot(
    document: RawDoc,
    slot,
    *,
    query: str = "",
    known_fingerprints: set[str] | None = None,
) -> RankedDocument:
    """Score a result with explainable relevance, scope, time, reliability and novelty."""
    full_text = "\n".join((document.title, document.snippet, document.content))
    lower_text = full_text.lower()
    required = tuple(slot.required_metrics)
    matched = tuple(metric for metric in required if metric.lower() in lower_text)
    query_terms = tuple(term for term in re.findall(r"\w+|[\u4e00-\u9fff]{2,}", query) if len(term) > 1)
    query_hits = sum(term.lower() in lower_text for term in query_terms)
    task_relevance = min(1.0, (len(matched) / len(required) if required else 0.0) + min(query_hits, 4) * 0.05)

    region = getattr(slot, "region", "")
    has_region = bool(region and region in full_text)
    national_only = any(token in full_text for token in ("全国", "全国范围", "全国平均")) and not has_region
    region_match = -0.5 if national_only else (1.0 if has_region else 0.2)

    period = getattr(slot, "time_period", "")
    temporal_match = 1.0 if period and period in full_text else (0.5 if not period else 0.0)

    reliability = max(0.0, min(1.0, document.credibility_score))
    if document.domain_type == "government" or ".gov.cn" in document.url.lower():
        reliability = min(1.0, reliability + 0.1)
    fingerprint = calculate_content_fingerprint(document.content or document.snippet)
    novelty = 0.0 if fingerprint and fingerprint in (known_fingerprints or set()) else 1.0
    components = {
        "task_relevance": task_relevance,
        "region_match": region_match,
        "temporal_match": temporal_match,
        "metric_coverage": len(matched) / len(required) if required else 0.0,
        "source_reliability": reliability,
        "novel_evidence": novelty,
    }
    score = (
        3.0 * components["task_relevance"]
        + 2.0 * components["region_match"]
        + components["temporal_match"]
        + 2.0 * components["metric_coverage"]
        + components["source_reliability"]
        + components["novel_evidence"]
    )
    return RankedDocument(
        document=document,
        score=score,
        components=components,
        matched_metrics=matched,
        fingerprint=fingerprint,
    )


def rank_documents_for_slot(
    documents: list[RawDoc],
    slot,
    *,
    query: str = "",
    known_fingerprints: set[str] | None = None,
) -> list[RankedDocument]:
    """Rank and deduplicate reposts deterministically, retaining the strongest source."""
    selected: dict[str, RankedDocument] = {}
    for document in documents:
        ranked = score_document_for_slot(
            document,
            slot,
            query=query,
            known_fingerprints=known_fingerprints,
        )
        key = normalize_url(document.url) or ranked.fingerprint or hashlib.sha256(
            document.title.encode("utf-8")
        ).hexdigest()
        existing = selected.get(key)
        if existing is None or (ranked.score, document.credibility_score, document.url) > (
            existing.score,
            existing.document.credibility_score,
            existing.document.url,
        ):
            selected[key] = ranked

    by_fingerprint: dict[str, RankedDocument] = {}
    deduped: list[RankedDocument] = []
    for ranked in selected.values():
        if ranked.fingerprint and ranked.fingerprint in by_fingerprint:
            existing = by_fingerprint[ranked.fingerprint]
            if ranked.score > existing.score:
                deduped.remove(existing)
                deduped.append(ranked)
                by_fingerprint[ranked.fingerprint] = ranked
            continue
        deduped.append(ranked)
        if ranked.fingerprint:
            by_fingerprint[ranked.fingerprint] = ranked
    return sorted(deduped, key=lambda item: (-item.score, item.document.url, item.document.title))


def assess_evidence_pack_coverage(
    spec: ResearchSpec,
    packs: list[EvidencePack],
    *,
    previous_evidence_ids: set[str] | None = None,
) -> CoverageSnapshot:
    by_slot = {pack.slot_id: pack for pack in packs}
    previous = previous_evidence_ids or set()
    new_ids: set[str] = set()
    all_sources: set[str] = set()
    slot_results: list[SlotCoverage] = []
    for slot in spec.question_slots:
        pack = by_slot.get(slot.slot_id)
        if pack is None:
            slot_results.append(
                SlotCoverage(slot.slot_id, (), tuple(slot.required_metrics), 0, 0, "empty")
            )
            continue
        matched = {
            metric
            for metric in slot.required_metrics
            if any(
                metric in chunk.text
                for chunk in pack.selected_chunks
            )
            or any(metric in claim.metric_id for claim in pack.selected_claims)
        }
        missing = tuple(metric for metric in slot.required_metrics if metric not in matched)
        claim_ids = {claim.claim_id for claim in pack.selected_claims}
        new_ids.update(claim_ids - previous)
        for source in pack.source_map.values():
            all_sources.add(source.canonical_url or source.doc_id)
        status = "complete" if not missing and pack.selected_chunks else ("partial" if pack.selected_chunks else "empty")
        slot_results.append(
            SlotCoverage(
                slot_id=slot.slot_id,
                matched_metrics=tuple(sorted(matched)),
                missing_metrics=missing,
                selected_claim_count=len(pack.selected_claims),
                selected_source_count=len(pack.source_map),
                status=status,
            )
        )
    return CoverageSnapshot(
        slots=tuple(slot_results),
        new_evidence_count=len(new_ids),
        independent_source_count=len(all_sources),
    )


class AdaptiveRetrievalController:
    """Feedback controller that stops on quality, budget, or zero gain."""

    def __init__(
        self,
        spec: ResearchSpec,
        *,
        query_engine: QueryEngine | None = None,
        budget: RetrievalBudget | None = None,
    ) -> None:
        self.spec = spec
        self.query_engine = query_engine or QueryEngine()
        self.budget = budget or RetrievalBudget(max_queries=spec.budget)

    def initial_plan(self, *, max_queries: int | None = None) -> AdaptiveQueryPlan:
        requested_limit = self.budget.remaining_queries if max_queries is None else max_queries
        limit = min(max(0, requested_limit), self.budget.remaining_queries)
        queries = self.query_engine.generate_research_queries(
            self.spec.region_name,
            focus=self.spec.research_focus,
            mode=self.spec.mode,
            max_queries=limit,
        )
        reserved = self.budget.reserve_queries(len(queries))
        return AdaptiveQueryPlan(
            spec=self.spec,
            queries=tuple(queries[:reserved]),
            round_number=1,
        )

    def next_round(
        self,
        packs: list[EvidencePack],
        *,
        round_number: int,
        previous_evidence_ids: set[str] | None = None,
        previous_new_evidence: int | None = None,
        max_queries: int = 4,
    ) -> RetrievalDecision:
        coverage = assess_evidence_pack_coverage(
            self.spec,
            packs,
            previous_evidence_ids=previous_evidence_ids,
        )
        if coverage.quality_met:
            return RetrievalDecision(coverage, stop_reason=RetrievalStopReason.QUALITY_MET, usage=self._usage())
        if self.budget.remaining_queries <= 0 or self.budget.remaining_fetches <= 0:
            return RetrievalDecision(coverage, stop_reason=RetrievalStopReason.BUDGET_EXHAUSTED, usage=self._usage())
        if round_number > 1 and previous_new_evidence == 0:
            return RetrievalDecision(coverage, stop_reason=RetrievalStopReason.ZERO_MARGINAL_EVIDENCE, usage=self._usage())

        queries = self.query_engine.generate_gap_queries(
            self.spec,
            list(coverage.missing_slot_ids),
            max_queries=min(max_queries, self.budget.remaining_queries),
        )
        if not queries:
            return RetrievalDecision(coverage, stop_reason=RetrievalStopReason.NO_GAP_QUERY, usage=self._usage())
        reserved = self.budget.reserve_queries(len(queries))
        return RetrievalDecision(
            coverage,
            queries=tuple(queries[:reserved]),
            usage=self._usage(),
        )

    def record_fetches(self, count: int) -> int:
        return self.budget.record_fetches(count)

    def _usage(self) -> dict[str, int]:
        return {
            "search_queries": self.budget.used_queries,
            "fetched_documents": self.budget.used_fetches,
            "remaining_queries": self.budget.remaining_queries,
            "remaining_fetches": self.budget.remaining_fetches,
        }
