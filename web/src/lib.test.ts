import { describe, expect, it } from "vitest";
import {
  formatTime,
  isTerminal,
  outcomeLabel,
  statusLabel,
  summarizePayload,
  verificationLabel,
} from "./lib";

describe("status helpers", () => {
  it("knows which statuses are terminal", () => {
    expect(isTerminal("RUNNING")).toBe(false);
    expect(isTerminal("QUEUED")).toBe(false);
    for (const status of [
      "SUCCEEDED",
      "FAILED",
      "CANCELLED",
      "BUDGET_EXHAUSTED",
      "INTERRUPTED",
    ]) {
      expect(isTerminal(status)).toBe(true);
    }
  });

  it("labels unknown values without crashing", () => {
    expect(statusLabel("SUCCEEDED")).toBe("已完成");
    expect(statusLabel("WHAT")).toBe("WHAT");
    expect(outcomeLabel(null)).toBe("进行中");
    expect(outcomeLabel("SUFFICIENT")).toBe("证据充分");
    expect(verificationLabel("INSUFFICIENT")).toBe("证据不足");
  });

  it("formats payloads deterministically", () => {
    expect(summarizePayload({})).toBe("");
    expect(summarizePayload({ documents: 3, focus: "竹产业" })).toBe(
      "documents=3 · focus=竹产业",
    );
  });

  it("returns the raw value for invalid timestamps", () => {
    expect(formatTime("not-a-date")).toBe("not-a-date");
  });
});
