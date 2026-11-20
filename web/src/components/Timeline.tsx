import type { EventOut } from "../api";
import { formatTime, summarizePayload } from "../lib";

export function Timeline({ events }: { events: EventOut[] }) {
  if (events.length === 0) {
    return <p className="muted">尚未收到事件。</p>;
  }
  return (
    <ol className="timeline">
      {events.map((event) => (
        <li key={event.seq} className={`event event-${event.event_type.split(".")[0]}`}>
          <div className="event-head">
            <span className="event-seq">#{event.seq}</span>
            <code>{event.event_type}</code>
            <time>{formatTime(event.created_at)}</time>
          </div>
          {Object.keys(event.payload).length > 0 ? (
            <p className="event-payload">{summarizePayload(event.payload)}</p>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
