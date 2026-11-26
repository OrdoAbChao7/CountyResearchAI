"""Named-enterprise leads for an enterprise-qualification question.

A lead is a display aid. It never feeds verification: naming a company, or reporting
what it does, is not evidence that the company holds the qualification being asked about.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, Field

from ..domain.company_names import company_names
from ..domain.question_targets import QuestionTarget
from ..domain.research_contracts import AtomicClaim
from ..evidence.graph import EvidenceGraphStore
from ..search.region_relevance import county_name_terms

LeadTier = Literal["named_lead", "operating_activity", "formal_qualification"]
QualificationStatus = Literal["insufficient_qualification_evidence", "formal_qualification_verified"]

_ALIAS_PREFIX = re.compile(r"^(?:浙江省|浙江|湖州市|安吉县|安吉)+")
_OPERATING = re.compile(r"生产|车间|生产线|研发|投产|量产|改造|升级|出口|产能|订单|制造|加工|数字化|设备")
_QUALIFICATION_WORDS = re.compile(r"龙头|链主|领军|头部")
_QUALIFICATION_SUFFIX = re.compile(r"(?:龙头|骨干|链主|领军|重点)企业$")
_TIER_RANK = {"named_lead": 0, "operating_activity": 1, "formal_qualification": 2}
_UNRESOLVED_REGIONS = {"", "UNKNOWN", "全国"}


class EnterpriseLeadCase(BaseModel):
    claim_id: str
    statement: str
    region: str = ""
    period: str = ""
    snapshot_id: str = ""
    span_id: str = ""
    title: str = ""
    url: str = ""


class EnterpriseLead(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    tier: LeadTier
    qualification_status: QualificationStatus = "insufficient_qualification_evidence"
    # "confirmed": a case Claim is attributed to the target region. "unconfirmed": the
    # stored attribution is unresolved or national while the quoted text names the region.
    region_status: Literal["confirmed", "unconfirmed"] = "unconfirmed"
    qualification_mentioned: bool = False
    cases: list[EnterpriseLeadCase] = Field(default_factory=list)


def _alias_key(name: str) -> str:
    return _ALIAS_PREFIX.sub("", name)


def _industry_term(target: QuestionTarget) -> str:
    stem = _QUALIFICATION_SUFFIX.sub("", target.label)
    return stem.removesuffix("产业")


def collect_enterprise_leads(
    target: QuestionTarget,
    graph: EvidenceGraphStore,
    claims: Iterable[AtomicClaim],
    *,
    run_id: str,
    supported_claim_ids: set[str],
) -> list[EnterpriseLead]:
    region = target.region.clean_name
    _, short_region = county_name_terms(region)
    industry = _industry_term(target)
    grouped: dict[str, dict[str, object]] = {}
    for claim in claims:
        names = company_names(claim.statement)
        if not names:
            continue
        stored_region = (claim.region_id or "").strip()
        confirmed = stored_region == region
        if not confirmed and stored_region not in _UNRESOLVED_REGIONS:
            continue  # Positively attributed to another place.
        try:
            chain = graph.get_chain(claim.claim_id, run_id=run_id) if run_id else None
        except KeyError:
            continue
        link = next(graph.intact_links(chain), None) if chain is not None else None
        quote = link.span.quote if link is not None else ""
        context = f"{claim.statement}\n{quote}"
        if industry and industry not in context:
            continue
        if not confirmed and short_region not in quote:
            continue  # An unresolved attribution needs the region in the quoted text.
        case = EnterpriseLeadCase(
            claim_id=claim.claim_id, statement=claim.statement, region=stored_region, period=claim.period,
            snapshot_id=link.snapshot.snapshot_id if link else "", span_id=link.span.span_id if link else "",
            title=link.snapshot.title if link else "", url=link.snapshot.canonical_url if link else "",
        )
        if claim.claim_id in supported_claim_ids:
            tier = "formal_qualification"
        elif _OPERATING.search(claim.statement):
            tier = "operating_activity"
        else:
            tier = "named_lead"
        for name in names:
            entry = grouped.setdefault(_alias_key(name), {
                "names": set(), "tier": "named_lead", "confirmed": False, "mentioned": False, "cases": {},
            })
            entry["names"].add(name)  # type: ignore[attr-defined]
            entry["confirmed"] = bool(entry["confirmed"]) or confirmed
            entry["mentioned"] = bool(entry["mentioned"]) or bool(_QUALIFICATION_WORDS.search(claim.statement))
            if _TIER_RANK[tier] > _TIER_RANK[str(entry["tier"])]:
                entry["tier"] = tier
            entry["cases"].setdefault(claim.claim_id, case)  # type: ignore[attr-defined]
    leads = []
    for entry in grouped.values():
        variants = sorted(entry["names"], key=lambda item: (-len(item), item))  # type: ignore[call-overload]
        tier = str(entry["tier"])
        leads.append(EnterpriseLead(
            name=variants[0], aliases=variants[1:], tier=tier,  # type: ignore[arg-type]
            qualification_status=(
                "formal_qualification_verified" if tier == "formal_qualification"
                else "insufficient_qualification_evidence"
            ),
            region_status="confirmed" if entry["confirmed"] else "unconfirmed",
            qualification_mentioned=bool(entry["mentioned"]),
            cases=sorted(entry["cases"].values(), key=lambda item: item.claim_id),  # type: ignore[attr-defined]
        ))
    return sorted(leads, key=lambda lead: (-_TIER_RANK[lead.tier], lead.name))
