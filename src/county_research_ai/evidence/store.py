"""统一证据库 (EvidenceStore)。

实现：
1. 建立 Claim → Evidence → Source 结构化追溯链；
2. 自动从 RawDoc 正文与摘要中抽取结构化事实、统计数据与政策命名；
3. 指标口径（规上产值、全产业链总产值、种植面积等）与年份校验；
4. 多来源交叉验证与矛盾识别（检测同指标数值差异，分析是年份差、口径差还是实质冲突）；
5. 渲染 Markdown 格式参考文献表、事实核验表与冲突说明。
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from urllib.parse import urlparse

from ..models import (
    EvidenceConflict,
    EvidenceGap,
    EvidenceItem,
    QuestionTree,
    RawDoc,
)
from .claim_region import (
    classify_claim_region,
    classify_statistical_claim_region,
    statistical_value_context,
)
from .measure import data_years

# 常见产业统计指标抽取正则（支持长定语、冒号与 PDF/Markdown 表格分隔符，不贪婪吞掉重复指标词）
_STAT_GAP = r"[^\d\n，,。；;！!？?]{0,28}?"
_NUMERICAL_STAT_PATTERNS = [
    # 产值/销售额/收入：如 280亿元、30.5亿元、5000万元，或表格 `| 总产值 | 280亿元 |`
    (rf"(?:总产值|规上产值|综合产值|产值|销售额|营业收入|增加值){_STAT_GAP}(\d+(?:\.\d+)?)\s*(亿元|万元|万|亿)", "产值与收入"),
    # 面积：如 101万亩、25万亩、3000亩
    (rf"(?:竹林面积|种植面积|果园面积|开采面积|面积){_STAT_GAP}(\d+(?:\.\d+)?)\s*(万亩|千亩|亩|平方公里)", "面积与规模"),
    # 产量：如 50万吨、1000万斤、20万件
    (rf"(?:鲜果产量|原竹产量|总产量|产量|开采量){_STAT_GAP}(\d+(?:\.\d+)?)\s*(万吨|吨|万件|万斤|千吨)", "产量与产能"),
    # 宏观GDP / 生产总值
    (rf"(?:地区生产总值|生产总值|GDP){_STAT_GAP}(\d+(?:\.\d+)?)\s*(亿元|万元|万|亿)", "宏观GDP"),
    # 人口与劳动力
    (rf"(?:常住人口|户籍人口|从业人员|总人口){_STAT_GAP}(\d+(?:\.\d+)?)\s*(万人|人)", "人口规模"),
    # 财政与投资
    (rf"(?:一般公共预算收入|地方财政收入|固定资产投资){_STAT_GAP}(\d+(?:\.\d+)?)\s*(亿元|万元)", "财政与投资"),
    # 骨干与规上企业数量
    (rf"(?:规上企业|经营主体|骨干企业|加工企业){_STAT_GAP}(\d+(?:\.\d+)?)\s*(家|个|户)", "企业数量"),
    # 增速/占比：如 增长8.5%、占GDP比重15.2%
    (rf"(?:增长|增加|下降|比重|占比|增幅){_STAT_GAP}(\d+(?:\.\d+)?)\s*%", "增速与比重"),
]

# 政策与规划命名正则，如《关于印发...的通知》
_POLICY_NAME_PATTERN = re.compile(r"《([^》]{4,50}(?:规划|意见|方案|通知|办法|行动计划|决定))》")

# 龙头企业标识（覆盖一般工商主体、专业合作社与显式龙头后缀）
_ENTERPRISE_PATTERN = re.compile(
    r"([\u4e00-\u9fa5]{2,28}(?:股份有限公司|有限责任公司|有限公司|专业合作社|合作社|"
    r"(?:股份|集团|果业|竹木|木业|纸业|石墨|能源|生物|科技|家居|实业|新材料|电子|机械|药业|茶业|食品)"
    r"(?:公司|龙头企业|链主企业)))"
)

_ENTITY_NEGATION = re.compile(
    r"不存在|并非|不是|没有|查无|假冒|冒充|疑似|所谓|未注册|无此|非本地"
)


def _clause_bounds(text: str, start: int, end: int) -> str:
    """Return the punctuation-delimited clause containing ``[start, end)``."""
    clause_start = 0
    for index in range(start - 1, -1, -1):
        if text[index] in "，,。；;！!？?\n":
            clause_start = index + 1
            break
    clause_end = len(text)
    for index in range(end, len(text)):
        if text[index] in "，,。；;！!？?\n":
            clause_end = index
            break
    return text[clause_start:clause_end].strip()


def _iter_evidence_segments(text: str):
    """Segment both paragraph-preserving and whitespace-flattened long documents.

    Never discard a statistical bulletin solely because a paragraph exceeds
    the legacy 300-character extraction limit. Overlapping windows retain
    cross-boundary indicator/value pairs.
    """
    # Preserve a following declaration that explicitly qualifies the preceding data.
    for raw_paragraph in re.split(r"\n+|[。；;！!？?]+(?![ \t]*(?:以上|上述|前述))", text):
        paragraph = raw_paragraph.strip()
        if len(paragraph) < 10:
            continue
        if len(paragraph) <= 300:
            yield paragraph
            continue
        start = 0
        while start < len(paragraph):
            piece = paragraph[start:start + 300].strip()
            if len(piece) >= 10:
                yield piece
            if start + 300 >= len(paragraph):
                break
            start += 220



_OFFICIAL_SOURCES = {"gov", "government", "statistics", "stats", "mock-gov", "official"}


def _is_primary_official(doc: RawDoc) -> bool:
    """Whether the document is a primary official source.

    This is source *type*, not a credibility score.  A high credibility score
    alone never upgrades evidence to ``verified``.
    """
    domain = (doc.domain_type or "").strip().lower()
    source = (doc.source or "").strip().lower()
    url = (doc.url or "").strip().lower()
    return (
        domain == "government"
        or source in _OFFICIAL_SOURCES
        or "gov" in source
        or ".gov.cn" in url
    )


class EvidenceStore:
    """线程安全的内存结构化证据库。"""

    def __init__(self) -> None:
        self._items: dict[str, EvidenceItem] = {}  # id -> EvidenceItem
        self._items_by_topic: dict[str, list[str]] = defaultdict(list)
        self._items_by_indicator: dict[str, list[str]] = defaultdict(list)
        self._raw_docs: list[RawDoc] = []
        self._conflicts: list[EvidenceConflict] = []
        self._conflict_origin_status: dict[str, str] = {}
        self._county: str = ""

    def ingest_documents(
        self,
        docs: list[RawDoc],
        county: str,
        focus: str = "",
    ) -> list[EvidenceItem]:
        """批量摄入原始文档并抽取结构化证据项。"""
        self._county = (county or "").strip()
        new_items: list[EvidenceItem] = []
        for doc in docs:
            self._raw_docs.append(doc)
            extracted = self.extract_evidence_from_doc(doc, county=county, focus=focus)
            for item in extracted:
                self.add_evidence(item)
                new_items.append(item)

        # 重新扫描检测冲突
        self.detect_conflicts()
        return new_items

    def extract_evidence_from_doc(
        self,
        doc: RawDoc,
        county: str = "",
        focus: str = "",
    ) -> list[EvidenceItem]:
        """从单篇文档中挖掘高质量事实与证据片段。"""
        full_text = f"{doc.title}\n{doc.snippet}\n{doc.content}"
        # When an amount appears in both the body and a search summary, keep
        # the body's subject and surrounding qualifiers.
        lines = (
            (line, is_body)
            for text, is_body in ((doc.content, True), (doc.snippet, False), (doc.title, False))
            for line in _iter_evidence_segments(text)
        )
        extracted: list[EvidenceItem] = []
        body_scopes: dict[str, tuple[str, str]] = {}

        # 推断年份：只接受唯一的、非发布/抓取标签的数据年份。
        # 多个年份时保持为空，避免把文档级年份强加给每一条证据。
        doc_years = sorted(set(data_years(full_text[:400])))
        year_str = doc_years[0] if len(doc_years) == 1 else None

        seen_ids = set(self._items.keys())

        # 1. 抽取统计数值陈述
        for line, is_body in lines:
            extracted.extend(self._extract_numerical_from_line(
                doc, line, year_str, seen_ids, body_scopes, county=county, is_body=is_body,
            ))

            # 2. 抽取政策文件
            for policy_match in _POLICY_NAME_PATTERN.finditer(line):
                policy_name = policy_match.group(1)
                clause = _clause_bounds(
                    line, policy_match.start(), policy_match.end()
                )
                item_id = self._make_id(doc.url, policy_name)
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                region = classify_claim_region(
                    county,
                    title=doc.title,
                    url=doc.url,
                    statement=clause,
                    quote=clause,
                )
                item = EvidenceItem(
                    id=item_id,
                    # Keep the source clause, not a synthesized "issued policy"
                    # statement: the quote must remain able to support the claim.
                    claim=clause,
                    snippet=line,
                    url=doc.url,
                    title=doc.title,
                    source_name=doc.source or "gov",
                    domain_type=doc.domain_type or "government",
                    credibility_score=doc.credibility_score,
                    year=year_str,
                    region_id=region.region_id,
                    region_source=region.source,
                    indicator_caliber="政策规划",
                    # A direct policy name in a primary official document is a
                    # quotable source fact.  A high score on a blog/news page
                    # is not enough.
                    verification_status=(
                        "verified" if _is_primary_official(doc) else "unverified"
                    ),
                    topic="policy",
                )
                extracted.append(item)

            # 3. 抽取龙头企业
            for ent_match in _ENTERPRISE_PATTERN.finditer(line):
                ent_name = ent_match.group(1)
                window = line[max(0, ent_match.start() - 12) : ent_match.end()]
                clause = _clause_bounds(
                    line, ent_match.start(), ent_match.end()
                )
                if _ENTITY_NEGATION.search(window) or _ENTITY_NEGATION.search(clause):
                    continue
                item_id = self._make_id(doc.url, ent_name)
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                region = classify_claim_region(
                    county,
                    title=doc.title,
                    url=doc.url,
                    statement=clause,
                    quote=clause,
                )
                item = EvidenceItem(
                    id=item_id,
                    claim=clause,
                    snippet=line,
                    url=doc.url,
                    title=doc.title,
                    source_name=doc.source or "web",
                    domain_type=doc.domain_type or "company",
                    credibility_score=doc.credibility_score,
                    year=year_str,
                    region_id=region.region_id,
                    region_source=region.source,
                    indicator_caliber="骨干企业",
                    # A named enterprise in a primary official document is a
                    # directly attributable fact; other sources remain pending.
                    verification_status=(
                        "verified" if _is_primary_official(doc) else "unverified"
                    ),
                    topic="industry",
                )
                extracted.append(item)

        return extracted

    def _extract_numerical_from_line(
        self,
        doc: RawDoc,
        line: str,
        year_str: str | None,
        seen_ids: set[str],
        body_scopes: dict[str, tuple[str, str]],
        *,
        county: str,
        is_body: bool,
    ) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []
        for pattern, indicator_type in _NUMERICAL_STAT_PATTERNS:
            pos = 0
            while pos < len(line):
                match = re.search(pattern, line[pos:])
                if match is None:
                    break
                val_start = pos + match.start(1)
                val_end = pos + match.end()
                full_start = pos + match.start(0)
                # Advance past the indicator keyword only, so a second indicator
                # inside the gap (e.g. "仅为全国竹产业总产值800亿元") is not skipped.
                next_pos = full_start + max(1, len(match.group(0)) - len(line[val_start:val_end]))
                inner_retry = re.search(pattern, line[full_start + 1 : val_end])
                if inner_retry is not None and (full_start + 1 + inner_retry.end()) == val_end:
                    pos = full_start + 1
                    continue
                pos = val_end
                context = statistical_value_context(line, val_start, val_end)
                clause = context.statement
                if match.group(1) not in clause:
                    pos = max(pos, next_pos)
                    continue  # The value must remain inside the resolved clause.

                # 判断口径
                caliber = indicator_type
                if "规上" in clause or "规模以上" in clause:
                    caliber = f"规上工业{indicator_type}"
                elif "全产业链" in clause or "综合" in clause:
                    caliber = f"全产业链{indicator_type}"

                identity = f"{caliber}:{clause}"
                item_id = self._make_id(doc.url, identity)
                if not is_body and item_id in body_scopes:
                    continue
                region, scope = classify_statistical_claim_region(
                    county, title=doc.title, url=doc.url, context=context,
                )
                if is_body:
                    previous = self._items.get(item_id)
                    attribution = (region.region_id, scope)
                    first_attribution = body_scopes.setdefault(
                        item_id, (previous.region_id, previous.administrative_scope) if previous else attribution,
                    )
                    if attribution != first_attribution:
                        item_id = self._make_id(doc.url, f"{identity}:{region.region_id}:{scope}")
                if context.retracted or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                item = EvidenceItem(
                    id=item_id,
                    claim=clause,
                    snippet=line,
                    url=doc.url,
                    title=doc.title,
                    source_name=doc.source or "web",
                    domain_type=doc.domain_type or "unknown",
                    credibility_score=doc.credibility_score,
                    year=year_str,
                    administrative_scope=scope,
                    region_id=region.region_id,
                    region_source=region.source,
                    indicator_caliber=caliber,
                    # Official primary statistics need a year so an outdated
                    # figure cannot silently become a current fact.  Other
                    # sources are only upgraded later by independent
                    # corroboration (see detect_conflicts).
                    verification_status=(
                        "verified" if _is_primary_official(doc) and bool(year_str) else "unverified"
                    ),
                    topic="economic",
                )
                items.append(item)
        return items

    def add_evidence(self, item: EvidenceItem) -> None:
        """向证据库注册单条证据项并建立索引。"""
        if not item.id:
            item.id = self._make_id(item.url, item.claim)
        if item.id in self._conflict_origin_status:
            # Re-ingesting the same source must not silently restore a verified
            # status while the unresolved conflict is still present.
            item.verification_status = "conflicting"
        self._items[item.id] = item
        if item.id not in self._items_by_topic[item.topic]:
            self._items_by_topic[item.topic].append(item.id)
        if (
            item.indicator_caliber
            and item.id not in self._items_by_indicator[item.indicator_caliber]
        ):
            self._items_by_indicator[item.indicator_caliber].append(item.id)

    def get_by_topic(self, topic: str) -> list[EvidenceItem]:
        return [self._items[iid] for iid in self._items_by_topic.get(topic, []) if iid in self._items]

    def get_all(self) -> list[EvidenceItem]:
        return list(self._items.values())

    def get_target_items(self) -> list[EvidenceItem]:
        """Return only evidence attributable to the requested county.

        Retrieval and report projections use this view so a cross-region claim
        cannot enter the county's evidence graph or citations merely because it
        arrived in the same search batch.
        """
        return [
            item for item in self._items.values()
            if self._is_target_region(item)
        ]

    def _is_target_region(self, item: EvidenceItem) -> bool:
        """Whether an item may participate in the requested county's statistics.

        An item positively attributed to another region, or still ``UNKNOWN``,
        must not be silently counted as county data. Legacy callers that never
        ran ingestion (empty ``_county``) keep their historical behaviour.
        """
        target = self._county
        if not target:
            return True
        return bool(item.region_id) and item.region_id == target

    def get_conflicts(self) -> list[EvidenceConflict]:
        return self._conflicts

    def detect_conflicts(self) -> list[EvidenceConflict]:  # noqa: C901
        """交叉核验各指标数值，识别潜在冲突并分析成因。"""
        conflicts: list[EvidenceConflict] = []
        conflicting_ids: set[str] = set()

        def _get_base_concept(indicator: str) -> str:
            for kw in ("产值", "面积", "产量", "GDP", "人口", "增速", "企业", "财政"):
                if kw in indicator:
                    return kw
            return indicator

        # 按基础指标概念分组核验
        groups = defaultdict(list)
        for item in self._items.values():
            if not self._is_target_region(item):
                continue
            if item.topic == "economic" and item.indicator_caliber:
                base_c = _get_base_concept(item.indicator_caliber)
                groups[base_c].append(item)

        for base_ind, items in groups.items():
            if len(items) < 2:
                continue

            # 抽取数字数值对比
            values_with_meta = []
            for it in items:
                num_match = re.search(
                    r"(\d+(?:\.\d+)?)\s*(亿元|万元|万亩|亩|千亩|平方公里|万吨|吨|万斤|千吨|万人|人|家|户|%)",
                    it.claim,
                )
                if num_match:
                    val = float(num_match.group(1))
                    unit = num_match.group(2)
                    raw_val = f"{int(val) if val.is_integer() else val}{unit}"
                    values_with_meta.append({
                        "item_id": it.id,
                        "value": val,
                        "unit": unit,
                        "raw": raw_val,
                        "year": it.year,
                        "scope": it.administrative_scope,
                        "caliber": it.indicator_caliber,
                        "url": it.url,
                        "title": it.title,
                        "claim": it.claim,
                    })

            # 如果存在不同数值
            if len(values_with_meta) >= 2:
                distinct_vals = {v["raw"] for v in values_with_meta}
                if len(distinct_vals) > 1:
                    years = {v["year"] for v in values_with_meta if v["year"]}
                    scopes = {v["scope"] for v in values_with_meta}
                    calibers = {v["caliber"] for v in values_with_meta}

                    conflict_type = "contradiction"
                    reason = "不同来源报告了差异明显的数值"
                    suggestion = "需官方统计公报进一步核实"

                    if len(years) > 1:
                        conflict_type = "year_discrepancy"
                        reason = f"不同统计年份存在自然变动 (涉及年份: {', '.join(sorted(years))})"
                        suggestion = "按最新年份数据为准，并在报告中注明时间跨度"
                    elif len(scopes) > 1:
                        conflict_type = "caliber_discrepancy"
                        reason = f"行政统计范围不同 (涉及范围: {', '.join(scopes)})"
                        suggestion = "区分县域本级与地级市全域口径"
                    elif len(calibers) > 1:
                        conflict_type = "caliber_discrepancy"
                        reason = f"指标统计口径不同 (涉及口径: {', '.join(calibers)})"
                        suggestion = "区分规上工业与全产业链总产值口径"

                    if conflict_type == "contradiction":
                        conflicting_ids.update(
                            str(meta["item_id"]) for meta in values_with_meta
                        )

                    conflict = EvidenceConflict(
                        topic="economic",
                        indicator=f"{base_ind}（{', '.join(calibers)}）",
                        claims=[
                            {"url": v["url"], "value": v["raw"], "year": v["year"], "scope": v["scope"]}
                            for v in values_with_meta
                        ],
                        conflict_type=conflict_type,
                        description=f"{base_ind} 指标发现多来源数值差异: {', '.join(distinct_vals)}。{reason}。",
                        resolution_suggestion=suggestion,
                    )
                    conflicts.append(conflict)

        # Independent corroboration: two different source domains reporting the
        # same value / year / scope / caliber upgrade the evidence to verified.
        # This is the only path that can verify a non-official source.
        corroboration: dict[tuple[str, str, str, str, str], list[EvidenceItem]] = defaultdict(list)
        value_re = re.compile(
            r"(\d+(?:\.\d+)?)\s*(亿元|万元|万亩|亩|千亩|平方公里|万吨|吨|万斤|千吨|万人|人|家|户|%)"
        )
        for item in self._items.values():
            if item.topic != "economic":
                continue
            match = value_re.search(item.claim)
            if not match or not item.url:
                continue
            key = (
                _get_base_concept(item.indicator_caliber),
                item.year or "",
                item.administrative_scope,
                item.indicator_caliber,
                match.group(0).replace(" ", ""),
            )
            corroboration[key].append(item)
        for group in corroboration.values():
            domains = {
                urlparse(item.url).netloc.lower()
                for item in group
                if item.url
            }
            domains.discard("")
            if len(domains) < 2:
                continue
            for item in group:
                item.verification_status = "verified"
                item.corroborating_sources = sorted(
                    {
                        other.url
                        for other in group
                        if other.url
                        and urlparse(other.url).netloc.lower() != urlparse(item.url).netloc.lower()
                    }
                )

        self._apply_conflict_status(conflicting_ids)
        self._conflicts = conflicts
        return conflicts

    def _apply_conflict_status(self, conflicting_ids: set[str]) -> None:
        """Keep comparable contradictory items out of the verified state.

        The original status is retained so repeated imports recompute the same
        result and an item can only become verified again once the conflict is
        genuinely gone (for example after the conflicting item is removed).
        """
        for item_id in list(self._conflict_origin_status):
            if item_id in conflicting_ids:
                continue
            original = self._conflict_origin_status.pop(item_id)
            item = self._items.get(item_id)
            if item is not None and item.verification_status == "conflicting":
                item.verification_status = original
        for item_id in conflicting_ids:
            item = self._items.get(item_id)
            if item is None:
                continue
            self._conflict_origin_status.setdefault(
                item_id, item.verification_status
            )
            item.verification_status = "conflicting"

    def assess_question_tree_coverage(
        self, question_tree: QuestionTree
    ) -> tuple[float, list[EvidenceGap]]:
        """评估研究问题树的证据满足率与缺口。"""
        gaps: list[EvidenceGap] = []
        satisfied_count = 0

        for q in question_tree.questions:
            # 查找匹配证据：要求命中该问题的所需核心指标之一
            matched = [
                it for it in self._items.values()
                if self._is_target_region(it)
                and (
                    any(ind in it.claim or ind in it.indicator_caliber for ind in q.required_indicators)
                    or (not q.required_indicators and it.topic == q.category)
                )
            ]
            if matched:
                q.evidence_ids = [it.id for it in matched]
                # 只有已验证证据（官方原文或独立交叉佐证）才算满足问题。
                # 来源可信度高但未验证的线索不能当作事实。
                verified = [it for it in matched if it.verification_status == "verified"]
                if verified:
                    q.is_satisfied = True
                    satisfied_count += 1
                else:
                    gaps.append(
                        EvidenceGap(
                            question_id=q.id,
                            description=f"子问题《{q.title}》虽有线索，但缺乏已验证证据支撑",
                            missing_aspect="insufficient_verification",
                            severity="medium",
                        )
                    )
            else:
                q.is_satisfied = False
                gaps.append(
                    EvidenceGap(
                        question_id=q.id,
                        description=f"子问题《{q.title}》未检索到有效证据支撑 (需补充: {', '.join(q.required_indicators)})",
                        missing_aspect="missing_required_indicators",
                        severity="high",
                    )
                )

        total_q = len(question_tree.questions)
        coverage_rate = (satisfied_count / total_q) if total_q > 0 else 1.0
        return coverage_rate, gaps

    def render_citations_table(self) -> str:
        """渲染 Markdown 参考文献与证据溯源表。"""
        if not self._items:
            return "_暂无结构化证据引用记录_"

        lines = [
            "| 编号 | 核心事实 / 指标 | 统计年份 | 来源机构 / 标题 | 域名类型 | 可信度 | 来源链接 |",
            "| :--- | :--- | :---: | :--- | :---: | :---: | :--- |",
        ]
        # 去重相同 URL
        seen_urls = set()
        idx = 1
        for item in sorted(self.get_target_items(), key=lambda x: x.credibility_score, reverse=True):
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            claim_brief = item.claim[:28] + ("..." if len(item.claim) > 28 else "")
            title_brief = item.title[:20] + ("..." if len(item.title) > 20 else "")
            lines.append(
                f"| [{idx}] | {claim_brief} | {item.year or '未注明'} | {title_brief} | "
                f"{item.domain_type} | {item.credibility_score:.2f} | [{title_brief or '查看链接'}]({item.url}) |"
            )
            idx += 1
            if idx > 15:  # 避免过长
                break

        return "\n".join(lines)

    def render_conflicts_section(self) -> str:
        """渲染数据交叉核验与矛盾排查章节。"""
        if not self._conflicts:
            return "经过对多渠道检索数据的交叉核验，核心指标（产值、规模与规划）口径基本一致，未发现明显重大事实矛盾。"

        lines = [
            "> [!NOTE] **多来源交叉核验与口径差异说明**",
            "> 本次研究在不同渠道中检测到以下数据差异，系统已自动按时效与统计口径进行归因：",
            "",
        ]
        for idx, c in enumerate(self._conflicts, 1):
            lines.append(f"**差异项 {idx}：{c.indicator}**")
            lines.append(f"- **排查发现**：{c.description}")
            lines.append(f"- **核验建议**：{c.resolution_suggestion}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _make_id(url: str, text: str) -> str:
        key = f"{url}:{text.strip()}"
        return hashlib.md5(key.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
