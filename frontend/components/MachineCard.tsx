"use client";

import clsx from "clsx";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { Anomaly, Reading, Sensor, SystemMetadata } from "@/lib/types";
import {
  METRIC_TYPE_LABEL,
  metricLabel,
  thresholdLabel,
  thresholdsForMetric,
} from "@/lib/format";
import { MetricChart } from "./MetricChart";

interface Props {
  sensor: Sensor;
  readings: Reading[];
  thresholds: SystemMetadata[];
  activeAnomaly?: Anomaly;
}

// Per-machine "degradation rate" control. Writes sim_stress (0..1) to the API,
// debounced; the simulator reads it each cycle to set how fast this machine
// climbs toward its alarm. Higher = breaches sooner / more often.
function StressSlider({ sensor }: { sensor: Sensor }) {
  const [value, setValue] = useState(sensor.sim_stress ?? 0.2);
  const editedAt = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  // Reconcile with polled data, but don't clobber a value the user just set.
  useEffect(() => {
    if (sensor.sim_stress === undefined) return;
    if (Date.now() - editedAt.current < 3000) return;
    setValue(sensor.sim_stress);
  }, [sensor.sim_stress]);

  const onChange = (next: number) => {
    setValue(next);
    editedAt.current = Date.now();
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      api.setSensorStress(sensor.sensor_id, next).catch(() => {
        /* transient; next poll reconciles */
      });
    }, 350);
  };

  useEffect(() => () => timer.current && clearTimeout(timer.current), []);

  const pct = Math.round(value * 100);
  return (
    <div className="flex items-center gap-2 px-4 py-2">
      <span className="shrink-0 text-[10px] uppercase tracking-wide text-mongo-mist">
        Degradation
      </span>
      <input
        type="range"
        min={0}
        max={100}
        value={pct}
        onChange={(e) => onChange(Number(e.target.value) / 100)}
        aria-label={`Degradation rate for ${sensor.equipment_id}`}
        className="h-1 flex-1 cursor-pointer accent-mongo-green-base"
      />
      <span className="w-8 shrink-0 text-right text-[11px] font-medium tabular-nums text-mongo-ink">
        {pct}%
      </span>
    </div>
  );
}

// Deterministically create an anomaly on this machine (demo/dev affordance).
// Disabled while one is already active — the dashboard's poll will flag the card
// and fire the alert toast within a few seconds, no manual refresh needed.
function TriggerAnomalyButton({
  sensor,
  disabled,
}: {
  sensor: Sensor;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState(false);

  const onClick = async () => {
    setBusy(true);
    try {
      await api.createAnomaly(sensor.sensor_id);
    } catch (e) {
      window.alert(`Could not create anomaly: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      onClick={onClick}
      disabled={busy || disabled}
      title={
        disabled
          ? "This machine already has an active anomaly"
          : "Create a test anomaly on this machine"
      }
      className="inline-flex items-center gap-1 rounded-md border border-mongo-border px-2.5 py-1 text-[11px] font-medium text-mongo-slate transition-colors hover:bg-mongo-bg disabled:opacity-40"
    >
      {busy ? "Creating…" : "Trigger anomaly"}
    </button>
  );
}

export function MachineCard({ sensor, readings, thresholds, activeAnomaly }: Props) {
  const metrics = sensor.metrics ?? [];

  // Build per-metric threshold lookup from system_metadata.
  const thresholdMap: Record<string, { max?: number; min?: number }> = {};
  for (const m of metrics) {
    const cfg = thresholds.find((t) => t.target_metric === m);
    if (cfg) thresholdMap[m] = thresholdsForMetric(cfg.rules, m);
  }

  const flagged = Boolean(activeAnomaly);

  return (
    <div
      className={clsx(
        "flex flex-col rounded-xl border bg-mongo-surface shadow-card",
        flagged
          ? "border-severity-highInk/40 ring-1 ring-severity-highInk/30"
          : "border-mongo-border"
      )}
    >
      <div className="flex items-start justify-between gap-2 border-b border-mongo-border px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span
              className={clsx(
                "inline-block h-2 w-2 shrink-0 rounded-full",
                flagged ? "bg-severity-highInk" : "bg-mongo-green-base"
              )}
            />
            <h3 className="truncate text-[15px] font-semibold text-mongo-ink">
              {sensor.equipment_id}
            </h3>
          </div>
          <p className="mt-0.5 truncate text-[10px] uppercase tracking-wide text-mongo-mist">
            {sensor.equipment_type.replace(/_/g, " ")} · {sensor.sensor_id}
          </p>
        </div>
        <span className="shrink-0 rounded-full bg-mongo-green-tint px-2 py-0.5 text-[10px] font-medium text-mongo-green-dark">
          {METRIC_TYPE_LABEL[sensor.metric_type]}
        </span>
      </div>

      {/* One time series per variable, stacked vertically, each with its own
          Y-scale + threshold line so metrics of very different magnitude
          (e.g. amplitude vs frequency) are both readable. */}
      <div className="flex flex-col gap-1 px-2.5 py-2.5">
        {metrics.map((m) => {
          const th = thresholdMap[m];
          return (
            <div key={m} className="pb-0.5">
              <div className="flex items-baseline justify-between px-1">
                <span className="text-[13px] font-medium text-mongo-ink">
                  {metricLabel(m)}
                </span>
                <span className="text-[11px] text-mongo-mist">{thresholdLabel(th, m)}</span>
              </div>
              <div className="mt-1">
                <MetricChart
                  readings={readings}
                  metrics={[m]}
                  thresholds={{ [m]: th }}
                  height={128}
                />
              </div>
            </div>
          );
        })}
      </div>

      <div className="border-t border-mongo-border">
        <StressSlider sensor={sensor} />
        <div className="flex justify-end px-4 pb-2.5">
          <TriggerAnomalyButton sensor={sensor} disabled={flagged} />
        </div>
      </div>

      {flagged && activeAnomaly && (
        <div className="rounded-b-xl bg-severity-high/40 px-4 py-1.5 text-[11px] font-medium text-severity-highInk">
          ⚠ {activeAnomaly.error_code} · {activeAnomaly.severity_type} severity
        </div>
      )}
    </div>
  );
}
