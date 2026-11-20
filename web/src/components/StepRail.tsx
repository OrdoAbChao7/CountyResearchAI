import type { Capabilities, TaskDetail, TaskSummary } from "../api";
import {
  formatTime,
  isTerminal,
  outcomeLabel,
  statusLabel,
  type WorkspaceStep,
} from "../lib";

interface Props {
  capabilities: Capabilities | null;
  tasks: TaskSummary[];
  detail: TaskDetail | null;
  step: WorkspaceStep;
  busy: boolean;
  onStep: (step: WorkspaceStep) => void;
  onSelectTask: (jobId: string) => void;
  onNewTask: () => void;
}

export function StepRail({
  capabilities,
  tasks,
  detail,
  step,
  busy,
  onStep,
  onSelectTask,
  onNewTask,
}: Props) {
  const terminal = detail ? isTerminal(detail.status) : false;
  const steps: Array<{
    number: WorkspaceStep;
    title: string;
    caption: string;
    available: boolean;
  }> = [
    {
      number: 1,
      title: "定义研究",
      caption: "目标 · 范围 · 门槛",
      available: true,
    },
    {
      number: 2,
      title: "运行研究",
      caption: "Agent 时间线",
      available: Boolean(detail),
    },
    {
      number: 3,
      title: "证据图谱",
      caption: "问题 · 证据 · 冲突",
      available: Boolean(detail) && terminal,
    },
    {
      number: 4,
      title: "报告工作台",
      caption: "已核验事实 · 引用",
      available: Boolean(detail) && terminal,
    },
  ];

  return (
    <aside className="step-rail" aria-label="研究工作流步骤">
      <header className="rail-brand">
        <p className="brand-kicker">EVIDENCE-NATIVE RESEARCH</p>
        <h1>AxiomScope</h1>
        <p className="brand-sub">县域产业研究 · 证据原生工作台</p>
        <div className="mode-chips">
          <span className={`chip ${capabilities?.mode_label === "LIVE" ? "chip-live" : ""}`}>
            {capabilities?.mode_label ?? "…"}
          </span>
          <span className="chip">API {capabilities?.api_version ?? "…"}</span>
        </div>
      </header>

      <nav className="step-list" aria-label="步骤导航">
        {steps.map((item) => (
          <button
            key={item.number}
            type="button"
            className={`step-button ${step === item.number ? "active" : ""}`}
            onClick={() => onStep(item.number)}
            disabled={!item.available || busy}
            aria-current={step === item.number ? "step" : undefined}
          >
            <span className="step-number">0{item.number}</span>
            <span className="step-copy">
              <strong>{item.title}</strong>
              <small>{item.caption}</small>
            </span>
            <span className="step-arrow" aria-hidden="true">
              →
            </span>
          </button>
        ))}
      </nav>

      <div className="rail-rule" />

      <section className="rail-runs" aria-label="运行记录">
        <div className="rail-runs-head">
          <h2>运行记录</h2>
          <button type="button" className="text-button" onClick={onNewTask}>
            新建
          </button>
        </div>
        {tasks.length === 0 ? (
          <p className="muted small">暂无运行记录。</p>
        ) : (
          <ul>
            {tasks.slice(0, 8).map((task) => (
              <li key={task.job_id}>
                <button
                  type="button"
                  className={`run-item ${detail?.job_id === task.job_id ? "selected" : ""}`}
                  onClick={() => onSelectTask(task.job_id)}
                  aria-current={
                    detail?.job_id === task.job_id ? "true" : undefined
                  }
                >
                  <span className="run-objective">{task.objective}</span>
                  <span className="run-meta">
                    <span>{statusLabel(task.status)}</span>
                    <span>{task.outcome ? outcomeLabel(task.outcome) : "—"}</span>
                    <time>{formatTime(task.created_at)}</time>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <footer className="rail-footer">
        <p>所有结论必须回到不可变快照中的精确引文。</p>
        <p>确定性校验不等于语义蕴含证明。</p>
      </footer>
    </aside>
  );
}
