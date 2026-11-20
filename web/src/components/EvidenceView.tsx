import { useState } from "react";
import type { FindingOut, SourceDetailOut, SourceOut } from "../api";
import { getSource } from "../api";
import { formatTime, verificationLabel, VERIFICATION_ORDER } from "../lib";
import { Badge } from "./Badge";

interface Props {
  findings: FindingOut[];
  sources: SourceOut[];
}

interface OpenSource {
  detail: SourceDetailOut;
  quote: string;
}

const CHECK_KEYS = [
  "independent_support",
  "supporting_edges",
  "contradicting_supported_claims",
  "span_integrity_failures",
  "value_present",
  "period_present",
  "statement_in_quote",
];

export function EvidenceView({ findings, sources }: Props) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [openSource, setOpenSource] = useState<OpenSource | null>(null);
  const [sourceError, setSourceError] = useState("");

  async function showSource(snapshotId: string, quote: string) {
    setSourceError("");
    try {
      const detail = await getSource(snapshotId);
      setOpenSource({ detail, quote });
    } catch (error) {
      setSourceError(error instanceof Error ? error.message : String(error));
    }
  }

  if (findings.length === 0 && sources.length === 0) {
    return <p className="muted">本次运行没有持久化的证据。</p>;
  }

  const groups = VERIFICATION_ORDER.map((status) => ({
    status,
    items: findings.filter((finding) => finding.status === status),
  })).filter((group) => group.items.length > 0);

  return (
    <div className="evidence-layout">
      <div className="evidence-main">
        <p className="hint">
          确定性校验只确认引文偏移、哈希、数值、单位、期间与口径；它不是语义蕴含证明。
        </p>
        {sourceError ? <p className="error-text">{sourceError}</p> : null}
        {groups.length === 0 ? <p className="muted">没有结构化结论。</p> : null}
        {groups.map((group) => (
          <section key={group.status} className="finding-group">
            <h3>
              <Badge value={group.status}>{verificationLabel(group.status)}</Badge>
              <span className="count">{group.items.length}</span>
            </h3>
            {group.items.map((finding) => {
              const isOpen = Boolean(expanded[finding.finding_id]);
              return (
                <article key={finding.finding_id} className="finding-card">
                  <button
                    type="button"
                    className="finding-head"
                    onClick={() =>
                      setExpanded((current) => ({
                        ...current,
                        [finding.finding_id]: !current[finding.finding_id],
                      }))
                    }
                  >
                    <span className="finding-text">{finding.text}</span>
                    <span className="chevron">{isOpen ? "▾" : "▸"}</span>
                  </button>
                  <div className="finding-meta">
                    <code>{finding.claim.claim_id}</code>
                    <span>{finding.claim.metric || "未标指标"}</span>
                    <span>
                      {finding.claim.value}
                      {finding.claim.unit}
                    </span>
                    <span>{finding.claim.period || "未标期间"}</span>
                    <span>{finding.claim.scope || "未标范围"}</span>
                    {finding.claim.verification_reason ? (
                      <span className="muted">原因: {finding.claim.verification_reason}</span>
                    ) : null}
                  </div>
                  {isOpen ? (
                    <div className="finding-body">
                      {CHECK_KEYS.filter((key) => key in finding.checks).length > 0 ? (
                        <dl className="checks">
                          {CHECK_KEYS.filter((key) => key in finding.checks).map((key) => (
                            <div key={key}>
                              <dt>{key}</dt>
                              <dd>{String(finding.checks[key])}</dd>
                            </div>
                          ))}
                        </dl>
                      ) : null}
                      {finding.links.map((link) => (
                        <div key={`${link.span_id}-${link.relation}`} className="evidence-link">
                          <div className="evidence-link-head">
                            <code>{link.span_id}</code>
                            <span>关系: {link.relation}</span>
                            <span>偏移: {link.start_offset ?? "?"}–{link.end_offset ?? "?"}</span>
                            <button
                              type="button"
                              onClick={() => showSource(link.snapshot_id, link.quote)}
                            >
                              查看来源
                            </button>
                          </div>
                          <blockquote>{link.quote}</blockquote>
                          <p className="muted">
                            {link.title || link.snapshot_id}
                            {link.url ? ` · ${link.url}` : ""}
                          </p>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </article>
              );
            })}
          </section>
        ))}

        <section className="finding-group">
          <h3>来源快照 ({sources.length})</h3>
          {sources.map((source) => (
            <div key={source.snapshot_id} className="source-row">
              <div>
                <strong>{source.title || source.snapshot_id}</strong>
                <p className="muted">
                  {source.url || "（无 URL）"} · {source.source_type} · {source.fetch_status} ·{" "}
                  {source.content_length} 字符
                </p>
              </div>
              <button type="button" onClick={() => showSource(source.snapshot_id, "")}>
                打开
              </button>
            </div>
          ))}
        </section>
      </div>

      {openSource ? (
        <aside className="source-viewer">
          <div className="source-viewer-head">
            <h3>{openSource.detail.title || openSource.detail.snapshot_id}</h3>
            <button type="button" onClick={() => setOpenSource(null)}>
              关闭
            </button>
          </div>
          <p className="muted">
            {openSource.detail.url || "（无 URL）"} · 观测{" "}
            {openSource.detail.observed_at
              ? formatTime(openSource.detail.observed_at)
              : "未知"}
          </p>
          <SourceContent content={openSource.detail.content} quote={openSource.quote} />
        </aside>
      ) : null}
    </div>
  );
}

function SourceContent({ content, quote }: { content: string; quote: string }) {
  const index = quote ? content.indexOf(quote) : -1;
  if (index === -1) {
    return (
      <>
        {quote ? (
          <p className="warn-text">引文未能在快照正文中精确定位（可能已被截断或改写）。</p>
        ) : null}
        <pre className="source-content">{content}</pre>
      </>
    );
  }
  return (
    <pre className="source-content">
      {content.slice(0, index)}
      <mark>{quote}</mark>
      {content.slice(index + quote.length)}
    </pre>
  );
}
