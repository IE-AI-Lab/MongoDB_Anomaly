"use client";

import Link from "next/link";
import clsx from "clsx";

import type { Anomaly } from "@/lib/types";
import { Card } from "@/components/ui/Card";
import { EmptyRow } from "@/components/ui/Spinner";
import {
  SEVERITY_DOT,
  STATUS_BADGE,
  statusLabel,
  detectionMethodBadge,
  detectionMethodLabel,
  relativeTime,
} from "@/lib/format";

const ACTIVE = new Set(["unresolved", "processing", "analyzed", "assigned"]);

export function AlertsPanel({ anomalies }: { anomalies: Anomaly[] }) {
  const active = anomalies.filter((a) => ACTIVE.has(a.status));

  return (
    <Card
      title="Recent Alerts"
      action={
        <span className="text-xs text-mongo-mist">{active.length} active</span>
      }
    >
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-mongo-border text-left text-xs text-mongo-mist">
              <th className="px-4 py-2 font-medium">Severity</th>
              <th className="px-4 py-2 font-medium">Machine</th>
              <th className="px-4 py-2 font-medium">Error</th>
              <th className="px-4 py-2 font-medium">Observed</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Detected</th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-mongo-border">
            {active.length === 0 && (
              <tr>
                <td colSpan={7}>
                  <EmptyRow label="No active alerts" />
                </td>
              </tr>
            )}
            {active.map((a) => (
              <tr key={a.anomaly_id} className="hover:bg-mongo-bg">
                <td className="px-4 py-2.5">
                  <span className="inline-flex items-center gap-2">
                    <span
                      className={clsx(
                        "inline-block h-2.5 w-2.5 rounded-full",
                        SEVERITY_DOT[a.severity_type]
                      )}
                    />
                    <span className="capitalize">{a.severity_type}</span>
                    <span className="text-xs text-mongo-mist">L{a.severity_level}</span>
                  </span>
                </td>
                <td className="px-4 py-2.5">
                  <div className="font-medium text-mongo-ink">{a.equipment_id ?? a.sensor_id}</div>
                  <div className="text-xs text-mongo-mist">{a.sensor_id}</div>
                </td>
                <td className="px-4 py-2.5">
                  <div className="font-mono text-xs">{a.error_code}</div>
                  {a.detection_method && (
                    <span
                      className={clsx(
                        "mt-1 inline-block rounded px-1.5 py-0.5 text-[10px] font-medium",
                        detectionMethodBadge(a.detection_method)
                      )}
                    >
                      {detectionMethodLabel(a.detection_method)}
                    </span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-xs text-mongo-slate">
                  {a.trigger_value?.observed} / limit {a.trigger_value?.limit}
                </td>
                <td className="px-4 py-2.5">
                  <span
                    className={clsx(
                      "rounded-full px-2 py-0.5 text-xs font-medium capitalize",
                      STATUS_BADGE[a.status]
                    )}
                  >
                    {statusLabel(a.status)}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-xs text-mongo-mist">
                  {relativeTime(a.timestamp_utc)}
                </td>
                <td className="px-4 py-2.5 text-right">
                  <Link
                    href={`/anomalies/${a.anomaly_id}`}
                    className="text-xs font-medium text-mongo-green-dark hover:underline"
                  >
                    View report →
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
