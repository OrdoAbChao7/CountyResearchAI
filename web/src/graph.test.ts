import { describe, expect, it } from "vitest";
import {
  LARGE_GRAPH_NODE_THRESHOLD,
  chooseGraphLayout,
  isLargeGraph,
} from "./graphLayout";

describe("graph layout selection", () => {
  it("keeps the cose layout for small and medium graphs", () => {
    expect(chooseGraphLayout(0)).toBe("cose");
    expect(chooseGraphLayout(LARGE_GRAPH_NODE_THRESHOLD)).toBe("cose");
  });

  it("switches to the bounded concentric layout above the threshold", () => {
    expect(chooseGraphLayout(LARGE_GRAPH_NODE_THRESHOLD + 1)).toBe("concentric");
    expect(chooseGraphLayout(400)).toBe("concentric");
    expect(isLargeGraph(400)).toBe(true);
    expect(isLargeGraph(LARGE_GRAPH_NODE_THRESHOLD)).toBe(false);
  });
});
