import { useEffect, useState } from "react";
import type { QuestionsView } from "../api";
import { getQuestions } from "../api";
import { formatPercent } from "../lib";
import { EmptyState, ErrorState, LoadingState } from "./StateViews";

export function QuestionsPanel({
  jobId,
  terminal,
  onOpenEvidence,
}: {
  jobId: string;
  terminal: boolean;
  onOpenEvidence: () => void;
}) {
  const [data, setData] = useState<QuestionsView | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!terminal) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    getQuestions(jobId)
      .then((loaded) => {
        if (!cancelled) setData(loaded);
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : String(caught));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, terminal]);

  if (loading) return <LoadingState label="正在读取问题树" rows={3} />;
  if (error) {
    return (
      <ErrorState
        title="问题树不可用"
        message={error}
        onRetry={() => window.location.reload()}
      />
    );
  }
  if (!data) {
    return (
      <EmptyState
        title="问题树尚未生成"
        description="问题树与覆盖率在运行完成后从持久化结果投影。"
      />
    );
  }

  return (
    <section className="questions-panel" aria-labelledby="questions-title">
      <div className="section-heading">
        <div>
          <p className="section-kicker">QUESTION TREE</p>
          <h2 id="questions-title">问题覆盖</h2>
        </div>
        <span className="coverage-value">{formatPercent(data.coverage_rate)}</span>
      </div>
      <p className="muted small">
        {data.county}
        {data.focus} · {data.reflection_turns} 轮反思 · 停止原因{" "}
        {data.retrieval_stop_reason || "—"}
      </p>
      <ol className="question-list">
        {data.questions.map((question) => (
          <li
            key={question.id}
            className={question.is_satisfied ? "satisfied" : "unsatisfied"}
          >
            <div className="question-head">
              <span className="question-state">
                {question.is_satisfied ? "已覆盖" : "未覆盖"}
              </span>
              <strong>{question.title}</strong>
            </div>
            <p className="muted small">
              {question.category || "未分类"} · 证据 {question.evidence_ids.length} 条
              {question.required_indicators.length > 0
                ? ` · 指标 ${question.required_indicators.join("、")}`
                : ""}
            </p>
          </li>
        ))}
      </ol>
      {data.gaps.length > 0 ? (
        <div className="mini-list">
          <h3>结构化缺口</h3>
          <ul>
            {data.gaps.map((gap, index) => (
              <li key={index}>
                {String(gap.description ?? gap.missing_aspect ?? "未命名缺口")}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {data.conflicts.length > 0 ? (
        <div className="mini-list">
          <h3>来源冲突</h3>
          <ul>
            {data.conflicts.map((conflict, index) => (
              <li key={index}>
                {String(conflict.description ?? conflict.indicator ?? "未命名冲突")}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <button type="button" onClick={onOpenEvidence}>
        打开证据抽屉
      </button>
    </section>
  );
}
