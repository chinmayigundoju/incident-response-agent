export type JsonRecord = Record<string, unknown>;

export type Incident = {
  id: string;
  external_alert_id: string | null;
  fingerprint: string | null;
  title: string;
  service: string;
  environment: string;
  severity: string;
  status: string;
  started_at: string;
  detected_at: string;
  mitigated_at: string | null;
  resolved_at: string | null;
  summary: string | null;
  confirmed_root_cause: string | null;
  created_at: string;
  updated_at: string;
};

export type IncidentEvent = {
  id: string;
  incident_id: string;
  occurred_at: string;
  actor_type: string;
  event_type: string;
  source: string;
  payload: JsonRecord;
  created_at: string;
};

export type Evidence = {
  id: string;
  incident_id: string;
  type: string;
  source: string;
  query: string | null;
  observed_at: string;
  content: JsonRecord;
  content_hash: string | null;
  created_at: string;
};

export type Hypothesis = {
  id: string;
  incident_id: string;
  statement: string;
  status: string;
  confidence: string | null;
  created_at: string;
  updated_at: string;
};

export type Recommendation = {
  id: string;
  incident_id: string;
  action_type: string;
  description: string;
  rationale: string;
  risk_level: string;
  approval_required: boolean;
  status: string;
  created_at: string;
  updated_at: string;
};

export type Postmortem = {
  id: string;
  incident_id: string;
  draft_markdown: string;
  final_markdown: string | null;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
};

export type MemoryHealth = { configured: boolean; available: boolean };

export type AutomationStatus = {
  mode: "manual" | "assisted" | "demo_autopilot";
  label: string;
  automatic_investigation: boolean;
  automatic_execution_after_approval: boolean;
  automatic_postmortem_after_root_cause: boolean;
  automatic_memory_after_postmortem_approval: boolean;
  simulated_autopilot: boolean;
};

export type ScenarioResult = { scenario: string; state: string };

export type MemoryCommitResult = {
  bank_id?: string;
  document_id: string;
  retained?: boolean;
  status?: string;
};

export type IncidentBundle = {
  incident: Incident;
  events: IncidentEvent[];
  evidence: Evidence[];
  hypotheses: Hypothesis[];
  recommendations: Recommendation[];
  postmortem: Postmortem | null;
  unavailable: string[];
};

export function asRecord(value: unknown): JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};
}

export function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function label(value: string): string {
  return value.replaceAll("_", " ");
}
