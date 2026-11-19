export function SourceContentView({
  content,
  quote,
}: {
  content: string;
  quote: string;
}) {
  const index = quote ? content.indexOf(quote) : -1;
  if (index === -1) {
    return (
      <>
        {quote ? (
          <p className="warn-text">
            引文未能在快照正文中精确定位（可能已被截断或改写）。
          </p>
        ) : null}
        <pre className="source-content">{content}</pre>
      </>
    );
  }
  return (
    <pre className="source-content">
      {content.slice(0, index)}
      <mark>{quote}</mark>
      {content.slice(index + quote.length)}
    </pre>
  );
}
