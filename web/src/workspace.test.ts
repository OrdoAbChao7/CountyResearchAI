import { describe, expect, it } from "vitest";
import type { EventOut } from "./api";
import {
  deriveTimeline,
  formatPercent,
  mergeEvents,
  readWorkspaceState,
  reduceEvents,
  workspaceSearch,
} from "./lib";

function event(
  seq: number,
  eventType: string,
  payload: Record<string, unknown> = {},
  createdAt = `2026-01-01T00:00:0${seq}Z`,
): EventOut {
  return {
    seq,
    event_type: eventType,
    payload,
    created_at: createdAt,
  };
}

describe("workspace URL state", () => {
  it("reads supported step and layout values", () => {
    expect(readWorkspaceState("?step=4&layout=graph&task=job_01")).toEqual({
      step: 4,
      layout: "graph",
      taskId: "job_01",
    });
  });

  it("rejects unsupported values and unsafe task ids", () => {
    expect(
      readWorkspaceState("?step=99&layout=hacked&task=<script>alert(1)</script>"),
    ).toEqual({ step: 1, layout: "split", taskId: null });
    expect(readWorkspaceState("?step=3&task=job-1.2")).toEqual({
      step: 3,
      layout: "split",
      taskId: "job-1.2",
    });
  });

  it("serializes defaults compactly and round-trips", () => {
    expect(workspaceSearch({ step: 1, layout: "split", taskId: null })).toBe("");
    const search = workspaceSearch({
      step: 4,
      layout: "workbench",
      taskId: "job_01",
    });
    expect(search).toBe("?step=4&layout=workbench&task=job_01");
    expect(readWorkspaceState(search)).toEqual({
      step: 4,
      layout: "workbench",
      taskId: "job_01",
    });
  });
});

describe("event reducer", () => {
  it("deduplicates by sequence and preserves event order", () => {
    const merged = mergeEvents(
      [event(2, "job.started"), event(1, "job.queued")],
      [event(2, "job.started"), event(3, "job.completed")],
    );
    expect(merged.map((item) => item.seq)).toEqual([1, 2, 3]);
  });

  it("tracks the last sequence across repeated merges", () => {
    const first = reduceEvents({ events: [], lastSeq: 0 }, [
      event(1, "job.queued"),
      event(2, "job.started"),
    ]);
    const second = reduceEvents(first, [
      event(2, "job.started"),
      event(4, "job.completed"),
    ]);
    expect(second.lastSeq).toBe(4);
    expect(second.events).toHaveLength(3);
  });
});

describe("agent timeline", () => {
  it("builds entries only from real lifecycle events", () => {
    const runs = deriveTimeline(
      [
        event(1, "agent.started", { agent: "economic" }),
        event(2, "agent.completed", {
          agent: "economic",
          content_chars: 1200,
        }),
        event(3, "retrieval.round.started", { round: 1 }),
        event(4, "reflection.completed", { turn: 1, is_sufficient: false }),
        event(5, "synthesis.started"),
        event(6, "synthesis.completed", { sections: 6 }),
        event(7, "report.rendered", { sections: 6 }),
      ],
      true,
    );
    expect(runs.map((run) => run.kind)).toEqual([
      "agent",
      "retrieval",
      "critic",
      "synthesis",
      "report",
    ]);
    expect(runs[0]).toMatchObject({
      label: "经济与财政 Agent",
      status: "completed",
      detail: "1200 字符分析",
    });
    expect(runs[1]).toMatchObject({
      status: "stopped",
      detail: "任务结束前未收到完成事件",
    });
    expect(runs[2]).toMatchObject({
      status: "completed",
      detail: "发现缺口或冲突",
    });
  });

  it("does not invent running agents for unknown events", () => {
    expect(
      deriveTimeline([event(1, "evidence.persisted", { items: 3 })], false),
    ).toEqual([]);
  });
});

describe("formatPercent", () => {
  it("formats numbers and missing values", () => {
    expect(formatPercent(0.678)).toBe("68%");
    expect(formatPercent(0)).toBe("0%");
    expect(formatPercent(null)).toBe("—");
    expect(formatPercent(undefined)).toBe("—");
    expect(formatPercent(Number.NaN)).toBe("—");
  });
});
