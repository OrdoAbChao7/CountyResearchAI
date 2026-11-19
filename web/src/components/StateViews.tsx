import type { ReactNode } from "react";

export function LoadingState({
  label = "正在加载",
  rows = 3,
}: {
  label?: string;
  rows?: number;
}) {
  return (
    <div className="state-panel loading-state" role="status" aria-live="polite">
      <p className="state-kicker">LOADING</p>
      <p>{label}…</p>
      <div className="skeleton" aria-hidden="true">
        {Array.from({ length: rows }, (_, index) => (
          <span key={index} style={{ width: `${92 - index * 14}%` }} />
        ))}
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="state-panel empty-state">
      <p className="state-kicker">EMPTY</p>
      <h3>{title}</h3>
      <p className="muted">{description}</p>
      {action}
    </div>
  );
}

export function ErrorState({
  title = "加载失败",
  message,
  onRetry,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="state-panel error-state" role="alert">
      <p className="state-kicker">ERROR</p>
      <h3>{title}</h3>
      <p className="error-text">{message}</p>
      {onRetry ? (
        <button type="button" onClick={onRetry}>
          重试
        </button>
      ) : null}
    </div>
  );
}
