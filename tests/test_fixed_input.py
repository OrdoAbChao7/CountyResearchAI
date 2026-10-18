from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from county_research_ai.evaluation.experiment_agents import (
    CountyResearchAIFixedInputResearcher,
    FixedInputGeneralPurposeAIResearcher,
    FixedInputResearcher,
)
from county_research_ai.evaluation.fixed_input import FixedInputPack
from county_research_ai.llm.base import LLMResponse
from county_research_ai.models import RawDoc


def _documents() -> list[RawDoc]:
    return [
        RawDoc(
            title="官方统计公报",
            url="https://example.gov.cn/bulletin",
            content="地区生产总值和产业结构数据。",
            source="gov",
        ),
        RawDoc(
            title="产业规划",
            url="https://example.gov.cn/plan",
            content="产业链和政策规划数据。",
            source="gov",
        ),
    ]


def test_fixed_input_pack_roundtrips_with_verified_content_hash(tmp_path):
    path = tmp_path / "pack.json"
    pack = FixedInputPack.create(
        pack_id="pack-1",
        region="新地区县",
        focus="特色产业",
        mode="snapshot",
        documents=_documents(),
    )

    pack.write(path)
    loaded = FixedInputPack.load(path)

    assert loaded == pack
    assert len(loaded.source_hash) == 64
    assert json.loads(path.read_text(encoding="utf-8"))["source_hash"] == pack.source_hash


def test_fixed_input_pack_rejects_ground_truth_or_duplicate_urls(tmp_path):
    path = tmp_path / "pack.json"
    payload = {
        "schema_version": "1.0",
        "pack_id": "pack-1",
        "region": "新地区县",
        "focus": "特色产业",
        "mode": "snapshot",
        "documents": [doc.model_dump(mode="json") for doc in _documents()],
        "ground_truth": {"claims": []},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported fixed-input field"):
        FixedInputPack.load(path)

    with pytest.raises(ValueError, match="duplicate document URL"):
        FixedInputPack.create(
            pack_id="pack-duplicate",
            region="新地区县",
            focus="特色产业",
            mode="snapshot",
            documents=[_documents()[0], _documents()[0]],
        )


def test_fixed_input_researcher_uses_only_frozen_documents(tmp_path):
    class FakeLLM:
        def __init__(self):
            self.messages = []

        def chat(self, messages, **kwargs):
            self.messages.append(messages)
            return LLMResponse(
                content="固定输入分析报告",
                model="gemini-3.1-flash-lite",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            )

    class SearchMustNotBeCalled:
        def search(self, *args, **kwargs):
            raise AssertionError("E2 fixed-input analysis must not search")

    pack = FixedInputPack.create(
        pack_id="pack-1",
        region="新地区县",
        focus="特色产业",
        mode="snapshot",
        documents=_documents(),
    )
    llm = FakeLLM()

    result = FixedInputResearcher().run(
        county=pack.region,
        focus=pack.focus,
        mode=pack.mode,
        documents=list(pack.documents),
        llm=llm,
        search=SearchMustNotBeCalled(),
        output_dir=tmp_path,
        input_pack_id=pack.pack_id,
        input_hash=pack.source_hash,
    )

    assert result.report == "固定输入分析报告"
    assert result.metadata == {
        "input_pack_id": "pack-1",
        "input_hash": pack.source_hash,
        "search_used": False,
    }
    assert len(llm.messages) == 1
    assert "官方统计公报" in llm.messages[0][-1]["content"]
    saved_sources = json.loads((tmp_path / "sources.json").read_text(encoding="utf-8"))
    assert [item["url"] for item in saved_sources] == [doc.url for doc in pack.documents]


def test_county_research_ai_fixed_input_path_does_not_access_search(tmp_path):
    class SearchMustNotBeCalled:
        def __getattr__(self, name):
            raise AssertionError(f"E2 unexpectedly accessed search: {name}")

    class FakeHandler:
        def render(self, context):
            return SimpleNamespace(markdown="C 固定输入报告")

    class FakeApplication:
        search = SearchMustNotBeCalled()

        def build_evidence(self, context):
            return context

        def analyze(self, context):
            return context

    pack = FixedInputPack.create(
        pack_id="pack-c",
        region="新地区县",
        focus="特色产业",
        mode="snapshot",
        documents=_documents(),
    )
    container = SimpleNamespace(
        app=SimpleNamespace(
            application=FakeApplication(),
            modes=SimpleNamespace(get=lambda mode: FakeHandler()),
        ),
        instrumented_llm=SimpleNamespace(usage_known=True),
    )

    result = CountyResearchAIFixedInputResearcher().run(
        pack=pack,
        container=container,
        output_dir=tmp_path,
    )

    assert result.report == "C 固定输入报告"
    assert result.usage_known is True
    assert result.metadata["search_used"] is False


def test_fixed_input_general_ai_plans_without_searching(tmp_path):
    class FakeLLM:
        def __init__(self):
            self.calls = []

        def chat(self, messages, **kwargs):
            self.calls.append(messages[-1]["content"])
            content = (
                '{"angles":["统计口径","产业链"]}'
                if len(self.calls) == 1
                else "通用 AI 固定输入报告"
            )
            return LLMResponse(
                content=content,
                model="gemini-3.1-flash-lite",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            )

    pack = FixedInputPack.create(
        pack_id="pack-b",
        region="新地区县",
        focus="特色产业",
        mode="snapshot",
        documents=_documents(),
    )
    llm = FakeLLM()

    result = FixedInputGeneralPurposeAIResearcher().run(
        county=pack.region,
        focus=pack.focus,
        mode=pack.mode,
        documents=list(pack.documents),
        llm=llm,
        search=None,
        output_dir=tmp_path,
        input_pack_id=pack.pack_id,
        input_hash=pack.source_hash,
        generation_tokens=512,
        planning_tokens=128,
    )

    assert result.report == "通用 AI 固定输入报告"
    assert len(llm.calls) == 2
    assert result.metadata["planning_used"] is True
    assert result.metadata["search_used"] is False
