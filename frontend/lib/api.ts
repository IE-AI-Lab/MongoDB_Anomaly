// Typed client for the data layer. All calls go through the Next rewrite proxy
// at /backend/* (next.config.mjs), so the browser makes same-origin requests.

import type {
  AgentLog,
  Anomaly,
  AnomalyStatus,
  KnowledgeDoc,
  KnowledgeSource,
  MetricType,
  QueueStatus,
  Reading,
  Sensor,
  SimStatus,
  Staff,
  SystemMetadata,
} from "./types";

const BASE = "/backend";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(
  path: string,
  init?: RequestInit & { json?: unknown }
): Promise<T> {
  const { json, headers, ...rest } = init ?? {};
  const res = await fetch(`${BASE}${path}`, {
    ...rest,
    headers: {
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
    cache: "no-store",
  });

  if (!res.ok) {
    let detail: unknown;
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      detail = body?.detail ?? body;
      if (typeof detail === "string") message = detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const qs = (params: Record<string, string | number | boolean | undefined>) => {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
};

export const api = {
  // --- machines / telemetry ---
  listSensors: (opts: { metric_type?: MetricType; is_active?: boolean } = {}) =>
    request<Sensor[]>(`/sensors${qs(opts)}`),
  getReadings: (sensorId: string, opts: { minutes?: number; limit?: number } = {}) =>
    request<Reading[]>(`/sensors/${encodeURIComponent(sensorId)}/readings${qs(opts)}`),
  getSystemMetadata: (opts: { config_type?: string; target_metric?: string } = {}) =>
    request<SystemMetadata[]>(`/system_metadata${qs(opts)}`),

  // --- anomalies ---
  listAnomalies: (opts: { status?: AnomalyStatus; sensor_id?: string; limit?: number } = {}) =>
    request<Anomaly[]>(`/anomalies${qs(opts)}`),
  getAnomaly: (id: string) => request<Anomaly>(`/anomalies/${encodeURIComponent(id)}`),
  assign: (id: string, employee_id: string) =>
    request<Anomaly>(`/anomalies/${encodeURIComponent(id)}/assign`, {
      method: "POST",
      json: { employee_id },
    }),
  resolve: (
    id: string,
    body: { outcome: string; resolution_notes: string; resolved_by?: string }
  ) =>
    request<Anomaly & { knowledge_document_id?: string }>(
      `/anomalies/${encodeURIComponent(id)}/resolve`,
      { method: "POST", json: body }
    ),

  // --- staff ---
  listStaff: (
    opts: { is_on_call?: boolean; specialization?: string; handled_severity_type?: string } = {}
  ) => request<Staff[]>(`/staff_on_call${qs(opts)}`),

  // --- agent traces ---
  listAgentLogs: (opts: { anomaly_id?: string; run_id?: string; limit?: number } = {}) =>
    request<AgentLog[]>(`/agent_logs${qs(opts)}`),

  // --- knowledge CRUD ---
  listKnowledge: (
    opts: { is_active?: boolean; source?: KnowledgeSource; equipment_type?: string; limit?: number } = {}
  ) => request<KnowledgeDoc[]>(`/knowledge${qs(opts)}`),
  createKnowledge: (body: Partial<KnowledgeDoc>) =>
    request<KnowledgeDoc>(`/knowledge`, { method: "POST", json: body }),
  patchKnowledge: (id: string, body: Partial<KnowledgeDoc>) =>
    request<KnowledgeDoc>(`/knowledge/${encodeURIComponent(id)}`, {
      method: "PATCH",
      json: body,
    }),
  deleteKnowledge: (id: string) =>
    request<{ deleted: boolean }>(`/knowledge/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),

  // --- queue / pipeline ---
  queueStatus: () => request<QueueStatus>(`/queues/status`),

  // --- plant assistant (stateless chat over a live plant snapshot) ---
  chat: (body: {
    message: string;
    history: { role: "user" | "assistant"; content: string }[];
  }) => request<{ reply: string }>(`/chat`, { method: "POST", json: body }),

  // --- simulation control ---
  simStatus: () => request<SimStatus>(`/simulation/status`),
  simStart: () => request<SimStatus>(`/simulation/start`, { method: "POST" }),
  simStop: () => request<SimStatus>(`/simulation/stop`, { method: "POST" }),
  simReset: () =>
    request<Record<string, unknown>>(`/simulation/reset`, {
      method: "POST",
      json: {},
    }),
};
