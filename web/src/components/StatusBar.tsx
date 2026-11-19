import type { Capabilities, EventOut, TaskDetail } from "../api";
import {
  formatPercent,
  isTerminal,
  outcomeLabel,
  statusLabel,
  type LayoutMode,
  type WorkspaceStep,
} from "../lib";

interface Props {
  capabilities: Capabilities | null;
  detail: TaskDetail | null;
  events: EventOut[];
  step: WorkspaceStep;
  layout: LayoutMode;
  onLayout: (layout: LayoutMode) => void;
}

const LAYOUTS: Array<{ value: LayoutMode; label: string }> = [
  { value: "graph", label: "图谱" },
  { value: "split", label: "分栏" },
  { value: "workbench", label: "工作台" },
];

export function StatusBar({
  capabilities,
  detail,
  events,
  step,
  layout,
  onLayout,
}: Props) {
  const result = (detail?.result ?? {}) as Record<string, unknown>;
  const deep = (result.deep_research ?? {}) as Record<string, unknown>;
  const coverage =
    typeof deep.coverage_rate === "number" ? deep.coverage_rate : null;

  return (
    <footer className="status-bar" aria-label="工作台状态栏">
      <div className="status-left">
        <span className="status-item">
          <span className="status-label">MODE</span>
          {capabilities?.mode_label ?? "…"}
        </span>
        <span className="status-item">
          <span className="status-label">STEP</span>0{step}/04
        </span>
        <span className="status-item">
          <span className="status-label">EVENTS</span>
          {events.length}
        </span>
        {detail ? (
          <>
            <span className="status-item">
              <span className="status-label">JOB</span>
              <code>{detail.job_id.slice(0, 10)}</code>
            </span>
            <span className="status-item">
              <span className="status-label">STATE</span>
              {statusLabel(detail.status)}
              {detail.outcome ? ` · ${outcomeLabel(detail.outcome)}` : ""}
            </span>
            <span className="status-item">
              <span className="status-label">COVERAGE</span>
              {formatPercent(coverage)}
            </span>
          </>
        ) : (
          <span className="status-item status-muted">未选择运行</span>
        )}
        {detail && isTerminal(detail.status) ? (
          <span className="status-item status-done">报告可读</span>
        ) : null}
      </div>
      <div className="layout-switch" role="group" aria-label="工作台布局">
        {LAYOUTS.map((item) => (
          <button
            key={item.value}
            type="button"
            aria-pressed={layout === item.value}
            className={layout === item.value ? "active" : ""}
            onClick={() => onLayout(item.value)}
          >
            {item.label}
          </button>
        ))}
      </div>
    </footer>
  );
}
