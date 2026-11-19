import { useEffect, useMemo, useState } from "react";
import type { ReportView, TaskDetail } from "../api";
import { getReportJson } from "../api";
import { formatTime, isTerminal } from "../lib";
import { MarkdownView } from "./MarkdownView";
import { EmptyState, ErrorState, LoadingState } from "./StateViews";

interface Props {
  detail: TaskDetail;
  focusClaimId: string | null;
  onCitation: (claimId: string) => void;
  onReportLoaded?: (report: ReportView) => void;
}

type ReportTab = "verified" | "disputes" | "narrative";

const CONFLICT_TYPE_LABELS: Record<string, string> = {
  contradiction: "数值矛盾",
  year_discrepancy: "年份差异",
  caliber_discrepancy: "口径差异",
  value_discrepancy: "数值差异",
  discrepancy: "来源差异",
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asRecords(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.map(asRecord).filter((item): item is Record<string, unknown> => item !== null)
    : [];
}

function conflictLabel(value: unknown): string {
  const raw = asText(value);
  return CONFLICT_TYPE_LABELS[raw] ?? (raw || "来源差异");
}

export function ReportStudio({
  detail,
  focusClaimId,
  onCitation,
  onReportLoaded,
}: Props) {
  const terminal = isTerminal(detail.status);
  const [report, setReport] = useState<ReportView | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<ReportTab>("verified");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!terminal) {
      setReport(null);
      setError("");
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    getReportJson(detail.job_id)
      .then((loaded) => {
        if (cancelled) return;
        setReport(loaded);
        onReportLoaded?.(loaded);
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
    // onReportLoaded is intentionally excluded: callers pass stable setters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.job_id, terminal, reloadKey]);

  const citationNumbers = useMemo(() => {
    const map = new Map<string, number>();
    for (const citation of report?.citations ?? []) {
      map.set(citation.claim_id, citation.n);
    }
    return map;
  }, [report]);

  useEffect(() => {
    if (!focusClaimId || !report) return undefined;
    setTab("verified");
    const handle = window.setTimeout(() => {
      const target = document.getElementById(`citation-${focusClaimId}`);
      target?.scrollIntoView({ block: "center", behavior: "smooth" });
      target?.focus({ preventScroll: true });
    }, 60);
    return () => window.clearTimeout(handle);
  }, [focusClaimId, report]);

  if (!terminal) {
    return (
      <section className="report-studio" aria-labelledby="report-title">
        <div className="section-heading">
          <h2 id="report-title">报告工作台</h2>
          <span className="section-note">等待运行结束</span>
        </div>
        <EmptyState
          title="报告尚未生成"
          description="工作台只会在运行完成后一次性展示程序生成的核验报告，不伪造逐节流式输出。你仍可在「运行研究」中查看真实 Agent 事件。"
        />
      </section>
    );
  }

  if (loading) {
    return <LoadingState label="正在读取核验报告" rows={4} />;
  }

  if (error) {
    return (
      <ErrorState
        title="报告读取失败"
        message={error}
        onRetry={() => setReloadKey((value) => value + 1)}
      />
    );
  }

  if (!report) {
    return (
      <EmptyState
        title="没有报告投影"
        description="后端未返回报告投影。请刷新任务或检查运行结果。"
      />
    );
  }

  function download() {
    if (!report) return;
    const blob = new Blob([report.markdown], {
      type: "text/markdown;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${detail.job_id}-verified-report.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section className="report-studio" aria-labelledby="report-title">
      <header className="report-head">
        <div>
          <p className="section-kicker">VERIFIED REPORT</p>
          <h2 id="report-title">
            {report.county}
            {report.focus}研究报告
          </h2>
          <p className="report-meta">
            <span className="badge badge-good">程序生成</span>
            <span>
              已核验 {report.verification.verified}/{report.verification.total}
            </span>
            <span>生成于 {formatTime(report.generated_at)}</span>
            <code>{report.provenance}</code>
          </p>
        </div>
        <div className="report-actions">
          <button type="button" onClick={download}>
            下载核验报告
          </button>
        </div>
      </header>

      <div className="report-tabs" role="tablist" aria-label="报告视图">
        <button
          id="report-tab-verified"
          type="button"
          role="tab"
          aria-selected={tab === "verified"}
          className={tab === "verified" ? "active" : ""}
          onClick={() => setTab("verified")}
        >
          核验报告
        </button>
        <button
          id="report-tab-disputes"
          type="button"
          role="tab"
          aria-selected={tab === "disputes"}
          className={tab === "disputes" ? "active" : ""}
          onClick={() => setTab("disputes")}
        >
          冲突与缺口
          <span className="tab-note">
            {report.conflicts.length + report.gaps.length}
          </span>
        </button>
        <button
          id="report-tab-narrative"
          type="button"
          role="tab"
          aria-selected={tab === "narrative"}
          className={tab === "narrative" ? "active" : ""}
          onClick={() => setTab("narrative")}
        >
          旧版叙述
          <span className="tab-note">{report.narrative.sections.length}</span>
        </button>
      </div>

      {tab === "verified" ? (
        <div
          className="report-layout"
          role="tabpanel"
          id="report-panel-verified"
          aria-labelledby="report-tab-verified"
        >
          <nav className="report-nav" aria-label="报告章节">
            <p className="nav-kicker">SECTIONS</p>
            {report.sections.map((section) => (
              <a key={section.id} href={`#report-${section.id}`}>
                <span>{section.order.toString().padStart(2, "0")}</span>
                {section.title}
              </a>
            ))}
            <div className="report-nav-meta">
              <p>{report.citations.length} 条编号引用</p>
              <p>{report.gaps.length} 个结构化缺口</p>
              <p>{report.conflicts.length} 组来源冲突</p>
            </div>
          </nav>

          <div className="report-body">
            <div className="verification-strip">
              <div>
                <span className="strip-label">核验</span>
                <strong>
                  {report.verification.verified} 条已支持 ·{" "}
                  {report.verification.unverified} 条未采信
                </strong>
              </div>
              <ul>
                {report.verification.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </div>

            {report.sections.map((section) => (
              <article
                key={section.id}
                id={`report-${section.id}`}
                className="report-section"
              >
                <header>
                  <h3>
                    <span className="section-order">
                      {section.order.toString().padStart(2, "0")}
                    </span>
                    {section.title}
                  </h3>
                  <span className="badge badge-good">{section.status}</span>
                </header>
                <MarkdownView markdown={section.content} />
                {section.citation_ids.length > 0 ? (
                  <div className="section-citations">
                    <span>引用</span>
                    {section.citation_ids.map((claimId) => {
                      const number = citationNumbers.get(claimId);
                      if (number === undefined) return null;
                      return (
                        <button
                          key={claimId}
                          id={`citation-${claimId}`}
                          type="button"
                          onClick={() => onCitation(claimId)}
                          title={`查看证据 ${claimId}`}
                        >
                          [{number}]
                        </button>
                      );
                    })}
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        </div>
      ) : tab === "disputes" ? (
        <DisputesPanel report={report} onCitation={onCitation} />
      ) : (
        <div
          className="narrative-panel"
          role="tabpanel"
          id="report-panel-narrative"
          aria-labelledby="report-tab-narrative"
        >
          <div className="narrative-note">
            <span className="badge badge-warn">
              {report.narrative.provenance === "native_sections"
                ? "原生章节"
                : "Markdown 拆分"}
            </span>
            <p>
              旧版叙述仅作背景材料，不参与核验报告事实表。
              {report.narrative.provenance === "markdown_split"
                ? "该模式没有原生章节结构，章节由已渲染 Markdown 确定性拆分而来。"
                : "章节来自快照模式的原生报告结构。"}
            </p>
          </div>
          {report.narrative.sections.length === 0 ? (
            <EmptyState
              title="没有旧版叙述"
              description={
                report.narrative.markdown_available
                  ? "报告文件存在，但没有可展示的章节。"
                  : "本次运行没有保存旧版叙述 Markdown。"
              }
            />
          ) : (
            report.narrative.sections.map((section) => (
              <article key={section.id} className="narrative-section">
                <h3>
                  <span className="section-order">
                    {section.order.toString().padStart(2, "0")}
                  </span>
                  {section.title}
                </h3>
                <MarkdownView markdown={section.content} />
              </article>
            ))
          )}
        </div>
      )}
    </section>
  );
}

function DisputesPanel({
  report,
  onCitation,
}: {
  report: ReportView;
  onCitation: (claimId: string) => void;
}) {
  const conflicts = report.conflicts;
  const claimConflicts = report.claim_conflicts;
  const gaps = report.gaps;

  return (
    <div
      className="disputes-panel"
      role="tabpanel"
      id="report-panel-disputes"
      aria-labelledby="report-tab-disputes"
    >
      <section className="dispute-block wide" aria-labelledby="conflicts-title">
        <header className="dispute-head">
          <div>
            <p className="section-kicker">CONFLICTS</p>
            <h3 id="conflicts-title">多来源数值冲突</h3>
          </div>
          <span className="badge badge-warn">{conflicts.length}</span>
        </header>
        {conflicts.length === 0 ? (
          <EmptyState
            title="没有记录数值冲突"
            description="这不代表来源之间不存在差异；只表示本次运行没有产生可比较的冲突记录。"
          />
        ) : (
          <ul className="conflict-list">
            {conflicts.map((conflict, index) => {
              const claims = asRecords(conflict.claims);
              const suggestion = asText(conflict.resolution_suggestion);
              return (
                <li
                  key={`${asText(conflict.indicator)}-${index}`}
                  className="conflict-card"
                >
                  <div className="conflict-head">
                    <strong>{asText(conflict.indicator) || "未标指标"}</strong>
                    <span className="badge badge-warn">
                      {conflictLabel(conflict.conflict_type)}
                    </span>
                  </div>
                  <p>{asText(conflict.description) || "未提供冲突描述。"}</p>
                  {claims.length > 0 ? (
                    <table className="conflict-claims">
                      <caption className="sr-only">冲突来源的数值与口径</caption>
                      <thead>
                        <tr>
                          <th scope="col">数值</th>
                          <th scope="col">年份</th>
                          <th scope="col">范围</th>
                          <th scope="col">来源</th>
                        </tr>
                      </thead>
                      <tbody>
                        {claims.map((claim, claimIndex) => (
                          <tr key={`${asText(claim.url)}-${claimIndex}`}>
                            <td>{asText(claim.value) || "—"}</td>
                            <td>{asText(claim.year) || "—"}</td>
                            <td>{asText(claim.scope) || "—"}</td>
                            <td>
                              {asText(claim.title) || "未标来源"}
                              {asText(claim.url) ? (
                                <span className="conflict-source">
                                  {asText(claim.url)}
                                </span>
                              ) : null}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : null}
                  {suggestion ? (
                    <p className="muted small">核验建议：{suggestion}</p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section
        className="dispute-block"
        aria-labelledby="claim-conflicts-title"
      >
        <header className="dispute-head">
          <div>
            <p className="section-kicker">VERIFIED CLAIMS</p>
            <h3 id="claim-conflicts-title">已核验结论冲突</h3>
          </div>
          <span className="badge badge-neutral">{claimConflicts.length}</span>
        </header>
        {claimConflicts.length === 0 ? (
          <EmptyState
            title="没有已核验结论互相冲突"
            description="只有具备独立支持且数值可比的结论才会进入这里。"
          />
        ) : (
          <ul className="claim-conflict-list">
            {claimConflicts.map((item, index) => {
              const claimId = asText(item.claim_id);
              const conflicting = Array.isArray(item.conflicting_claim_ids)
                ? item.conflicting_claim_ids.filter(
                    (value): value is string => typeof value === "string",
                  )
                : [];
              return (
                <li key={claimId || index}>
                  <div className="conflict-head">
                    <code>{claimId || "未标结论"}</code>
                    {claimId ? (
                      <button
                        type="button"
                        className="text-button"
                        onClick={() => onCitation(claimId)}
                      >
                        查看证据
                      </button>
                    ) : null}
                  </div>
                  {asText(item.reason) ? (
                    <p className="muted small">{asText(item.reason)}</p>
                  ) : null}
                  {conflicting.length > 0 ? (
                    <p className="muted small claim-conflict-refs">
                      冲突结论：
                      {conflicting.map((id) => (
                        <button
                          key={id}
                          type="button"
                          className="text-button"
                          onClick={() => onCitation(id)}
                        >
                          {id}
                        </button>
                      ))}
                    </p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className="dispute-block" aria-labelledby="gaps-title">
        <header className="dispute-head">
          <div>
            <p className="section-kicker">GAPS</p>
            <h3 id="gaps-title">结构化证据缺口</h3>
          </div>
          <span className="badge badge-warn">{gaps.length}</span>
        </header>
        {gaps.length === 0 ? (
          <EmptyState
            title="没有记录结构化缺口"
            description="这不代表现有证据已经充分；只表示本次运行没有产生缺口记录。"
          />
        ) : (
          <table className="gap-table">
            <caption className="sr-only">结构化证据缺口</caption>
            <thead>
              <tr>
                <th scope="col">子问题</th>
                <th scope="col">缺口</th>
                <th scope="col">缺失方面</th>
                <th scope="col">严重度</th>
              </tr>
            </thead>
            <tbody>
              {gaps.map((gap, index) => (
                <tr key={`${asText(gap.question_id)}-${index}`}>
                  <td>{asText(gap.question_id) || "—"}</td>
                  <td>{asText(gap.description) || "—"}</td>
                  <td>{asText(gap.missing_aspect) || "—"}</td>
                  <td>{asText(gap.severity) || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
