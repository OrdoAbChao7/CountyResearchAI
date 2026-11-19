import type { EventOut } from "./api";

export const TERMINAL_STATUSES = [
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
  "BUDGET_EXHAUSTED",
  "INTERRUPTED",
] as const;

export const EVENT_TYPES = [
  "job.queued",
  "job.started",
  "job.requeued",
  "job.resumed",
  "job.cancel_requested",
  "job.cancelled",
  "job.failed",
  "job.interrupted",
  "job.completed",
  "budget.exhausted",
  "evidence.persisted",
  "stage.collect.started",
  "stage.collect.completed",
  "stage.discover.started",
  "stage.discover.completed",
  "stage.evidence.started",
  "stage.evidence.completed",
  "stage.analyze.started",
  "stage.analyze.completed",
  "stage.report.started",
  "stage.report.completed",
  "question_tree.created",
  "question_tree.coverage",
  "retrieval.round.started",
  "retrieval.round.completed",
  "evidence.ingested",
  "reflection.started",
  "reflection.completed",
  "gaps.detected",
  "conflicts.detected",
  "agent.started",
  "agent.completed",
  "synthesis.started",
  "synthesis.completed",
  "report.rendered",
];

export type WorkspaceStep = 1 | 2 | 3 | 4;
export type LayoutMode = "graph" | "split" | "workbench";

export interface WorkspaceState {
  step: WorkspaceStep;
  layout: LayoutMode;
  taskId: string | null;
}

const LAYOUTS: LayoutMode[] = ["graph", "split", "workbench"];

export function readWorkspaceState(search: string): WorkspaceState {
  const params = new URLSearchParams(search);
  const rawStep = Number(params.get("step"));
  const step: WorkspaceStep =
    rawStep === 2 || rawStep === 3 || rawStep === 4 ? rawStep : 1;
  const layoutParam = params.get("layout") ?? "";
  const layout: LayoutMode = LAYOUTS.includes(layoutParam as LayoutMode)
    ? (layoutParam as LayoutMode)
    : "split";
  const rawTask = params.get("task") ?? "";
  const taskId = /^[A-Za-z0-9_:.-]{1,200}$/.test(rawTask) ? rawTask : null;
  return { step, layout, taskId };
}

export function workspaceSearch(state: WorkspaceState): string {
  const params = new URLSearchParams();
  if (state.step !== 1) params.set("step", String(state.step));
  if (state.layout !== "split") params.set("layout", state.layout);
  if (state.taskId) params.set("task", state.taskId);
  const value = params.toString();
  return value ? `?${value}` : "";
}

const STATUS_LABELS: Record<string, string> = {
  QUEUED: "排队中",
  RUNNING: "运行中",
  SUCCEEDED: "已完成",
  FAILED: "失败",
  CANCELLED: "已取消",
  BUDGET_EXHAUSTED: "预算耗尽",
  INTERRUPTED: "已中断",
};

const OUTCOME_LABELS: Record<string, string> = {
  SUFFICIENT: "证据充分",
  BUDGET_EXHAUSTED: "预算耗尽",
  NO_PROGRESS: "无进展",
  CONFLICT_UNRESOLVED: "冲突未解决",
  NEEDS_HUMAN_REVIEW: "需人工复核",
  CANCELLED: "已取消",
  FAILED: "失败",
};

const VERIFICATION_LABELS: Record<string, string> = {
  SUPPORTED: "已支持",
  CONTRADICTED: "被反证",
  NEEDS_REVIEW: "冲突待复核",
  NOT_COMPARABLE: "不可比",
  OUTDATED: "已过期",
  INSUFFICIENT: "证据不足",
};

export function isTerminal(status: string): boolean {
  return (TERMINAL_STATUSES as readonly string[]).includes(status);
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function outcomeLabel(outcome: string | null): string {
  if (!outcome) return "进行中";
  return OUTCOME_LABELS[outcome] ?? outcome;
}

export function verificationLabel(status: string): string {
  return VERIFICATION_LABELS[status] ?? status;
}

export function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("zh-CN", { hour12: false });
}

export function summarizePayload(payload: Record<string, unknown>): string {
  const entries = Object.entries(payload);
  if (entries.length === 0) return "";
  return entries
    .map(([key, value]) => {
      const rendered =
        typeof value === "string" ? value : JSON.stringify(value);
      return `${key}=${rendered}`;
    })
    .join(" · ")
    .slice(0, 300);
}

export const VERIFICATION_ORDER = [
  "SUPPORTED",
  "NEEDS_REVIEW",
  "CONTRADICTED",
  "OUTDATED",
  "NOT_COMPARABLE",
  "INSUFFICIENT",
] as const;

export interface EventStreamState {
  events: EventOut[];
  lastSeq: number;
}

export function mergeEvents(
  current: EventOut[],
  incoming: EventOut[],
): EventOut[] {
  const bySeq = new Map<number, EventOut>();
  for (const event of current) bySeq.set(event.seq, event);
  for (const event of incoming) bySeq.set(event.seq, event);
  return [...bySeq.values()].sort((left, right) => left.seq - right.seq);
}

export function reduceEvents(
  state: EventStreamState,
  incoming: EventOut[],
): EventStreamState {
  const events = mergeEvents(state.events, incoming);
  return {
    events,
    lastSeq: events.length > 0 ? events[events.length - 1].seq : state.lastSeq,
  };
}

