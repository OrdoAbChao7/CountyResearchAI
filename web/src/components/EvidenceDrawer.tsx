import { useEffect, useMemo, useRef, useState } from "react";
import type {
  EvidenceItemView,
  EvidenceListResponse,
  SourceDetailOut,
} from "../api";
import { getSource, listEvidence } from "../api";
import { formatTime, verificationLabel } from "../lib";
import { SourceContentView } from "./SourceContentView";
import { EmptyState, ErrorState, LoadingState } from "./StateViews";

interface Props {
  jobId: string | null;
  open: boolean;
  focusClaimId: string | null;
  onClose: () => void;
  onSelect?: (item: EvidenceItemView | null) => void;
}

const STATUS_OPTIONS = [
  "",
  "SUPPORTED",
  "NEEDS_REVIEW",
  "CONTRADICTED",
  "OUTDATED",
  "NOT_COMPARABLE",
  "INSUFFICIENT",
];

export function EvidenceDrawer({
  jobId,
  open,
  focusClaimId,
  onClose,
  onSelect,
}: Props) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [topic, setTopic] = useState("");
  const [minCredibility, setMinCredibility] = useState(0);
  const [data, setData] = useState<EvidenceListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<EvidenceItemView | null>(null);
  const [source, setSource] = useState<SourceDetailOut | null>(null);
  const [sourceQuote, setSourceQuote] = useState("");
  const [sourceError, setSourceError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const drawerRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) return undefined;
    const previous = document.activeElement as HTMLElement | null;
    const focusTimer = window.setTimeout(() => closeRef.current?.focus(), 30);

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const root = drawerRef.current;
      if (!root) return;
      const focusable = Array.from(
        root.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => element.offsetParent !== null);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    window.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(focusTimer);
      window.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, [open, onClose]);

  useEffect(() => {
    if (!open || !focusClaimId) return;
    setQuery("");
    setStatus("");
    setTopic("");
    setMinCredibility(0);
  }, [open, focusClaimId]);

  useEffect(() => {
    if (!open || !jobId) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    listEvidence(jobId, {
      q: query.trim() || undefined,
      status: status || undefined,
      topic: topic.trim() || undefined,
      minCredibility: minCredibility || undefined,
      limit: 200,
    })
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
  }, [open, jobId, query, status, topic, minCredibility, reloadKey]);

  useEffect(() => {
    if (!data) return;
    if (focusClaimId) {
      const match = data.items.find((item) => item.claim_id === focusClaimId);
      if (match) {
        setSelected(match);
        onSelect?.(match);
        return;
      }
    }
    setSelected((current) => {
      if (current && data.items.some((item) => item.claim_id === current.claim_id)) {
        return current;
      }
      return null;
    });
    // onSelect is a stable callback from the app shell.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, focusClaimId]);

  const selectedLink = useMemo(
    () => selected?.links.find((link) => link.relation !== "contradicts") ?? selected?.links[0],
    [selected],
  );

  async function openSource(snapshotId: string, quote: string) {
    setSourceError("");
    try {
      const detail = await getSource(snapshotId);
      setSource(detail);
      setSourceQuote(quote);
    } catch (caught) {
      setSourceError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  function choose(item: EvidenceItemView) {
    setSelected(item);
    setSource(null);
    setSourceQuote("");
    onSelect?.(item);
  }

  if (!open || !jobId) return null;

  return (
    <div className="drawer-backdrop" onMouseDown={onClose}>
      <aside
        ref={drawerRef}
        className="evidence-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="evidence-drawer-title"
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="drawer-head">
          <div>
            <p className="section-kicker">EVIDENCE DRAWER</p>
            <h2 id="evidence-drawer-title">证据抽屉</h2>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="关闭证据抽屉"
          >
            关闭
          </button>
        </header>

        <div className="drawer-filters">
          <label>
            搜索
            <input
              value={query}
              placeholder="指标、结论或来源标题"
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <label>
            状态
            <select value={status} onChange={(event) => setStatus(event.target.value)}>
              {STATUS_OPTIONS.map((option) => (
                <option key={option || "all"} value={option}>
                  {option ? verificationLabel(option) : "全部状态"}
                </option>
              ))}
            </select>
          </label>
          <label>
            主题
            <input
              value={topic}
              placeholder="如 竹产业"
              onChange={(event) => setTopic(event.target.value)}
            />
          </label>
          <label>
            最低可信度
            <select
              value={minCredibility}
              onChange={(event) => setMinCredibility(Number(event.target.value))}
            >
              <option value={0}>不限</option>
              <option value={0.5}>0.5</option>
              <option value={0.8}>0.8</option>
              <option value={0.9}>0.9</option>
            </select>
          </label>
        </div>

        <div className="drawer-body">
          <div className="drawer-list" aria-busy={loading}>
            {loading ? <LoadingState label="正在读取证据" rows={3} /> : null}
            {error ? (
              <ErrorState
                message={error}
                onRetry={() => setReloadKey((value) => value + 1)}
              />
            ) : null}
            {!loading && !error && data && data.items.length === 0 ? (
              <EmptyState
                title="没有匹配的证据"
                description="尝试清除筛选条件，或确认该运行是否已持久化证据。"
              />
            ) : null}
            {data && data.items.length > 0 ? (
              <>
                <p className="drawer-count">
                  显示 {data.items.length} / {data.total} 条
                </p>
                <ul>
                  {data.items.map((item) => (
                    <li key={item.claim_id}>
                      <button
                        type="button"
                        className={`evidence-row ${
                          selected?.claim_id === item.claim_id ? "selected" : ""
                        }`}
                        onClick={() => choose(item)}
                        aria-current={
                          selected?.claim_id === item.claim_id ? "true" : undefined
                        }
                      >
                        <span className="evidence-row-head">
                          <span className="citation-chip">
                            {item.citation_number ? `[${item.citation_number}]` : "—"}
                          </span>
                          <span className={`status-dot status-${item.status}`}>
                            {verificationLabel(item.status)}
                          </span>
                          <span className="credibility">
                            可信度 {item.credibility.toFixed(2)}
                          </span>
                        </span>
                        <span className="evidence-statement">{item.statement}</span>
                        <span className="evidence-meta">
                          <span>{item.metric || "未标指标"}</span>
                          <span>
                            {item.value}
                            {item.unit}
                          </span>
                          <span>{item.period || "未标期间"}</span>
                          {item.topic ? <span>{item.topic}</span> : null}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </div>

          <div className="drawer-detail">
            {!selected ? (
              <EmptyState
                title="选择一条证据"
                description="查看结论、确定性校验原因、精确引文与来源快照。"
              />
            ) : (
              <>
                <div className="detail-block">
                  <div className="detail-heading">
                    <h3>{selected.statement}</h3>
                    <span className={`status-dot status-${selected.status}`}>
                      {verificationLabel(selected.status)}
                    </span>
                  </div>
                  <dl className="evidence-facts">
                    <div>
                      <dt>指标</dt>
                      <dd>{selected.metric || "—"}</dd>
                    </div>
                    <div>
                      <dt>数值</dt>
                      <dd>
                        {selected.value}
                        {selected.unit}
                      </dd>
                    </div>
                    <div>
                      <dt>期间</dt>
                      <dd>{selected.period || "—"}</dd>
                    </div>
                    <div>
                      <dt>范围</dt>
                      <dd>{selected.scope || "—"}</dd>
                    </div>
                    <div>
                      <dt>口径</dt>
                      <dd>{selected.caliber || "—"}</dd>
                    </div>
                    <div>
                      <dt>编号</dt>
                      <dd>
                        {selected.citation_number
                          ? `[${selected.citation_number}]`
                          : "—"}
                      </dd>
                    </div>
                  </dl>
                  {selected.reason ? (
                    <p className="muted small">校验原因: {selected.reason}</p>
                  ) : null}
                  {selected.question_ids.length > 0 ? (
                    <p className="muted small">
                      关联问题: {selected.question_ids.join("、")}
                    </p>
                  ) : null}
                </div>

                <div className="detail-block">
                  <h3>证据链</h3>
                  {selected.links.length === 0 ? (
                    <p className="muted small">没有可追溯的引文。</p>
                  ) : (
                    selected.links.map((link) => (
                      <div
                        key={`${link.span_id}-${link.relation}`}
                        className="quote-block"
                      >
                        <div className="quote-head">
                          <code>{link.span_id}</code>
                          <span>关系 {link.relation}</span>
                          <span>
                            偏移 {link.start_offset ?? "?"}–
                            {link.end_offset ?? "?"}
                          </span>
                          <button
                            type="button"
                            onClick={() => void openSource(link.snapshot_id, link.quote)}
                          >
                            查看来源
                          </button>
                        </div>
                        <blockquote>{link.quote}</blockquote>
                        <p className="muted small">
                          {link.title || link.snapshot_id}
                          {link.url ? ` · ${link.url}` : ""}
                        </p>
                      </div>
                    ))
                  )}
                  {selectedLink ? (
                    <p className="muted small">
                      首要来源: {selectedLink.title || selectedLink.url}
                    </p>
                  ) : null}
                </div>

                {sourceError ? <p className="error-text">{sourceError}</p> : null}
                {source ? (
                  <div className="detail-block">
                    <div className="detail-heading">
                      <h3>{source.title || source.snapshot_id}</h3>
                      <button type="button" onClick={() => setSource(null)}>
                        收起
                      </button>
                    </div>
                    <p className="muted small">
                      {source.url || "（无 URL）"} · 观测{" "}
                      {source.observed_at ? formatTime(source.observed_at) : "未知"}
                    </p>
                    <SourceContentView content={source.content} quote={sourceQuote} />
                  </div>
                ) : null}
              </>
            )}
          </div>
        </div>
      </aside>
    </div>
  );
}
