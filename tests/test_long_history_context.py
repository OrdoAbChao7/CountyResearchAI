import json

import pytest

from county_research_ai.domain.research_contracts import AtomicClaim, EvidencePack
from county_research_ai.evidence.ledger import build_evidence_ledger
from county_research_ai.llm.long_history_analyzer import LongHistoryAnalyzer
from county_research_ai.models import (
    CountyInfo,
    GeoHistoricalFactor,
    HistoricalPeriod,
    LongHistoryPattern,
    ProcessedData,
    RawDoc,
)


def test_history_context_prioritizes_topic_relevant_sources_and_respects_budget():
    data = ProcessedData(
        county=CountyInfo(name="甲县"),
        focus="历史",
        docs=[
            RawDoc(title="现代产业", url="https://example.com/modern", content="产业发展" * 100),
            RawDoc(title="传统农业", url="https://example.com/agri", content="传统农业" * 100),
        ],
    )

    context = LongHistoryAnalyzer._history_context(data, "传统 农业", 80)

    assert "https://example.com/agri" in context
    assert len(context) <= 80


def test_history_context_falls_back_when_no_document_matches():
    data = ProcessedData(
        county=CountyInfo(name="甲县"),
        focus="历史",
        docs=[RawDoc(title="来源", url="https://example.com", content="无关键词" * 20)],
    )

    context = LongHistoryAnalyzer._history_context(data, "完全不同", 60)

    assert context
    assert len(context) <= 60


def test_history_context_selects_matching_passage_not_only_matching_document():
    data = ProcessedData(
        county=CountyInfo(name="甲县"),
        focus="历史",
        docs=[RawDoc(
            title="地方志",
            url="https://example.com/history",
            content="".join(["无关背景。" * 80, "清代盐业带动县城商贸繁荣。"]),
        )],
    )

    context = LongHistoryAnalyzer._history_context(data, "盐业 商贸", 400)

    assert "清代盐业带动县城商贸繁荣" in context


def test_history_context_keeps_multiple_sources_when_budget_allows():
    data = ProcessedData(
        county=CountyInfo(name="甲县"),
        focus="历史",
        docs=[
            RawDoc(title="来源甲", url="https://example.com/a", content="农业发展。" * 20),
            RawDoc(title="来源乙", url="https://example.com/b", content="农业变迁。" * 20),
        ],
    )

    context = LongHistoryAnalyzer._history_context(data, "农业", 500)

    assert "https://example.com/a" in context
    assert "https://example.com/b" in context


def test_history_pack_context_returns_period_scoped_pack_and_source_trace():
    data = ProcessedData(
        county=CountyInfo(name="甲县"),
        focus="历史",
        docs=[RawDoc(
            title="县志沿革",
            url="https://example.gov.cn/timeline",
            content="1956年县办工业形成。2018年县办工业升级。",
        )],
    )
    ledger = build_evidence_ledger(data)

    period_ledger = LongHistoryAnalyzer._build_period_ledger(ledger)
    context, pack = LongHistoryAnalyzer._history_pack_context(
        data, period_ledger, "县办工业", "1949-1978", 3000
    )

    assert isinstance(pack, EvidencePack)
    assert [chunk.year_hints for chunk in pack.selected_chunks] == [["1956"]]
    assert pack.selected_chunks[0].parent_chunk_id
    assert "1956年县办工业形成" in context
    assert "2018年县办工业升级" not in context
    assert "https://example.gov.cn/timeline" in context


def test_period_ledger_sentence_split_preserves_decimal_facts_and_offsets():
    content = "2024年GDP为722.5亿元，工业增加值300.6亿元，同比增长7.7%。后续段落。"
    data = ProcessedData(
        county=CountyInfo(name="德清县"),
        focus="长周期",
        docs=[RawDoc(title="统计公报", url="https://example.gov.cn/stats", content=content)],
    )

    period_ledger = LongHistoryAnalyzer._build_period_ledger(build_evidence_ledger(data))
    passages = list(period_ledger.chunks.values())

    assert any("722.5亿元" in chunk.text and "300.6亿元" in chunk.text and "7.7%" in chunk.text for chunk in passages)
    assert all(
        content[chunk.start_offset:chunk.end_offset] == chunk.text
        for chunk in passages
    )


def test_history_context_fallback_does_not_split_decimal_values():
    data = ProcessedData(
        county=CountyInfo(name="德清县"),
        focus="长周期",
        docs=[RawDoc(
            title="统计公报",
            url="https://example.gov.cn/stats",
            content="德清县 GDP 为722.5亿元。工业增加值为300.6亿元。",
        )],
    )

    context = LongHistoryAnalyzer._history_context(data, "不存在的检索词", 500)

    assert "722.5亿元" in context
    assert "300.6亿元" in context


def test_period_ledger_remaps_claims_to_derived_sentence_chunks():
    content = "2024年德清县地区生产总值为722.5亿元。2023年工业增加值为300.6亿元。"
    data = ProcessedData(
        county=CountyInfo(name="德清县"),
        focus="长周期",
        docs=[RawDoc(title="统计公报", url="https://example.gov.cn/stats", content=content)],
    )
    ledger = build_evidence_ledger(data)
    source_chunk = next(iter(ledger.chunks.values()))
    ledger.add_claim(AtomicClaim(
        claim_id="claim:gdp:2024",
        statement="2024年德清县地区生产总值为722.5亿元",
        region_id="德清县",
        metric_id="地区生产总值",
        value="722.5",
        unit="亿元",
        period="2024",
        source_ids=[source_chunk.document_id],
        evidence_chunk_ids=[source_chunk.chunk_id],
        verification_status="supported",
    ))

    period_ledger = LongHistoryAnalyzer._build_period_ledger(ledger)

    mapped_claim = period_ledger.claims["claim:gdp:2024"]
    mapped_chunks = period_ledger.chunks_for_claim(mapped_claim.claim_id)
    assert mapped_chunks
    assert all("722.5亿元" in chunk.text for chunk in mapped_chunks)
    assert all(chunk.document_id == source_chunk.document_id for chunk in mapped_chunks)


