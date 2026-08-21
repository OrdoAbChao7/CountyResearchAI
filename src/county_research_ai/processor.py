"""数据处理模块。

负责将采集层的 RawDoc 列表转化为面向 LLM 的 ProcessedData 证据包。
核心职责:去重 → 清洗 → 截断 → 排序 → 筛选 → 打包。

设计原则:DocumentProcessor 是纯内存处理器,不直接调用 Storage。
Pipeline 负责在 process() 调用前后处理缓存与落盘。
"""
from __future__ import annotations

import hashlib
import logging
import re
from difflib import SequenceMatcher

from .config import QualityConfig
from .models import CountyInfo, ProcessedData, RawDoc

logger = logging.getLogger(__name__)

# ---- 来源类型权重表(用于排序,权重越高越靠前) ----
_SOURCE_WEIGHTS: dict[str, float] = {
    "government": 3.0,
    "research": 2.5,
    "news": 2.0,
    "company": 1.5,
    "social": 1.0,
    "unknown": 0.5,
}

# ---- HTML 标签清理正则 ----
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


class DocumentProcessor:
    """数据处理层:原始文档 → 处理后证据包。

    Usage:
        processor = DocumentProcessor(quality_config=settings.quality)
        processed = processor.process(raw_docs, county=county_info, focus="竹产业")
    """

    def __init__(self, quality_config: QualityConfig | None = None) -> None:
        self._quality = quality_config or QualityConfig()

    def process(
        self,
        raw_docs: list[RawDoc],
        *,
        county: CountyInfo,
        focus: str,
    ) -> ProcessedData:
        """完整处理流程:去重 → 清洗 → 排序 → 筛选 → 打包。

        Args:
            raw_docs: 采集层产出的原始文档列表
            county: 县域信息
            focus: 研究方向

        Returns:
            处理后的 ProcessedData(含去重、清洗、排序后的文档列表)
        """
        if not raw_docs:
            logger.warning("DocumentProcessor.process: 输入文档为空")
            return ProcessedData(county=county, focus=focus)

        # 1. 多维去重
        docs = self.deduplicate(raw_docs)
        logger.info("去重: %d → %d 文档", len(raw_docs), len(docs))

        # 2. 内容清洗
        docs = [self.clean(doc) for doc in docs]

        # 3. 质量筛选
        docs = self.filter_by_quality(docs)
        if not docs:
            logger.warning("质量筛选后无有效文档,返回空 ProcessedData")
            return ProcessedData(county=county, focus=focus)

        # 4. 来源排序
        docs = self.rank_by_source(docs)

        # 5. 构造证据包
        return self.build_evidence_pack(docs, county=county, focus=focus)

    # ---- 各子步骤 ----

    def deduplicate(self, docs: list[RawDoc]) -> list[RawDoc]:
        """多维去重:URL 精确去重 + 标题相似度去重 + 内容 hash 去重。

        优先级:URL > 标题相似度 > 内容 hash
        """
        # Pass 1: URL 精确去重
        seen_urls: set[str] = set()
        url_deduped: list[RawDoc] = []
        for doc in docs:
            if doc.url and doc.url not in seen_urls:
                seen_urls.add(doc.url)
                url_deduped.append(doc)

        # Pass 2: 标题相似度去重(相似度 > 0.85 视为重复)
        seen_titles: list[str] = []
        title_deduped: list[RawDoc] = []
        for doc in url_deduped:
            title = doc.title.strip()
            if not title:
                continue
            is_dup = False
            for seen in seen_titles:
                if SequenceMatcher(None, title, seen).ratio() > 0.85:
                    is_dup = True
                    break
            if not is_dup:
                seen_titles.append(title)
                title_deduped.append(doc)

        # Pass 3: 内容 hash 去重(仅对有实质性 content 的文档,短文本跳过)
        seen_hashes: set[str] = set()
        content_deduped: list[RawDoc] = []
        min_content_len = 20  # 低于此长度的内容不参与 hash 去重
        for doc in title_deduped:
            content_key = doc.content or doc.snippet
            if len(content_key) < min_content_len:
                # 内容过短,跳过 hash 去重(可能是默认值或占位符)
                content_deduped.append(doc)
                continue
            content_hash = hashlib.md5(
                content_key.encode("utf-8"), usedforsecurity=False
            ).hexdigest()
            if content_hash not in seen_hashes:
                seen_hashes.add(content_hash)
                content_deduped.append(doc)

        return content_deduped

    def clean(self, doc: RawDoc) -> RawDoc:
        """内容清洗:HTML 标签 → 空白字符 → 截断。

        同时推断 domain_type 和 credibility_score(如未设置)。
        """
        # 清洗 content
        cleaned_content = self._clean_text(doc.content)
        if cleaned_content != doc.content:
            doc.content = cleaned_content

        # 清洗 snippet
        cleaned_snippet = self._clean_text(doc.snippet)
        if cleaned_snippet != doc.snippet:
            doc.snippet = cleaned_snippet

        # 截断 content 到 max_evidence_length
        max_len = self._quality.max_evidence_length
        if doc.content and len(doc.content) > max_len:
            doc.content = doc.content[: max_len - 3] + "..."

        # 推断 domain_type(如未设置)
        if doc.domain_type == "unknown":
            doc.domain_type = self._infer_domain_type(doc.url, doc.source)

        # 推断 credibility_score(如未设置,保持默认 0.5)
        if doc.credibility_score == 0.5:
            doc.credibility_score = self._infer_credibility(doc.domain_type)

        # 生成 source_summary(如未设置)
        if not doc.source_summary:
            doc.source_summary = self._generate_summary(doc)

        return doc

    def filter_by_quality(self, docs: list[RawDoc]) -> list[RawDoc]:
        """按质量配置过滤文档。

        过滤规则:
        - credibility_score < min_credibility_score → 过滤
        - content + snippet 长度 < min_content_length → 过滤
        """
        min_creds = self._quality.min_credibility_score
        min_len = self._quality.min_content_length
        result: list[RawDoc] = []
        filtered_count = 0
        for doc in docs:
            if doc.credibility_score < min_creds:
                filtered_count += 1
                continue
            text_len = len(doc.content) + len(doc.snippet)
            if text_len < min_len:
                filtered_count += 1
                continue
            result.append(doc)
        if filtered_count:
            logger.info(
                "质量筛选: 过滤 %d 篇低质量文档(可信度<%.2f 或内容<%d 字符)",
                filtered_count, min_creds, min_len,
            )
        return result

    def rank_by_source(self, docs: list[RawDoc]) -> list[RawDoc]:
        """按来源类型排序(政府 > 研究 > 新闻 > 企业 > 社交 > 未知)。

        同类型按 credibility_score 降序。
        """
        gov_weight = self._quality.government_source_weight

        def _sort_key(doc: RawDoc) -> tuple[float, float]:
            base_weight = _SOURCE_WEIGHTS.get(doc.domain_type, 0.5)
            # 政府来源额外加权
            if doc.domain_type == "government":
                base_weight *= gov_weight
            # 元组:(来源权重,可信度),降序排列
            return (-base_weight, -doc.credibility_score)

        return sorted(docs, key=_sort_key)

    def build_evidence_pack(
        self, docs: list[RawDoc], *, county: CountyInfo, focus: str
    ) -> ProcessedData:
        """构造 ProcessedData(供 LLM 消费的证据包)。

        计算 total_chars 并返回 ProcessedData 实例。
        """
        total = sum(len(d.content) + len(d.snippet) for d in docs)
        return ProcessedData(
            county=county,
            focus=focus,
            docs=docs,
            total_chars=total,
        )

    # ---- 内部辅助 ----

    @staticmethod
    def _clean_text(text: str) -> str:
        """清理文本中的 HTML 标签和多余空白。"""
        if not text:
            return ""
        text = _HTML_TAG_RE.sub("", text)
        text = _WHITESPACE_RE.sub(" ", text)
        return text.strip()

    @staticmethod
    def _infer_domain_type(url: str, source: str) -> str:
        """根据 URL 或 source 推断 domain_type。"""
        url_lower = url.lower() if url else ""
        if source == "gov" or "gov.cn" in url_lower or ".gov." in url_lower:
            return "government"
        if "sciencedirect" in url_lower or "cnki" in url_lower or "journal" in url_lower:
            return "research"
        if "news" in url_lower or "xinhuanet" in url_lower or "people" in url_lower:
            return "news"
        if "company" in url_lower or "corp" in url_lower or "company" in source.lower():
            return "company"
        if "weibo" in url_lower or "wechat" in url_lower or "social" in url_lower:
            return "social"
        return "unknown"

    @staticmethod
    def _infer_credibility(domain_type: str) -> float:
        """根据 domain_type 推断默认可信度。"""
        mapping = {
            "government": 0.9,
            "research": 0.85,
            "news": 0.7,
            "company": 0.6,
            "social": 0.4,
            "unknown": 0.5,
        }
        return mapping.get(domain_type, 0.5)

    @staticmethod
    def _generate_summary(doc: RawDoc) -> str:
        """为文档生成一句话摘要。"""
        text = doc.snippet or doc.content or ""
        if not text:
            return ""
        # 取前 80 字符
        summary = text[:80].strip()
        if len(text) > 80:
            summary += "..."
        return summary
