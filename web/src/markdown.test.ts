import { describe, expect, it } from "vitest";
import {
  isSafeHref,
  parseInline,
  parseMarkdown,
} from "./lib/markdown";

describe("safe inline markdown", () => {
  it("parses emphasis, code and https links", () => {
    expect(parseInline("**重点** 与 `code`")).toEqual([
      { type: "strong", text: "重点" },
      { type: "text", text: " 与 " },
      { type: "code", text: "code" },
    ]);
    expect(parseInline("[来源](https://example.com/a)")).toEqual([
      { type: "link", text: "来源", href: "https://example.com/a" },
    ]);
  });

  it("does not emit links for javascript or data URLs", () => {
    const tokens = parseInline("[坏链接](javascript:alert(1))");
    expect(tokens.every((token) => token.type !== "link")).toBe(true);
    expect(isSafeHref("javascript:alert(1)")).toBe(false);
    expect(isSafeHref("data:text/html,<script>alert(1)</script>")).toBe(false);
    expect(isSafeHref("https://example.com")).toBe(true);
  });

  it("keeps raw HTML as literal text tokens", () => {
    const tokens = parseInline('<img src=x onerror=alert(1)>');
    expect(tokens).toEqual([
      { type: "text", text: '<img src=x onerror=alert(1)>' },
    ]);
  });
});

describe("safe block markdown", () => {
  it("parses headings, lists, quotes and tables", () => {
    const blocks = parseMarkdown(
      [
        "# 标题",
        "",
        "段落 **加粗**",
        "",
        "- 一",
        "- 二",
        "",
        "> 引用",
        "",
        "| 指标 | 数值 |",
        "| --- | ---: |",
        "| 产值 | 12.5 亿元 |",
      ].join("\n"),
    );
    expect(blocks[0]).toEqual({ type: "heading", level: 1, text: "标题" });
    expect(blocks[1]).toEqual({ type: "paragraph", text: "段落 **加粗**" });
    expect(blocks[2]).toEqual({ type: "bullet", items: ["一", "二"] });
    expect(blocks[3]).toEqual({ type: "quote", text: "引用" });
    expect(blocks[4]).toEqual({
      type: "table",
      headers: ["指标", "数值"],
      rows: [["产值", "12.5 亿元"]],
    });
  });

  it("preserves escaped pipes inside table cells", () => {
    const blocks = parseMarkdown(
      ["| 项 | 值 |", "| --- | --- |", "| A | x \\| y |"].join("\n"),
    );
    expect(blocks[0]).toMatchObject({
      type: "table",
      rows: [["A", "x | y"]],
    });
  });

  it("treats script tags as paragraph text, never markup", () => {
    const blocks = parseMarkdown("<script>alert(1)</script>");
    expect(blocks).toEqual([
      { type: "paragraph", text: "<script>alert(1)</script>" },
    ]);
  });
});