def test_extracted_historical_periods_narrow_evidence_pack_routing():
    periods = [
        HistoricalPeriod(name="抗战时期", start="1937年", end="1945年"),
        HistoricalPeriod(name="工业起步", start="1956年", end="1965年"),
        HistoricalPeriod(name="工业调整", start="1966年", end="1976年"),
        HistoricalPeriod(name="改革开放", start="1978年", end="2000年"),
    ]

    resolved = LongHistoryAnalyzer._resolve_period_for_task(periods, "1949-1978")

    assert resolved == "1956-1978"


def test_extracted_period_routing_falls_back_when_no_period_overlaps_task():
    periods = [HistoricalPeriod(name="当代", start="2001", end="至今")]

    resolved = LongHistoryAnalyzer._resolve_period_for_task(periods, "1949-1978")

    assert resolved == "1949-1978"


def test_resolved_dynamic_period_controls_selected_evidence_chunks():
    data = ProcessedData(
        county=CountyInfo(name="甲县"),
        focus="历史",
        docs=[RawDoc(
            title="县志",
            url="https://example.gov.cn/timeline",
            content="1950年开展水利建设。1956年设立国营工厂。1978年调整工业布局。1980年发展乡镇企业。",
        )],
    )
    periods = [HistoricalPeriod(name="工业化", start="1956", end="1978")]
    period = LongHistoryAnalyzer._resolve_period_for_task(periods, "1949-1978")
    ledger = LongHistoryAnalyzer._build_period_ledger(build_evidence_ledger(data))

    context, pack = LongHistoryAnalyzer._history_pack_context(
        data, ledger, "国营 工业", period, 3000
    )

    assert "1956年设立国营工厂" in context
    assert "1950年开展水利建设" not in context
    assert "1980年发展乡镇企业" not in context
    assert pack.excluded_evidence_reasons


def test_long_history_checkpoint_resumes_completed_analysis_tasks(tmp_path):
    calls: dict[str, int] = {}
    resumed_dates: list[str] = []

    class CountingAnalyzer(LongHistoryAnalyzer):
        fail_modern = True

        def _count(self, task):
            calls[task] = calls.get(task, 0) + 1

        def extract_periods(self, **kwargs):
            self._count("periods")
            return [HistoricalPeriod(name="县志阶段", start="1950", end="1978")]

        def analyze_geo_origin(self, **kwargs):
            self._count("geo")
            return [GeoHistoricalFactor(name="交通", impact="连接区域")]

        def analyze_traditional_economy(self, **kwargs):
            self._count("traditional")
            return "传统经济分析"

        def analyze_modern_shocks(self, **kwargs):
            self._count("modern")
            if self.fail_modern:
                raise RuntimeError("simulated interruption")
            return "近代分析"

        def analyze_state_period(self, **kwargs):
            self._count("state")
            resumed_dates.append(kwargs["date_str"])
            return "计划经济分析"

        def analyze_reform_period(self, **kwargs):
            self._count("reform")
            return "改革开放分析"

        def analyze_contemporary_status(self, **kwargs):
            self._count("contemporary")
            return "当代分析"

        def classify_long_history_pattern(self, **kwargs):
            self._count("pattern")
            return LongHistoryPattern(pattern_type="路径依赖")

        def generate_summary(self, **kwargs):
            self._count("summary")
            return "摘要"

    data = ProcessedData(
        county=CountyInfo(name="甲县"),
        focus="历史",
        docs=[RawDoc(title="县志", url="https://example.gov.cn/history", content="1956年工业形成。")],
    )
    checkpoint_path = tmp_path / "long-history-checkpoint.json"

    first = CountingAnalyzer(llm=object(), checkpoint_path=checkpoint_path)
    try:
        first.analyze(data.county, data)
    except RuntimeError as error:
        assert str(error) == "simulated interruption"
    else:
        raise AssertionError("first run should stop at the simulated interruption")

    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["state"]["analysis_date"] = "2000-01-01"
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")
    CountingAnalyzer.fail_modern = False
    resumed = CountingAnalyzer(llm=object(), checkpoint_path=checkpoint_path)
    result = resumed.analyze(data.county, data)

    assert calls["periods"] == calls["geo"] == calls["traditional"] == 1
    assert calls["modern"] == 2
    assert calls["state"] == calls["reform"] == calls["contemporary"] == 1
    assert calls["pattern"] == calls["summary"] == 1
    assert result.summary == "摘要"
    assert resumed_dates == ["2000-01-01"]

    changed_data = data.model_copy(update={
        "docs": [RawDoc(
            title="县志",
            url="https://example.gov.cn/history",
            content="1956年工业形成。新增了不同的历史事实。",
        )]
    })
    with pytest.raises(ValueError, match="configuration hash mismatch"):
        CountingAnalyzer(llm=object(), checkpoint_path=checkpoint_path).analyze(
            changed_data.county, changed_data
        )
