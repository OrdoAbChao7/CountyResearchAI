import type {
  EvidenceItemView,
  EventOut,
  GraphNode,
  ReportView,
  TaskDetail,
} from "../api";
import {
  formatPercent,
  formatTime,
  isTerminal,
  outcomeLabel,
  statusLabel,
  type WorkspaceStep,
} from "../lib";

interface Props {
  detail: TaskDetail | null;
  events: EventOut[];
  selectedNode: GraphNode | null;
  selectedEvidence: EvidenceItemView | null;
  report: ReportView | null;
  step: WorkspaceStep;
  onStep: (step: WorkspaceStep) => void;
  onOpenEvidence: (claimId: string) => void;
  onOpenReport: (claimId: string) => void;
  onLocateGraph: (claimId: string) => void;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function ContextPanel({
  detail,
  events,
  selectedNode,
  selectedEvidence,
  report,
  step,
  onStep,
  onOpenEvidence,
  onOpenReport,
  onLocateGraph,
}: Props) {
  if (!detail) {
    return (
      <aside className="context-panel" aria-label="运行上下文">
        <div className="context-scroll">
          <header className="context-head">
            <p className="section-kicker">CONTEXT</p>
            <h2>未选择运行</h2>
            <p className="muted">
              在 01 定义一个研究任务，或从左侧运行记录中选择一次已持久化的运行。
            </p>
          </header>
          <section className="context-block" aria-labelledby="context-empty-title">
            <h3 id="context-empty-title">工作台导航</h3>
            <div className="context-actions">
              <button type="button" onClick={() => onStep(1)}>
                定义研究
              </button>
            </div>
          </section>
          <p className="muted small">
            这里只显示来自 SQLite 任务记录与事件流的真实数据，不预填虚构指标。
          </p>
        </div>
      </aside>
    );
  }
  const terminal = isTerminal(detail.status);
  const result = asRecord(detail.result);
  const deep = asRecord(result.deep_research);
  const evidenceSummary = asRecord(result.evidence);
  const reportProjection = asRecord(result.report);
  const questions = Array.isArray(asRecord(deep.question_tree).questions)
    ? (asRecord(deep.question_tree).questions as unknown[])
    : [];
  const items = Array.isArray(deep.items) ? deep.items : [];
  const gaps = Array.isArray(deep.gaps) ? deep.gaps : [];
  const conflicts = Array.isArray(deep.conflicts) ? deep.conflicts : [];
  const coverage = asNumber(deep.coverage_rate);
  const supported = asNumber(evidenceSummary.supported_claims);
  const claims = asNumber(evidenceSummary.claims);
  const independent = asNumber(evidenceSummary.independent_sources);

  return (
    <aside className="context-panel" aria-label="运行上下文">
      <div className="context-scroll">
        <header className="context-head">
          <p className="section-kicker">CONTEXT</p>
          <h2>{detail.regions.join("、") || "未指定地区"}</h2>
          <p className="muted">
            {detail.contract.research_focus || detail.objective}
          </p>
          <div className="context-chips">
            <span className="badge badge-info">{statusLabel(detail.status)}</span>
            {detail.outcome ? (
              <span className="badge badge-neutral">
                {outcomeLabel(detail.outcome)}
              </span>
            ) : null}
            <span className="badge badge-neutral">{detail.mode_label}</span>
          </div>
        </header>

        <section className="context-block" aria-labelledby="run-summary-title">
          <h3 id="run-summary-title">运行摘要</h3>
          <dl className="metric-grid">
            <div>
              <dt>问题覆盖</dt>
              <dd>{formatPercent(coverage)}</dd>
            </div>
            <div>
              <dt>问题</dt>
              <dd>{questions.length}</dd>
            </div>
            <div>
              <dt>证据项</dt>
              <dd>{items.length}</dd>
            </div>
            <div>
              <dt>已支持结论</dt>
              <dd>{supported ?? "—"}</dd>
            </div>
            <div>
              <dt>结构化结论</dt>
              <dd>{claims ?? "—"}</dd>
            </div>
            <div>
              <dt>独立来源</dt>
              <dd>{independent ?? "—"}</dd>
            </div>
            <div>
              <dt>冲突</dt>
              <dd>{conflicts.length}</dd>
            </div>
            <div>
              <dt>缺口</dt>
              <dd>{gaps.length}</dd>
            </div>
          </dl>
          <p className="muted small">
            报告来源: {asString(reportProjection.provenance) || "未生成"}
          </p>
          {report ? (
            <p className="muted small">
              核验事实 {report.verification.verified}/{report.verification.total} ·
              引用 {report.citations.length}
            </p>
          ) : null}
        </section>

        <section className="context-block" aria-labelledby="selection-title">
          <h3 id="selection-title">当前选中</h3>
          {selectedEvidence ? (
            <div className="selection-card">
              <span className={`status-dot status-${selectedEvidence.status}`}>
                {selectedEvidence.status}
              </span>
              <p>{selectedEvidence.statement}</p>
              <p className="muted small">
                {selectedEvidence.value}
                {selectedEvidence.unit} · {selectedEvidence.period || "未标期间"} ·{" "}
                {selectedEvidence.title || "未标来源"}
              </p>
              <div className="selection-actions">
                <button
                  type="button"
                  onClick={() => onOpenEvidence(selectedEvidence.claim_id)}
                >
                  查看证据
                </button>
                <button
                  type="button"
                  onClick={() => onOpenReport(selectedEvidence.claim_id)}
                >
                  报告定位
                </button>
                <button
                  type="button"
                  onClick={() => onLocateGraph(selectedEvidence.claim_id)}
                >
                  图谱定位
                </button>
              </div>
            </div>
          ) : selectedNode ? (
            <NodeDetail
              node={selectedNode}
              onOpenEvidence={onOpenEvidence}
              onOpenReport={onOpenReport}
              onLocateGraph={onLocateGraph}
            />
          ) : (
            <p className="muted small">
              在图谱或报告引用中选择节点、冲突或缺口，这里会显示可追溯细节。
            </p>
          )}
        </section>

        <section className="context-block" aria-labelledby="next-title">
          <h3 id="next-title">工作台导航</h3>
          <div className="context-actions">
            <button
              type="button"
              disabled={step === 2}
              onClick={() => onStep(2)}
            >
              运行时间线
            </button>
            <button
              type="button"
              disabled={!terminal || step === 3}
              onClick={() => onStep(3)}
            >
              证据图谱
            </button>
            <button
              type="button"
              disabled={!terminal || step === 4}
              onClick={() => onStep(4)}
            >
              报告工作台
            </button>
          </div>
        </section>

        <section className="context-block" aria-labelledby="lifecycle-title">
          <h3 id="lifecycle-title">生命周期</h3>
          <ul className="lifecycle">
            <li>
              <span>创建</span>
              <time>{formatTime(detail.created_at)}</time>
            </li>
            <li>
              <span>开始</span>
              <time>
                {detail.started_at ? formatTime(detail.started_at) : "—"}
              </time>
            </li>
            <li>
              <span>结束</span>
              <time>
                {detail.finished_at ? formatTime(detail.finished_at) : "—"}
              </time>
            </li>
            <li>
              <span>事件</span>
              <span>{events.length}</span>
            </li>
          </ul>
          {detail.outcome_reason ? (
            <p className="muted small">结束原因: {detail.outcome_reason}</p>
          ) : null}
          {detail.error_code ? (
            <p className="error-text small">
              {detail.error_code}
              {detail.error_code === "process_restarted"
                ? " · 进程重启导致中断，可手动恢复"
                : ""}
            </p>
          ) : null}
        </section>
      </div>
    </aside>
  );
}

function NodeDetail({
  node,
  onOpenEvidence,
  onOpenReport,
  onLocateGraph,
}: {
  node: GraphNode;
  onOpenEvidence: (claimId: string) => void;
  onOpenReport: (claimId: string) => void;
  onLocateGraph: (claimId: string) => void;
}) {
  const data = node.data;
  const claimId = asString(data.claim_id);
  const description = asString(data.description);
  return (
    <div className="selection-card">
      <span className={`type-tag type-${node.type}`}>{node.type}</span>
      <p className="selection-label">{node.label}</p>
      <p className="muted small">{node.sublabel}</p>
      {asString(data.status) ? (
        <p className="muted small">状态: {asString(data.status)}</p>
      ) : null}
      {asString(data.value) || asString(data.unit) ? (
        <p className="muted small">
          数值: {asString(data.value)}
          {asString(data.unit)} · {asString(data.period) || "未标期间"} ·{" "}
          {asString(data.caliber) || "未标口径"}
        </p>
      ) : null}
      {description ? <p className="small">{description}</p> : null}
      {asString(data.missing_aspect) ? (
        <p className="muted small">
          缺失方面: {asString(data.missing_aspect)}
        </p>
      ) : null}
      {asString(data.resolution_suggestion) ? (
        <p className="muted small">
          核验建议: {asString(data.resolution_suggestion)}
        </p>
      ) : null}
      {claimId ? (
        <div className="selection-actions">
          <button type="button" onClick={() => onOpenEvidence(claimId)}>
            查看证据
          </button>
          <button type="button" onClick={() => onOpenReport(claimId)}>
            报告定位
          </button>
          <button type="button" onClick={() => onLocateGraph(claimId)}>
            图谱定位
          </button>
        </div>
      ) : null}
    </div>
  );
}
