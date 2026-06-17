"use client";

import clsx from "clsx";

import { api } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import { Card } from "@/components/ui/Card";
import type { SeverityType } from "@/lib/types";

// Agent job queue depth, per severity stream, plus the dead-letter count.
// Backed by GET /queues/status (Redis XLEN). When dispatch isn't redis the
// endpoint returns available=false and we show a muted "not active" note.
const ROWS: { sev: SeverityType; label: string; dot: string }[] = [
  { sev: "high", label: "High", dot: "bg-severity-highInk" },
  { sev: "medium", label: "Medium", dot: "bg-severity-mediumInk" },
  { sev: "low", label: "Low", dot: "bg-severity-lowInk" },
];

export function QueuePanel({ resetSignal }: { resetSignal?: number } = {}) {
  // resetSignal is a dep: when it changes (operator hit Reset) the hook
  // re-fetches immediately, so the depths drop to 0 without a poll-tick lag.
  const q = usePolling(() => api.queueStatus(), 5000, [resetSignal]);
  const data = q.data;
  const dlq = data?.dlq ?? 0;

  return (
    <Card
      title="Agent Queue"
      action={
        data && !data.available ? (
          <span className="text-xs text-mongo-mist">not active</span>
        ) : (
          <span className="text-xs text-mongo-mist">priority order</span>
        )
      }
    >
      <div className="divide-y divide-mongo-border">
        {ROWS.map(({ sev, label, dot }) => (
          <div key={sev} className="flex items-center justify-between px-4 py-2.5 text-sm">
            <span className="inline-flex items-center gap-2">
              <span className={clsx("inline-block h-2 w-2 rounded-full", dot)} />
              {label}
            </span>
            <span className="font-mono text-mongo-ink">{data?.streams?.[sev] ?? "—"}</span>
          </div>
        ))}
        <div
          className={clsx(
            "flex items-center justify-between px-4 py-2.5 text-sm",
            dlq > 0 && "bg-severity-high/20"
          )}
        >
          <span
            className={clsx(
              "inline-flex items-center gap-2 font-medium",
              dlq > 0 ? "text-severity-highInk" : "text-mongo-slate"
            )}
            title="Jobs that failed every retry and were dead-lettered"
          >
            Dead-letter
          </span>
          <span
            className={clsx(
              "font-mono",
              dlq > 0 ? "font-semibold text-severity-highInk" : "text-mongo-ink"
            )}
          >
            {data ? dlq : "—"}
          </span>
        </div>
      </div>
    </Card>
  );
}
