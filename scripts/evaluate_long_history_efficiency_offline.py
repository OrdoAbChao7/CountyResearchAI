"""Compare archived long-history prompt-context sizes without provider calls."""
from __future__ import annotations

import json
from pathlib import Path

from evaluate_adaptive_retrieval_offline import load_docs

from county_research_ai.evidence.ledger import build_evidence_ledger
from county_research_ai.llm.long_history_analyzer import LongHistoryAnalyzer
from county_research_ai.models import CountyInfo, ProcessedData

ARCHIVES = (
    Path("experiments/independent_comparison/runs/continuation_matched_budget_deepseek_flash_20261019/continuation_matched_budget_deepseek_flash_20261019_region_03_long-history_r1_C/data/raw/于都县/20261018/raw_docs.json"),
    Path("experiments/independent_comparison/runs/continuation_matched_budget_deepseek_flash_20261019/continuation_matched_budget_deepseek_flash_20261019_region_01_long-history_r1_C/data/raw/德清县/20261018/raw_docs.json"),
    Path("experiments/independent_comparison/runs/formal_target_deepseek_20261018_corrected_r1/formal_target_deepseek_20261018_corrected_r1_region_02_长汀县_long-history_r1_C/data/raw/长汀县/20261018/raw_docs.json"),
)
TOPICS = (
    ("地理 建县 区位 河流 交通 行政", ""),
    ("传统 农业 手工业 商贸 盐业", "before 1840"),
    ("近代 战争 铁路 公路 口岸 工业", "1840-1948"),
    ("计划经济 国营 工厂 水利 矿山 1950 1960 1970", "1949-1978"),
    ("改革开放 乡镇企业 外资 民营 1980 1990", "1978-2000"),
    ("新世纪 产业 转型 发展 2000 2010 2020", "2001-至今"),
)
TASK_CONFIGS = (
    LongHistoryAnalyzer.PERIODS_CONFIG,
    LongHistoryAnalyzer.GEO_ORIGIN_CONFIG,
    LongHistoryAnalyzer.TRADITIONAL_CONFIG,
    LongHistoryAnalyzer.MODERN_CONFIG,
    LongHistoryAnalyzer.STATE_CONFIG,
    LongHistoryAnalyzer.REFORM_CONFIG,
    LongHistoryAnalyzer.CONTEMPORARY_CONFIG,
)


def evaluate(path: Path) -> dict[str, object]:
    county_name = path.parts[-3]
    data = ProcessedData(county=CountyInfo(name=county_name), focus="长周期兴衰史", docs=load_docs(path))
    full = data.render_for_llm(max_chars=18000)
    ledger = LongHistoryAnalyzer._build_period_ledger(build_evidence_ledger(data))
    selected = [
        LongHistoryAnalyzer._history_pack_context(data, ledger, topic, period, 6000)
        for topic, period in TOPICS
    ]
    contexts = [context for context, _ in selected]
    packs = [pack for _, pack in selected]
    optimized_contexts = [full, *contexts]
    analyzer = LongHistoryAnalyzer(llm=object())
    legacy_prompts = [
        analyzer._build_prompt_from_config(
            config,
            county=county_name,
            date="2026-10-19",
            processed_data=full,
        )
        for config in TASK_CONFIGS
    ]
    optimized_prompts = [
        analyzer._build_prompt_from_config(
            config,
            county=county_name,
            date="2026-10-19",
            processed_data=context,
        )
        for config, context in zip(TASK_CONFIGS, optimized_contexts, strict=True)
    ]
    legacy_prompt_chars = sum(map(len, legacy_prompts))
    optimized_prompt_chars = sum(map(len, optimized_prompts))
    return {
        "archive": str(path),
        "documents": len(data.docs),
        "sources_in_full_context": sum(doc.url in full for doc in data.docs),
        "legacy_prompt_chars_first_seven_calls": legacy_prompt_chars,
        "optimized_prompt_chars_first_seven_calls": optimized_prompt_chars,
        "prompt_char_reduction_pct_first_seven_calls": round(100 * (legacy_prompt_chars - optimized_prompt_chars) / legacy_prompt_chars, 1) if legacy_prompt_chars else 0,
        "legacy_context_chars": sum(len(full) for _ in TASK_CONFIGS),
        "optimized_context_chars": sum(map(len, optimized_contexts)),
        "optimized_topic_context_chars": list(map(len, contexts)),
        "topic_context_source_counts": [len(pack.source_map) for pack in packs],
        "topic_context_chunk_counts": [len(pack.selected_chunks) for pack in packs],
        "topic_context_period_excluded": [
            sum(reason == "outside_requested_period" for reason in pack.excluded_evidence_reasons.values())
            for pack in packs
        ],
        "topic_keyword_presence": [
            sum(term in context for term in topic.split())
            for context, (topic, _) in zip(contexts, TOPICS, strict=True)
        ],
        "topic_lexical_coverage_vs_legacy": [
            {
                "legacy_terms_present": [term for term in topic.split() if term in full],
                "optimized_terms_present": [term for term in topic.split() if term in context],
                "retained_legacy_term_fraction": (
                    round(
                        sum(term in context for term in topic.split() if term in full)
                        / sum(term in full for term in topic.split()),
                        3,
                    )
                    if any(term in full for term in topic.split())
                    else None
                ),
            }
            for context, (topic, _) in zip(contexts, TOPICS, strict=True)
        ],
    }


def main() -> None:
    rows = [evaluate(path) for path in ARCHIVES if path.exists()]
    print(json.dumps({"offline_only": True, "provider_calls": 0, "archives_found": len(rows), "results": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
