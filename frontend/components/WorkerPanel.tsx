"use client";

import clsx from "clsx";

import type { MetricType, Staff } from "@/lib/types";
import { Card } from "@/components/ui/Card";
import { EmptyRow } from "@/components/ui/Spinner";
import { METRIC_TYPE_LABEL, ROLE_LABEL } from "@/lib/format";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

const specLabel = (s: string) =>
  METRIC_TYPE_LABEL[s as MetricType] ?? s.charAt(0).toUpperCase() + s.slice(1);

export function WorkerPanel({ staff }: { staff: Staff[] }) {
  const available = staff.filter((s) => s.is_on_call).length;

  return (
    <Card className="flex h-full flex-col">
      <header className="border-b border-mongo-border px-5 py-4">
        <h2 className="text-base font-semibold text-mongo-ink">Field Workers</h2>
        <p className="mt-0.5 text-xs text-mongo-mist">{available} available</p>
      </header>

      <ul className="divide-y divide-mongo-border overflow-y-auto">
        {staff.length === 0 && <EmptyRow label="No staff" />}
        {staff.map((s) => (
          <li key={s.employee_id} className="flex items-start gap-3 px-5 py-3.5">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-mongo-green-darker text-xs font-semibold text-mongo-green-base">
              {initials(s.name)}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <p className="truncate text-sm font-semibold text-mongo-ink">{s.name}</p>
                <span
                  className={clsx(
                    "shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium",
                    s.is_on_call
                      ? "bg-mongo-green-tint text-mongo-green-dark"
                      : "bg-mongo-border text-mongo-slate"
                  )}
                >
                  {s.is_on_call ? "Free" : "Busy"}
                </span>
              </div>
              <p className="truncate text-xs text-mongo-mist">
                {ROLE_LABEL[s.role] ?? s.role} · handles {s.handled_severity_type}
              </p>
              <div className="mt-1.5 flex flex-wrap items-center gap-1">
                {s.specialization.map((tag) => (
                  <span
                    key={tag}
                    className="rounded bg-mongo-bg px-1.5 py-0.5 text-[11px] text-mongo-slate"
                  >
                    {specLabel(tag)}
                  </span>
                ))}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
