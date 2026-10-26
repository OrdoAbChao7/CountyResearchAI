import type { TaskSummary } from "../api";
import { formatTime, outcomeLabel, statusLabel } from "../lib";
import { Badge } from "./Badge";

interface Props {
  tasks: TaskSummary[];
  selectedId: string | null;
  onSelect: (jobId: string) => void;
}

export function TaskList({ tasks, selectedId, onSelect }: Props) {
  return (
    <section className="task-list">
      <h2>任务历史</h2>
      {tasks.length === 0 ? <p className="muted">暂无任务。</p> : null}
      <ul>
        {tasks.map((task) => (
          <li key={task.job_id}>
            <button
              type="button"
              className={task.job_id === selectedId ? "task-item selected" : "task-item"}
              onClick={() => onSelect(task.job_id)}
            >
              <span className="task-objective">{task.objective}</span>
              <span className="task-meta">
                <Badge value={task.status}>{statusLabel(task.status)}</Badge>
                <span>{task.mode_label}</span>
                <span>{formatTime(task.created_at)}</span>
              </span>
              <span className="task-outcome">
                {task.outcome ? outcomeLabel(task.outcome) : "—"}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
