import { useState } from "react";
import type { EventOut, FindingOut, SourceOut, TaskDetail } from "../api";
import { formatTime, isTerminal, outcomeLabel, statusLabel } from "../lib";
import { Badge } from "./Badge";
import { BriefView } from "./BriefView";
import { EvidenceView } from "./EvidenceView";
import { Timeline } from "./Timeline";

interface Props {
  detail: TaskDetail;
  events: EventOut[];
  findings: FindingOut[];
  sources: SourceOut[];
  brief: string;
  busy: boolean;
  onCancel: () => void;
  onResume: () => void;
  onRefresh: () => void;
}

type Tab = "timeline" | "evidence" | "brief";

export function TaskDetailPanel({
  detail,
  events,
  findings,
  sources,
  brief,
  busy,
  onCancel,
  onResume,
  onRefresh,
}: Props) {
  const [tab, setTab] = useState<Tab>("timeline");
  const terminal = isTerminal(detail.status);
  const canResume = detail.status !== "RUNNING" && detail.status !== "SUCCEEDED";

  return (
    <section className="detail">
      <header className="detail-head">
        <div>
          <h2>{detail.objective}</h2>
          <p className="task-meta">
            <Badge value={detail.status}>{statusLabel(detail.status)}</Badge>
            {detail.outcome ? (
              <Badge value={detail.outcome}>{outcomeLabel(detail.outcome)}</Badge>
            ) : null}
            <span>{detail.mode_label}</span>
            <span>{detail.mode}</span>
            <span>{detail.regions.join("、")}</span>
            <span>创建 {formatTime(detail.created_at)}</span>
          </p>
          {detail.outcome_reason ? (
            <p className="muted">结束原因: {detail.outcome_reason}</p>
          ) : null}
          {detail.error_code ? (
            <p className="error-text">
              {detail.error_code}: {detail.error_code === "process_restarted"
                ? "进程重启导致任务中断，可手动恢复。"
                : "执行失败。"}
            </p>
          ) : null}
        </div>
        <div className="detail-actions">
          {!terminal ? (
            <button type="button" onClick={onCancel} disabled={busy || detail.cancel_requested}>
              {detail.cancel_requested ? "正在取消…" : "取消"}
            </button>
          ) : null}
          {canResume && detail.status !== "QUEUED" ? (
            <button type="button" onClick={onResume} disabled={busy}>
              恢复运行
            </button>
          ) : null}
          <button type="button" onClick={onRefresh} disabled={busy}>
            刷新
          </button>
        </div>
      </header>

      <dl className="contract-summary">
        <div>
          <dt>范围</dt>
          <dd>
            {detail.contract.date_window.start ?? "…"} ~{" "}
            {detail.contract.date_window.end ?? "…"}
          </dd>
        </div>
        <div>
          <dt>必答问题</dt>
          <dd>{detail.contract.required_questions.length} 个</dd>
        </div>
        <div>
          <dt>独立来源门槛</dt>
          <dd>{detail.contract.evidence_thresholds.min_independent_sources}</dd>
        </div>
        <div>
          <dt>支持结论门槛</dt>
          <dd>{detail.contract.evidence_thresholds.min_supported_claims}</dd>
        </div>
        <div>
          <dt>预算执行</dt>
          <dd>
            {String(
              (detail.budget_enforcement.enforced as unknown[] | undefined)?.join(", ") ??
                "—",
            )}
            {Array.isArray(detail.budget_enforcement.not_enforced_on_workflow_path) &&
            (detail.budget_enforcement.not_enforced_on_workflow_path as unknown[]).length > 0
              ? ` · 未执行: ${(detail.budget_enforcement.not_enforced_on_workflow_path as unknown[]).join(", ")}`
              : ""}
          </dd>
        </div>
      </dl>

      <nav className="tabs">
        <button type="button" className={tab === "timeline" ? "active" : ""} onClick={() => setTab("timeline")}>
          时间线 ({events.length})
        </button>
        <button type="button" className={tab === "evidence" ? "active" : ""} onClick={() => setTab("evidence")}>
          证据 ({findings.length})
        </button>
        <button type="button" className={tab === "brief" ? "active" : ""} onClick={() => setTab("brief")}>
          决策简报
        </button>
      </nav>

      <div className="tab-body">
        {tab === "timeline" ? <Timeline events={events} /> : null}
        {tab === "evidence" ? (
          <EvidenceView findings={findings} sources={sources} />
        ) : null}
        {tab === "brief" ? (
          <BriefView jobId={detail.job_id} brief={brief} reportPath={detail.report_path} />
        ) : null}
      </div>
    </section>
  );
}
