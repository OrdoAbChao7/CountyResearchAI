import { useEffect, useRef } from "react";
import cytoscape from "cytoscape";
import type { GraphEdge, GraphNode, GraphView } from "../api";
import { NODE_COLORS, STATUS_COLORS } from "../graphPalette";
import { chooseGraphLayout, isLargeGraph } from "../graphLayout";

interface Props {
  view: GraphView;
  focusId: string | null;
  showLabels?: boolean;
  onSelectNode: (node: GraphNode) => void;
  onSelectEdge: (edge: GraphEdge) => void;
}

const SANS =
  'system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';

// 参考 MiroFish 的呈现方式：节点退化成按类型上色的小圆点，文字移到节点右侧。
// 这样标签长度不再撑大节点，密集处也不会框挤框；类型交给颜色表达，
// 由筛选胶囊兼作图例。
const STYLES: cytoscape.StylesheetJson = [
  {
    selector: "node",
    style: {
      width: 17,
      height: 17,
      "background-color": NODE_COLORS.evidence,
      // 白色描边把点与连线、网格分开，是它看起来干净的另一半原因
      "border-width": 2,
      "border-color": "#ffffff",
      label: "data(label)",
      color: "#141414",
      "font-size": 11.5,
      "font-family": SANS,
      // 外置单行标签：短类型截更短，才能在 25 个节点的小画布里少压几处
      "text-wrap": "ellipsis",
      "text-max-width": "120px",
      "text-valign": "center",
      "text-halign": "right",
      "text-margin-x": 7,
      // 缩放过小时隐藏标签，避免糊成一片
      "min-zoomed-font-size": 6,
      "text-background-color": "#ffffff",
      "text-background-opacity": 0.85,
      "text-background-padding": "1px",
    },
  },
  {
    selector: "node.node-county",
    style: {
      "background-color": NODE_COLORS.county,
      width: 30,
      height: 30,
      "border-width": 3,
      "font-size": 13,
      "font-weight": "bold",
    },
  },
  {
    selector: "node.node-question",
    style: {
      "background-color": NODE_COLORS.question,
      width: 22,
      height: 22,
      "font-size": 12,
      // 图问题的文字最长，给足一行位置，超出仍省略
      "text-max-width": "168px",
    },
  },
  {
    selector: "node.node-evidence",
    style: {
      "background-color": NODE_COLORS.evidence,
      width: 17,
      height: 17,
      "font-size": 11,
      "text-max-width": "132px",
    },
  },
  // 证据的核验状态用描边环表达，填充仍表示「证据」这一类型
  {
    selector: "node.node-evidence.status-SUPPORTED",
    style: { "border-color": STATUS_COLORS.SUPPORTED, "border-width": 2.5 },
  },
  {
    selector: "node.node-evidence.status-NEEDS_REVIEW",
    style: { "border-color": STATUS_COLORS.NEEDS_REVIEW, "border-width": 2.5 },
  },
  {
    selector: "node.node-evidence.status-CONTRADICTED",
    style: { "border-color": STATUS_COLORS.CONTRADICTED, "border-width": 2.5 },
  },
  {
    selector: "node.node-evidence.status-INSUFFICIENT",
    style: {
      "border-color": STATUS_COLORS.INSUFFICIENT,
      "border-width": 2,
      "border-style": "dashed",
    },
  },
  {
    selector: "node.node-source",
    style: {
      "background-color": NODE_COLORS.source,
      shape: "diamond",
      width: 13,
      height: 13,
      "font-size": 10.5,
    },
  },
  {
    selector: "node.node-topic",
    style: {
      "background-color": NODE_COLORS.topic,
      width: 13,
      height: 13,
      "border-style": "dashed",
      "font-size": 10.5,
    },
  },
  {
    selector: "node.node-gap",
    style: {
      "background-color": NODE_COLORS.gap,
      shape: "diamond",
      width: 17,
      height: 17,
    },
  },
  {
    selector: "node.node-conflict",
    style: {
      "background-color": NODE_COLORS.conflict,
      shape: "hexagon",
      width: 24,
      height: 24,
    },
  },
  // 右半区的节点把标签挂到左边：同一条竖列上的两个节点就不会朝同一侧挤文字
  {
    selector: "node.label-left",
    style: { "text-halign": "left", "text-margin-x": -7 },
  },
  // 关掉标签后仍保留点云，悬停单个节点时再单独显示
  {
    selector: "node.hide-label",
    style: { "text-opacity": 0 },
  },
  {
    selector: "edge",
    style: {
      width: 1,
      "line-color": "rgba(20,20,20,.18)",
      "target-arrow-color": "rgba(20,20,20,.18)",
      "target-arrow-shape": "triangle",
      "curve-style": "bezier",
      // 同一对节点之间的多条边会自动错开曲率，不会叠成一根
      "control-point-step-size": 30,
      "arrow-scale": 0.7,
    },
  },
  {
    selector: "edge.edge-supported_by",
    style: { "line-color": "#3f5be0", "target-arrow-color": "#3f5be0" },
  },
  {
    selector: "edge.edge-has_question",
    style: {
      "line-color": "rgba(20,20,20,.35)",
      "target-arrow-color": "rgba(20,20,20,.35)",
    },
  },
  {
    selector: "edge.edge-cited_from",
    style: {
      "line-color": "rgba(20,20,20,.25)",
      "target-arrow-color": "rgba(20,20,20,.25)",
    },
  },
  {
    selector: "edge.edge-belongs_to",
    style: {
      "line-color": "rgba(20,20,20,.15)",
      "target-arrow-color": "rgba(20,20,20,.15)",
      "line-style": "dashed",
    },
  },
  {
    selector: "edge.edge-has_gap",
    style: {
      "line-color": "#ff9800",
      "target-arrow-color": "#ff9800",
      "line-style": "dashed",
    },
  },
  {
    selector: "edge.edge-conflicts_with",
    style: {
      "line-color": "#e02135",
      "target-arrow-color": "#e02135",
      "line-style": "dashed",
      width: 2,
    },
  },
  {
    selector: ".faded",
    style: { opacity: 0.16 },
  },
  {
    selector: "node.focused",
    style: { "border-width": 3, "border-color": "#141414" },
  },
];