export type TimelineKind = "agent" | "synthesis" | "critic" | "retrieval" | "report";
export type TimelineStatus = "running" | "completed" | "stopped";

export interface TimelineRun {
  key: string;
  kind: TimelineKind;
  label: string;
  detail: string;
  startedAt: string;
  completedAt: string | null;
  status: TimelineStatus;
}

const AGENT_LABELS: Record<string, string> = {
  economic: "经济与财政 Agent",
  policy: "政策与制度 Agent",
  industry: "产业链与企业 Agent",
  rise_fall: "产业兴衰 Agent",
  long_history: "长周期历史 Agent",
};

export function agentLabel(name: string): string {
  return AGENT_LABELS[name] ?? name;
}

function payloadString(payload: Record<string, unknown>, key: string): string {
  const value = payload[key];
  return typeof value === "string" ? value : "";
}

function payloadNumber(
  payload: Record<string, unknown>,
  key: string,
): number | null {
  const value = payload[key];
  return typeof value === "number" ? value : null;
}

export function deriveTimeline(
  events: EventOut[],
  terminal: boolean,
): TimelineRun[] {
  const runs = new Map<string, TimelineRun>();
  const order: string[] = [];

  function upsert(
    key: string,
    init: Omit<TimelineRun, "status" | "completedAt" | "detail">,
  ): TimelineRun {
    const existing = runs.get(key);
    if (existing) return existing;
    const run: TimelineRun = {
      ...init,
      completedAt: null,
      status: "running",
      detail: "",
    };
    runs.set(key, run);
    order.push(key);
    return run;
  }

  for (const event of [...events].sort((left, right) => left.seq - right.seq)) {
    const payload = event.payload ?? {};
    if (event.event_type === "agent.started") {
      const name = payloadString(payload, "agent") || "agent";
      upsert(`agent:${name}`, {
        key: `agent:${name}`,
        kind: "agent",
        label: agentLabel(name),
        startedAt: event.created_at,
      });
    } else if (event.event_type === "agent.completed") {
      const name = payloadString(payload, "agent") || "agent";
      const run = upsert(`agent:${name}`, {
        key: `agent:${name}`,
        kind: "agent",
        label: agentLabel(name),
        startedAt: event.created_at,
      });
      run.completedAt = event.created_at;
      run.status = "completed";
      const chars = payloadNumber(payload, "content_chars");
      run.detail = chars === null ? "已完成" : `${chars} 字符分析`;
    } else if (event.event_type === "synthesis.started") {
      upsert("synthesis", {
        key: "synthesis",
        kind: "synthesis",
        label: "综合写作",
        startedAt: event.created_at,
      });
    } else if (event.event_type === "synthesis.completed") {
      const run = upsert("synthesis", {
        key: "synthesis",
        kind: "synthesis",
        label: "综合写作",
        startedAt: event.created_at,
      });
      run.completedAt = event.created_at;
      run.status = "completed";
      const sections = payloadNumber(payload, "sections");
      run.detail = sections === null ? "已完成" : `${sections} 个章节`;
    } else if (event.event_type === "reflection.started") {
      const turn = payloadNumber(payload, "turn") ?? 1;
      upsert(`critic:${turn}`, {
        key: `critic:${turn}`,
        kind: "critic",
        label: `Critic 反思 · 第 ${turn} 轮`,
        startedAt: event.created_at,
      });
    } else if (event.event_type === "reflection.completed") {
      const turn = payloadNumber(payload, "turn") ?? 1;
      const run = upsert(`critic:${turn}`, {
        key: `critic:${turn}`,
        kind: "critic",
        label: `Critic 反思 · 第 ${turn} 轮`,
        startedAt: event.created_at,
      });
      run.completedAt = event.created_at;
      run.status = "completed";
      const sufficient = payload["is_sufficient"];
      run.detail = sufficient === true ? "证据充分" : "发现缺口或冲突";
    } else if (event.event_type === "retrieval.round.started") {
      const round = payloadNumber(payload, "round") ?? 1;
      upsert(`retrieval:${round}`, {
        key: `retrieval:${round}`,
        kind: "retrieval",
        label: `检索第 ${round} 轮`,
        startedAt: event.created_at,
      });
    } else if (event.event_type === "retrieval.round.completed") {
      const round = payloadNumber(payload, "round") ?? 1;
      const run = upsert(`retrieval:${round}`, {
        key: `retrieval:${round}`,
        kind: "retrieval",
        label: `检索第 ${round} 轮`,
        startedAt: event.created_at,
      });
      run.completedAt = event.created_at;
      run.status = "completed";
      const documents = payloadNumber(payload, "documents");
      run.detail = documents === null ? "已完成" : `${documents} 篇文档`;
    } else if (event.event_type === "report.rendered") {
      upsert("report", {
        key: "report",
        kind: "report",
        label: "报告渲染",
        startedAt: event.created_at,
      });
      const run = runs.get("report") as TimelineRun;
      run.completedAt = event.created_at;
      run.status = "completed";
      const sections = payloadNumber(payload, "sections");
      run.detail = sections === null ? "已生成" : `${sections} 个章节`;
    }
  }

  for (const run of runs.values()) {
    if (!terminal && run.status === "running") continue;
    if (terminal && run.status === "running") {
      run.status = "stopped";
      run.detail = "任务结束前未收到完成事件";
    }
  }
  return order.map((key) => runs.get(key) as TimelineRun);
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${Math.round(value * 100)}%`;
}
