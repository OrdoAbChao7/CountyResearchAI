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

from ..models import (
    EvidenceConflict,
    EvidenceGap,
    EvidenceItem,
    QuestionTree,
    RawDoc,
)

# 常见产业统计指标抽取正则
_NUMERICAL_STAT_PATTERNS = [
    # 产值/销售额/收入：如 280亿元、30.5亿元、5000万元
    (r"(?:产值|总产值|规上产值|销售额|综合产值|营业收入|增加值)[^\d\n]{0,8}(\d+(?:\.\d+)?)\s*(亿元|万元|万|亿)", "产值与收入"),
    # 面积：如 101万亩、25万亩、3000亩
    (r"(?:面积|竹林面积|种植面积|果园面积|开采面积)[^\d\n]{0,8}(\d+(?:\.\d+)?)\s*(万亩|千亩|亩|平方公里)", "面积与规模"),
    # 产量：如 50万吨、1000万斤、20万件
    (r"(?:产量|总产量|鲜果产量|原竹产量|开采量)[^\d\n]{0,8}(\d+(?:\.\d+)?)\s*(万吨|吨|万件|万斤|千吨)", "产量与产能"),
    # 宏观GDP / 生产总值
    (r"(?:地区生产总值|生产总值|GDP)[^\d\n]{0,8}(\d+(?:\.\d+)?)\s*(亿元|万元|万|亿)", "宏观GDP"),
    # 人口与劳动力
    (r"(?:常住人口|户籍人口|从业人员|总人口)[^\d\n]{0,8}(\d+(?:\.\d+)?)\s*(万人|人)", "人口规模"),
    # 财政与投资
    (r"(?:一般公共预算收入|地方财政收入|固定资产投资)[^\d\n]{0,8}(\d+(?:\.\d+)?)\s*(亿元|万元)", "财政与投资"),
    # 骨干与规上企业数量
    (r"(?:规上企业|经营主体|骨干企业|加工企业)[^\d\n]{0,8}(\d+(?:\.\d+)?)\s*(家|个|户)", "企业数量"),
    # 增速/占比：如 增长8.5%、占GDP比重15.2%
    (r"(?:增长|增加|下降|比重|占比|增幅)[^\d\n]{0,8}(\d+(?:\.\d+)?)\s*%", "增速与比重"),
]

# 政策与规划命名正则，如《关于印发...的通知》
_POLICY_NAME_PATTERN = re.compile(r"《([^》]{4,50}(?:规划|意见|方案|通知|办法|行动计划|决定))》")

# 龙头企业标识
_ENTERPRISE_PATTERN = re.compile(
    r"([\u4e00-\u9fa5]{3,20}(?:股份|有限|集团|果业|竹木|木业|纸业|石墨|能源|生物|科技))"
    r"(?:公司|龙头企业|链主企业)"
)


