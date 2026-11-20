import type { EventOut } from "../api";
import {
  deriveTimeline,
  formatTime,
  summarizePayload,
  type TimelineRun,
} from "../lib";
import { EmptyState } from "./StateViews";

const KIND_LABELS: Record<TimelineRun["kind"], string> = {
  agent: "AGENT",
  synthesis: "SYNTHESIS",
  critic: "CRITIC",
  retrieval: "RETRIEVAL",
  report: "REPORT",
};

const STATUS_LABELS: Record<TimelineRun["status"], string> = {
  running: "运行中",
  completed: "已完成",
  stopped: "未完成",
};

export function AgentTimeline({
  events,
  terminal,
}: {
  events: EventOut[];
  terminal: boolean;
}) {
  if (events.length === 0) {
    return (
      <EmptyState
        title="尚未收到运行事件"
        description="事件通过现有 SSE 流进入工作台；这里不会显示推测的进度或伪造的 Agent 状态。"
      />
    );
  }
  const runs = deriveTimeline(events, terminal);

  return (
    <div className="agent-timeline-wrap">
      <section aria-labelledby="agent-timeline-title">
        <div className="section-heading">
          <h2 id="agent-timeline-title">Agent 时间线</h2>
          <span className="section-note">
            {terminal ? "运行已结束" : "按真实事件增量更新"}
          </span>
        </div>
        {runs.length === 0 ? (
          <p className="muted small">
            当前事件中没有 Agent、Critic、检索或综合写作记录。
          </p>
        ) : (
          <ol className="agent-timeline">
            {runs.map((run) => (
              <li key={run.key} className={`agent-run status-${run.status}`}>
                <span className="agent-kind">{KIND_LABELS[run.kind]}</span>
                <div className="agent-main">
                  <div className="agent-head">
                    <strong>{run.label}</strong>
                    <span className={`run-state state-${run.status}`}>
                      {STATUS_LABELS[run.status]}
                    </span>
                  </div>
                  <p className="agent-detail">
                    {run.detail || "等待完成事件"}
                  </p>
                  <p className="agent-time">
                    开始 {formatTime(run.startedAt)}
                    {run.completedAt
                      ? ` · 结束 ${formatTime(run.completedAt)}`
                      : ""}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section aria-labelledby="event-log-title" className="event-log-section">
        <div className="section-heading">
          <h2 id="event-log-title">事件流</h2>
          <span className="section-note">{events.length} 条</span>
        </div>
        <ol className="event-log">
          {events.map((event) => (
            <li key={event.seq} className="event-row">
              <span className="event-seq">#{event.seq}</span>
              <code className="event-type">{event.event_type}</code>
              <span className="event-time">{formatTime(event.created_at)}</span>
              {Object.keys(event.payload ?? {}).length > 0 ? (
                <span className="event-payload">
                  {summarizePayload(event.payload)}
                </span>
              ) : null}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
