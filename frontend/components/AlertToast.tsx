"use client";

import Link from "next/link";

import type { Anomaly } from "@/lib/types";
import { breachPhrase, metricLabel, metricUnit } from "@/lib/format";
import { buttonClasses } from "@/components/ui/Button";

export interface ToastItem {
  anomaly: Anomaly;
  id: string;
}

export function AlertToastStack({
  toasts,
  onDismiss,
}: {
  toasts: ToastItem[];
  onDismiss: (id: string) => void;
}) {
  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-5 right-5 z-50 flex w-[340px] flex-col gap-3">
      {toasts.map(({ anomaly: a, id }) => {
        const m = a.trigger_value?.metric ?? "";
        const observed = a.trigger_value?.observed;
        const limit = a.trigger_value?.limit;
        return (
          <div
            key={id}
            className="animate-toast-in overflow-hidden rounded-xl border border-mongo-border border-t-4 border-t-severity-highInk bg-mongo-surface shadow-pop"
          >
            <div className="px-4 py-3">
              <div className="flex items-start justify-between">
                <span className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-severity-highInk">
                  <span className="inline-block h-2 w-2 rounded-full bg-severity-highInk" />
                  Anomaly detected
                </span>
                <button
                  onClick={() => onDismiss(id)}
                  className="-mt-1 text-mongo-mist hover:text-mongo-ink"
                  aria-label="Dismiss"
                >
                  ✕
                </button>
              </div>

              <p className="mt-1.5 text-base font-semibold text-mongo-ink">
                {a.equipment_id ?? a.sensor_id}
              </p>
              <p className="mt-0.5 text-[13px] text-mongo-slate">
                {metricLabel(m).toLowerCase()} reading{" "}
                <span className="font-semibold text-severity-highInk">
                  {observed}
                  {metricUnit(m)}
                </span>{" "}
                {breachPhrase(observed, limit)}
              </p>

              <Link
                href={`/anomalies/${a.anomaly_id}`}
                onClick={() => onDismiss(id)}
                className={buttonClasses("secondary", "sm", "mt-3 w-full border-mongo-green-dark text-mongo-green-dark hover:bg-mongo-green-tint")}
              >
                View Report
              </Link>
            </div>
          </div>
        );
      })}
    </div>
  );
}
