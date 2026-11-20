import { useEffect, useRef } from "react";
import cytoscape from "cytoscape";
import type { GraphEdge, GraphNode, GraphView } from "../api";
import { chooseGraphLayout, isLargeGraph } from "../graphLayout";

interface Props {
  view: GraphView;
  focusId: string | null;
  onSelectNode: (node: GraphNode) => void;
  onSelectEdge: (edge: GraphEdge) => void;
}

const STYLES: cytoscape.StylesheetJson = [
  {
    selector: "node",
    style: {
      "background-color": "#161616",
      "border-width": 1,
      "border-color": "#4a4a4a",
      color: "#f4f4ef",
      label: "data(label)",
      "font-size": 10,
      "font-family": "Consolas, monospace",
      "text-wrap": "ellipsis",
      "text-max-width": "110px",
      "text-valign": "center",
      "text-halign": "center",
      width: 34,
      height: 34,
    },
  },
  {
    selector: "node.node-county",
    style: {
      "background-color": "#ff6b1a",
      "border-color": "#ff6b1a",
      color: "#111111",
      shape: "round-rectangle",
      width: 86,
      height: 38,
      "font-size": 12,
      "font-weight": "bold",
    },
  },
  {
    selector: "node.node-question",
    style: {
      "background-color": "#f4f4ef",
      "border-color": "#f4f4ef",
      color: "#111111",
      shape: "round-rectangle",
      width: 120,
      height: 44,
      "text-max-width": "110px",
    },
  },
  {
    selector: "node.node-evidence",
    style: {
      "background-color": "#1e1e1e",
      "border-color": "#ff6b1a",
      "border-width": 1.5,
      shape: "ellipse",
    },
  },
  {
    selector: "node.node-evidence.status-SUPPORTED",
    style: { "border-color": "#7fd6a2", "border-width": 2 },
  },
  {
    selector: "node.node-evidence.status-NEEDS_REVIEW",
    style: { "border-color": "#ffb347", "border-width": 2 },
  },
  {
    selector: "node.node-evidence.status-CONTRADICTED",
    style: { "border-color": "#ff5f56", "border-width": 2 },
  },
  {
    selector: "node.node-evidence.status-INSUFFICIENT",
    style: { "border-color": "#6e6e6e", "border-style": "dashed" },
  },
  {
    selector: "node.node-source",
    style: {
      "background-color": "#2a2a2a",
      "border-color": "#8a8a8a",
      shape: "diamond",
      width: 24,
      height: 24,
      "font-size": 8,
    },
  },
  {
    selector: "node.node-topic",
    style: {
      "background-color": "#0d0d0d",
      "border-color": "#c9c9c2",
      "border-style": "dashed",
      shape: "round-rectangle",
      width: 74,
      height: 30,
      "font-size": 9,
    },
  },
  {
    selector: "node.node-gap",
    style: {
      "background-color": "#2a160b",
      "border-color": "#ffb347",
      shape: "diamond",
      width: 40,
      height: 40,
    },
  },
  {
    selector: "node.node-conflict",
    style: {
      "background-color": "#3a1010",
      "border-color": "#ff5f56",
      "border-width": 2,
      shape: "hexagon",
      width: 48,
      height: 48,
    },
  },
  {
    selector: "edge",
    style: {
      width: 1,
      "line-color": "#5f5f5f",
      "target-arrow-color": "#5f5f5f",
      "target-arrow-shape": "triangle",
      "curve-style": "bezier",
      "arrow-scale": 0.7,
    },
  },
  {
    selector: "edge.edge-supported_by",
    style: { "line-color": "#ff6b1a", "target-arrow-color": "#ff6b1a" },
  },
  {
    selector: "edge.edge-has_question",
    style: { "line-color": "#f4f4ef", "target-arrow-color": "#f4f4ef" },
  },
  {
    selector: "edge.edge-cited_from",
    style: { "line-color": "#6e6e6e", "target-arrow-color": "#6e6e6e" },
  },
  {
    selector: "edge.edge-belongs_to",
    style: {
      "line-color": "#3f3f3f",
      "target-arrow-color": "#3f3f3f",
      "line-style": "dashed",
    },
  },
  {
    selector: "edge.edge-has_gap",
    style: {
      "line-color": "#ffb347",
      "target-arrow-color": "#ffb347",
      "line-style": "dashed",
    },
  },
  {
    selector: "edge.edge-conflicts_with",
    style: {
      "line-color": "#ff5f56",
      "target-arrow-color": "#ff5f56",
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
    style: { "border-width": 3, "border-color": "#ffffff" },
  },
];

export default function GraphCanvas({
  view,
  focusId,
  onSelectNode,
  onSelectEdge,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
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
            style: { "min-zoomed-font-size": 9 },
          },
          {
            selector: "node.node-evidence",
            style: {
              "background-color": "#555555",
              "border-width": 2,
              width: 20,
              height: 20,
            },
          },
          {
            selector: "node.node-source",
            style: {
              "background-color": "#6a6a6a",
              "border-color": "#b0b0a8",
              width: 14,
              height: 14,
            },
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
            nodeRepulsion: () => 5200,
            idealEdgeLength: () => 92,
            edgeElasticity: () => 80,
            gravity: 0.28,
            numIter: 650,
            randomize: true,
          };

    const cy = cytoscape({
      container,
      elements,
      style: styles,
      layout,
      wheelSensitivity: 0.18,
      minZoom: 0.18,
      maxZoom: 2.6,
    });
    cyRef.current = cy;

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
      cy.fit(undefined, 36);
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      cy.destroy();
      cyRef.current = null;
    };
  }, [view, onSelectNode, onSelectEdge]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().removeClass("faded focused");
    if (!focusId) {
      cy.fit(undefined, 36);
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
