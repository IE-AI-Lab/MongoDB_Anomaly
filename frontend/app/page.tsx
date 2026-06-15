"use client";

import { useEffect, useState } from "react";

import { useDashboardData } from "@/hooks/useDashboardData";
import { MachineCard } from "@/components/MachineCard";
import { WorkerPanel } from "@/components/WorkerPanel";
import { AlertsPanel } from "@/components/AlertsPanel";
import { AlertToastStack, type ToastItem } from "@/components/AlertToast";
import { SimControls } from "@/components/SimControls";
import { Spinner } from "@/components/ui/Spinner";
import type { Anomaly } from "@/lib/types";

// Module-scoped so a given anomaly toasts exactly once per browser session —
// navigating to another page and back must NOT replay toasts (component state
// would reset on remount and re-fire them).
const toastSeen = new Set<string>();
let toastPrimed = false;

export default function DashboardPage() {
  const {
    sensors,
    readingsBySensor,
    thresholds,
    anomalies,
    staff,
    loading,
    error,
  } = useDashboardData();

  // Newest active anomaly per sensor, for the per-card warning banner.
  const anomalyBySensor: Record<string, Anomaly> = {};
  for (const a of anomalies) {
    if (a.status === "unresolved" || a.status === "analyzed") {
      if (!anomalyBySensor[a.sensor_id]) anomalyBySensor[a.sensor_id] = a;
    }
  }

  // Toast on newly-seen anomalies (diff against previously-seen ids). We watch
  // unresolved AND analyzed, not just unresolved: the agent worker advances an
  // anomaly unresolved -> analyzed within seconds, often faster than the poll
  // interval, so keying only on "unresolved" would miss the toast entirely.
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  useEffect(() => {
    if (loading) return; // wait for the first completed fetch before priming
    const active = anomalies.filter(
      (a) => a.status === "unresolved" || a.status === "analyzed"
    );
    if (!toastPrimed) {
      // First load this session: record what already exists without toasting it.
      active.forEach((a) => toastSeen.add(a.anomaly_id));
      toastPrimed = true;
      return;
    }
    const fresh = active.filter((a) => !toastSeen.has(a.anomaly_id));
    if (fresh.length) {
      fresh.forEach((a) => toastSeen.add(a.anomaly_id));
      setToasts((prev) =>
        [...fresh.map((a) => ({ anomaly: a, id: a.anomaly_id })), ...prev].slice(0, 4)
      );
    }
  }, [anomalies, loading]);

  // Auto-dismiss each toast after 12s.
  useEffect(() => {
    if (toasts.length === 0) return;
    const timers = toasts.map((t) =>
      setTimeout(() => setToasts((prev) => prev.filter((x) => x.id !== t.id)), 12000)
    );
    return () => timers.forEach(clearTimeout);
  }, [toasts]);

  const dismiss = (id: string) => setToasts((prev) => prev.filter((t) => t.id !== id));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-mongo-ink">Machine Dashboard</h1>
          <p className="text-sm text-mongo-mist">
            Real-time sensor telemetry · {sensors.length} machines monitored
          </p>
        </div>
        <div className="flex items-center gap-3">
          {loading && <Spinner />}
          <SimControls />
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-severity-high bg-severity-high/30 px-4 py-3 text-sm text-severity-highInk">
          Could not reach the data layer ({error.message}). Is the API running on
          port 8000?
        </div>
      )}

      {/* Left column: machine side-scroll with Recent Alerts directly below.
          Right column: the Field Workers rail spans down beside both. */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-6">
          <section className="min-w-0">
            {sensors.length === 0 && !loading ? (
              <div className="rounded-xl border border-dashed border-mongo-border px-6 py-10 text-sm text-mongo-mist">
                No machines found. Seed the database with{" "}
                <code className="font-mono">python -m scripts.init_db</code>.
              </div>
            ) : (
              // Side-scroll: exactly 3 machine columns fit; scroll right for more.
              <div className="scroll-x flex snap-x snap-mandatory gap-6 overflow-x-auto pb-3">
                {sensors.map((s) => (
                  <div
                    key={s.sensor_id}
                    className="w-[calc((100%-3rem)/3)] min-w-[300px] shrink-0 snap-start"
                  >
                    <MachineCard
                      sensor={s}
                      readings={readingsBySensor[s.sensor_id] ?? []}
                      thresholds={thresholds}
                      activeAnomaly={anomalyBySensor[s.sensor_id]}
                    />
                  </div>
                ))}
              </div>
            )}
          </section>

          <AlertsPanel anomalies={anomalies} />
        </div>

        {/* Right rail: field workers, spanning beside machines + alerts */}
        <div>
          <WorkerPanel staff={staff} />
        </div>
      </div>

      <AlertToastStack toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}
