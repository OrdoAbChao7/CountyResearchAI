import type { EventOut, TaskDetail } from "../api";
import {
  formatTime,
  isTerminal,
  outcomeLabel,
  statusLabel,
} from "../lib";
import { AgentTimeline } from "./AgentTimeline";
import { EmptyState } from "./StateViews";

interface Props {
  detail: TaskDetail | null;
  events: EventOut[];
  busy: boolean;
  onCancel: () => void;
  onResume: () => void;
  onRefresh: () => void;
  onGraph: () => void;
  onReport: () => void;
}

export function RunStep({
  detail,
  events,
  busy,
  onCancel,
  onResume,
  onRefresh,
  onGraph,
  onReport,
}: Props) {
  if (!detail) {
    return (
      <EmptyState
        title="尚未选择运行"
        description="从左侧运行记录选择一次研究，或先在 01 定义一个研究任务。"
      />
    );
  }
  const terminal = isTerminal(detail.status);
  const canResume =
    detail.status !== "RUNNING" && detail.status !== "SUCCEEDED";
  const contract = detail.contract;

  return (
    <section className="run-step" aria-labelledby="run-title">
      <header className="stage-head">
        <div>
          <p className="section-kicker">STEP 02 / RUN</p>
          <h2 id="run-title">{detail.objective}</h2>
          <p className="stage-lede">
            {detail.regions.join("、")} · {detail.mode_label} ·{" "}
            {detail.contract.research_focus || "未指定方向"}
          </p>
        </div>
        <div className="run-actions">
          {!terminal ? (
            <button
              type="button"
              onClick={onCancel}
              disabled={busy || detail.cancel_requested}
            >
              {detail.cancel_requested ? "正在取消…" : "取消"}
            </button>
          ) : null}
          {canResume ? (
            <button type="button" onClick={onResume} disabled={busy}>
              恢复运行
            </button>
          ) : null}
          <button type="button" onClick={onRefresh} disabled={busy}>
            刷新
          </button>
        </div>
      </header>

      <div className="run-status-strip">
        <div>
          <span className="strip-label">状态</span>
          <strong>{statusLabel(detail.status)}</strong>
        </div>
        <div>
          <span className="strip-label">结果</span>
          <strong>{detail.outcome ? outcomeLabel(detail.outcome) : "进行中"}</strong>
        </div>
        <div>
          <span className="strip-label">创建</span>
          <strong>{formatTime(detail.created_at)}</strong>
        </div>
        <div>
          <span className="strip-label">结束</span>
          <strong>
            {detail.finished_at ? formatTime(detail.finished_at) : "—"}
          </strong>
        </div>
        {terminal ? (
          <div className="result-links">
            <button type="button" onClick={onGraph}>
              查看证据图谱
            </button>
            <button type="button" onClick={onReport}>
              打开报告工作台
            </button>
          </div>
        ) : null}
      </div>

      {detail.outcome_reason ? (
        <p className="muted small">结束原因: {detail.outcome_reason}</p>
      ) : null}
      {detail.error_code ? (
        <p className="error-text">
          {detail.error_code}:{" "}
          {detail.error_code === "process_restarted"
            ? "进程重启导致任务中断，可手动恢复。"
            : "执行失败。"}
        </p>
      ) : null}

      <dl className="contract-summary">
        <div>
          <dt>时间窗口</dt>
          <dd>
            {contract.date_window.start || contract.date_window.end
              ? `${contract.date_window.start ?? "…"} ~ ${contract.date_window.end ?? "…"}`
              : "未限定"}
          </dd>
        </div>
        <div>
          <dt>必答问题</dt>
          <dd>{contract.required_questions.length} 个</dd>
        </div>
        <div>
          <dt>独立来源门槛</dt>
          <dd>{contract.evidence_thresholds.min_independent_sources}</dd>
        </div>
        <div>
          <dt>支持结论门槛</dt>
          <dd>{contract.evidence_thresholds.min_supported_claims}</dd>
        </div>
        <div>
          <dt>截止秒数</dt>
          <dd>{contract.budget.deadline_seconds}</dd>
        </div>
        <div>
          <dt>运行模式</dt>
          <dd>{detail.mode_label}</dd>
        </div>
      </dl>

      <AgentTimeline events={events} terminal={terminal} />
    </section>
  );
}
