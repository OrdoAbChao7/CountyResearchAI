export interface DateWindow {
  start: string | null;
  end: string | null;
}

export interface EvidenceThresholds {
  min_independent_sources: number;
  min_supported_claims: number;
  min_supported_ratio: number;
  evidence_requirement: string;
}

export interface BudgetCaps {
  max_steps: number;
  max_search_calls: number;
  max_tokens: number;
  max_cost: number;
  deadline_seconds: number;
  max_documents: number;
}

export interface ResearchContract {
  objective: string;
  regions: string[];
  date_window: DateWindow;
  required_questions: string[];
  evidence_thresholds: EvidenceThresholds;
  budget: BudgetCaps;
  requested_output: {
    format: string;
    language: string;
    include_evidence_appendix: boolean;
    max_words: number;
  };
  domain_adapter: string;
  mode: string;
  research_focus: string;
  options: Record<string, unknown>;
}

export interface TaskSummary {
  job_id: string;
  status: string;
  outcome: string | null;
  outcome_reason: string;
  objective: string;
  regions: string[];
  mode: string;
  mode_label: string;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  cancel_requested: boolean;
  error_code: string;
  report_path: string;
}

export interface TaskDetail extends TaskSummary {
  contract: ResearchContract;
  result: Record<string, unknown>;
  budget_enforcement: Record<string, unknown>;
}

export interface EventOut {
  seq: number;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface ClaimOut {
  claim_id: string;
  statement: string;
  region: string;
  metric: string;
  value: string;
  unit: string;
  period: string;
  scope: string;
  caliber: string;
  version: string;
  verification_status: string;
  verification_reason: string;
}

export interface EvidenceLinkOut {
  relation: string;
  span_id: string;
  quote: string;
  start_offset: number | null;
  end_offset: number | null;
  offset_status: string;
  snapshot_id: string;
  url: string;
  title: string;
  observed_at: string | null;
  published_at: string | null;
}

export interface FindingOut {
  finding_id: string;
  section: string;
  text: string;
  status: string;
  claim: ClaimOut;
  links: EvidenceLinkOut[];
  checks: Record<string, unknown>;
}

export interface SourceOut {
  snapshot_id: string;
  title: string;
  url: string;
  source_type: string;
  fetch_status: string;
  observed_at: string | null;
  published_at: string | null;
  content_length: number;
}

export interface SourceDetailOut extends SourceOut {
  content: string;
}

export interface Capabilities {
  api_version: string;
  job_schema_version: number;
  evidence_schema_version: number;
  mode_label: string;
  live_enabled: boolean;
  enforced_caps: string[];
  bounded_per_call_caps: string[];
  unenforced_caps: string[];
  docs_url: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as {
        error?: { code?: string; message?: string };
      };
      if (body.error) {
        message = `${body.error.code ?? "error"}: ${body.error.message ?? ""}`;
      }
    } catch {
      // Non-JSON error body; keep the status text.
    }
    throw new Error(message);
  }
  const text = await response.text();
  return (text ? JSON.parse(text) : null) as T;
}

export function getCapabilities(): Promise<Capabilities> {
  return request<Capabilities>("/api/v1/capabilities");
}

export function listTasks(): Promise<TaskSummary[]> {
  return request<TaskSummary[]>("/api/v1/research/tasks");
}

export function createTask(contract: ResearchContract): Promise<TaskDetail> {
  return request<TaskDetail>("/api/v1/research/tasks", {
    method: "POST",
    body: JSON.stringify({ contract }),
  });
}

export function getTask(jobId: string): Promise<TaskDetail> {
  return request<TaskDetail>(`/api/v1/research/tasks/${jobId}`);
}

export function cancelTask(jobId: string): Promise<TaskSummary> {
  return request<TaskSummary>(`/api/v1/research/tasks/${jobId}/cancel`, {
    method: "POST",
  });
}

export function resumeTask(jobId: string): Promise<TaskDetail> {
  return request<TaskDetail>(`/api/v1/research/tasks/${jobId}/resume`, {
    method: "POST",
  });
}

export function listEvents(
  jobId: string,
  after = 0,
): Promise<EventOut[]> {
  return request<EventOut[]>(
    `/api/v1/research/tasks/${jobId}/events?after=${after}`,
  );
}

export function listFindings(jobId: string): Promise<FindingOut[]> {
  return request<FindingOut[]>(`/api/v1/research/tasks/${jobId}/findings`);
}

export function listSources(jobId: string): Promise<SourceOut[]> {
  return request<SourceOut[]>(`/api/v1/research/tasks/${jobId}/sources`);
}

export function getSource(snapshotId: string): Promise<SourceDetailOut> {
  return request<SourceDetailOut>(
    `/api/v1/research/sources/${encodeURIComponent(snapshotId)}`,
  );
}

export async function getBrief(jobId: string): Promise<string> {
  const response = await fetch(`/api/v1/research/tasks/${jobId}/brief`);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.text();
}

export async function getReport(jobId: string): Promise<string> {
  const response = await fetch(`/api/v1/research/tasks/${jobId}/report`);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.text();
}

export function streamUrl(jobId: string): string {
  return `/api/v1/research/tasks/${jobId}/stream`;
}
