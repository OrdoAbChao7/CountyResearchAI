"""Project topic coverage and contract-question evidence for API consumers."""
from __future__ import annotations

import re
from html import escape

from ...evidence.graph import EvidenceGraphStore
from ..contract_coverage import ContractQuestionResult
from ..evidence_service import load_run_evidence
from ..jobs import JobRecord
from .common import deep_projection, normalize_text, visible_conflicts
from .models import QuestionsView, QuestionView

CONTRACT_STATUS_LABELS = {
    "SUPPORTED": "有可核验证据",
    "INSUFFICIENT": "缺少可核验答案",
    "NEEDS_REVIEW": "需要人工核对问题或证据要求",
    "CONFLICT_UNRESOLVED": "答案证据存在待复核冲突",
}
_REASON_LABELS = {
    "claim_region_mismatch": "结论归属其他地区",
    "conflicting_contract_evidence": "同口径数值冲突",
    "conflicting_supported_claims": "已有支持结论相互冲突",
    "custom_evidence_requirement": "需要人工核对自定义证据要求",
    "different_metric_or_qualification": "指标或企业资格不符",
    "direct_statement_missing": "未定位到直接的原文陈述",
    "false_or_broken_reference": "引用无法通过完整性校验",
    "incompatible_unit": "单位与所问指标不符",
    "insufficient_source_credibility": "缺少可信来源佐证",
    "missing_numeric_value": "未提取到可核验数值",
    "no_verified_supporting_span": "缺少通过核验的直接引文",
    "outside_requested_period": "结论期间超出问题要求",
    "outside_selected_evidence": "未进入本次验收的证据包",
    "partial_reporting_period": "原文只覆盖部分期间",
    "partial_statistics_scope": "统计只覆盖部分企业或样本",
    "provisional_or_nonfactual": "候选或非事实陈述",
    "reporting_period_unconfirmed": "原文无法确认报告期",
    "source_region_mismatch": "来源标注的上级区划不符",
    "unsupported_multi_region": "历史合同包含多个地区",
    "unsupported_question_form": "需要人工核对该问法的验收条件",
}
_REQUEST_LABELS = {"executed": "已执行", "reused": "复用", "skipped": "已跳过"}
_SEARCH_STATUS_LABELS = {"results": "有结果", "empty": "无结果", "failed": "失败", "skipped": "未请求"}


def build_questions_view(job: JobRecord, *, graph: EvidenceGraphStore) -> QuestionsView:
    has_contract_questions = bool(job.contract.required_questions)
    deep = deep_projection(job, required=not has_contract_questions)
    tree = deep.get("question_tree") or {}
    has_conflicts = bool(deep.get("conflicts"))
    evidence = load_run_evidence(graph, job) if has_contract_questions or has_conflicts else None
    conflicts = (
        visible_conflicts(deep, evidence.findings, graph.list_run_snapshots(job.job_id))
        if has_conflicts and evidence is not None else []
    )
    questions = [
        QuestionView(
            id=str(question.get("id", "")),
            title=str(question.get("title", "")),
            category=str(question.get("category", "")),
            description=str(question.get("description", "")),
            required_indicators=list(question.get("required_indicators", []) or []),
            evidence_ids=[str(value) for value in question.get("evidence_ids", []) or []],
            is_satisfied=bool(question.get("is_satisfied")),
        )
        for question in tree.get("questions", []) or []
    ]
    return QuestionsView(
        run_id=job.job_id,
        county=str(tree.get("county", job.county)),
        focus=str(tree.get("focus", job.focus)),
        mode=str(tree.get("mode", job.mode)),
        coverage_rate=deep.get("coverage_rate"),
        questions=questions,
        contract_questions=evidence.coverage.questions if has_contract_questions and evidence is not None else [],
        gaps=list(deep.get("gaps") or []),
        conflicts=conflicts,
        reflection_turns=int(deep.get("reflection_turns", 0) or 0),
        retrieval_stop_reason=str(deep.get("retrieval_stop_reason", "")),
    )