export default function GraphCanvas({
  view,
  focusId,
  showLabels = true,
  onSelectNode,
  onSelectEdge,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const fitReadableRef = useRef<(() => void) | null>(null);
  const nodeMap = useRef(new Map<string, GraphNode>());
  const edgeMap = useRef(new Map<string, GraphEdge>());

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    nodeMap.current = new Map(view.nodes.map((node) => [node.id, node]));
    edgeMap.current = new Map(view.edges.map((edge) => [edge.id, edge]));

    const elements: cytoscape.ElementDefinition[] = [
      ...view.nodes.map((node) => ({
        data: {
          id: node.id,
          label: node.label,
          type: node.type,
          sublabel: node.sublabel,
          status: String(node.data.status ?? ""),
        },
        classes: [
          `node-${node.type}`,
          node.data.status ? `status-${String(node.data.status)}` : "",
        ]
          .filter(Boolean)
          .join(" "),
      })),
      ...view.edges.map((edge) => ({
        data: {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          type: edge.type,
          label: edge.label,
        },
        classes: `edge-${edge.type}`,
      })),
    ];

    const layoutName = chooseGraphLayout(view.nodes.length);
    const dense = isLargeGraph(view.nodes.length);
    const styles: cytoscape.StylesheetJson = dense
      ? [
          ...STYLES,
          {
            selector: "node",
            // 400 个节点的点云里，外置标签只会互相叠字；缩略级直接隐藏，
            // 悬停单个节点时再显示（见 mouseover 处理）
            style: { "text-opacity": 0 },
          },
          {
            selector: "node.node-evidence",
            style: { width: 9, height: 9, "border-width": 1.5 },
          },
          {
            selector: "node.node-source",
            style: { width: 7, height: 7, "border-width": 1 },
          },
          {
            selector: "node.node-county",
            style: { width: 18, height: 18, "border-width": 2 },
          },
          {
            selector: "node.node-question",
            style: { width: 12, height: 12 },
          },
          {
            selector: "edge",
            style: { "line-opacity": 0.28, width: 0.5 },
          },
        ]
      : STYLES;
    const layout: cytoscape.LayoutOptions =
      layoutName === "concentric"
        ? {
            name: "concentric",
            animate: false,
            fit: true,
            padding: 36,
            minNodeSpacing: 18,
            levelWidth: () => 3,
            concentric: (node: cytoscape.NodeSingular) => node.degree(false),
          }
        : {
            name: "cose",
            animate: false,
            fit: true,
            padding: 36,
            // 标签横排在节点右侧，横向留白比纵向更要紧：边距给到标签宽度量级，
            // 纵向多余的高度随后会被比例归一压掉。
            nodeRepulsion: () => 3200,
            idealEdgeLength: () => 120,
            edgeElasticity: () => 90,
            gravity: 1.1,
            componentSpacing: 50,
            nodeOverlap: 18,
            // 不要开 nodeDimensionsIncludeLabels：标签改成外置后，节点包围盒变成
            // 「宽而扁」，把这个算进布局会让 cose 把节点竖着摞成一列。
            numIter: 800,
            // 随机初始位置会让同一份数据每次排版都不一样，偶尔挤成一团；
            // 初始位置由下面的圆周撒点给定，保证布局可复现。
            randomize: false,
          };

    const cy = cytoscape({
      container,
      elements,
      style: styles,
      // 滚轮灵敏度：cytoscape 每个刻度大约放大 10^((delta/-250)*sens)，
      // 实测每格约为 4.8 × sens 个百分点。0.18 时只有 0.8%（几乎不动），
      // 1.5 时 7.2% 又太快，取 0.8 → 约 3.8%，介于两者之间
      wheelSensitivity: 0.8,
      minZoom: 0.18,
      maxZoom: 2.6,
      // 关掉框选：不按修饰键时任何拖动都只做平移，不会误开橡皮筋选择
      boxSelectionEnabled: false,
      panningEnabled: true,
      userPanningEnabled: true,
    });
    cyRef.current = cy;

    // 容器尚未布局（宽度近似 0，例如标签页在后台渲染）时，fit 会把整个图压成一个点，
    // 之后再也不会恢复。这种情况先挂起，等 ResizeObserver 报告可用尺寸再处理。
    const usable = () => container.clientWidth >= 120 && container.clientHeight >= 120;
    let pendingFit = false;

    // 证据图常呈竖向链式，纯 fit 会把字号压到 5px 级别而不可读。
    // 小图保底 0.75 倍缩放，超出的部分交由平移查看。
    const fitReadable = () => {
      if (!usable()) {
        pendingFit = true;
        return;
      }
      cy.fit(undefined, 36);
      if (!dense && cy.zoom() < 0.75) {
        cy.zoom(0.75);
        cy.center();
      }
    };
    // 证据图常被拉成竖长链，画布却是横向的，fit 后只能得到 0.5 左右的缩放。
    // 这里只压缩纵轴（标签是横排的，纵向压缩不易互相遮挡），让内容比例贴近画布。
    // 每次都从「布局刚结束时的坐标」重算，所以重复调用是幂等的：画布比例变化
    // （切分栏、拉窗口）时会重新贴合，而不是越压越扁。
    const basePositions = new Map<string, { x: number; y: number }>();
    const normalizeAspect = () => {
      if (!usable() || basePositions.size === 0) return;
      let x1 = Infinity;
      let x2 = -Infinity;
      let y1 = Infinity;
      let y2 = -Infinity;
      basePositions.forEach(({ x, y }) => {
        x1 = Math.min(x1, x);
        x2 = Math.max(x2, x);
        y1 = Math.min(y1, y);
        y2 = Math.max(y2, y);
      });
      const width = x2 - x1;
      const height = y2 - y1;
      if (!width || !height) return;
      // 最多压到 0.6：再压就是把节点叠在一起，宁可让字号小一点
      const scale = Math.min(
        1,
        Math.max(
          0.6,
          (width * container.clientHeight) / (height * container.clientWidth),
        ),
      );
      const midY = (y1 + y2) / 2;
      cy.batch(() => {
        cy.nodes().forEach((node) => {
          const base = basePositions.get(node.id());
          if (base) {
            node.position({ x: base.x, y: midY + (base.y - midY) * scale });
          }
        });
      });
    };

    fitReadableRef.current = fitReadable;

    // cose 从随机初值出发，同一份数据每次排版可能差别很大（偶尔挤成一团）。
    // 按 id 排序后均匀铺在一个圆周上作为确定性初值，布局就稳定可复现。
    if (layoutName === "cose") {
      const seeded = cy.nodes().sort((a, b) => (a.id() < b.id() ? -1 : 1));
      const radius = Math.max(140, Math.sqrt(seeded.length) * 80);
      seeded.forEach((node, index) => {
        const angle = (index / Math.max(1, seeded.length)) * Math.PI * 2;
        node.position({ x: Math.cos(angle) * radius, y: Math.sin(angle) * radius });
      });
    }

    cy.one("layoutstop", () => {
      if (!usable()) {
        pendingFit = true;
        return;
      }
      cy.nodes().forEach((node) => {
        const { x, y } = node.position();
        basePositions.set(node.id(), { x, y });
      });
      if (!dense) {
        // 右半区的节点标签改挂左侧，把密集处的文字分散到两边。
        // 中线按「节点中心」算，不能用带标签的包围盒：标签都在右侧，
        // 会把中线推右，几乎所有节点都被判到左半区。
        let minX = Infinity;
        let maxX = -Infinity;
        basePositions.forEach(({ x }) => {
          minX = Math.min(minX, x);
          maxX = Math.max(maxX, x);
        });
        const midX = (minX + maxX) / 2;
        cy.batch(() => {
          cy.nodes().forEach((node) => {
            // 左半区朝左、右半区朝右：标签一律朝外，不会在对角线方向顶到一起
            node.toggleClass("label-left", node.position("x") <= midX);
          });
        });
        normalizeAspect();
      }
      fitReadable();
    });
    cy.layout(layout).run();

    // 小图上密集处标签仍会互相压住：悬停时把该节点提到最上层并放宽省略宽度，
    // 让用户能就地读完整标签，而不必先点开右侧详情。
    // 放宽标签会触发该节点的文字重新排版，扫过画布时不值得每次都做，
    // 因此只在指针停留 120ms 之后才展开（拖动平移时基本不会触发）。
    let hoverTimer = 0;
    cy.on("mouseover", "node", (event: cytoscape.EventObject) => {
      const node = event.target;
      node.style("z-index", 999);
      window.clearTimeout(hoverTimer);
      hoverTimer = window.setTimeout(() => {
        node.style({ "text-max-width": "300px", "text-opacity": 1 });
      }, 120);
    });
    cy.on("mouseout", "node", (event: cytoscape.EventObject) => {
      window.clearTimeout(hoverTimer);
      event.target.removeStyle("z-index text-max-width text-opacity");
    });

    cy.on("tap", "node", (event: cytoscape.EventObject) => {
      const node = nodeMap.current.get(event.target.id());
      if (node) onSelectNode(node);
    });
    cy.on("tap", "edge", (event: cytoscape.EventObject) => {
      const edge = edgeMap.current.get(event.target.id());
      if (edge) onSelectEdge(edge);
    });
    cy.on("tap", (event: cytoscape.EventObject) => {
      if (event.target === cy) {
        // Preserve the current selection; background taps should not fabricate one.
      }
    });

    const observer = new ResizeObserver(() => {
      cy.resize();
      if (pendingFit && usable()) {
        // 首次可用尺寸出现：这时才补做比例归一与适配
        pendingFit = false;
        cy.nodes().forEach((node) => {
          const { x, y } = node.position();
          basePositions.set(node.id(), { x, y });
        });
        if (!dense) normalizeAspect();
        fitReadable();
        return;
      }
      // 画布比例变了，重新贴合一次（幂等，不会越压越扁）
      if (!dense) normalizeAspect();
      fitReadable();
    });
    observer.observe(container);

    return () => {
      window.clearTimeout(hoverTimer);
      observer.disconnect();
      cy.destroy();
      cyRef.current = null;
    };
  }, [view, onSelectNode, onSelectEdge]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.nodes().toggleClass("hide-label", !showLabels);
  }, [showLabels, view]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().removeClass("faded focused");
    if (!focusId) {
      if (fitReadableRef.current) fitReadableRef.current();
      else cy.fit(undefined, 36);
      return;
    }
    const node = cy.getElementById(focusId);
    if (node.empty()) return;
    const neighborhood = node.closedNeighborhood();
    cy.elements().difference(neighborhood).addClass("faded");
    node.addClass("focused");
    cy.fit(neighborhood, 50);
  }, [focusId]);

  return (
    <div
      ref={containerRef}
      className="graph-canvas"
      aria-hidden="true"
      data-testid="graph-canvas"
      data-layout={chooseGraphLayout(view.nodes.length)}
      data-node-count={view.nodes.length}
      data-edge-count={view.edges.length}
    />
  );
}
