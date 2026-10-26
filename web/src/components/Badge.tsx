import type { ReactNode } from "react";

const CLASS_MAP: Record<string, string> = {
  QUEUED: "badge-neutral",
  RUNNING: "badge-info",
  SUCCEEDED: "badge-good",
  FAILED: "badge-bad",
  CANCELLED: "badge-muted",
  BUDGET_EXHAUSTED: "badge-warn",
  INTERRUPTED: "badge-warn",
  SUFFICIENT: "badge-good",
  NO_PROGRESS: "badge-muted",
  CONFLICT_UNRESOLVED: "badge-warn",
  NEEDS_HUMAN_REVIEW: "badge-warn",
  SUPPORTED: "badge-good",
  NEEDS_REVIEW: "badge-warn",
  CONTRADICTED: "badge-bad",
  NOT_COMPARABLE: "badge-muted",
  OUTDATED: "badge-muted",
  INSUFFICIENT: "badge-neutral",
};

export function Badge({
  value,
  children,
}: {
  value: string;
  children: ReactNode;
}) {
  return <span className={`badge ${CLASS_MAP[value] ?? "badge-neutral"}`}>{children}</span>;
}
