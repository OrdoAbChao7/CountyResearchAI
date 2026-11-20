"""Target-window propagation from the contract to queries and collection."""
from __future__ import annotations

from datetime import date, datetime, timezone

from county_research_ai.api.worker import request_from_contract
from county_research_ai.application.context import ResearchContext
from county_research_ai.domain.research_contracts import ResearchContract
from county_research_ai.models import RawDoc, ResearchRequest
from county_research_ai.search.base import SearchProvider
from county_research_ai.search.collector import SearchCollector
from county_research_ai.search.query_engine import QueryEngine
from tests.test_research_application import make_application


class RecordingProvider(SearchProvider):
    name = "recording"

    def __init__(self, published_at: datetime | None = None) -> None:
        self.queries: list[str] = []
        self.published_at = published_at

    def search(self, query, max_results=10):
        self.queries.append(query)
        return [
            RawDoc(
                title="安吉县2024年国民经济和社会发展统计公报",
                url="https://anji.gov.cn/tjgb2024",
                snippet="安吉县竹产业总产值达到280亿元。",
                content="2024年安吉县竹产业总产值达到280亿元。",
                published_at=self.published_at,
            )
        ]


def test_research_request_derives_target_years_and_period():
    request = ResearchRequest(
        county="安吉县",
        date_start=date(2024, 1, 1),
        date_end=date(2024, 12, 31),
    )
    assert request.target_years == ["2024"]
    assert request.time_period == "2024"

    multi = ResearchRequest(
        county="安吉县",
        date_start=date(2023, 1, 1),
        date_end=date(2024, 12, 31),
    )
    assert multi.target_years == ["2023", "2024"]
    assert multi.time_period == "2023-2024"

    assert ResearchRequest(county="安吉县").target_years == []
    assert ResearchRequest(county="安吉县").time_period == ""


def test_contract_to_request_reuses_to_research_spec():
    contract = ResearchContract(
        objective="2024 年竹产业评估",
        regions=["安吉县"],
        date_window={"start": "2024-01-01", "end": "2024-12-31"},
        research_focus="竹产业",
        required_questions=["2024年竹产业总产值是多少？"],
    )
    spec = contract.to_research_spec()
    assert spec.target_years == ["2024"]
    assert "2024" in spec.required_question_slots[0].time_period

    request = request_from_contract(contract)
    assert request.county == "安吉县"
    assert request.focus == "竹产业"
    assert request.date_start == date(2024, 1, 1)
    assert request.date_end == date(2024, 12, 31)
    assert request.target_years == ["2024"]


def test_query_engine_adds_the_target_year_for_every_mode():
    engine = QueryEngine()
    for mode in ("snapshot", "rise-fall", "long-history"):
        queries = engine.generate_research_queries(
            "安吉县", "竹产业", mode, target_years=["2024"]
        )
        texts = [query.query for query in queries]
        assert any("2024年" in text for text in texts), (mode, texts)

    snapshot = engine.generate_research_queries(
        "安吉县", "竹产业", "snapshot", target_years=["2024"]
    )
    assert "安吉县 2024年 统计公报 国民经济和社会发展统计公报" in [
        query.query for query in snapshot
    ]


def test_research_spec_carries_target_years_into_every_slot():
    spec = QueryEngine().generate_research_spec(
        "安吉县", "竹产业", "snapshot", target_years=["2024"]
    )
    assert spec.target_years == ["2024"]
    assert spec.question_slots
    assert all(slot.time_period == "2024" for slot in spec.question_slots)


def test_application_passes_window_to_search_port(tmp_path):
    application, search, _ = make_application(tmp_path)
    context = ResearchContext.from_request(
        ResearchRequest(
            county="安吉县",
            focus="竹产业",
            mode="snapshot",
            date_start=date(2024, 1, 1),
            date_end=date(2024, 12, 31),
        )
    )

    application.collect_materials(context)

    assert search.calls[-1]["date_start"] == date(2024, 1, 1)
    assert search.calls[-1]["date_end"] == date(2024, 12, 31)
    assert search.calls[-1]["target_years"] == ["2024"]


def test_collector_sends_target_year_into_real_queries(tmp_settings):
    web = RecordingProvider()
    gov = RecordingProvider()
    collector = SearchCollector(
        web_provider=web,
        gov_provider=gov,
        settings=tmp_settings,
        query_engine=QueryEngine(),
    )

    docs = collector.collect(
        county="安吉县",
        focus="竹产业",
        target_years=["2024"],
        date_start=date(2024, 1, 1),
        date_end=date(2024, 12, 31),
    )

    assert docs
    assert any("2024年" in query for query in web.queries + gov.queries)


def test_2025_published_page_with_2024_data_is_not_filtered_out(tmp_settings):
    provider = RecordingProvider(
        published_at=datetime(2025, 3, 1, tzinfo=timezone.utc)
    )
    collector = SearchCollector(
        web_provider=provider,
        gov_provider=None,
        settings=tmp_settings,
        query_engine=QueryEngine(),
    )

    docs = collector.collect(
        county="安吉县",
        focus="竹产业",
        target_years=["2024"],
        date_start=date(2024, 1, 1),
        date_end=date(2024, 12, 31),
    )

    assert len(docs) == 1
    assert docs[0].published_at is not None
    assert docs[0].published_at.year == 2025
