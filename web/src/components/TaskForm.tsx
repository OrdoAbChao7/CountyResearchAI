import { useState } from "react";
import type { FormEvent } from "react";
import type { ResearchContract } from "../api";

interface Props {
  busy: boolean;
  error: string;
  onCreate: (contract: ResearchContract) => void;
}

export function TaskForm({ busy, error, onCreate }: Props) {
  const [objective, setObjective] = useState("评估德清县 2024 年产业发展与财政健康");
  const [regions, setRegions] = useState("德清县");
  const [focus, setFocus] = useState("");
  const [mode, setMode] = useState("snapshot");
  const [questions, setQuestions] = useState(
    "2024 年地区生产总值是多少？\n规模以上工业增加值及增速是多少？",
  );
  const [start, setStart] = useState("2024-01-01");
  const [end, setEnd] = useState("2024-12-31");
  const [maxSteps, setMaxSteps] = useState(8);
  const [maxSearch, setMaxSearch] = useState(3);
  const [deadline, setDeadline] = useState(300);
  const [maxDocuments, setMaxDocuments] = useState(10);
  const [minSources, setMinSources] = useState(1);
  const [minSupported, setMinSupported] = useState(1);
  const [localError, setLocalError] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    const regionList = regions
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    if (!objective.trim() || regionList.length === 0) {
      setLocalError("研究目标与地区不能为空。");
      return;
    }
    setLocalError("");
    const contract: ResearchContract = {
      objective: objective.trim(),
      regions: regionList,
      date_window: { start: start || null, end: end || null },
      required_questions: questions
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean),
      evidence_thresholds: {
        min_independent_sources: Number(minSources),
        min_supported_claims: Number(minSupported),
        min_supported_ratio: 0,
        evidence_requirement: "",
      },
      budget: {
        max_steps: Number(maxSteps),
        max_search_calls: Number(maxSearch),
        max_tokens: 0,
        max_cost: 0,
        deadline_seconds: Number(deadline),
        max_documents: Number(maxDocuments),
      },
      requested_output: {
        format: "decision_brief",
        language: "zh",
        include_evidence_appendix: true,
        max_words: 0,
      },
      domain_adapter: "county_industry",
      mode,
      research_focus: focus.trim(),
      options: {},
    };
    onCreate(contract);
  }

  const message = localError || error;

  return (
    <form className="task-form" onSubmit={submit}>
      <h2>新建研究任务</h2>
      <label>
        研究目标
        <textarea value={objective} onChange={(event) => setObjective(event.target.value)} rows={2} />
      </label>
      <div className="grid-2">
        <label>
          地区（逗号分隔）
          <input value={regions} onChange={(event) => setRegions(event.target.value)} />
        </label>
        <label>
          研究方向（可选）
          <input
            value={focus}
            placeholder="留空则自动识别"
            onChange={(event) => setFocus(event.target.value)}
          />
        </label>
      </div>
      <div className="grid-2">
        <label>
          模式
          <select value={mode} onChange={(event) => setMode(event.target.value)}>
            <option value="snapshot">产业现状快照</option>
            <option value="rise-fall">产业兴衰规律</option>
            <option value="long-history">长周期兴衰史</option>
          </select>
        </label>
        <label>
          起始日期
          <input type="date" value={start} onChange={(event) => setStart(event.target.value)} />
        </label>
        <label>
          结束日期
          <input type="date" value={end} onChange={(event) => setEnd(event.target.value)} />
        </label>
      </div>
      <label>
        必答问题（每行一个）
        <textarea value={questions} onChange={(event) => setQuestions(event.target.value)} rows={3} />
      </label>
      <fieldset>
        <legend>预算与证据门槛</legend>
        <div className="grid-3">
          <label>
            最大步骤
            <input type="number" min={1} max={50} value={maxSteps} onChange={(event) => setMaxSteps(Number(event.target.value))} />
          </label>
          <label>
            最大搜索调用
            <input type="number" min={0} max={100} value={maxSearch} onChange={(event) => setMaxSearch(Number(event.target.value))} />
          </label>
          <label>
            截止秒数
            <input type="number" min={0} value={deadline} onChange={(event) => setDeadline(Number(event.target.value))} />
          </label>
          <label>
            最大文档数
            <input type="number" min={0} max={500} value={maxDocuments} onChange={(event) => setMaxDocuments(Number(event.target.value))} />
          </label>
          <label>
            最少独立来源
            <input type="number" min={0} value={minSources} onChange={(event) => setMinSources(Number(event.target.value))} />
          </label>
          <label>
            最少支持结论
            <input type="number" min={0} value={minSupported} onChange={(event) => setMinSupported(Number(event.target.value))} />
          </label>
        </div>
      </fieldset>
      <p className="hint">
        未配置 Provider 密钥时任务以 MOCK 模式运行，只验证管线与证据链，不代表真实检索质量。
      </p>
      {message ? <p className="error-text">{message}</p> : null}
      <button type="submit" disabled={busy}>
        {busy ? "提交中…" : "开始研究"}
      </button>
    </form>
  );
}
