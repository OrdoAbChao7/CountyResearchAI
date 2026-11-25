export type InlineToken =
  | { type: "text"; text: string }
  | { type: "strong"; text: string }
  | { type: "code"; text: string }
  | { type: "link"; text: string; href: string };

export type MarkdownBlock =
  | { type: "heading"; level: number; text: string }
  | { type: "paragraph"; text: string }
  | { type: "bullet"; items: string[] }
  | { type: "ordered"; items: string[] }
  | { type: "quote"; text: string }
  | { type: "code"; text: string }
  | { type: "divider" }
  | { type: "table"; headers: string[]; rows: string[][] };

const INLINE_PATTERN = /\*\*([^*\n]+)\*\*|`([^`\n]+)`|\[([^\]\n]+)\]\(([^)\s]+)\)/g;

export function isSafeHref(href: string): boolean {
  try {
    const url = new URL(href);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

export function parseInline(text: string): InlineToken[] {
  const tokens: InlineToken[] = [];
  let lastIndex = 0;
  for (const match of text.matchAll(INLINE_PATTERN)) {
    const index = match.index ?? 0;
    if (index > lastIndex) {
      tokens.push({ type: "text", text: text.slice(lastIndex, index) });
    }
    if (match[1] !== undefined) {
      tokens.push({ type: "strong", text: match[1] });
    } else if (match[2] !== undefined) {
      tokens.push({ type: "code", text: match[2] });
    } else {
      const label = match[3] ?? "";
      const href = match[4] ?? "";
      if (isSafeHref(href)) {
        tokens.push({ type: "link", text: label, href });
      } else {
        tokens.push({ type: "text", text: label });
      }
    }
    lastIndex = index + match[0].length;
  }
  if (lastIndex < text.length) {
    tokens.push({ type: "text", text: text.slice(lastIndex) });
  }
  return tokens;
}

function splitTableRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  const cells: string[] = [];
  let cell = "";
  for (let index = 0; index < trimmed.length; index += 1) {
    const character = trimmed[index];
    if (character === "\\" && trimmed[index + 1] === "|") {
      cell += "|";
      index += 1;
      continue;
    }
    if (character === "|") {
      cells.push(cell.trim());
      cell = "";
      continue;
    }
    cell += character;
  }
  cells.push(cell.trim());
  return cells;
}

function isTableDivider(line: string): boolean {
  if (!line.trimStart().startsWith("|")) return false;
  const cells = splitTableRow(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function isDivider(line: string): boolean {
  return /^(?:-{3,}|\*{3,}|_{3,})$/.test(line);
}

function isBlockStart(line: string): boolean {
  return (
    !line ||
    /^#{1,6}\s+/.test(line) ||
    line.startsWith("```") ||
    line.startsWith("|") ||
    /^[-*+]\s+/.test(line) ||
    /^\d+[.)]\s+/.test(line) ||
    /^>\s?/.test(line) ||
    isDivider(line)
  );
}

function collectLines(
  lines: string[],
  start: number,
  matches: (line: string) => string | undefined,
): { items: string[]; next: number } {
  const items: string[] = [];
  let index = start;
  while (index < lines.length) {
    const line = lines[index].trim();
    const matched = matches(line);
    if (!matched) break;
    items.push(matched);
    index += 1;
  }
  return { items, next: index };
}

export function parseMarkdown(markdown: string): MarkdownBlock[] {
  const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
  const blocks: MarkdownBlock[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index].trim();
    index += 1;
    if (!line) continue;

    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      blocks.push({
        type: "heading",
        level: heading[1].length,
        text: heading[2].trim(),
      });
      continue;
    }
    if (line.startsWith("```")) {
      const code: string[] = [];
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        code.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      blocks.push({ type: "code", text: code.join("\n") });
      continue;
    }
    if (isTableDivider(lines[index] ?? "")) {
      const headers = splitTableRow(line);
      index += 1;
      const rows: string[][] = [];
      while (index < lines.length && lines[index].trim().startsWith("|")) {
        rows.push(splitTableRow(lines[index]));
        index += 1;
      }
      blocks.push({ type: "table", headers, rows });
      continue;
    }
    if (isDivider(line)) {
      blocks.push({ type: "divider" });
      continue;
    }

    const bullet = /^[-*+]\s+(.*)$/.exec(line);
    if (bullet) {
      const collected = collectLines(lines, index, (candidate) =>
        /^[-*+]\s+(.*)$/.exec(candidate.trim())?.[1],
      );
      blocks.push({ type: "bullet", items: [bullet[1].trim(), ...collected.items] });
      index = collected.next;
      continue;
    }
    const ordered = /^\d+[.)]\s+(.*)$/.exec(line);
    if (ordered) {
      const collected = collectLines(lines, index, (candidate) =>
        /^\d+[.)]\s+(.*)$/.exec(candidate.trim())?.[1],
      );
      blocks.push({ type: "ordered", items: [ordered[1].trim(), ...collected.items] });
      index = collected.next;
      continue;
    }
    const quote = /^>\s?(.*)$/.exec(line);
    if (quote) {
      const collected = collectLines(lines, index, (candidate) =>
        /^>\s?(.*)$/.exec(candidate.trim())?.[1],
      );
      blocks.push({ type: "quote", text: [quote[1].trim(), ...collected.items].join("\n") });
      index = collected.next;
      continue;
    }

    const paragraph: string[] = [line];
    while (index < lines.length && !isBlockStart(lines[index].trim())) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    blocks.push({ type: "paragraph", text: paragraph.join("\n") });
  }
  return blocks;
}
