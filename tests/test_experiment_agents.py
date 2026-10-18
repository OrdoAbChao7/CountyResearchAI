from __future__ import annotations

import json

from county_research_ai.evaluation.experiment_agents import (
    GeneralPurposeAIResearcher,
    TraditionalSearchResearcher,
)
from county_research_ai.llm.base import LLMResponse
from county_research_ai.models import RawDoc


class FakeLLM:
    name = "fake-real-llm"

    def __init__(self, planning: bool = False):
        self.calls = []
        self.planning = planning

    def chat(self, messages, **kwargs):
        self.calls.append(messages[-1]["content"])
        if self.planning and len(self.calls) == 1:
            content = json.dumps({"queries": ["新地区县 产业统计公报", "新地区县 龙头企业"]})
        else:
            content = "研究报告\n- 事实：来源支持"
        return LLMResponse(
            content=content,
            model="gemini-3.1-flash-lite",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        )


class FakeSearch:
    name = "fake-search"

    def __init__(self):
        self.queries = []
        self.max_results = []

    def search(self, query, max_results=10):
        self.queries.append(query)
        self.max_results.append(max_results)
        return [RawDoc(title="source", url="https://example.gov.cn/source", content="source content")]


def test_traditional_researcher_uses_fixed_queries_and_returns_report(tmp_path):
    search = FakeSearch()
    result = TraditionalSearchResearcher().run(
        county="新地区县",
        focus="特色产业",
        mode="snapshot",
        llm=FakeLLM(),
        search=search,
        output_dir=tmp_path,
    )

    assert len(search.queries) == 3
    assert result.report.startswith("研究报告")
    assert result.usage_known is True


def test_general_ai_researcher_plans_before_searching(tmp_path):
    search = FakeSearch()
    result = GeneralPurposeAIResearcher().run(
        county="新地区县",
        focus="特色产业",
        mode="snapshot",
        llm=FakeLLM(planning=True),
        search=search,
        output_dir=tmp_path,
    )

    assert search.queries == ["新地区县 产业统计公报", "新地区县 龙头企业"]
    assert search.max_results == [10, 10]
    assert result.metadata["planning_used"] is True


def test_search_result_budget_is_forwarded_to_provider(tmp_path):
    search = FakeSearch()

    TraditionalSearchResearcher().run(
        county="新地区县",
        focus="特色产业",
        mode="snapshot",
        llm=FakeLLM(),
        search=search,
        output_dir=tmp_path,
        max_results=1,
    )

    assert search.max_results == [1, 1, 1]
