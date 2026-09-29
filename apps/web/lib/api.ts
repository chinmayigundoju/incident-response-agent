import {
  Evidence,
  AutomationStatus,
  Hypothesis,
  Incident,
  IncidentBundle,
  IncidentEvent,
  JsonRecord,
  MemoryCommitResult,
  MemoryHealth,
  Postmortem,
  Recommendation,
  ScenarioResult,
} from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 20_000): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  const externalSignal = init.signal;
  const abort = () => controller.abort();
  externalSignal?.addEventListener("abort", abort, { once: true });
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      cache: "no-store",
      signal: controller.signal,
    });
    const payload = (await response.json().catch(() => ({}))) as {
      error?: { code?: string; message?: string };
    };
    if (!response.ok) {
      throw new ApiError(
        payload.error?.message ?? `The API request failed (${response.status}).`,
        response.status,
        payload.error?.code,
      );
    }
    return payload as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("The request timed out before the server completed the operation.");
    }
    throw new Error("The API is currently unreachable. Check the Docker services and try again.");
  } finally {
    window.clearTimeout(timeout);
    externalSignal?.removeEventListener("abort", abort);
  }
}

function post<T>(path: string, body?: JsonRecord, timeoutMs?: number): Promise<T> {
  return request<T>(
    path,
    {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    },
    timeoutMs,
  );
}

export const api = {
  health: (signal?: AbortSignal) => request<{ status: string; service: string }>("/health", { signal }),
  memoryHealth: (signal?: AbortSignal) => request<MemoryHealth>("/api/v1/memory/health", { signal }),
  automationStatus: (signal?: AbortSignal) => request<AutomationStatus>("/api/v1/automation/status", { signal }),
  incidents: () => request<Incident[]>("/api/v1/incidents"),
  incident: (id: string) => request<Incident>(`/api/v1/incidents/${id}`),
  events: (id: string) => request<IncidentEvent[]>(`/api/v1/incidents/${id}/events`),
  evidence: (id: string) => request<Evidence[]>(`/api/v1/incidents/${id}/evidence`),
  hypotheses: (id: string) => request<Hypothesis[]>(`/api/v1/incidents/${id}/hypotheses`),
  recommendations: (id: string) => request<Recommendation[]>(`/api/v1/incidents/${id}/recommendations`),
  postmortem: (id: string) => request<Postmortem>(`/api/v1/incidents/${id}/postmortem`),
  investigate: (id: string) => post<JsonRecord>(`/api/v1/incidents/${id}/investigate`, undefined, 150_000),
  approveRecommendation: (id: string, recommendationId: string, body: JsonRecord) =>
    post<JsonRecord>(`/api/v1/incidents/${id}/recommendations/${recommendationId}/approve`, body),
  rejectRecommendation: (id: string, recommendationId: string, body: JsonRecord) =>
    post<JsonRecord>(`/api/v1/incidents/${id}/recommendations/${recommendationId}/reject`, body),
  executeRecommendation: (id: string, recommendationId: string) =>
    post<JsonRecord>(`/api/v1/incidents/${id}/recommendations/${recommendationId}/execute`, undefined, 60_000),
  verifyRecovery: (id: string) => post<JsonRecord>(`/api/v1/incidents/${id}/verify-recovery`, undefined, 60_000),
  confirmRootCause: (id: string, body: JsonRecord) =>
    post<JsonRecord>(`/api/v1/incidents/${id}/root-cause/confirm`, body),
  generatePostmortem: (id: string) => post<Postmortem>(`/api/v1/incidents/${id}/postmortem`),
  approvePostmortem: (id: string, body: JsonRecord) =>
    post<Postmortem>(`/api/v1/incidents/${id}/postmortem/approve`, body),
  commitMemory: (id: string) =>
    post<MemoryCommitResult>(`/api/v1/incidents/${id}/memory/commit`, undefined, 330_000),
  activateScenario: (scenario: string) =>
    post<ScenarioResult>(`/api/v1/demo/scenarios/${scenario}/activate`, undefined, 30_000),
};

export async function getIncidentBundle(id: string): Promise<IncidentBundle> {
  const resources = await Promise.allSettled([
    api.incident(id),
    api.events(id),
    api.evidence(id),
    api.hypotheses(id),
    api.recommendations(id),
    api.postmortem(id),
  ]);
  if (resources[0].status === "rejected") throw resources[0].reason;
  const unavailable: string[] = [];
  const optional = <T>(index: number, name: string, fallback: T): T => {
    const resource = resources[index];
    if (resource.status === "fulfilled") return resource.value as T;
    if (!(name === "postmortem" && resource.reason instanceof ApiError && resource.reason.status === 404)) {
      unavailable.push(name);
    }
    return fallback;
  };
  return {
    incident: resources[0].value,
    events: optional(1, "events", []),
    evidence: optional(2, "evidence", []),
    hypotheses: optional(3, "hypotheses", []),
    recommendations: optional(4, "recommendations", []),
    postmortem: optional(5, "postmortem", null),
    unavailable,
  };
}
