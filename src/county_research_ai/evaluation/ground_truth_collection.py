"""Pure validation helpers for real continuation Ground Truth collection."""
from __future__ import annotations

import hashlib
import html
import json
import re
from typing import Any

from .ground_truth import GroundTruthClaim


def build_query_plan(
    *,
    region_id: str,
    region: str,
    province: str,
    mode: str,
) -> list[dict[str, str]]:
    """Create two task-matched searches with intentionally different contexts."""
    if mode == "snapshot":
        queries = (
            (
                "official_bulletin",
                f"{province}{region} 2024 国民经济和社会发展统计公报 GDP 工业 农业 产业 官方",
            ),
            (
                "official_yearbook",
                f"{province}{region} 2024年1-12月 主要经济指标 统计局 官方表格",
            ),
        )
    elif mode == "rise-fall":
        queries = (
            (
                "historical_statistics",
                f"{province}{region} 2024年 国民经济和社会发展统计公报 统计局 官方",
            ),
            (
                "official_comparison",
                f"{province}{region} 2024 GDP 工业 投资 居民收入 主要经济指标 统计局 官方表格",
            ),
        )
    elif mode == "long-history":
        queries = (
            (
                "local_history",
                f"{province}{region} 资源型产业体系 2000 2006 2007 资源转型 工业 官方",
            ),
            (
                "industrial_history",
                f"{province}{region} 2000 2006 2007 工业 产业结构 政府工作报告 官方",
            ),
        )
    else:
        raise ValueError(f"unsupported Ground Truth research mode: {mode}")
    return [
        {
            "context_id": f"{region_id}_{mode}_{suffix}",
            "query": query,
            "region": region,
            "province": province,
            "mode": mode,
        }
        for suffix, query in queries
    ]


def parse_extraction_response(content: str) -> dict[str, Any]:
    """Parse a JSON object returned by the extraction LLM."""
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        start = text.find("{")
        if start < 0:
            raise ValueError("LLM extraction response has no JSON object") from None
        try:
            value, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError as exc:
            raise ValueError("LLM extraction response is not valid JSON") from exc
    if not isinstance(value, dict) or not isinstance(value.get("claims"), list):
        raise ValueError("LLM extraction response must contain a claims list")
    return value


