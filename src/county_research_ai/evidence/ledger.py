"""Structured evidence ledger and adapters for the legacy research flow."""
from __future__ import annotations

import hashlib
import re

from ..domain.research_contracts import (
    AtomicClaim,
    EvidenceChunk,
    EvidencePack,
    QuestionSlot,
    SourceDocument,
)
from ..models import ProcessedData
from .claim_region import classify_claim_region
from .measure import derive_measure_key, infer_period
from .source_contract import serialize_source_documents
from .store import EvidenceStore


def _period_match(year_hints: list[str], period: str) -> str:
    years = [int(value) for value in re.findall(r"(?<!\d)(?:1\d{3}|20\d{2})(?!\d)", period)]
    if not years:
        return ""
    if re.search(r"before|prior|之前|以前|前", period, re.IGNORECASE):
        start, end = 1, max(years)
    elif re.search(r"至今|现在|present", period, re.IGNORECASE):
        start, end = min(years), 9999
    else:
        start, end = min(years), max(years)
    for hint in year_hints:
        try:
            year = int(hint)
        except ValueError:
            continue
        if start <= year <= end:
            return str(year)
    return ""


def _claim_region_allowed(claim: AtomicClaim, target_region: str) -> bool:
    """Keep target and unresolved claims; drop positively other-region claims.

    ``UNKNOWN`` stays visible so the verifier can explain why it was not used,
    but an explicit other province/city/county must not enter a target county's
    evidence pack or conclusions. Empty region ids keep legacy callers working.
    """
    region = (claim.region_id or "").strip()
    if not target_region or not region:
        return True
    return region == target_region or region.upper() == "UNKNOWN"


def _filter_unmatched_candidates(
    candidates: list[tuple[int, str, EvidenceChunk, str]],
) -> tuple[list[tuple[int, str, EvidenceChunk, str]], dict[str, str]]:
    relevant = [candidate for candidate in candidates if candidate[0] > 50]
    if not relevant:
        return candidates, {}

    period_by_source: dict[str, list[tuple[int, str, EvidenceChunk, str]]] = {}
    for score, chunk_id, chunk, reason in candidates:
        if score == 50:
            year = reason.removeprefix("period:")
            period_by_source.setdefault(chunk.document_id, []).append(
                (score, chunk_id, chunk, f"period_only:{year}")
            )
    period_context = []
    for source_candidates in period_by_source.values():
        period_context.extend(source_candidates[:1])
        if len(source_candidates) > 1:
            period_context.append(source_candidates[-1])
    selected_period_ids = {item[1] for item in period_context}
    excluded = {
        chunk_id: "unmatched_requirements" if score == 0 else "period_only_fallback"
        for score, chunk_id, _, _ in candidates
        if score <= 50 and chunk_id not in selected_period_ids
    }
    return relevant + period_context, excluded


