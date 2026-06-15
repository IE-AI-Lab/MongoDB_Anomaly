// TypeScript mirrors of the Mongo document contracts the data layer returns
// (see ingestor_service + scripts/init_db.py). Responses always strip `_id`.

export type MetricType = "environment" | "vibration" | "pressure" | "flow";
export type SeverityType = "low" | "medium" | "high";
export type AnomalyStatus = "unresolved" | "analyzed" | "assigned" | "resolved";
export type StaffRole = "staff" | "senior" | "manager";

export interface Sensor {
  sensor_id: string;
  metric_type: MetricType;
  facility_id: string;
  equipment_id: string;
  equipment_type: string;
  metrics: string[]; // metric fields this sensor reports, e.g. ["temp_celsius"]
  expected_interval_seconds: number;
  is_active: boolean;
}

// telemetry_history doc. Metric values are FLATTENED under `reading`
// (e.g. reading.temp_celsius), alongside metric_type/unit_system.
export interface Reading {
  timestamp_utc: string;
  sensor_id: string;
  sequence_number?: number;
  quality?: string;
  reading: {
    metric_type: MetricType;
    unit_system?: string;
    [metric: string]: number | string | undefined;
  };
}

export interface TriggerValue {
  metric: string;
  observed: number;
  limit: number;
  unit: string;
  consecutive_count: number;
}

export interface SimilarCase {
  document_id?: string;
  section_title?: string;
  text_content?: string;
  score?: number;
  [k: string]: unknown;
}

export interface Anomaly {
  anomaly_id: string;
  timestamp_utc: string;
  sensor_id: string;
  facility_id?: string;
  equipment_id?: string;
  metric_type?: MetricType;
  error_code: string;
  severity_level: number;
  severity_type: SeverityType;
  breach_ratio?: number;
  trigger_value: TriggerValue;
  status: AnomalyStatus;
  description?: string;
  recommended_solution?: string;
  similar_cases?: SimilarCase[];
  recommended_employee_id?: string;
  assigned_to_employee_id?: string;
  agent_run_id?: string;
  resolution_notes?: string;
  resolved_by?: string;
  resolved_at_utc?: string;
  created_at_utc?: string;
  updated_at_utc?: string;
}

export interface Staff {
  employee_id: string;
  name: string;
  role: StaffRole;
  escalation_rank: number;
  specialization: string[];
  handled_severity_type: SeverityType;
  is_on_call: boolean;
  contact_method?: string;
  phone_number?: string;
  email?: string;
  facility_ids?: string[];
  is_active: boolean;
}

export interface KnowledgeDoc {
  document_id: string;
  source_file?: string;
  page_number?: number | null;
  section_title: string;
  equipment_type?: string | null;
  associated_error_codes: string[];
  text_content: string;
  chunk_index?: number;
  is_active: boolean;
  curation_status?: string;
  ingested_at_utc?: string;
  updated_at_utc?: string;
}

export interface ExecutionStep {
  step_index: number;
  tool_name: string;
  started_at?: string;
  completed_at?: string;
  input_summary?: Record<string, unknown>;
  output_summary?: Record<string, unknown>;
  success?: boolean;
  latency_ms?: number;
}

export interface AgentLog {
  run_id: string;
  anomaly_id: string;
  started_at?: string;
  completed_at?: string;
  status: "running" | "completed" | "failed";
  agent_name?: string;
  agent_version?: string;
  model_id?: string;
  execution_steps?: ExecutionStep[];
  final_action_taken?: string;
  tokens_used?: { prompt: number; completion: number; total: number; embedding: number };
  error?: { code?: string; message?: string };
}

export interface SystemMetadata {
  config_type: string;
  target_metric: string;
  rules?: Record<string, number | Record<string, unknown>>;
  running?: boolean;
  description?: string;
}

export interface SimStatus {
  running: boolean;
}

export type KnowledgeSource = "seed" | "feedback" | "manual";