def claims_from_extraction(
    extraction: dict[str, Any],
    *,
    region: str,
    mode: str,
    evidence: dict[str, dict[str, Any]],
    known_contexts: set[str],
) -> list[GroundTruthClaim]:
    """Convert only source-supported LLM rows into rich Ground Truth claims."""
    rows = extraction.get("claims")
    if not isinstance(rows, list) or not rows:
        raise ValueError("LLM extraction returned no claims")
    claims: list[GroundTruthClaim] = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"claim row {index} is not an object")
        required = (
            "claim",
            "metric",
            "unit",
            "expected_answer",
            "metric_year",
            "administrative_scope",
            "source_title",
            "source_date",
            "primary_context_id",
            "primary_url",
            "evidence_excerpt",
            "verification_urls",
            "verification_evidence",
            "verification_context_ids",
            "confidence",
        )
        missing = [field for field in required if not str(row.get(field, "")).strip()]
        if missing:
            raise ValueError(f"claim row {index} missing fields: {', '.join(missing)}")
        primary_url = str(row["primary_url"]).strip()
        verification_urls = _string_list(row["verification_urls"], "verification_urls")
        source_urls = _unique([primary_url, *verification_urls])
        if len(source_urls) < 2:
            raise ValueError(f"claim row {index} requires two distinct source URLs")
        for url in source_urls:
            if url not in evidence:
                raise ValueError(f"claim row {index} cites source not in evidence: {url}")

        primary_context = str(row["primary_context_id"]).strip()
        declared_verification_contexts = _string_list(
            row["verification_context_ids"], "verification_context_ids"
        )
        primary_contexts = _contexts_for_url(primary_url, evidence)
        observed_verification_contexts = _contexts_for_urls(verification_urls, evidence)
        verification_contexts = observed_verification_contexts or set(
            declared_verification_contexts
        )
        contexts = _contexts_from_evidence(
            primary_url=primary_url,
            verification_urls=verification_urls,
            evidence=evidence,
            fallback=[primary_context, *verification_contexts],
        )
        primary_contexts = primary_contexts or {primary_context}
        if (
            len(contexts) < 2
            or any(context not in known_contexts for context in contexts)
            or len(primary_contexts | verification_contexts) < 2
        ):
            raise ValueError(
                f"claim row {index} requires sources from two known verification contexts"
            )

        primary_excerpt = str(row["evidence_excerpt"]).strip()
        if not _contains_verbatim(primary_excerpt, str(evidence[primary_url].get("text", ""))):
            raise ValueError(f"claim row {index} primary evidence is not verbatim")
        verification_evidence = row["verification_evidence"]
        if not isinstance(verification_evidence, list):
            raise ValueError(f"claim row {index} verification_evidence must be a list")
        verification_excerpt_by_url: dict[str, str] = {}
        for item in verification_evidence:
            if not isinstance(item, dict):
                raise ValueError(f"claim row {index} has invalid verification evidence")
            url = str(item.get("url", "")).strip()
            excerpt = str(item.get("excerpt", "")).strip()
            if url and excerpt:
                verification_excerpt_by_url[url] = excerpt
        repaired_verification_excerpts: list[str] = []
        for url in verification_urls:
            excerpt = verification_excerpt_by_url.get(url, "")
            repaired = _repair_verification_excerpt(
                excerpt,
                source_text=str(evidence[url].get("text", "")),
                claim_text=str(row["claim"]),
            )
            if not repaired:
                raise ValueError(
                    f"claim row {index} verification evidence is not verbatim: {url}"
                )
            repaired_verification_excerpts.append(repaired)

        confidence = str(row["confidence"]).strip().lower()
        if confidence not in {"high", "medium"}:
            raise ValueError(f"claim row {index} has unsupported confidence: {confidence}")
        claim_key = hashlib.sha1(
            f"{region}|{mode}|{index}|{row['claim']}".encode()
        ).hexdigest()[:12]
        claims.append(
            GroundTruthClaim(
                claim_id=f"continuation_{claim_key}",
                claim=str(row["claim"]).strip(),
                source=str(row["source_title"]).strip(),
                url=primary_url,
                date=str(row["source_date"]).strip(),
                region=region,
                metric=str(row["metric"]).strip(),
                unit=str(row["unit"]).strip(),
                evidence_excerpt=primary_excerpt,
                confidence=confidence,
                verification_status="VERIFIED",
                verification_sources=tuple(source_urls),
                verification_contexts=tuple(contexts),
                verification_excerpts=tuple(
                    [primary_excerpt, *repaired_verification_excerpts]
                ),
                research_mode=mode,
                expected_answer=str(row["expected_answer"]).strip(),
                source_title=str(row["source_title"]).strip(),
                source_date=str(row["source_date"]).strip(),
                metric_year=str(row["metric_year"]).strip(),
                administrative_scope=str(row["administrative_scope"]).strip(),
            )
        )
    return claims


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    values = [str(item).strip() for item in value if str(item).strip()]
    if not values:
        raise ValueError(f"{field} must not be empty")
    return values


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _contexts_from_evidence(
    *,
    primary_url: str,
    verification_urls: list[str],
    evidence: dict[str, dict[str, Any]],
    fallback: list[str],
) -> list[str]:
    inferred: list[str] = []
    for url in [primary_url, *verification_urls]:
        values = evidence.get(url, {}).get("context_ids", [])
        if isinstance(values, list):
            inferred.extend(str(value).strip() for value in values if str(value).strip())
    inferred = _unique(inferred)
    if len(inferred) >= 2:
        return inferred
    return _unique(fallback)


def _contexts_for_url(url: str, evidence: dict[str, dict[str, Any]]) -> set[str]:
    values = evidence.get(url, {}).get("context_ids", [])
    if not isinstance(values, list):
        return set()
    return {str(value).strip() for value in values if str(value).strip()}


def _contexts_for_urls(urls: list[str], evidence: dict[str, dict[str, Any]]) -> set[str]:
    contexts: set[str] = set()
    for url in urls:
        contexts.update(_contexts_for_url(url, evidence))
    return contexts


def _contains_verbatim(excerpt: str, text: str) -> bool:
    needle = _compact(excerpt)
    haystack = _compact(text)
    return bool(needle) and needle in haystack


def _repair_verification_excerpt(
    excerpt: str,
    *,
    source_text: str,
    claim_text: str,
) -> str | None:
    """Return an exact source window when a table citation added irrelevant cells."""
    if not excerpt:
        return None
    if _contains_verbatim(excerpt, source_text):
        return excerpt
    numeric_tokens = re.findall(r"\d+\.\d+", _compact(excerpt))
    if not numeric_tokens:
        numeric_tokens = re.findall(r"\d+\.\d+", _compact(claim_text))
    if not numeric_tokens:
        return None
    lines = source_text.splitlines()
    for index, line in enumerate(lines):
        if not any(token in _compact(line) for token in numeric_tokens):
            continue
        start = max(0, index - 1)
        end = min(len(lines), index + 4)
        candidate = "\n".join(lines[start:end]).strip()
        if all(token in _compact(candidate) for token in numeric_tokens):
            return candidate
    return None


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", html.unescape(value).replace("\\", ""))