class EvidenceLedger:
    """Mutable in-memory ledger with explicit source/chunk/claim relations."""

    def __init__(self) -> None:
        self.sources: dict[str, SourceDocument] = {}
        self.chunks: dict[str, EvidenceChunk] = {}
        self.claims: dict[str, AtomicClaim] = {}
        self._relations: dict[str, list[tuple[str, str]]] = {}

    def add_source(self, source: SourceDocument) -> None:
        existing = self.sources.get(source.doc_id)
        if existing is not None and existing.content_hash != source.content_hash:
            raise ValueError(f"source doc_id collision with different content: {source.doc_id}")
        self.sources[source.doc_id] = source
        for chunk in source.chunks:
            if chunk.source_id != source.doc_id:
                raise ValueError(f"chunk source mismatch: {chunk.chunk_id}")
            self.chunks[chunk.chunk_id] = chunk
        self._refresh_repost_relations(source)

    def add_claim(self, claim: AtomicClaim) -> None:
        if claim.claim_id in self.claims and self.claims[claim.claim_id] != claim:
            raise ValueError(f"claim id collision: {claim.claim_id}")
        if claim.verification_status == "verified" and not claim.evidence_chunk_ids:
            claim = claim.model_copy(
                update={
                    "verification_status": "unverified",
                    "verification_reason": "no_evidence_chunk",
                }
            )
        self.claims[claim.claim_id] = claim

    def set_verification_status(
        self, claim_id: str, status: str, *, reason: str = ""
    ) -> None:
        claim = self.claims.get(claim_id)
        if claim is None:
            raise KeyError(f"unknown claim: {claim_id}")
        if status == "verified" and not claim.evidence_chunk_ids:
            status = "unverified"
            reason = reason or "no_evidence_chunk"
        self.claims[claim_id] = claim.model_copy(
            update={"verification_status": status, "verification_reason": reason}
        )

    def source_relations(self, source_id: str) -> list[tuple[str, str]]:
        return list(self._relations.get(source_id, []))

    def chunks_for_claim(self, claim_id: str) -> list[EvidenceChunk]:
        claim = self.claims.get(claim_id)
        if claim is None:
            return []
        return [self.chunks[chunk_id] for chunk_id in claim.evidence_chunk_ids if chunk_id in self.chunks]

    def sources_for_claim(self, claim_id: str) -> list[SourceDocument]:
        claim = self.claims.get(claim_id)
        if claim is None:
            return []
        return [self.sources[source_id] for source_id in claim.source_ids if source_id in self.sources]

    def find_claims(
        self,
        *,
        metric: str = "",
        period: str = "",
        scope: str = "",
        version: str = "",
    ) -> list[AtomicClaim]:
        result = []
        for claim in self.claims.values():
            if metric and claim.metric_id != metric:
                continue
            if period and claim.period != period:
                continue
            if scope and claim.administrative_scope != scope:
                continue
            if version and claim.series_version != version:
                continue
            result.append(claim)
        return sorted(result, key=lambda item: item.claim_id)

    def find_equivalent_claims(self, claim: AtomicClaim) -> list[AtomicClaim]:
        """Find same-identity claims while allowing supported unit conversion."""
        matches = []
        normalized = claim.normalized_numeric_value()
        for candidate in self.claims.values():
            if candidate.claim_id == claim.claim_id:
                continue
            if (
                candidate.region_id,
                candidate.metric_id,
                candidate.period,
                candidate.administrative_scope,
                candidate.statistical_caliber,
                candidate.series_version,
            ) != (
                claim.region_id,
                claim.metric_id,
                claim.period,
                claim.administrative_scope,
                claim.statistical_caliber,
                claim.series_version,
            ):
                continue
            candidate_value = candidate.normalized_numeric_value()
            if normalized is not None and candidate_value is not None:
                if normalized == candidate_value:
                    matches.append(candidate)
            elif candidate.value == claim.value and candidate.unit == claim.unit:
                matches.append(candidate)
        return sorted(matches, key=lambda item: item.claim_id)

    def select_evidence_pack(self, slot: QuestionSlot) -> EvidencePack:
        target_region = (slot.region or "").strip()
        candidates: list[tuple[int, str, EvidenceChunk, str]] = []
        requested_years = set(
            re.findall(r"(?<!\d)(?:1\d{3}|20\d{2})(?!\d)", slot.research_question)
        )
        period_matches = {
            chunk.chunk_id: _period_match(chunk.year_hints, slot.time_period)
            for chunk in self.chunks.values()
        }
        has_period_matches = any(period_matches.values())
        period_excluded: list[str] = []
        claim_by_chunk: dict[str, list[AtomicClaim]] = {}
        for claim in self.claims.values():
            for chunk_id in claim.evidence_chunk_ids:
                claim_by_chunk.setdefault(chunk_id, []).append(claim)
        for chunk in self.chunks.values():
            if has_period_matches and chunk.year_hints and not period_matches[chunk.chunk_id]:
                period_excluded.append(chunk.chunk_id)
                continue
            linked_claims = claim_by_chunk.get(chunk.chunk_id, [])
            if (
                target_region
                and linked_claims
                and not any(
                    _claim_region_allowed(claim, target_region)
                    for claim in linked_claims
                )
            ):
                continue
            matched = [
                metric
                for metric in slot.required_metrics
                if metric in chunk.text or any(metric in claim.metric_id for claim in linked_claims)
            ]
            period_year = period_matches[chunk.chunk_id]
            matched_requested_years = sorted(requested_years.intersection(chunk.year_hints))
            score = (
                100 * len(matched)
                + 100 * len(matched_requested_years)
                + (50 if period_year else 0)
                + (10 if linked_claims else 0)
            )
            reasons = []
            if period_year:
                reasons.append(f"period:{period_year}")
            if matched_requested_years:
                reasons.append(f"requested_year:{','.join(matched_requested_years)}")
            if matched:
                reasons.append(f"required_metric:{','.join(matched)}")
            reason = ";".join(reasons) if reasons else "fallback"
            candidates.append((score, chunk.chunk_id, chunk, reason))
        candidates.sort(
            key=lambda item: (
                -item[0],
                item[2].document_id,
                item[2].start_offset if item[2].start_offset is not None else -1,
                item[1],
            )
        )

        candidates, unmatched_excluded = _filter_unmatched_candidates(candidates)

        # Break up same-source runs so a single long document cannot consume
        # the whole slot before another relevant source is considered.
        first_by_source: dict[str, tuple[int, str, EvidenceChunk, str]] = {}
        remaining = []
        for candidate in candidates:
            source_id = candidate[2].document_id
            if source_id not in first_by_source:
                first_by_source[source_id] = candidate
            else:
                remaining.append(candidate)
        candidates = sorted(
            first_by_source.values(), key=lambda item: (-item[0], item[1])
        ) + remaining

        selected: list[EvidenceChunk] = []
        omitted: list[str] = list(period_excluded)
        reasons: dict[str, str] = {}
        total_chars = 0
        for _, chunk_id, chunk, reason in candidates:
            chunk_chars = len(chunk.text)
            if total_chars + chunk_chars <= slot.budget_chars:
                selected.append(chunk)
                total_chars += chunk_chars
                reasons[chunk_id] = reason
            else:
                omitted.append(chunk_id)

        selected_ids = {chunk.chunk_id for chunk in selected}
        selected_claims = sorted(
            {
                claim.claim_id: claim
                for claim in self.claims.values()
                if selected_ids.intersection(claim.evidence_chunk_ids)
                and _claim_region_allowed(claim, target_region)
            }.values(),
            key=lambda item: item.claim_id,
        )
        selected_reasons = {
            chunk_id: reasons[chunk_id]
            for chunk_id in selected_ids
            if chunk_id in reasons
        }
        excluded_reasons = {
            chunk_id: "budget_exceeded"
            for chunk_id in omitted
        }
        excluded_reasons.update({chunk_id: "outside_requested_period" for chunk_id in period_excluded})
        excluded_reasons.update(unmatched_excluded)
        source_map = {
            chunk.source_id: self.sources[chunk.source_id]
            for chunk in selected
            if chunk.source_id in self.sources
        }
        missing = [
            metric
            for metric in slot.required_metrics
            if not any(
                metric in chunk.text or any(metric in claim.metric_id for claim in claim_by_chunk.get(chunk.chunk_id, []))
                for chunk in selected
            )
        ]
        status = "complete" if not missing and selected else ("partial" if selected else "empty")
        pack_key = f"{slot.slot_id}|{slot.budget_chars}|{','.join(chunk.chunk_id for chunk in selected)}"
        pack_id = hashlib.sha256(pack_key.encode("utf-8")).hexdigest()[:24]
        return EvidencePack(
            pack_id=pack_id,
            research_slot=slot,
            selected_chunks=selected,
            selected_claims=selected_claims,
            source_map=source_map,
            token_budget=slot.budget_chars,
            selected_evidence_reasons=selected_reasons,
            excluded_evidence_reasons=excluded_reasons,
            total_chars=total_chars,
            missing_requirements=missing,
            status=status,
        )

    def _refresh_repost_relations(self, source: SourceDocument) -> None:
        self._relations.setdefault(source.doc_id, [])
        for other_id, other in self.sources.items():
            if other_id == source.doc_id or not source.canonical_url:
                continue
            if other.canonical_url != source.canonical_url:
                continue
            relation = ("same_source_repost", other_id)
            reverse = ("same_source_repost", source.doc_id)
            if relation not in self._relations[source.doc_id]:
                self._relations[source.doc_id].append(relation)
            self._relations.setdefault(other_id, [])
            if reverse not in self._relations[other_id]:
                self._relations[other_id].append(reverse)