def _markdown_text(text: str) -> str:
    return re.sub(r"([\\`*_\[\]|~])", r"\\\1", escape(normalize_text(text), quote=False))


_LEAD_TIER_LABELS = {
    "named_lead": "具名线索",
    "operating_activity": "经营活动证据（非资格证据）",
    "formal_qualification": "正式资格证据",
}
_LEAD_CASE_LIMIT = 5


def _enterprise_lead_lines(question: ContractQuestionResult) -> list[str]:
    leads = question.enterprise_leads
    if not leads:
        return []
    lines = [
        f"  - 具名企业线索 {len(leads)} 家。经营活动或被提及不等于龙头资格，"
        "资格需正式认定公告、政府公示或企业名录的直接引文。"
    ]
    for lead in leads:
        qualification = (
            "龙头资格已核验" if lead.qualification_status == "formal_qualification_verified" else "龙头资格证据不足"
        )
        region = "地域已确认" if lead.region_status == "confirmed" else "地域未确认"
        lines.append(
            f"    - {_markdown_text(lead.name)} · {_LEAD_TIER_LABELS[lead.tier]} · {qualification} · {region}"
        )
        for case in lead.cases[:_LEAD_CASE_LIMIT]:
            identifiers = " / ".join(filter(None, (case.snapshot_id, case.span_id)))
            source = _markdown_text(case.title or "来源未确认")
            if identifiers:
                source += f" · {_markdown_text(identifiers)}"
            lines.append(f"      - {_markdown_text(case.statement)} · {source}")
        if len(lead.cases) > _LEAD_CASE_LIMIT:
            lines.append(f"      - 另有 {len(lead.cases) - _LEAD_CASE_LIMIT} 条经营案例")
    return lines


def contract_question_lines(
    questions: list[ContractQuestionResult], *, citation_numbers: dict[str, int] | None = None,
) -> list[str]:
    numbers = citation_numbers or {}
    lines: list[str] = []
    for question in questions:
        references = " ".join(f"[{numbers[claim_id]}]" for claim_id in question.claim_ids if claim_id in numbers)
        status = CONTRACT_STATUS_LABELS[question.status]
        lines.append(f"- {_markdown_text(question.question)} · {status} {references}".rstrip())
        if question.reason in _REASON_LABELS:
            lines.append(f"  - {_REASON_LABELS[question.reason]}")
        if question.missing_metrics:
            missing = _markdown_text("、".join(question.missing_metrics))
            lines.append(f"  - 缺失指标或证据 · {missing}")
        for candidate in question.candidates:
            reason = _REASON_LABELS.get(candidate.reason, candidate.reason)
            source = _markdown_text(candidate.title or "来源未确认")
            identifiers = " / ".join(filter(None, (candidate.snapshot_id, candidate.span_id)))
            if identifiers:
                source += f" · {_markdown_text(identifiers)}"
            disposition = {"SUPPORTED": "采信", "DISPUTED": "待复核", "REJECTED": "未采信"}[candidate.status]
            if candidate.reason == "insufficient_source_credibility":
                disposition = "待核验"
            lines.append(f"  - {disposition} · {source} · {_markdown_text(candidate.period or '期间未确认')} · {_markdown_text(reason)}")
        lines.extend(_enterprise_lead_lines(question))
        if question.query_executions is None:
            lines.append("  - 未保存逐条检索记录。")
        elif not question.query_executions:
            lines.append("  - 本次运行没有记录该问题的查询。")
        for execution in question.query_executions or []:
            request = _REQUEST_LABELS[execution.request]
            status = _SEARCH_STATUS_LABELS[execution.status]
            route = f" · {_markdown_text(execution.provider)}" if execution.provider else ""
            reason = f" · {_markdown_text(execution.reason)}" if execution.reason else ""
            lines.append(
                f"  - 第 {execution.round} 轮 · {request} · {status}{route} · 返回 {execution.returned_documents} 份"
                f"{reason} · {_markdown_text(execution.query)}"
            )
    return lines
