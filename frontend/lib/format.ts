import type { AnomalyStatus, MetricType, SeverityType } from "./types";

// Per-metric display metadata (label, unit, line color for charts).
export const METRIC_META: Record<
  string,
  { label: string; unit: string; color: string }
> = {
  temp_celsius: { label: "Temperature", unit: "°C", color: "#DB3030" },
  humidity_percent: { label: "Humidity", unit: "%", color: "#016BF8" },
  amplitude_mm: { label: "Vibration", unit: "mm/s", color: "#C28A00" },
  frequency_hz: { label: "Frequency", unit: "Hz", color: "#8F4DBF" },
  pressure_bar: { label: "Pressure", unit: "bar", color: "#00684A" },
  flow_rate_lpm: { label: "Flow rate", unit: "L/min", color: "#016BF8" },
};

export const metricLabel = (m: string) => METRIC_META[m]?.label ?? m;
export const metricUnit = (m: string) => METRIC_META[m]?.unit ?? "";
export const metricColor = (m: string, i = 0) =>
  METRIC_META[m]?.color ?? ["#00684A", "#016BF8", "#B45AF2", "#FFC010"][i % 4];

export const METRIC_TYPE_LABEL: Record<MetricType, string> = {
  environment: "Environment",
  vibration: "Vibration",
  pressure: "Pressure",
  flow: "Flow",
};

// Tailwind class bundles for severity + status badges (see tailwind.config.ts).
export const SEVERITY_BADGE: Record<SeverityType, string> = {
  low: "bg-severity-low text-severity-lowInk",
  medium: "bg-severity-medium/40 text-severity-mediumInk",
  high: "bg-severity-high text-severity-highInk",
};

export const SEVERITY_DOT: Record<SeverityType, string> = {
  low: "bg-severity-lowInk",
  medium: "bg-severity-mediumInk",
  high: "bg-severity-highInk",
};

export const STATUS_BADGE: Record<AnomalyStatus, string> = {
  unresolved: "bg-severity-high text-severity-highInk",
  processing: "bg-[#FEF3C7] text-[#92580C]",
  analyzed: "bg-mongo-green-tint text-mongo-green-dark",
  assigned: "bg-[#E1F7FF] text-[#095896]",
  resolved: "bg-mongo-border text-mongo-slate",
};

// Human labels for anomaly statuses. `processing` reads as "In progress".
export const STATUS_LABEL: Record<AnomalyStatus, string> = {
  unresolved: "Unresolved",
  processing: "In progress",
  analyzed: "Analyzed",
  assigned: "Assigned",
  resolved: "Resolved",
};

export const statusLabel = (s: AnomalyStatus): string => STATUS_LABEL[s] ?? s;

export const ROLE_LABEL: Record<string, string> = {
  staff: "Staff",
  senior: "Senior",
  manager: "Manager",
};

// How an anomaly was detected (detector/detect.py: threshold / rate_of_change /
// statistical). Short label + a muted badge class for the alert views.
const DETECTION_METHOD_META: Record<string, { label: string; badge: string }> = {
  threshold: { label: "Threshold", badge: "bg-mongo-border text-mongo-slate" },
  rate_of_change: { label: "Rate of change", badge: "bg-[#FEF3C7] text-[#92580C]" },
  statistical: { label: "Statistical", badge: "bg-[#E1F7FF] text-[#095896]" },
};

export const detectionMethodLabel = (m?: string) =>
  m ? DETECTION_METHOD_META[m]?.label ?? m.replace(/_/g, " ") : "";
export const detectionMethodBadge = (m?: string) =>
  (m && DETECTION_METHOD_META[m]?.badge) || "bg-mongo-border text-mongo-slate";

// The whole app renders timestamps in Spain/Madrid local time. Backend stores &
// returns UTC (ISO with Z); we convert at the display layer only. Europe/Madrid is
// DST-aware (CEST = UTC+2 in summer, CET = UTC+1 in winter), so it stays correct
// year-round regardless of where the operator's browser is.
export const APP_TIME_ZONE = "Europe/Madrid";

// Backend timestamps come from PyMongo *naive* (no tz offset), e.g.
// "2026-06-23T14:06:00". JS parses a tz-less ISO string as LOCAL time, which
// shifts UTC values by the viewer's offset (the "2h ago for something just
// created" bug). Treat any tz-less timestamp as UTC by appending "Z", then the
// APP_TIME_ZONE conversion shows correct Madrid time. Strings that already carry
// a zone ("…Z" / "+02:00") are left untouched.
function toDate(iso: string): Date {
  const hasZone = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(iso);
  return new Date(hasZone || !iso.includes("T") ? iso : `${iso}Z`);
}

export function formatTime(iso?: string): string {
  if (!iso) return "—";
  const d = toDate(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString([], {
    timeZone: APP_TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatDateTime(iso?: string): string {
  if (!iso) return "—";
  const d = toDate(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString([], {
    timeZone: APP_TIME_ZONE,
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function relativeTime(iso?: string): string {
  if (!iso) return "—";
  const then = toDate(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const secs = Math.round((Date.now() - then) / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

// Pull the max/min threshold for a metric out of a system_metadata rules object.
export function thresholdsForMetric(
  rules: Record<string, number | Record<string, unknown>> | undefined,
  metric: string
): { max?: number; min?: number } {
  if (!rules) return {};
  // Threshold keys follow the exact `max_allowed_<metric>` / `min_allowed_<metric>`
  // contract (e.g. max_allowed_temp_celsius). Match exactly — a substring match on
  // the metric's first token would collide between metrics sharing a prefix.
  const out: { max?: number; min?: number } = {};
  const max = rules[`max_allowed_${metric}`];
  const min = rules[`min_allowed_${metric}`];
  if (typeof max === "number") out.max = max;
  if (typeof min === "number") out.min = min;
  return out;
}

// Header text for a variable's threshold, e.g. "threshold 80°C" / "min 12 L/min".
export function thresholdLabel(
  th: { max?: number; min?: number } | undefined,
  metric: string
): string {
  if (!th) return "";
  const u = metricUnit(metric);
  if (th.max !== undefined) return `threshold ${th.max}${u}`;
  if (th.min !== undefined) return `min ${th.min}${u}`;
  return "";
}

// Direction-aware phrasing for an anomaly toast/alert.
export function breachPhrase(observed?: number, limit?: number): string {
  if (observed === undefined || limit === undefined) return "breached its limit";
  return observed < limit
    ? `dropped below limit of ${limit}`
    : `exceeded limit of ${limit}`;
}