def build_evidence_ledger(processed: ProcessedData) -> EvidenceLedger:
    """Adapt legacy processed docs and extracted EvidenceItems into the ledger."""
    ledger = EvidenceLedger()
    source_records = serialize_source_documents(processed.docs)
    source_by_url: dict[str, SourceDocument] = {}
    for record in source_records:
        chunks = [
            EvidenceChunk(
                chunk_id=chunk["chunk_id"],
                document_id=record["doc_id"],
                text=chunk["text"],
                heading=chunk.get("heading", ""),
                start_offset=chunk.get("start_offset"),
                end_offset=chunk.get("end_offset"),
                offset_status="exact",
                year_hints=sorted(set(re.findall(r"(?<!\d)(?:1\d{3}|20\d{2})(?!\d)", chunk.get("text", "")))),
                content_hash=chunk.get("content_hash", ""),
            )
            for chunk in record.get("chunks", [])
        ]
        source = SourceDocument(
            doc_id=record["doc_id"],
            source_title=record.get("title", ""),
            canonical_url=record.get("canonical_url", ""),
            content=record.get("content", ""),
            content_hash=record.get("content_hash", ""),
            fetch_status=record.get("fetch_status", "unknown"),
            provider=record.get("provider", "unknown"),
            source_type=record.get("source_type", "unknown"),
            publish_date=record.get("published_at"),
            retrieved_at=record.get("retrieved_at"),
            metadata=record.get("metadata", {}),
            chunks=chunks,
        )
        ledger.add_source(source)
        source_by_url[source.url] = source

    store = EvidenceStore()
    items = store.ingest_documents(
        processed.docs,
        county=processed.county.name,
        focus=processed.focus,
    )
    for item in items:
        source = source_by_url.get(item.url)
        evidence_chunk_ids = []
        if source is not None:
            evidence_chunk_ids = [
                chunk.chunk_id
                for chunk in source.chunks
                if (item.snippet and item.snippet in chunk.text)
                or (item.claim and item.claim in chunk.text)
            ]
        value_match = re.search(r"(\d+(?:\.\d+)?)(\s*(?:亿元|万元|万人|亩|%))", item.claim)
        value = value_match.group(1) if value_match else ""
        unit = value_match.group(2).strip() if value_match else ""
        chunk_text = "\n".join(
            ledger.chunks[chunk_id].text
            for chunk_id in evidence_chunk_ids
            if chunk_id in ledger.chunks
        )
        if not chunk_text and source is not None:
            chunk_text = source.content
        period = item.year or infer_period(
            item.claim,
            chunk_text=chunk_text,
            value=value,
            title=source.source_title if source is not None else "",
            published_at=source.publish_date if source is not None else None,
            content_prefix=source.content if source is not None else "",
        )
        source_ids = [source.doc_id] if source is not None else []
        for repost_url in item.corroborating_sources:
            repost = source_by_url.get(repost_url)
            if repost is not None and repost.doc_id not in source_ids:
                source_ids.append(repost.doc_id)
        region = classify_claim_region(
            processed.county.name,
            title=source.source_title if source is not None else item.title,
            url=source.canonical_url if source is not None else item.url,
            statement=item.claim,
            quote=item.snippet or chunk_text,
            scope=item.administrative_scope,
        )
        claim = AtomicClaim(
            claim_id=item.id,
            statement=item.claim,
            region_id=region.region_id,
            region_source=region.source,
            metric_id=item.indicator_caliber or item.topic,
            measure_id=derive_measure_key(
                item.claim, chunk_text=chunk_text, value=value
            ),
            value=value,
            unit=unit,
            period=period,
            administrative_scope=item.administrative_scope,
            statistical_caliber=item.indicator_caliber,
            source_ids=source_ids,
            evidence_chunk_ids=evidence_chunk_ids,
            verification_status=(
                item.verification_status
                if evidence_chunk_ids
                else "unverified"
            ),
            verification_reason=("no_evidence_chunk" if not evidence_chunk_ids else ""),
        )
        ledger.add_claim(claim)
    return ledger
