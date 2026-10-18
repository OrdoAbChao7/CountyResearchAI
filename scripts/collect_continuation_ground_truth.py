"""Collect and freeze the real continuation Ground Truth with DeepSeek.

The script is deliberately strict: it opens the Ground Truth-only gate before
any business call, searches two task-specific contexts, fetches source text,
requires verbatim excerpts from two distinct URLs, and refuses to write a
frozen benchmark when a region/task quota is incomplete.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from county_research_ai.config import load_settings
from county_research_ai.evaluation.gate import require_ground_truth_collection_gate
from county_research_ai.evaluation.ground_truth import GroundTruthClaim, GroundTruthStore
from county_research_ai.evaluation.ground_truth_collection import (
    build_query_plan,
    claims_from_extraction,
    parse_extraction_response,
)
from county_research_ai.llm.client import OpenAICompatibleClient
from county_research_ai.search.web_search import DeepSeekSearchProvider

DEFAULT_MAX_RESULTS = 5
DEFAULT_FETCH_PER_CONTEXT = 4
DEFAULT_EXTRACTION_ATTEMPTS = 3


def collect_continuation_ground_truth(
    *,
    gate_path: Path,
    precheck_path: Path,
    regions_path: Path,
    work_dir: Path,
    output_path: Path,
    manifest_path: Path,
    max_results: int = DEFAULT_MAX_RESULTS,
    fetch_per_context: int = DEFAULT_FETCH_PER_CONTEXT,
    extraction_attempts: int = DEFAULT_EXTRACTION_ATTEMPTS,
    resume: bool = True,
    region_ids: set[str] | None = None,
    modes: set[str] | None = None,
) -> dict[str, Any]:
    gate_result = require_ground_truth_collection_gate(gate_path, precheck_path)
    settings = load_settings()
    search = DeepSeekSearchProvider(settings=settings, enabled=True)
    llm = OpenAICompatibleClient(settings=settings)
    regions_config = _load_regions(regions_path)
    task_quota = regions_config["tasks"]
    work_dir = Path(work_dir)
    tasks_dir = work_dir / "tasks"
    raw_dir = work_dir / "raw"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    all_claims: list[GroundTruthClaim] = []
    completed_tasks = 0
    selected_regions = [
        region
        for region in regions_config["regions"]
        if region_ids is None or str(region["id"]) in region_ids
    ]
    if region_ids is not None and {str(region["id"]) for region in selected_regions} != region_ids:
        missing = sorted(region_ids - {str(region["id"]) for region in selected_regions})
        raise ValueError(f"unknown region ids: {missing}")
    selected_modes = [mode for mode in task_quota if modes is None or mode in modes]
    if modes is not None and set(selected_modes) != modes:
        raise ValueError(f"unknown modes: {sorted(modes - set(selected_modes))}")
    for region in selected_regions:
        region_id = str(region["id"])
        region_name = str(region["name"])
        province = str(region.get("province", ""))
        for mode in selected_modes:
            expected_count = task_quota[mode]
            task_key = f"{region_id}_{mode}"
            task_path = tasks_dir / f"{task_key}.json"
            if resume and task_path.is_file():
                claims = _load_task_claims(task_path)
                if len(claims) == int(expected_count):
                    all_claims.extend(claims)
                    completed_tasks += 1
                    continue

            plan = build_query_plan(
                region_id=region_id,
                region=region_name,
                province=province,
                mode=mode,
            )
            evidence, context_metadata, search_calls, fetch_calls = _collect_evidence(
                search,
                plan,
                max_results=max_results,
                fetch_per_context=fetch_per_context,
            )
            raw_task_dir = raw_dir / task_key
            raw_task_dir.mkdir(parents=True, exist_ok=True)
            _write_jsonl(raw_task_dir / "sources.jsonl", list(evidence.values()))
            (raw_task_dir / "contexts.json").write_text(
                json.dumps(context_metadata, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            claims, _ = _extract_task_claims(
                llm,
                region_name=region_name,
                province=province,
                mode=mode,
                expected_count=int(expected_count),
                plan=plan,
                evidence=evidence,
                extraction_attempts=extraction_attempts,
                raw_task_dir=raw_task_dir,
            )
            if len(claims) != int(expected_count):
                raise ValueError(
                    f"{task_key} produced {len(claims)} claims, expected {expected_count}"
                )
            _write_task_claims(task_path, claims)
            all_claims.extend(claims)
            completed_tasks += 1
            _write_collection_progress(
                work_dir,
                completed_tasks=completed_tasks,
                search_calls=search_calls,
                fetch_calls=fetch_calls,
            )

    GroundTruthStore.validate_rich_claims(all_claims)
    _write_claim_source(output_path, all_claims)
    source_hash = _sha256(output_path)
    manifest = {
        "status": "COLLECTED_CONTINUATION_BENCHMARK_SOURCE",
        "schema_version": "continuation-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "gate_id": gate_result["gate"].get("gate_id"),
        "source_path": str(Path(output_path)),
        "source_hash": source_hash,
        "claim_count": len(all_claims),
        "claims_per_region": dict(sorted(Counter(c.region for c in all_claims).items())),
        "claims_per_region_task": _claims_per_region_task(all_claims),
        "search_provider": search.name,
        "llm_provider": settings.llm.provider,
        "model": settings.llm.model,
        "search_stats": search.stats(),
        "search_stats_scope": "current_process_only",
        "retained_successful_search_contexts": _retained_context_count(
            raw_dir, selected_regions, selected_modes
        ),
        "llm_requests": sum(
            len(list((raw_dir / f"{region['id']}_{mode}").glob("extraction_*.json")))
            for region in selected_regions
            for mode in selected_modes
        ),
        "llm_requests_scope": "retained_extraction_artifacts_only",
        "api_keys_logged": False,
        "resume_enabled": resume,
    }
    Path(manifest_path).parent.mkdir(parents=True, exist_ok=True)
    Path(manifest_path).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _claims_per_region_task(claims: list[GroundTruthClaim]) -> dict[str, int]:
    counts = Counter((claim.region, claim.research_mode) for claim in claims)
    return {
        f"{region}::{mode}": count
        for (region, mode), count in sorted(counts.items())
    }


def _retained_context_count(
    raw_dir: Path,
    regions: list[dict[str, Any]],
    modes: list[str],
) -> int:
    count = 0
    for region in regions:
        for mode in modes:
            path = raw_dir / f"{region['id']}_{mode}" / "contexts.json"
            if not path.is_file():
                continue
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, list):
                count += len(value)
    return count


def _collect_evidence(
    search: DeepSeekSearchProvider,
    plan: list[dict[str, str]],
    *,
    max_results: int,
    fetch_per_context: int,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], int, int]:
    evidence: dict[str, dict[str, Any]] = {}
    context_metadata: list[dict[str, Any]] = []
    search_calls = 0
    fetch_calls = 0
    for context in plan:
        docs = _retry_call(
            lambda query=context["query"]: search.search(query, max_results=max_results),
            label=f"search:{context['context_id']}",
        )
        search_calls += 1
        context_metadata.append(
            {
                "context_id": context["context_id"],
                "query": context["query"],
                "result_count": len(docs),
            }
        )
        for doc in docs[:fetch_per_context]:
            if not doc.url:
                continue
            fetched: dict[str, Any] = {}
            try:
                fetched = _retry_call(
                    lambda url=doc.url: search.fetch(url),
                    label=f"fetch:{doc.url}",
                    attempts=1,
                )
                fetch_calls += 1
            except Exception as exc:
                fetched = {"fetch_error": type(exc).__name__}
            record = evidence.setdefault(
                doc.url,
                {
                    "url": doc.url,
                    "title": doc.title,
                    "snippet": doc.snippet,
                    "search_summary": str(doc.metadata.get("raw_result", {}).get("summary", "")),
                    "text": "",
                    "source": doc.source,
                    "published_date": doc.metadata.get("published_date")
                    or doc.metadata.get("raw_result", {}).get("date"),
                    "context_ids": [],
                },
            )
            if context["context_id"] not in record["context_ids"]:
                record["context_ids"].append(context["context_id"])
            fetched_text = str(fetched.get("content", "")) if isinstance(fetched, dict) else ""
            record["text"] = fetched_text or record["text"] or doc.content or doc.snippet
            if fetched.get("title") and not record["title"]:
                record["title"] = str(fetched["title"])
    if len(evidence) < 2:
        raise ValueError("DeepSeek Search/Fetch returned fewer than two source URLs")
    return evidence, context_metadata, search_calls, fetch_calls


def _extract_task_claims(
    llm: OpenAICompatibleClient,
    *,
    region_name: str,
    province: str,
    mode: str,
    expected_count: int,
    plan: list[dict[str, str]],
    evidence: dict[str, dict[str, Any]],
    extraction_attempts: int,
    raw_task_dir: Path,
) -> tuple[list[GroundTruthClaim], int]:
    prompt = _build_extraction_prompt(
        region_name=region_name,
        province=province,
        mode=mode,
        expected_count=expected_count,
        plan=plan,
        evidence=evidence,
    )
    last_error: Exception | None = None
    for attempt in range(1, extraction_attempts + 1):
        response = llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你是严格的事实核验员。只能使用输入材料，不得补写、推测或把预计值写成最终值。"
                        "必须输出可解析 JSON，不要输出 Markdown。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=7000,
        )
        (raw_task_dir / f"extraction_{attempt:02d}.json").write_text(
            json.dumps(
                {
                    "attempt": attempt,
                    "model": response.model,
                    "usage": {
                        "prompt_tokens": response.prompt_tokens,
                        "completion_tokens": response.completion_tokens,
                        "total_tokens": response.total_tokens,
                    },
                    "content": response.content,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        try:
            extraction = parse_extraction_response(response.content)
            claims = claims_from_extraction(
                extraction,
                region=region_name,
                mode=mode,
                evidence=evidence,
                known_contexts={item["context_id"] for item in plan},
            )
            if len(claims) != expected_count:
                raise ValueError(
                    f"expected exactly {expected_count} claims, got {len(claims)}"
                )
            return claims, attempt
        except (TypeError, ValueError) as exc:
            last_error = exc
            prompt = (
                _build_extraction_prompt(
                    region_name=region_name,
                    province=province,
                    mode=mode,
                    expected_count=expected_count,
                    plan=plan,
                    evidence=evidence,
                )
                + f"\n上一次输出未通过本地校验，具体错误为：{exc}。请修正后重新输出完整 JSON。"
            )
    raise ValueError(
        f"{region_name}/{mode} extraction failed after {extraction_attempts} attempts: {last_error}"
    )


def _build_extraction_prompt(
    *,
    region_name: str,
    province: str,
    mode: str,
    expected_count: int,
    plan: list[dict[str, str]],
    evidence: dict[str, dict[str, Any]],
) -> str:
    mode_instruction = {
        "snapshot": "抽取当前/最近统计期的客观指标，如 GDP、三次产业、工业、人口、投资、财政或产业规模。",
        "rise-fall": "抽取 2019—2024 或材料覆盖期内的年份变化、增长/下降、转折点和产业演变事实；每条要有明确年份或时期。",
        "long-history": "抽取历史沿革、传统生计、工业起步、制度/交通/资源变化和产业转型的具体历史事实；每条要有明确年份或时期。",
    }[mode]
    context_text = "\n".join(
        f"- context_id={item['context_id']}：{item['query']}" for item in plan
    )
    source_text = []
    for url, item in evidence.items():
        text = str(item.get("text", ""))[:7000]
        source_text.append(
            "\n".join(
                [
                    f"SOURCE_URL: {url}",
                    f"SOURCE_TITLE: {item.get('title', '')}",
                    f"SOURCE_CONTEXTS: {','.join(item.get('context_ids', []))}",
                    f"SOURCE_DATE: {item.get('published_date') or 'unknown'}",
                    f"SOURCE_TEXT:\n{text}",
                ]
            )
        )
    schema = {
        "claims": [
            {
                "claim": "原文支持的一句话事实",
                "metric": "指标或历史主题",
                "unit": "单位/类别/事件",
                "expected_answer": "用于评分的完整标准答案，含年份、数值、口径和范围",
                "metric_year": "统计年份或历史时期",
                "administrative_scope": "县域本级/地级市全市等",
                "source_title": "主来源标题",
                "source_date": "主来源发布日期或年份",
                "primary_context_id": plan[0]["context_id"],
                "primary_url": "必须来自 SOURCE_URL",
                "evidence_excerpt": "必须逐字摘自主来源 SOURCE_TEXT",
                "verification_urls": ["必须来自另一个来源的 SOURCE_URL"],
                "verification_evidence": [
                    {"url": "与 verification_urls 中一致", "excerpt": "必须逐字摘自该来源"}
                ],
                "verification_context_ids": [plan[1]["context_id"]],
                "confidence": "high 或 medium",
            }
        ]
    }
    return f"""为 {province}{region_name} 的 {mode} 任务建立真实 Ground Truth。

