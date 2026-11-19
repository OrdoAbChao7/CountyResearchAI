import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from "react";
import type { GraphEdge, GraphNode, GraphNodeType, GraphView } from "../api";
import { getGraph } from "../api";
import { EmptyState, ErrorState, LoadingState } from "./StateViews";

const GraphCanvas = lazy(() => import("./GraphCanvas"));

interface Props {
  jobId: string;
  terminal: boolean;
  selectedNodeId: string | null;
  onSelectNode: (node: GraphNode | null) => void;
  onEvidence: (claimId: string) => void;
  onOpenReport: (claimId: string) => void;
}

const TYPE_LABELS: Record<GraphNodeType, string> = {
  county: "县域",
  question: "问题",
  evidence: "证据",
  source: "来源",
  topic: "指标",
  gap: "缺口",
  conflict: "冲突",
};

const ALL_TYPES: GraphNodeType[] = [
  "county",
  "question",
  "evidence",
  "source",
  "topic",
  "gap",
  "conflict",
];

export function GraphPanel({
  jobId,
  terminal,
  selectedNodeId,
  onSelectNode,
  onEvidence,
  onOpenReport,
}: Props) {
  const [graph, setGraph] = useState<GraphView | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [includeSources, setIncludeSources] = useState(true);
  const [topic, setTopic] = useState("");
  const [query, setQuery] = useState("");
  const [visibleTypes, setVisibleTypes] = useState<Set<GraphNodeType>>(
    () => new Set(ALL_TYPES),
  );
  const [viewMode, setViewMode] = useState<"graph" | "list">("graph");
  const [topicOptions, setTopicOptions] = useState<string[]>([]);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!terminal) {
      setGraph(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    getGraph(jobId, {
      maxNodes: 400,
      maxEdges: 800,
      includeSources,
      topics: topic ? [topic] : undefined,
    })
      .then((loaded) => {
        if (cancelled) return;
        setGraph(loaded);
        if (!topic) {
          setTopicOptions(
            loaded.nodes
              .filter((node) => node.type === "topic")
              .map((node) => node.label)
              .sort((left, right) => left.localeCompare(right, "zh-CN")),
          );
        }
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
  }, [jobId, terminal, includeSources, topic, reloadKey]);

  const filtered = useMemo(() => {
    if (!graph) return null;
    const needle = query.trim().toLowerCase();
    const allowed = new Set(
      graph.nodes
        .filter((node) => visibleTypes.has(node.type))
        .filter((node) => {
          if (!needle) return true;
          return `${node.label} ${node.sublabel}`
            .toLowerCase()
            .includes(needle);
        })
        .map((node) => node.id),
    );
    return {
      nodes: graph.nodes.filter((node) => allowed.has(node.id)),
      edges: graph.edges.filter(
        (edge) => allowed.has(edge.source) && allowed.has(edge.target),
      ),
    };
  }, [graph, query, visibleTypes]);

  const displayView = useMemo<GraphView | null>(() => {
    if (!graph || !filtered) return null;
    return { ...graph, nodes: filtered.nodes, edges: filtered.edges };
  }, [graph, filtered]);

  const handleSelectNode = useCallback(
    (node: GraphNode) => {
      onSelectNode(node);
      if (node.type === "evidence" && typeof node.data.claim_id === "string") {
        onEvidence(node.data.claim_id);
      }
    },
    [onSelectNode, onEvidence],
  );

  const handleSelectEdge = useCallback(
    (edge: GraphEdge) => {
      const source =
        graph?.nodes.find((node) => node.id === edge.source) ?? null;
      if (source) onSelectNode(source);
    },
    [graph, onSelectNode],
  );

  function toggleType(type: GraphNodeType) {
    setVisibleTypes((current) => {
      const next = new Set(current);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }

  if (!terminal) {
    return (
      <section className="graph-panel" aria-labelledby="graph-title">
        <div className="section-heading">
          <h2 id="graph-title">证据图谱</h2>
          <span className="section-note">等待运行结束</span>
        </div>
        <EmptyState
          title="图谱尚未生成"
          description="问题树、证据项、来源、冲突与缺口在运行完成后从持久化结果投影，不在运行中伪造节点。"
        />
      </section>
    );
  }

  if (loading && !graph) return <LoadingState label="正在构建证据图谱" rows={5} />;
  if (error) {
    return (
      <ErrorState
        title="图谱读取失败"
        message={error}
        onRetry={() => setReloadKey((value) => value + 1)}
      />
    );
  }
  if (!graph || !filtered) {
    return (
      <EmptyState
        title="没有图谱投影"
        description="该运行没有深度研究产物，或图谱投影不可用。"
      />
    );
  }

  return (
    <section className="graph-panel" aria-labelledby="graph-title">
      <div className="section-heading">
        <div>
          <p className="section-kicker">EVIDENCE GRAPH</p>
          <h2 id="graph-title">证据图谱</h2>
        </div>
        <div className="graph-stats">
          <span>
            {graph.meta.returned_nodes}/{graph.meta.total_nodes} 节点
          </span>
          <span>
            {graph.meta.returned_edges}/{graph.meta.total_edges} 边
          </span>
          {graph.meta.truncated ? (
            <span className="badge badge-warn">已截断</span>
          ) : null}
          {graph.meta.unmatched_conflicts > 0 ? (
            <span className="badge badge-bad">
              {graph.meta.unmatched_conflicts} 组冲突未匹配
            </span>
          ) : null}
        </div>
      </div>

      <div className="graph-toolbar">
        <label className="inline-field">
          搜索节点
          <input
            value={query}
            placeholder="标签或副标题"
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <label className="inline-field">
          指标主题
          <select value={topic} onChange={(event) => setTopic(event.target.value)}>
            <option value="">全部指标</option>
            {topicOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={includeSources}
            onChange={(event) => setIncludeSources(event.target.checked)}
          />
          显示来源节点
        </label>
        <div className="view-switch" role="tablist" aria-label="图谱视图">
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === "graph"}
            className={viewMode === "graph" ? "active" : ""}
            onClick={() => setViewMode("graph")}
          >
            图形
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === "list"}
            className={viewMode === "list" ? "active" : ""}
            onClick={() => setViewMode("list")}
          >
            列表
          </button>
        </div>
      </div>

      <div className="type-filters" aria-label="节点类型筛选">
        {ALL_TYPES.map((type) => {
          const count = graph.meta.counts[type] ?? 0;
          return (
            <button
              key={type}
              type="button"
              className={`filter-chip ${visibleTypes.has(type) ? "active" : ""}`}
              aria-pressed={visibleTypes.has(type)}
              onClick={() => toggleType(type)}
            >
              {TYPE_LABELS[type]}
              <span>{count}</span>
            </button>
          );
        })}
      </div>

      {filtered.nodes.length === 0 ? (
        <EmptyState
          title="筛选后没有节点"
          description="恢复节点类型或清空搜索条件。"
        />
      ) : viewMode === "graph" ? (
        <Suspense fallback={<LoadingState label="正在加载图形画布" rows={3} />}>
          <GraphCanvas
            view={displayView ?? graph}
            focusId={selectedNodeId}
            onSelectNode={handleSelectNode}
            onSelectEdge={handleSelectEdge}
          />
        </Suspense>
      ) : (
        <GraphListView
          nodes={filtered.nodes}
          edges={filtered.edges}
          selectedNodeId={selectedNodeId}
          onSelectNode={handleSelectNode}
          onEvidence={onEvidence}
          onOpenReport={onOpenReport}
        />
      )}

      <p className="graph-footnote">
        图谱只展示本次运行持久化的问题、证据、来源与冲突关系；来源节点按规范化
        URL 合并，缺失冲突来源不会生成虚构连线。
      </p>
    </section>
  );
}

function GraphListView({
  nodes,
  edges,
  selectedNodeId,
  onSelectNode,
  onEvidence,
  onOpenReport,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedNodeId: string | null;
  onSelectNode: (node: GraphNode) => void;
  onEvidence: (claimId: string) => void;
  onOpenReport: (claimId: string) => void;
}) {
  const byId = useMemo(
    () => new Map(nodes.map((node) => [node.id, node])),
    [nodes],
  );
  return (
    <div className="graph-list-view">
      <table>
        <caption className="sr-only">证据图谱节点列表</caption>
        <thead>
          <tr>
            <th scope="col">类型</th>
            <th scope="col">节点</th>
            <th scope="col">副标题</th>
            <th scope="col">操作</th>
          </tr>
        </thead>
        <tbody>
          {nodes.map((node) => (
            <tr
              key={node.id}
              className={selectedNodeId === node.id ? "selected" : ""}
            >
              <td>
                <span className={`type-tag type-${node.type}`}>
                  {TYPE_LABELS[node.type]}
                </span>
              </td>
              <th scope="row">
                <button type="button" onClick={() => onSelectNode(node)}>
                  {node.label}
                </button>
              </th>
              <td>{node.sublabel || "—"}</td>
              <td className="row-actions">
                {node.type === "evidence" &&
                typeof node.data.claim_id === "string" ? (
                  <>
                    <button
                      type="button"
                      onClick={() => onEvidence(String(node.data.claim_id))}
                    >
                      打开证据
                    </button>
                    <button
                      type="button"
                      onClick={() => onOpenReport(String(node.data.claim_id))}
                    >
                      报告定位
                    </button>
                  </>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <details className="edge-details">
        <summary>关系列表（{edges.length}）</summary>
        <ul>
          {edges.map((edge) => (
            <li key={edge.id}>
              <code>{edge.type}</code>{" "}
              {byId.get(edge.source)?.label ?? edge.source} →{" "}
              {byId.get(edge.target)?.label ?? edge.target}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
