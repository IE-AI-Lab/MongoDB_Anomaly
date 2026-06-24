"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";

import { api } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import type { Anomaly, SimilarCase } from "@/lib/types";
import { Card } from "@/components/ui/Card";
import { EmptyRow, LoadingRow } from "@/components/ui/Spinner";
import { AssignWorker } from "@/components/AssignWorker";
import { FeedbackForm } from "@/components/FeedbackForm";
import {
  STATUS_BADGE,
  statusLabel,
  breachPhrase,
  formatDateTime,
  metricLabel,
} from "@/lib/format";

// Reports worth reviewing: anything not yet resolved (open/processing/analyzed/assigned).
const ACTIVE = new Set(["unresolved", "processing", "analyzed", "assigned"]);

function similarCaseText(c: SimilarCase | string): { title: string; body: string } {
  if (typeof c === "string") return { title: "Similar case", body: c };
  return {
    title: c.section_title ?? c.document_id ?? "Similar case",
    body: c.text_content ?? JSON.stringify(c),
  };
}

export default function FeedbackPage() {
  const { data, loading, refresh } = usePolling(
    () => api.listAnomalies({ limit: 100 }),
    8000
  );
  const reports = (data ?? []).filter((a) => ACTIVE.has(a.status));
  const [selectedId, setSelectedId] = useState<string>();

  // Keep a valid selection: default to the newest report; re-pick if the
  // selected one resolved away.
  useEffect(() => {
    const list = (data ?? []).filter((a) => ACTIVE.has(a.status));
    if (list.length === 0) {
      if (selectedId) setSelectedId(undefined);
      return;
    }
    if (!selectedId || !list.some((r) => r.anomaly_id === selectedId)) {
      setSelectedId(list[0].anomaly_id);
    }
  }, [data, selectedId]);

  const selected = reports.find((r) => r.anomaly_id === selectedId);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold text-mongo-ink">Worker Feedback</h1>
        <p className="text-sm text-mongo-mist">
          Review reports, assign workers, and submit post-resolution feedback
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
        {/* Master: open reports */}
        <Card
          title="Open Reports"
          action={
            <button
              onClick={refresh}
              className="rounded p-1 text-mongo-mist hover:bg-mongo-bg hover:text-mongo-ink"
              aria-label="Refresh"
              title="Refresh"
            >
              ↻
            </button>
          }
          className="self-start"
        >
          {loading && !data ? (
            <LoadingRow />
          ) : reports.length === 0 ? (
            <EmptyRow label="No open reports." />
          ) : (
            <ul className="max-h-[70vh] divide-y divide-mongo-border overflow-y-auto">
              {reports.map((r) => {
                const active = r.anomaly_id === selectedId;
                return (
                  <li key={r.anomaly_id}>
                    <button
                      onClick={() => setSelectedId(r.anomaly_id)}
                      className={clsx(
                        "w-full border-l-2 px-4 py-3 text-left transition-colors",
                        active
                          ? "border-mongo-green-dark bg-mongo-green-tint/40"
                          : "border-transparent hover:bg-mongo-bg"
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-semibold text-mongo-ink">
                          {r.equipment_id ?? r.sensor_id}
                        </span>
                        <span className="text-[11px] text-mongo-mist">
                          {formatDateTime(r.timestamp_utc)}
                        </span>
                      </div>
                      <div className="mt-1 flex items-center justify-between gap-2">
                        <span className="text-xs text-mongo-slate">
                          {metricLabel(r.trigger_value?.metric ?? "")}
                        </span>
                        <span
                          className={clsx(
                            "rounded-full px-2 py-0.5 text-[11px] font-medium capitalize",
                            STATUS_BADGE[r.status]
                          )}
                        >
                          {r.status === "unresolved" ? "open" : statusLabel(r.status)}
                        </span>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        {/* Detail */}
        <div>
          {selected ? (
            <ReportDetail anomaly={selected} onChanged={refresh} />
          ) : (
            <Card>
              <div className="px-6 py-16 text-center text-sm text-mongo-mist">
                {reports.length === 0
                  ? "No open reports right now. New anomalies will show up here for review."
                  : "Select a report on the left to review it."}
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function ReportDetail({
  anomaly,
  onChanged,
}: {
  anomaly: Anomaly;
  onChanged: () => void;
}) {
  const tv = anomaly.trigger_value;
  const isAssigned = anomaly.status === "assigned" || anomaly.status === "resolved";

  return (
    <div className="space-y-5">
      <Card>
        <div className="px-5 py-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-mongo-ink">
                {anomaly.equipment_id ?? anomaly.sensor_id}{" "}
                <span className="font-normal text-mongo-slate">
                  — {metricLabel(tv?.metric ?? "")}
                </span>
              </h2>
              <p className="mt-1 text-sm text-mongo-slate">
                Reading{" "}
                <span className="font-semibold text-severity-highInk">
                  {tv?.observed}
                </span>{" "}
                {breachPhrase(tv?.observed, tv?.limit)} ·{" "}
                {formatDateTime(anomaly.timestamp_utc)}
              </p>
            </div>
            <span
              className={clsx(
                "shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium capitalize",
                STATUS_BADGE[anomaly.status]
              )}
            >
              {statusLabel(anomaly.status)}
            </span>
          </div>

          <div className="mt-4">
            {isAssigned ? (
              <div className="rounded-lg border border-mongo-border bg-mongo-bg px-4 py-2.5 text-sm">
                <span className="text-mongo-slate">Assigned to </span>
                <span className="font-medium text-mongo-ink">
                  {anomaly.assigned_to_employee_id ?? "—"}
                </span>
              </div>
            ) : (
              <AssignWorker
                key={anomaly.anomaly_id}
                anomaly={anomaly}
                onAssigned={onChanged}
              />
            )}
          </div>
        </div>
      </Card>

      <Card title="Agent analysis">
        <p
          className={clsx(
            "px-5 py-4 text-sm",
            anomaly.description ? "text-mongo-ink" : "italic text-mongo-mist"
          )}
        >
          {anomaly.description || "The agent has not written a description yet."}
        </p>
      </Card>

      <Card title="Recommended solution">
        <p
          className={clsx(
            "px-5 py-4 text-sm",
            anomaly.recommended_solution ? "text-mongo-ink" : "italic text-mongo-mist"
          )}
        >
          {anomaly.recommended_solution || "No recommendation recorded."}
        </p>
      </Card>

      <Card title="Similar past cases (from knowledge base)">
        <div className="space-y-3 px-5 py-4">
          {!anomaly.similar_cases || anomaly.similar_cases.length === 0 ? (
            <p className="text-sm text-mongo-mist">No similar cases retrieved.</p>
          ) : (
            anomaly.similar_cases.map((c, i) => {
              const { title, body } = similarCaseText(c);
              return (
                <div
                  key={i}
                  className="rounded-lg border-l-2 border-mongo-green-dark bg-mongo-bg px-3 py-2.5"
                >
                  <p className="text-sm font-medium text-mongo-ink">{title}</p>
                  <p className="mt-1 text-sm text-mongo-slate">{body}</p>
                </div>
              );
            })
          )}
        </div>
      </Card>

      {isAssigned && (
        <Card title="Submit feedback">
          <div className="px-5 py-4">
            <FeedbackForm
              key={anomaly.anomaly_id}
              anomaly={anomaly}
              onResolved={onChanged}
            />
          </div>
        </Card>
      )}
    </div>
  );
}
