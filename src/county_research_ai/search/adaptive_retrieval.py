"""Deterministic QuestionSlot-driven retrieval planning and coverage feedback."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum

from ..domain.question_targets import contract_period_in_window, question_target
from ..domain.research_contracts import EvidencePack, QuestionSlot, ResearchSpec, SourceDocument
from ..evidence.source_contract import meets_source_credibility_threshold
from ..evidence.source_identity import source_groups
from ..models import RawDoc
from .content_extractor import calculate_content_fingerprint, normalize_url
from .query_engine import GeneratedQuery, QueryEngine
from .request_history import SearchRequestHistory, SearchRequestKey, normalize_query


class RetrievalStopReason(str, Enum):
    QUALITY_MET = "quality_met"
    BUDGET_EXHAUSTED = "budget_exhausted"
    ZERO_MARGINAL_EVIDENCE = "zero_marginal_evidence"
    NO_GAP_QUERY = "no_gap_query"
    MAX_ROUNDS = "max_rounds_reached"
    STRATEGY_EXHAUSTED = "strategy_exhausted"
    SEARCH_SOURCE_UNAVAILABLE = "search_source_unavailable"
    SEARCH_SOURCE_NO_RESULTS = "search_source_no_results"

    __str__ = str.__str__


_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


def claim_period_in_window(
    period: str, target_years: Iterable[str] | None
) -> bool:
    """Return whether a claim period is fully inside the requested years.

    A multi-year span such as ``2024-2025`` is not a 2024 annual fact, so every
    year named by the claim must be one of the target years. An empty claim
    period is never promoted into the window.
    """
    targets = {str(year).strip() for year in target_years or [] if str(year).strip()}
    if not targets:
        return True
    years = set(_YEAR.findall(period or ""))
    if not years:
        return False
    return years <= targets


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
    target_years: tuple[str, ...] = ()
    selected_claim_count: int = 0
    in_window_claim_count: int = 0
    in_window_source_count: int = 0
    eligible_claim_ids: frozenset[str] = frozenset()

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
    def topic_coverage_met(self) -> bool:
        core = [slot for slot in self.slots if self._is_core(slot)]
        return bool(core) and all(slot.status == "complete" for slot in core)

    @property
    def period_coverage_met(self) -> bool:
        return not self.target_years or self.in_window_claim_count > 0

    @property
    def period_gap(self) -> bool:
        return not self.period_coverage_met

    @property
    def quality_met(self) -> bool:
        """Topic and target-period coverage must both hold.

        Topical completeness alone is not evidence that the requested year was
        actually researched.
        """
        return self.topic_coverage_met and self.period_coverage_met

    def period_coverage_summary(self) -> dict[str, object]:
        """Separate topic coverage from target-window coverage for reporting."""
        return {
            "target_years": list(self.target_years),
            "selected_claim_count": self.selected_claim_count,
            "in_window_claim_count": self.in_window_claim_count,
            "in_window_source_count": self.in_window_source_count,
            "topic_coverage_met": self.topic_coverage_met,
            "period_coverage_met": self.period_coverage_met,
            "period_gap": self.period_gap,
            "missing_slot_ids": list(self.missing_slot_ids),
        }

    @staticmethod
    def _is_core(slot: SlotCoverage) -> bool:
        return slot.slot_id.startswith("contract:") or slot.slot_id.rsplit(":", 1)[-1] in {
            "economic_scale", "industry_structure", "origin", "growth",
            "administration", "geography", "traditional",
        }


@dataclass
class ContractRetrievalProgress:
    """Per-run evidence deltas before final verification and contract acceptance."""

    document_ids: set[str] = field(default_factory=set)
    claim_ids: set[str] = field(default_factory=set)
    eligible_claim_ids: set[str] = field(default_factory=set)
    covered_slot_ids: set[str] = field(default_factory=set)

    def observe(
        self,
        sources: Mapping[str, SourceDocument],
        claim_ids: Iterable[str],
        coverage: CoverageSnapshot,
    ) -> dict[str, object]:
        new_documents = sources.keys() - self.document_ids
        new_claims = set(claim_ids) - self.claim_ids
        new_eligible = coverage.eligible_claim_ids - self.eligible_claim_ids
        covered = set(coverage.satisfied_slot_ids)
        newly_covered = covered - self.covered_slot_ids
        new_groups = sum(
            not self.document_ids.intersection(group["source_ids"])
            for group in source_groups(sources.values())
        )
        if newly_covered:
            progress = "contract_coverage_improved"
        elif not new_documents:
            progress = "no_new_documents"
        elif not new_claims:
            progress = "no_new_claims"
        else:
            progress = "new_claims_without_contract_coverage"
        self.document_ids.update(sources)
        self.claim_ids.update(new_claims)
        self.eligible_claim_ids.update(new_eligible)
        self.covered_slot_ids = covered
        return {
            "evidence_progress": progress,
            "new_document_count": len(new_documents),
            "new_claim_count": len(new_claims),
            "new_selected_claim_count": coverage.new_evidence_count,
            "new_eligible_claim_count": len(new_eligible),
            "new_source_group_count": new_groups,
            "new_covered_slot_count": len(newly_covered),
            "eligible_claim_count": len(coverage.eligible_claim_ids),
            "eligible_source_group_count": coverage.independent_source_count,
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
    max_queries: int | None = 12,
    round_number: int = 1,
) -> AdaptiveQueryPlan:
    engine = query_engine or QueryEngine()
    if any(slot.is_contract_question for slot in spec.question_slots):
        queries = engine.generate_contract_queries(spec)[:max_queries]
    else:
        queries = engine.generate_research_queries(
            spec.region_name,
            focus=spec.research_focus,
            mode=spec.mode,
            max_queries=max_queries,
            target_years=spec.target_years,
        )
    return AdaptiveQueryPlan(spec=spec, queries=tuple(queries), round_number=round_number)


def score_document_for_slot(
    document: RawDoc,
    slot: QuestionSlot,
    *,
    query: str = "",
    known_fingerprints: set[str] | None = None,
) -> RankedDocument:
    """Score a result with explainable relevance, scope, time, reliability and novelty."""
    full_text = "\n".join((document.title, document.snippet, document.content))
    lower_text = full_text.lower()
    target = question_target(slot) if slot.is_contract_question else None
    required = (target.label,) if target else tuple(slot.required_metrics)
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
    fingerprint = calculate_content_fingerprint(document.content or document.snippet, title=document.title)
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


def _incoming_source_eligible(source: SourceDocument) -> bool:
    return meets_source_credibility_threshold(source.metadata, allow_unscored=True)


def _contract_slot_candidates(
    slot: QuestionSlot,
    pack: EvidencePack,
    target_years: tuple[str, ...],
    source_credibility_check: Callable[[SourceDocument], bool],
) -> tuple[str, set[str], dict[str, SourceDocument]]:
    target = question_target(slot)
    if target is None or slot.evidence_requirement:
        return slot.research_question, set(), {}
    chunks = {chunk.chunk_id: chunk for chunk in pack.selected_chunks}
    claim_ids: set[str] = set()
    sources: dict[str, SourceDocument] = {}
    for claim in pack.selected_claims:
        if not target.matches_claim(slot, claim):
            continue
        if not slot.time_period and not claim_period_in_window(claim.period, target_years):
            continue
        for chunk_id in claim.evidence_chunk_ids:
            chunk = chunks.get(chunk_id)
            source = pack.source_map.get(chunk.document_id) if chunk else None
            if (
                chunk is not None
                and source is not None
                and target.has_factual_quote(claim, chunk.text, title=source.title, content=source.content)
                and source_credibility_check(source)
            ):
                claim_ids.add(claim.claim_id)
                sources[source.doc_id] = source
    return target.label, claim_ids, sources


def assess_evidence_pack_coverage(
    spec: ResearchSpec,
    packs: list[EvidencePack],
    *,
    previous_evidence_ids: set[str] | None = None,
    source_credibility_check: Callable[[SourceDocument], bool] = _incoming_source_eligible,
) -> CoverageSnapshot:
    by_slot = {pack.slot_id: pack for pack in packs}
    previous = previous_evidence_ids or set()
    target_years = tuple(
        dict.fromkeys(str(year).strip() for year in spec.target_years if str(year).strip())
    )
    new_ids: set[str] = set()
    all_sources: set[str] = set()
    eligible_claims: set[str] = set()
    eligible_sources: dict[str, SourceDocument] = {}
    selected_claim_ids: set[str] = set()
    in_window_claim_ids: set[str] = set()
    in_window_source_ids: set[str] = set()
    slot_results: list[SlotCoverage] = []
    for slot in spec.question_slots:
        pack = by_slot.get(slot.slot_id)
        if pack is None:
            slot_results.append(
                SlotCoverage(slot.slot_id, (), tuple(slot.required_metrics), 0, 0, "empty")
            )
            continue
        missing: tuple[str, ...]
        if slot.is_contract_question:
            label, candidates, candidate_sources = _contract_slot_candidates(
                slot, pack, target_years, source_credibility_check,
            )
            eligible_claims.update(candidates)
            eligible_sources.update(candidate_sources)
            ready = bool(candidates)
            matched, missing = ({label}, ()) if ready else (set(), (label,))
        else:
            matched = {
                metric
                for metric in slot.required_metrics
                if any(metric in chunk.text for chunk in pack.selected_chunks)
                or any(metric in claim.metric_id for claim in pack.selected_claims)
            }
            missing = tuple(metric for metric in slot.required_metrics if metric not in matched)
            ready = not missing and bool(pack.selected_chunks)
        claim_ids = {claim.claim_id for claim in pack.selected_claims}
        new_ids.update(claim_ids - previous)
        for source in pack.source_map.values():
            all_sources.add(source.canonical_url or source.doc_id)
        for claim in pack.selected_claims:
            selected_claim_ids.add(claim.claim_id)
            in_window = (
                contract_period_in_window(claim.period, slot.time_period)
                if slot.is_contract_question and slot.time_period
                else claim_period_in_window(claim.period, target_years)
            )
            if in_window:
                in_window_claim_ids.add(claim.claim_id)
                in_window_source_ids.update(claim.source_ids or pack.source_map)
        status = "complete" if ready else ("partial" if pack.selected_chunks else "empty")
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
    has_contract_questions = any(slot.is_contract_question for slot in spec.question_slots)
    independent_sources = len(source_groups(eligible_sources.values())) if has_contract_questions else len(all_sources)
    return CoverageSnapshot(
        slots=tuple(slot_results),
        new_evidence_count=len(new_ids),
        independent_source_count=independent_sources,
        target_years=target_years,
        selected_claim_count=len(selected_claim_ids),
        in_window_claim_count=len(in_window_claim_ids),
        in_window_source_count=len(in_window_source_ids),
        eligible_claim_ids=frozenset(eligible_claims),
    )


def _channel_request_keys(query: GeneratedQuery) -> tuple[SearchRequestKey, SearchRequestKey] | None:
    """Plan by channel when a collector has no provider-key resolver."""
    text = normalize_query(query.query)
    if not text:
        return None
    key = (query.target_channel, text, 0)
    return key, key


class AdaptiveRetrievalController:
    """Feedback controller that stops on quality, budget, or zero gain."""

    def __init__(
        self,
        spec: ResearchSpec,
        *,
        query_engine: QueryEngine | None = None,
        budget: RetrievalBudget | None = None,
        search_history: SearchRequestHistory | None = None,
        request_keys: Callable[[GeneratedQuery], tuple[SearchRequestKey, SearchRequestKey] | None] | None = None,
        source_credibility_check: Callable[[SourceDocument], bool] | None = None,
    ) -> None:
        self.spec = spec
        self.query_engine = query_engine or QueryEngine()
        self.budget = budget or RetrievalBudget(max_queries=spec.budget)
        self.search_history = search_history or SearchRequestHistory()
        self._request_keys = request_keys or _channel_request_keys
        self._source_credibility_check = source_credibility_check or _incoming_source_eligible

    def _reserve_queries(
        self, candidates: Iterable[GeneratedQuery], max_requests: int, *, one_per_slot: bool = False,
    ) -> tuple[GeneratedQuery, ...]:
        limit = min(max(0, max_requests), self.budget.remaining_queries)
        new_requests: set[SearchRequestKey] = set()
        selected_uses: set[tuple[SearchRequestKey, str]] = set()
        selected_slots: set[str] = set()
        selected: list[GeneratedQuery] = []
        for query in candidates:
            if one_per_slot and query.slot_id in selected_slots:
                continue
            keys = self._request_keys(query)
            if keys is None or not self.search_history.can_use(*keys, query.slot_id):
                continue
            request, route = keys
            use = (route, query.slot_id)
            if use in selected_uses:
                continue
            if request not in new_requests and request not in self.search_history.responses:
                if len(new_requests) >= limit:
                    continue
                new_requests.add(request)
            selected_uses.add(use)
            selected_slots.add(query.slot_id)
            # Retain each slot and route even when its backend request is shared.
            selected.append(query)
        self.budget.reserve_queries(len(new_requests))
        return tuple(selected)

    def initial_plan(self, *, max_queries: int | None = None) -> AdaptiveQueryPlan:
        limit = self.budget.remaining_queries if max_queries is None else max_queries
        initial = build_adaptive_query_plan(self.spec, self.query_engine, max_queries=None)
        return AdaptiveQueryPlan(self.spec, self._reserve_queries(initial.queries, limit))

    def next_round(
        self,
        packs: list[EvidencePack],
        *,
        round_number: int,
        previous_evidence_ids: set[str] | None = None,
        previous_new_evidence: int | None = None,
        max_queries: int = 4,
        allow_followup: bool = True,
    ) -> RetrievalDecision:
        coverage = assess_evidence_pack_coverage(
            self.spec,
            packs,
            previous_evidence_ids=previous_evidence_ids,
            source_credibility_check=self._source_credibility_check,
        )
        if coverage.quality_met:
            return RetrievalDecision(coverage, stop_reason=RetrievalStopReason.QUALITY_MET, usage=self._usage())
        if self.budget.remaining_fetches <= 0:
            return RetrievalDecision(coverage, stop_reason=RetrievalStopReason.BUDGET_EXHAUSTED, usage=self._usage())
        if any(slot.is_contract_question for slot in self.spec.question_slots):
            candidates = self.query_engine.generate_contract_queries(self.spec, slot_ids=coverage.missing_slot_ids)
            candidates.extend(self.query_engine.generate_contract_queries(
                self.spec, slot_ids=coverage.missing_slot_ids, supplemental=True,
            ))
            queries = self._reserve_queries(candidates, max_queries, one_per_slot=True) if allow_followup else ()
            reason = self._contract_stop_reason(candidates, allow_followup) if not queries else None
            return RetrievalDecision(coverage, queries=queries, stop_reason=reason, usage=self._usage())

        no_search_budget = self.budget.remaining_queries <= 0
        if round_number > 1 and previous_new_evidence == 0:
            reason = (
                RetrievalStopReason.BUDGET_EXHAUSTED if no_search_budget
                else RetrievalStopReason.ZERO_MARGINAL_EVIDENCE
            )
            return RetrievalDecision(coverage, stop_reason=reason, usage=self._usage())

        candidates = self.query_engine.generate_gap_queries(
            self.spec, list(coverage.missing_slot_ids), max_queries=None,
        )
        if coverage.period_gap:
            candidates = self.query_engine.generate_period_queries(
                self.spec.region_name, self.spec.research_focus, self.spec.target_years,
            ) + candidates
        queries = self._reserve_queries(candidates, max_queries)
        if not queries:
            reason = (
                RetrievalStopReason.BUDGET_EXHAUSTED if no_search_budget
                else RetrievalStopReason.NO_GAP_QUERY
            )
            return RetrievalDecision(coverage, stop_reason=reason, usage=self._usage())
        return RetrievalDecision(coverage, queries=queries, usage=self._usage())

    def _contract_stop_reason(
        self, candidates: list[GeneratedQuery], allow_followup: bool,
    ) -> RetrievalStopReason:
        if self.budget.remaining_queries <= 0:
            return RetrievalStopReason.BUDGET_EXHAUSTED
        routed = [(keys, query.slot_id) for query in candidates if (keys := self._request_keys(query)) is not None]
        if not routed:
            return RetrievalStopReason.SEARCH_SOURCE_UNAVAILABLE
        history = self.search_history
        if any(history.can_use(*keys, slot_id) for keys, slot_id in routed):
            return RetrievalStopReason.BUDGET_EXHAUSTED if allow_followup else RetrievalStopReason.MAX_ROUNDS
        responses = [history.responses[key] for (key, _), _ in routed if key in history.responses]
        if responses and not any(responses):
            if all(response is None for response in responses):
                return RetrievalStopReason.SEARCH_SOURCE_UNAVAILABLE
            return RetrievalStopReason.SEARCH_SOURCE_NO_RESULTS
        return RetrievalStopReason.STRATEGY_EXHAUSTED

    def record_fetches(self, count: int) -> int:
        return self.budget.record_fetches(count)

    def _usage(self) -> dict[str, int]:
        return {
            "search_queries": self.budget.used_queries,
            "fetched_documents": self.budget.used_fetches,
            "remaining_queries": self.budget.remaining_queries,
            "remaining_fetches": self.budget.remaining_fetches,
        }
