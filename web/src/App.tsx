import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as api from "./api";
import {
  EVENT_TYPES,
  isTerminal,
  mergeEvents,
  readWorkspaceState,
  workspaceSearch,
  type LayoutMode,
  type WorkspaceStep,
} from "./lib";
import { ContextPanel } from "./components/ContextPanel";
import { DefineStep } from "./components/DefineStep";
import { EvidenceDrawer } from "./components/EvidenceDrawer";
import { GraphPanel } from "./components/GraphPanel";
import { QuestionsPanel } from "./components/QuestionsPanel";
import { ReportStudio } from "./components/ReportStudio";
import { RunStep } from "./components/RunStep";
import { LoadingState } from "./components/StateViews";
import { StatusBar } from "./components/StatusBar";
import { StepRail } from "./components/StepRail";

const STEP_TITLES: Record<WorkspaceStep, string> = {
  1: "定义研究",
  2: "运行研究",
  3: "证据图谱",
  4: "报告工作台",
};

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export default function App() {
  const initial = useRef(readWorkspaceState(window.location.search));
  const [capabilities, setCapabilities] = useState<api.Capabilities | null>(null);
  const [tasks, setTasks] = useState<api.TaskSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(
    initial.current.taskId,
  );
  const [detail, setDetail] = useState<api.TaskDetail | null>(null);
  const [events, setEvents] = useState<api.EventOut[]>([]);
  const [step, setStep] = useState<WorkspaceStep>(initial.current.step);
  const [layout, setLayout] = useState<LayoutMode>(initial.current.layout);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState<api.ReportView | null>(null);
  const [selectedNode, setSelectedNode] = useState<api.GraphNode | null>(null);
  const [selectedEvidence, setSelectedEvidence] =
    useState<api.EvidenceItemView | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerFocus, setDrawerFocus] = useState<string | null>(null);
  const [reportFocus, setReportFocus] = useState<string | null>(null);
  const [graphFocusClaim, setGraphFocusClaim] = useState<string | null>(null);

  const terminal = detail ? isTerminal(detail.status) : false;

  useEffect(() => {
    api
      .getCapabilities()
      .then(setCapabilities)
      .catch((caught) => setError(message(caught)));
    api
      .listTasks()
      .then((loaded) => {
        setTasks(loaded);
        setSelectedId((current) => {
          if (current && loaded.some((task) => task.job_id === current)) {
            return current;
          }
          return loaded[0]?.job_id ?? null;
        });
      })
      .catch((caught) => setError(message(caught)));
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setEvents([]);
      setReport(null);
      return undefined;
    }
    let cancelled = false;
    setDetail(null);
    setEvents([]);
    setReport(null);
    setSelectedNode(null);
    setSelectedEvidence(null);
    setReportFocus(null);
    setGraphFocusClaim(null);

    async function load() {
      try {
        const current = await api.getTask(selectedId as string);
        if (cancelled) return;
        setDetail(current);
        setTasks((previous) =>
          previous.map((task) =>
            task.job_id === current.job_id ? current : task,
          ),
        );
        const loadedEvents = await api.listEvents(current.job_id);
        if (cancelled) return;
        setEvents((previous) => mergeEvents(previous, loadedEvents));
      } catch (caught) {
        if (!cancelled) setError(message(caught));
      }
    }

    void load();
    const interval = window.setInterval(() => void load(), 1500);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [selectedId]);

  useEffect(() => {
    if (!selectedId) return undefined;
    const source = new EventSource(api.streamUrl(selectedId));
    const handler = (event: MessageEvent<string>) => {
      try {
        const parsed = JSON.parse(event.data) as api.EventOut;
        setEvents((previous) => mergeEvents(previous, [parsed]));
      } catch {
        // Polling remains authoritative if a frame is malformed.
      }
    };
    for (const type of EVENT_TYPES) {
      source.addEventListener(type, handler as EventListener);
    }
    source.onerror = () => source.close();
    return () => source.close();
  }, [selectedId]);

  useEffect(() => {
    if (step > 1 && !selectedId) setStep(1);
  }, [step, selectedId]);

  useEffect(() => {
    if (!detail) return;
    if (step >= 3 && !isTerminal(detail.status)) setStep(2);
  }, [step, detail]);

  useEffect(() => {
    const search = workspaceSearch({ step, layout, taskId: selectedId });
    const next = `${window.location.pathname}${search}${window.location.hash}`;
    window.history.replaceState(null, "", next);
  }, [step, layout, selectedId]);

  const createTask = useCallback(async (contract: api.ResearchContract) => {
    setBusy(true);
    setError("");
    try {
      const created = await api.createTask(contract);
      setTasks((previous) => [created, ...previous]);
      setSelectedId(created.job_id);
      setDetail(created);
      setStep(2);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }, []);

  const selectTask = useCallback((jobId: string) => {
    setSelectedId(jobId);
    setStep(2);
    setDrawerOpen(false);
    setDrawerFocus(null);
    setSelectedNode(null);
    setSelectedEvidence(null);
    setGraphFocusClaim(null);
  }, []);

  const refresh = useCallback(async () => {
    if (!selectedId) return;
    setBusy(true);
    try {
      const current = await api.getTask(selectedId);
      setDetail(current);
      const loadedEvents = await api.listEvents(selectedId);
      setEvents((previous) => mergeEvents(previous, loadedEvents));
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }, [selectedId]);

  const cancel = useCallback(async () => {
    if (!detail) return;
    setBusy(true);
    try {
      await api.cancelTask(detail.job_id);
      await refresh();
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }, [detail, refresh]);

  const resume = useCallback(async () => {
    if (!detail) return;
    setBusy(true);
    try {
      const resumed = await api.resumeTask(detail.job_id);
      setDetail(resumed);
      setStep(2);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }, [detail]);

  const openEvidence = useCallback((claimId: string) => {
    setDrawerFocus(claimId);
    setDrawerOpen(true);
  }, []);

  const closeDrawer = useCallback(() => {
    setDrawerOpen(false);
  }, []);

  const openReport = useCallback(
    (claimId: string) => {
      if (!detail || !isTerminal(detail.status)) return;
      setReportFocus(claimId);
      setStep(4);
    },
    [detail],
  );

  const locateInGraph = useCallback(
    (claimId: string) => {
      if (!detail || !isTerminal(detail.status)) return;
      setGraphFocusClaim(claimId);
      setLayout("graph");
      setStep(3);
      setDrawerOpen(false);
    },
    [detail],
  );

  const selectNode = useCallback((node: api.GraphNode | null) => {
    setSelectedNode(node);
    setSelectedEvidence(null);
    setGraphFocusClaim(null);
  }, []);

  const handleDrawerSelect = useCallback(
    (item: api.EvidenceItemView | null) => {
      setSelectedEvidence(item);
      if (item) setDrawerFocus(item.claim_id);
    },
    [],
  );

  const stage = useMemo(() => {
    if (step === 1) {
      return (
        <DefineStep
          capabilities={capabilities}
          tasks={tasks}
          busy={busy}
          error={error}
          onCreate={(contract) => void createTask(contract)}
          onSelectTask={selectTask}
        />
      );
    }
    if (step === 2) {
      return (
        <RunStep
          detail={detail}
          events={events}
          busy={busy}
          onCancel={() => void cancel()}
          onResume={() => void resume()}
          onRefresh={() => void refresh()}
          onGraph={() => {
            setLayout("graph");
            setStep(3);
          }}
          onReport={() => {
            setLayout("workbench");
            setStep(4);
          }}
        />
      );
    }
    if (!detail) {
      return (
        <LoadingState
          label="正在恢复运行上下文与持久化产物"
          rows={4}
        />
      );
    }

    if (step === 3) {
      if (layout === "graph") {
        return (
          <GraphPanel
            jobId={detail.job_id}
            terminal={terminal}
            selectedNodeId={selectedNode?.id ?? null}
            focusClaimId={graphFocusClaim}
            onSelectNode={selectNode}
            onEvidence={openEvidence}
            onOpenReport={openReport}
          />
        );
      }
      if (layout === "split") {
        return (
          <div className="stage-split">
            <GraphPanel
              jobId={detail.job_id}
              terminal={terminal}
              selectedNodeId={selectedNode?.id ?? null}
              focusClaimId={graphFocusClaim}
              onSelectNode={selectNode}
              onEvidence={openEvidence}
              onOpenReport={openReport}
            />
            <ReportStudio
              detail={detail}
              focusClaimId={reportFocus}
              onCitation={openEvidence}
              onReportLoaded={setReport}
            />
          </div>
        );
      }
      return (
        <div className="stage-split">
          <GraphPanel
            jobId={detail.job_id}
            terminal={terminal}
            selectedNodeId={selectedNode?.id ?? null}
            focusClaimId={graphFocusClaim}
            onSelectNode={selectNode}
            onEvidence={openEvidence}
            onOpenReport={openReport}
          />
          <QuestionsPanel
            jobId={detail.job_id}
            terminal={terminal}
            onOpenEvidence={() => {
              setDrawerFocus(null);
              setDrawerOpen(true);
            }}
          />
        </div>
      );
    }

    if (layout === "workbench") {
      return (
        <ReportStudio
          detail={detail}
          focusClaimId={reportFocus}
          onCitation={openEvidence}
          onReportLoaded={setReport}
        />
      );
    }
    if (layout === "graph") {
      return (
        <div className="stage-split">
          <ReportStudio
            detail={detail}
            focusClaimId={reportFocus}
            onCitation={openEvidence}
            onReportLoaded={setReport}
          />
          <GraphPanel
            jobId={detail.job_id}
            terminal={terminal}
            selectedNodeId={selectedNode?.id ?? null}
            focusClaimId={graphFocusClaim}
            onSelectNode={selectNode}
            onEvidence={openEvidence}
            onOpenReport={openReport}
          />
        </div>
      );
    }
    return (
      <div className="stage-split">
        <ReportStudio
          detail={detail}
          focusClaimId={reportFocus}
          onCitation={openEvidence}
          onReportLoaded={setReport}
        />
        <QuestionsPanel
          jobId={detail.job_id}
          terminal={terminal}
          onOpenEvidence={() => {
            setDrawerFocus(null);
            setDrawerOpen(true);
          }}
        />
      </div>
    );
  }, [
    capabilities,
    busy,
    cancel,
    createTask,
    detail,
    error,
    events,
    graphFocusClaim,
    layout,
    locateInGraph,
    openEvidence,
    openReport,
    refresh,
    reportFocus,
    resume,
    selectNode,
    selectTask,
    selectedNode,
    step,
    tasks,
    terminal,
  ]);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <StepRail
        capabilities={capabilities}
        tasks={tasks}
        detail={detail}
        step={step}
        busy={busy}
        onStep={setStep}
        onSelectTask={selectTask}
        onNewTask={() => setStep(1)}
      />

      <div className="stage-shell">
        <header className="top-bar">
          <div className="breadcrumb">
            <span>AXIOMSCOPE</span>
            <span className="breadcrumb-sep">/</span>
            <span>{STEP_TITLES[step]}</span>
          </div>
          <div className="top-actions">
            <span className={`mode-pill ${capabilities?.mode_label === "LIVE" ? "live" : ""}`}>
              {capabilities?.mode_label ?? "…"}
            </span>
            <button
              type="button"
              onClick={() => {
                setDrawerFocus(null);
                setDrawerOpen(true);
              }}
              disabled={!detail || !terminal}
            >
              证据抽屉
            </button>
            <button
              type="button"
              onClick={() => void refresh()}
              disabled={busy || !selectedId}
            >
              刷新
            </button>
          </div>
        </header>

        {error ? (
          <div className="error-banner" role="alert">
            <span>{error}</span>
            <button type="button" onClick={() => setError("")}>
              关闭
            </button>
          </div>
        ) : null}

        <main id="main-content" className="stage-content" tabIndex={-1}>
          {stage}
        </main>
      </div>

      <ContextPanel
        detail={detail}
        events={events}
        selectedNode={selectedNode}
        selectedEvidence={selectedEvidence}
        report={report}
        step={step}
        onStep={setStep}
        onOpenEvidence={openEvidence}
        onOpenReport={openReport}
        onLocateGraph={locateInGraph}
      />

      <StatusBar
        capabilities={capabilities}
        detail={detail}
        events={events}
        step={step}
        layout={layout}
        onLayout={setLayout}
      />

      <EvidenceDrawer
        jobId={selectedId}
        open={drawerOpen}
        focusClaimId={drawerFocus}
        onClose={closeDrawer}
        onSelect={handleDrawerSelect}
        onLocateGraph={locateInGraph}
      />
    </div>
  );
}
