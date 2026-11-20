import { useEffect, useState } from "react";
import * as api from "./api";
import { EVENT_TYPES, isTerminal } from "./lib";
import { TaskDetailPanel } from "./components/TaskDetailPanel";
import { TaskForm } from "./components/TaskForm";
import { TaskList } from "./components/TaskList";

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function mergeEvents(
  current: api.EventOut[],
  incoming: api.EventOut[],
): api.EventOut[] {
  const bySeq = new Map<number, api.EventOut>();
  for (const event of current) bySeq.set(event.seq, event);
  for (const event of incoming) bySeq.set(event.seq, event);
  return [...bySeq.values()].sort((left, right) => left.seq - right.seq);
}

export default function App() {
  const [capabilities, setCapabilities] = useState<api.Capabilities | null>(null);
  const [tasks, setTasks] = useState<api.TaskSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<api.TaskDetail | null>(null);
  const [events, setEvents] = useState<api.EventOut[]>([]);
  const [findings, setFindings] = useState<api.FindingOut[]>([]);
  const [sources, setSources] = useState<api.SourceOut[]>([]);
  const [brief, setBrief] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .getCapabilities()
      .then(setCapabilities)
      .catch((caught) => setError(message(caught)));
    api
      .listTasks()
      .then((loaded) => {
        setTasks(loaded);
        if (loaded.length > 0) setSelectedId(loaded[0].job_id);
      })
      .catch((caught) => setError(message(caught)));
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;

    async function load() {
      try {
        const current = await api.getTask(selectedId as string);
        if (cancelled) return;
        setDetail(current);
        setTasks((previous) =>
          previous.map((task) => (task.job_id === current.job_id ? current : task)),
        );
        const loadedEvents = await api.listEvents(current.job_id);
        if (cancelled) return;
        setEvents((previous) => mergeEvents(previous, loadedEvents));
        if (isTerminal(current.status)) {
          const [loadedFindings, loadedSources, loadedBrief] = await Promise.all([
            api.listFindings(current.job_id),
            api.listSources(current.job_id),
            api.getBrief(current.job_id),
          ]);
          if (cancelled) return;
          setFindings(loadedFindings);
          setSources(loadedSources);
          setBrief(loadedBrief);
        }
      } catch (caught) {
        if (!cancelled) setError(message(caught));
      }
    }

    setEvents([]);
    setFindings([]);
    setSources([]);
    setBrief("");
    void load();
    const interval = window.setInterval(() => void load(), 1500);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [selectedId]);

  useEffect(() => {
    if (!selectedId) return;
    const source = new EventSource(api.streamUrl(selectedId));
    const handler = (event: MessageEvent<string>) => {
      try {
        const parsed = JSON.parse(event.data) as api.EventOut;
        setEvents((previous) => mergeEvents(previous, [parsed]));
      } catch {
        // Ignore malformed frames; polling remains authoritative.
      }
    };
    for (const type of EVENT_TYPES) {
      source.addEventListener(type, handler as EventListener);
    }
    source.onerror = () => source.close();
    return () => source.close();
  }, [selectedId]);

  async function createTask(contract: api.ResearchContract) {
    setBusy(true);
    setError("");
    try {
      const created = await api.createTask(contract);
      setTasks((previous) => [created, ...previous]);
      setSelectedId(created.job_id);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!detail) return;
    setBusy(true);
    try {
      await api.cancelTask(detail.job_id);
      const current = await api.getTask(detail.job_id);
      setDetail(current);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  async function resume() {
    if (!detail) return;
    setBusy(true);
    try {
      const resumed = await api.resumeTask(detail.job_id);
      setDetail(resumed);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  async function refresh() {
    if (!selectedId) return;
    setBusy(true);
    try {
      const current = await api.getTask(selectedId);
      setDetail(current);
      const loadedEvents = await api.listEvents(selectedId);
      setEvents((previous) => mergeEvents(previous, loadedEvents));
      if (isTerminal(current.status)) {
        const [loadedFindings, loadedSources, loadedBrief] = await Promise.all([
          api.listFindings(selectedId),
          api.listSources(selectedId),
          api.getBrief(selectedId),
        ]);
        setFindings(loadedFindings);
        setSources(loadedSources);
        setBrief(loadedBrief);
      }
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <header className="brand">
          <div>
            <p className="brand-kicker">Evidence-Native Research</p>
            <h1>AxiomScope</h1>
            <p className="brand-sub">县域产业研究 · 证据原生工作台</p>
          </div>
          <div className="mode-chips">
            <span className={`chip ${capabilities?.mode_label === "LIVE" ? "chip-live" : ""}`}>
              {capabilities?.mode_label ?? "…"}
            </span>
            <span className="chip">API {capabilities?.api_version ?? "…"}</span>
          </div>
        </header>
        {error ? (
          <div className="error-banner">
            <span>{error}</span>
            <button type="button" onClick={() => setError("")}>
              关闭
            </button>
          </div>
        ) : null}
        <TaskForm busy={busy} error="" onCreate={(contract) => void createTask(contract)} />
        <TaskList tasks={tasks} selectedId={selectedId} onSelect={setSelectedId} />
      </aside>

      <main className="workspace">
        {detail ? (
          <TaskDetailPanel
            detail={detail}
            events={events}
            findings={findings}
            sources={sources}
            brief={brief}
            busy={busy}
            onCancel={() => void cancel()}
            onResume={() => void resume()}
            onRefresh={() => void refresh()}
          />
        ) : (
          <div className="empty-state">
            <h2>从一个可验证的研究问题开始</h2>
            <p>
              提交任务后，这里会显示运行时间线、结论级证据链和决策简报。
              所有结论必须能回到不可变来源快照中的精确引文。
            </p>
            <p className="muted">
              未配置 Provider 密钥时使用 MOCK 数据，只验证产品链路与证据校验，不代表真实检索质量。
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
