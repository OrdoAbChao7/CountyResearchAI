import type { ReactNode } from "react";
import {
  isSafeHref,
  parseInline,
  parseMarkdown,
  type InlineToken,
} from "../lib/markdown";

function inline(tokens: InlineToken[], keyPrefix: string): ReactNode[] {
  return tokens.map((token, index) => {
    const key = `${keyPrefix}-${index}`;
    if (token.type === "code") return <code key={key}>{token.text}</code>;
    if (token.type === "strong") return <strong key={key}>{token.text}</strong>;
    if (token.type === "link") {
      if (!isSafeHref(token.href)) return <span key={key}>{token.text}</span>;
      return (
        <a key={key} href={token.href} target="_blank" rel="noreferrer noopener">
          {token.text}
        </a>
      );
    }
    return <span key={key}>{token.text}</span>;
  });
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  return inline(parseInline(text), keyPrefix);
}

export function MarkdownView({
  markdown,
  className = "",
}: {
  markdown: string;
  className?: string;
}) {
  const blocks = parseMarkdown(markdown);
  return (
    <div className={`markdown-view ${className}`.trim()}>
      {blocks.map((block, index) => {
        const key = `block-${index}`;
        if (block.type === "heading") {
          const content = renderInline(block.text, key);
          if (block.level === 1) return <h1 key={key}>{content}</h1>;
          if (block.level === 2) return <h2 key={key}>{content}</h2>;
          return <h3 key={key}>{content}</h3>;
        }
        if (block.type === "paragraph") {
          return <p key={key}>{renderInline(block.text, key)}</p>;
        }
        if (block.type === "bullet") {
          return (
            <ul key={key}>
              {block.items.map((item, itemIndex) => (
                <li key={`${key}-${itemIndex}`}>
                  {renderInline(item, `${key}-${itemIndex}`)}
                </li>
              ))}
            </ul>
          );
        }
        if (block.type === "ordered") {
          return (
            <ol key={key}>
              {block.items.map((item, itemIndex) => (
                <li key={`${key}-${itemIndex}`}>
                  {renderInline(item, `${key}-${itemIndex}`)}
                </li>
              ))}
            </ol>
          );
        }
        if (block.type === "quote") {
          return <blockquote key={key}>{renderInline(block.text, key)}</blockquote>;
        }
        if (block.type === "code") {
          return (
            <pre key={key} className="markdown-code">
              <code>{block.text}</code>
            </pre>
          );
        }
        if (block.type === "divider") return <hr key={key} />;
        return (
          <div key={key} className="markdown-table-wrap">
            <table>
              <thead>
                <tr>
                  {block.headers.map((header, cellIndex) => (
                    <th key={`${key}-h-${cellIndex}`}>
                      {renderInline(header, `${key}-h-${cellIndex}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {block.rows.map((row, rowIndex) => (
                  <tr key={`${key}-r-${rowIndex}`}>
                    {block.headers.map((_, cellIndex) => (
                      <td key={`${key}-r-${rowIndex}-${cellIndex}`}>
                        {renderInline(
                          row[cellIndex] ?? "",
                          `${key}-r-${rowIndex}-${cellIndex}`,
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}
