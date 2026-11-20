import type { Capabilities, ResearchContract, TaskSummary } from "../api";
import { formatTime, outcomeLabel, statusLabel } from "../lib";
import { TaskForm } from "./TaskForm";

interface Props {
  capabilities: Capabilities | null;
  tasks: TaskSummary[];
  busy: boolean;
  error: string;
  onCreate: (contract: ResearchContract) => void;
  onSelectTask: (jobId: string) => void;
}

export function DefineStep({
  capabilities,
  tasks,
  busy,
  error,
  onCreate,
  onSelectTask,
}: Props) {
  return (
    <section className="define-step" aria-labelledby="define-title">
      <header className="stage-head">
        <div>
          <p className="section-kicker">STEP 01 / CONTRACT</p>
          <h2 id="define-title">定义一个可验证的研究问题</h2>
          <p className="stage-lede">
            明确地区、方向、时间窗口与证据门槛。运行完成后，只有能回到不可变快照精确引文的结论才会进入核验报告。
          </p>
        </div>
        <div className="stage-meta">
          <span className="badge badge-neutral">API {capabilities?.api_version ?? "…"}</span>
          <span className="badge badge-neutral">
            {capabilities?.mode_label ?? "…"}
          </span>
        </div>
      </header>

      <div className="define-grid">
        <TaskForm
          busy={busy}
          error={error}
          onCreate={(contract) => onCreate(contract)}
        />
        <aside className="define-notes" aria-label="研究约束说明">
          <h3>证据原生约束</h3>
          <ol>
            <li>
              <strong>事实表来自结构化结论</strong>
              <span>
                数值、单位、期间、范围与口径必须同时通过确定性校验。
              </span>
            </li>
            <li>
              <strong>冲突不会被静默忽略</strong>
              <span>
                可比数值互相矛盾时，结论不能继续标记为“已支持”，冲突会进入报告专章。
              </span>
            </li>
            <li>
              <strong>旧版叙述不冒充核验事实</strong>
              <span>
                叙述稿按原生章节或 Markdown 拆分标注入库，只作背景材料。
              </span>
            </li>
          </ol>
          <p className="muted small">
            未配置 Provider 密钥时以 MOCK 运行，只验证产品链路、事件与证据校验，不代表真实检索质量。
          </p>
        </aside>
      </div>

      <section className="recent-runs" aria-labelledby="recent-title">
        <div className="section-heading">
          <h3 id="recent-title">最近运行</h3>
          <span className="section-note">{tasks.length} 条</span>
        </div>
        {tasks.length === 0 ? (
          <p className="muted small">还没有运行记录。</p>
        ) : (
          <div className="recent-grid">
            {tasks.slice(0, 4).map((task) => (
              <button
                key={task.job_id}
                type="button"
                className="recent-card"
                onClick={() => onSelectTask(task.job_id)}
              >
                <span className="recent-objective">{task.objective}</span>
                <span className="recent-meta">
                  {statusLabel(task.status)} ·{" "}
                  {task.outcome ? outcomeLabel(task.outcome) : "—"}
                </span>
                <span className="recent-time">{formatTime(task.created_at)}</span>
              </button>
            ))}
          </div>
        )}
      </section>
    </section>
  );
}
