import type { GraphNodeType } from "./api";

/**
 * 图谱节点配色：参考 MiroFish 的「按类型上色 + 图例」做法，但收敛到本项目
 * 的克制色系（单强调色 + 状态色），不再引入彩虹相板。
 *
 * 这些颜色既用于画布节点，也用于筛选胶囊前的色点，保持两处一致。
 */
export const NODE_COLORS: Record<GraphNodeType, string> = {
  county: "#2f4ad0",
  question: "#7a3fa8",
  evidence: "#0f7f74",
  source: "#8c9199",
  topic: "#6b7a3a",
  gap: "#a86400",
  conflict: "#c81b2d",
};

/** 证据节点的状态环颜色：填充表示类型，环表示核验状态。 */
export const STATUS_COLORS: Record<string, string> = {
  SUPPORTED: "#007a45",
  NEEDS_REVIEW: "#d97b00",
  CONTRADICTED: "#c81b2d",
  INSUFFICIENT: "rgba(20,20,20,.45)",
};
