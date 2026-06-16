"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { AgentLog, Anomaly, SimilarCase } from "@/lib/types";
import { Card } from "@/components/ui/Card";
import { buttonClasses } from "@/components/ui/Button";
import { LoadingRow } from "@/components/ui/Spinner";
import { AssignWorker } from "@/components/AssignWorker";
import { AgentTrace } from "@/components/AgentTrace";
import {
  SEVERITY_BADGE,
  STATUS_BADGE,
  detectionMethodBadge,
  detectionMethodLabel,
  formatDateTime,
} from "@/lib/format";
import clsx from "clsx";

function similarCaseText(c: SimilarCase | string): { title: string; body: string } {
  if (typeof c === "string") return { title: "Similar case", body: c };
  return {
    title: c.section_title ?? c.document_id ?? "Similar case",
    body: c.text_content ?? JSON.stringify(c),
  };
}

export default function ReportPage({ params }: { params: { id: string } }) {
  const { id } = params;
  const [anomaly, setAnomaly] = useState<Anomaly>();
  const [logs, setLogs] = useState<AgentLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();

  const load = useCallback(async () => {
    try {
      const [a, l] = await Promise.all([
        api.getAnomaly(id),
        api.listAgentLogs({ anomaly_id: id }).catch(() => [] as AgentLog[]),
      ]);
      setAnomaly(a);
      setLogs(l);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <LoadingRow label="Loading report…" />;
  if (error || !anomaly)
    return (
      <div className="rounded-lg border border-severity-high bg-severity-high/30 px-4 py-3 text-sm text-severity-highInk">
        {error ?? "Anomaly not found."}{" "}
        <Link href="/" className="font-medium underline">
          Back to dashboard
        </Link>
      </div>
    );

  const tv = anomaly.trigger_value;
  const canFeedback = anomaly.status === "assigned" || anomaly.status === "resolved";

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2 text-sm text-mongo-mist">
        <Link href="/" className="hover:text-mongo-ink">
          Dashboard
        </Link>
        <span>/</span>
        <span className="font-mono text-mongo-ink">{anomaly.anomaly_id}</span>
      </div>

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-mongo-ink">
            {anomaly.equipment_id ?? anomaly.sensor_id}
          </h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm">
            <span
              className={clsx(
                "rounded-full px-2 py-0.5 text-xs font-medium capitalize",
                SEVERITY_BADGE[anomaly.severity_type]
              )}
            >
              {anomaly.severity_type} · L{anomaly.severity_level}
            </span>
            <span
              className={clsx(
                "rounded-full px-2 py-0.5 text-xs font-medium capitalize",
                STATUS_BADGE[anomaly.status]
              )}
            >
              {anomaly.status}
            </span>
            <span className="font-mono text-xs text-mongo-slate">{anomaly.error_code}</span>
            {anomaly.detection_method && (
              <span
                className={clsx(
                  "rounded px-1.5 py-0.5 text-[10px] font-medium",
                  detectionMethodBadge(anomaly.detection_method)
                )}
                title="How the detector flagged this anomaly"
              >
                {detectionMethodLabel(anomaly.detection_method)}
              </span>
            )}
            <span className="text-xs text-mongo-mist">{formatDateTime(anomaly.timestamp_utc)}</span>
          </div>
        </div>
        {canFeedback && (
          <Link
            href={`/anomalies/${anomaly.anomaly_id}/feedback`}
            className={buttonClasses("primary")}
          >
            Submit feedback →
          </Link>
        )}
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        {/* Left/main: analysis */}
        <div className="space-y-5 lg:col-span-2">
          <Card title="Agent analysis">
            <div className="space-y-4 px-4 py-4">
              <Field label="Description" value={anomaly.description} fallback="The agent has not written a description yet." />
              <Field
                label="Recommended solution"
                value={anomaly.recommended_solution}
                fallback="No recommendation recorded."
              />
            </div>
          </Card>

          <Card title="Similar past cases (RAG)">
            <div className="space-y-3 px-4 py-4">
              {(!anomaly.similar_cases || anomaly.similar_cases.length === 0) && (
                <p className="text-sm text-mongo-mist">No similar cases retrieved.</p>
              )}
              {anomaly.similar_cases?.map((c, i) => {
                const { title, body } = similarCaseText(c);
                return (
                  <div
                    key={i}
                    className="rounded-lg border border-mongo-border bg-mongo-bg px-3 py-2.5"
                  >
                    <p className="text-sm font-medium text-mongo-ink">{title}</p>
                    <p className="mt-1 text-sm text-mongo-slate">{body}</p>
                  </div>
                );
              })}
            </div>
          </Card>

          <Card title="Agent execution trace">
            <AgentTrace logs={logs} />
          </Card>
        </div>

        {/* Right: trigger + assignment */}
        <div className="space-y-5">
          <Card title="Trigger">
            <dl className="divide-y divide-mongo-border text-sm">
              <Row k="Sensor" v={anomaly.sensor_id} />
              <Row k="Metric" v={tv?.metric} />
              <Row k="Observed" v={`${tv?.observed} ${tv?.unit ?? ""}`} />
              <Row k="Limit" v={`${tv?.limit} ${tv?.unit ?? ""}`} />
              <Row
                k="Breach"
                v={anomaly.breach_ratio !== undefined ? `${Math.round(anomaly.breach_ratio * 100)}%` : "—"}
              />
              <Row k="Consecutive" v={String(tv?.consecutive_count ?? "—")} />
              <Row k="Facility" v={anomaly.facility_id} />
            </dl>
          </Card>

          <Card title="Assignment">
            <div className="px-4 py-4">
              <AssignWorker anomaly={anomaly} onAssigned={(u) => setAnomaly(u)} />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  fallback,
}: {
  label: string;
  value?: string;
  fallback: string;
}) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-mongo-mist">{label}</p>
      <p className={clsx("mt-1 text-sm", value ? "text-mongo-ink" : "text-mongo-mist italic")}>
        {value || fallback}
      </p>
    </div>
  );
}

function Row({ k, v }: { k: string; v?: string }) {
  return (
    <div className="flex items-center justify-between px-4 py-2">
      <dt className="text-mongo-mist">{k}</dt>
      <dd className="font-medium text-mongo-ink">{v ?? "—"}</dd>
    </div>
  );
}