任务要求：{mode_instruction}
必须输出恰好 {expected_count} 条 claims。每条 claim 都必须同时由两个不同 URL 支持，并且两个 URL 分别来自两个不同 context_id。主来源必须来自第一个 context_id，verification_urls 中至少一个 URL 必须来自第二个 context_id。不要把同一页面的镜像、转载或同一统计稿件重复计为独立来源；如无法双重核验，就不要输出该 claim。

两个独立检索上下文：
{context_text}

强制规则：
1. 只使用下面的 SOURCE_TEXT；不能依赖记忆，不能补写来源中没有的数字或因果关系。
2. evidence_excerpt 和 verification_evidence.excerpt 必须逐字复制原文，不能改写；每个摘录至少包含支撑 claim 的关键事实。
3. source_date、metric_year、administrative_scope 必须明确；预计值、初步值、修订值必须保留原文口径，不得静默合并。
4. primary_context_id 和 verification_context_ids 必须来自两个不同的 context_id；primary_url 与 verification_urls 必须是不同 URL。
5. 只返回 JSON，不要 Markdown 代码围栏，不要解释。

返回结构示例（仅示范结构，不得使用示范内容）：
{json.dumps(schema, ensure_ascii=False, indent=2)}

来源材料：
{chr(10).join(source_text)}
"""


def _load_regions(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("regions"), list):
        raise ValueError("regions config is invalid")
    tasks = value.get("tasks")
    if not isinstance(tasks, dict) or not tasks:
        raise ValueError("regions config has no task quotas")
    return {"regions": value["regions"], "tasks": tasks}


def _load_task_claims(path: Path) -> list[GroundTruthClaim]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = value.get("claims") if isinstance(value, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"invalid task checkpoint: {path}")
    claims = [GroundTruthClaim.from_dict(row) for row in rows]
    GroundTruthStore.validate_rich_claims(claims)
    return claims


def _write_task_claims(path: Path, claims: list[GroundTruthClaim]) -> None:
    path.write_text(
        json.dumps(
            {"claims": [claim.to_dict() for claim in claims]},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_claim_source(path: Path, claims: list[GroundTruthClaim]) -> None:
    GroundTruthStore.write(path, claims)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_collection_progress(
    work_dir: Path,
    *,
    completed_tasks: int,
    search_calls: int,
    fetch_calls: int,
) -> None:
    (work_dir / "progress.json").write_text(
        json.dumps(
            {
                "completed_task_modes_observed": completed_tasks,
                "last_task_search_calls": search_calls,
                "last_task_fetch_calls": fetch_calls,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "api_keys_logged": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _retry_call(function, *, label: str, attempts: int = 3):
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return function()
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(2**(attempt - 1))
    raise RuntimeError(f"{label} failed after {attempts} attempts: {last_error}") from last_error


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", type=Path, required=True)
    parser.add_argument("--precheck", type=Path, required=True)
    parser.add_argument("--regions", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS)
    parser.add_argument("--fetch-per-context", type=int, default=DEFAULT_FETCH_PER_CONTEXT)
    parser.add_argument("--extraction-attempts", type=int, default=DEFAULT_EXTRACTION_ATTEMPTS)
    parser.add_argument("--region-id", action="append", dest="region_ids")
    parser.add_argument("--mode", action="append", dest="modes")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    result = collect_continuation_ground_truth(
        gate_path=args.gate,
        precheck_path=args.precheck,
        regions_path=args.regions,
        work_dir=args.work_dir,
        output_path=args.output,
        manifest_path=args.manifest,
        max_results=args.max_results,
        fetch_per_context=args.fetch_per_context,
        extraction_attempts=args.extraction_attempts,
        resume=not args.no_resume,
        region_ids=set(args.region_ids) if args.region_ids else None,
        modes=set(args.modes) if args.modes else None,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "claim_count": result["claim_count"],
                "search_stats": result["search_stats"],
                "llm_requests": result["llm_requests"],
                "api_keys_logged": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