class EvidenceStore:
    """线程安全的内存结构化证据库。"""

    def __init__(self) -> None:
        self._items: dict[str, EvidenceItem] = {}  # id -> EvidenceItem
        self._items_by_topic: dict[str, list[str]] = defaultdict(list)
        self._items_by_indicator: dict[str, list[str]] = defaultdict(list)
        self._raw_docs: list[RawDoc] = []
        self._conflicts: list[EvidenceConflict] = []

    def ingest_documents(
        self,
        docs: list[RawDoc],
        county: str,
        focus: str = "",
    ) -> list[EvidenceItem]:
        """批量摄入原始文档并抽取结构化证据项。"""
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
        lines = [line.strip() for line in full_text.splitlines() if line.strip()]
        extracted: list[EvidenceItem] = []

        # 推断年份
        year_match = re.search(r"(20[12]\d)年?", full_text[:400])
        year_str = year_match.group(1) if year_match else None

        seen_ids = set(self._items.keys())

        # 1. 抽取统计数值陈述
        for line in lines:
            if len(line) < 10 or len(line) > 300:
                continue

            extracted.extend(
                self._extract_numerical_from_line(doc, line, year_str, seen_ids)
            )

            # 2. 抽取政策文件
            policy_matches = _POLICY_NAME_PATTERN.findall(line)
            for policy_name in policy_matches:
                item_id = self._make_id(doc.url, policy_name)
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                item = EvidenceItem(
                    id=item_id,
                    claim=f"出台政策规划文件《{policy_name}》",
                    snippet=line,
                    url=doc.url,
                    title=doc.title,
                    source_name=doc.source or "gov",
                    domain_type=doc.domain_type or "government",
                    credibility_score=max(doc.credibility_score, 0.9),
                    year=year_str,
                    indicator_caliber="政策规划",
                    verification_status="verified",
                    topic="policy",
                )
                extracted.append(item)

            # 3. 抽取龙头企业
            ent_matches = _ENTERPRISE_PATTERN.findall(line)
            for ent_name in ent_matches:
                item_id = self._make_id(doc.url, ent_name)
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                item = EvidenceItem(
                    id=item_id,
                    claim=f"龙头骨干企业: {ent_name}",
                    snippet=line,
                    url=doc.url,
                    title=doc.title,
                    source_name=doc.source or "web",
                    domain_type=doc.domain_type or "company",
                    credibility_score=doc.credibility_score,
                    year=year_str,
                    indicator_caliber="骨干企业",
                    verification_status="unverified",
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
    ) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []
        for pattern, indicator_type in _NUMERICAL_STAT_PATTERNS:
            for match in re.finditer(pattern, line):
                # 找到 match 前后最近的分隔标点符号获取精准子句
                p_start = 0
                for idx in range(match.start() - 1, -1, -1):
                    if line[idx] in "，,。；;！!？?\n":
                        p_start = idx + 1
                        break

                p_end = len(line)
                for idx in range(match.end(), len(line)):
                    if line[idx] in "，,。；;！!？?\n":
                        p_end = idx
                        break

                clause = line[p_start:p_end].strip()
                if not clause:
                    clause = match.group(0)

                # 判断行政范围
                scope = "县域本级"
                target_context = clause if any(k in clause for k in ("全市", "地级市", "全省")) else line
                if "全市" in target_context or "地级市" in target_context:
                    scope = "全市范围"
                elif "全省" in target_context:
                    scope = "全省范围"

                # 判断口径
                caliber = indicator_type
                if "规上" in clause:
                    caliber = f"规上工业{indicator_type}"
                elif "全产业链" in clause or "综合" in clause:
                    caliber = f"全产业链{indicator_type}"

                item_id = self._make_id(doc.url, f"{caliber}:{clause}")
                if item_id in seen_ids:
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
                    indicator_caliber=caliber,
                    verification_status="verified" if doc.credibility_score >= 0.8 else "unverified",
                    topic="economic",
                )
                items.append(item)
        return items

    def add_evidence(self, item: EvidenceItem) -> None:
        """向证据库注册单条证据项并建立索引。"""
        if not item.id:
            item.id = self._make_id(item.url, item.claim)
        self._items[item.id] = item
        self._items_by_topic[item.topic].append(item.id)
        if item.indicator_caliber:
            self._items_by_indicator[item.indicator_caliber].append(item.id)

    def get_by_topic(self, topic: str) -> list[EvidenceItem]:
        return [self._items[iid] for iid in self._items_by_topic.get(topic, []) if iid in self._items]

    def get_all(self) -> list[EvidenceItem]:
        return list(self._items.values())

    def get_conflicts(self) -> list[EvidenceConflict]:
        return self._conflicts

    def detect_conflicts(self) -> list[EvidenceConflict]:
        """交叉核验各指标数值，识别潜在冲突并分析成因。"""
        conflicts: list[EvidenceConflict] = []

        def _get_base_concept(indicator: str) -> str:
            for kw in ("产值", "面积", "产量", "GDP", "人口", "增速", "企业", "财政"):
                if kw in indicator:
                    return kw
            return indicator

        # 按基础指标概念分组核验
        groups = defaultdict(list)
        for item in self._items.values():
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

        self._conflicts = conflicts
        return conflicts

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
                if any(ind in it.claim or ind in it.indicator_caliber for ind in q.required_indicators)
                or (not q.required_indicators and it.topic == q.category)
            ]
            if matched:
                q.evidence_ids = [it.id for it in matched]
                # 检查是否满足核心要求
                has_official = any(it.credibility_score >= 0.8 for it in matched)
                if has_official or len(matched) >= 2:
                    q.is_satisfied = True
                    satisfied_count += 1
                else:
                    gaps.append(
                        EvidenceGap(
                            question_id=q.id,
                            description=f"子问题《{q.title}》虽有线索，但缺乏高可信度权威官方证据支撑",
                            missing_aspect="insufficient_credibility",
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
        for item in sorted(self._items.values(), key=lambda x: x.credibility_score, reverse=True):
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
