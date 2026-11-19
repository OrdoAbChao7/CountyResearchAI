export type GraphLayoutName = "cose" | "concentric";

/**
 * Cose is readable for small evidence graphs but blocks the main thread on
 * larger projections. Above this cutoff the canvas switches to a deterministic
 * concentric layout, which keeps 400-node graphs interactive.
 */
export const LARGE_GRAPH_NODE_THRESHOLD = 240;

export function chooseGraphLayout(nodeCount: number): GraphLayoutName {
  return nodeCount > LARGE_GRAPH_NODE_THRESHOLD ? "concentric" : "cose";
}

export function isLargeGraph(nodeCount: number): boolean {
  return nodeCount > LARGE_GRAPH_NODE_THRESHOLD;
}
