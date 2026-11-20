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
];

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
