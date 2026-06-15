"use client";

import { useCallback, useState } from "react";
import clsx from "clsx";

import { api } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";

/**
 * Simulation controls for the dashboard header. Polls /simulation/status so
 * Start/Stop and the Live pill reflect live state regardless of who changed it.
 */
export function SimControls() {
  const status = usePolling(() => api.simStatus(), 5000);
  const running = status.data?.running ?? true;
  const [busy, setBusy] = useState<null | "start" | "stop" | "reset">(null);

  const act = useCallback(
    async (which: "start" | "stop" | "reset") => {
      setBusy(which);
      try {
        if (which === "start") await api.simStart();
        else if (which === "stop") await api.simStop();
        else {
          if (
            !window.confirm(
              "Reset the simulation? This purges all anomalies, telemetry and agent traces, and frees all staff."
            )
          ) {
            return;
          }
          await api.simReset();
        }
        status.refresh();
      } catch (e) {
        window.alert(`Action failed: ${(e as Error).message}`);
      } finally {
        setBusy(null);
      }
    },
    [status]
  );

  const btn =
    "inline-flex items-center gap-1.5 rounded-lg border bg-white px-3.5 py-1.5 text-sm font-medium transition-colors disabled:opacity-50";

  return (
    <div className="flex items-center gap-3">
      <span className="text-sm text-mongo-mist">Simulation</span>
      {running ? (
        <button
          onClick={() => act("stop")}
          disabled={busy !== null}
          className={clsx(btn, "border-severity-high text-severity-highInk hover:bg-severity-high/20")}
        >
          ❚❚ Stop
        </button>
      ) : (
        <button
          onClick={() => act("start")}
          disabled={busy !== null}
          className={clsx(btn, "border-mongo-green-dark text-mongo-green-dark hover:bg-mongo-green-tint")}
        >
          ▶ Start
        </button>
      )}
      <button
        onClick={() => act("reset")}
        disabled={busy !== null}
        className={clsx(btn, "border-mongo-border text-mongo-slate hover:bg-mongo-bg")}
        title="Purge anomalies/telemetry and reset machines"
      >
        ↺ Reset
      </button>
      <span
        className={clsx(
          "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm font-medium",
          running
            ? "border-mongo-green-base/70 text-mongo-green-dark"
            : "border-mongo-border text-mongo-mist"
        )}
      >
        <span
          className={clsx(
            "inline-block h-2 w-2 rounded-full",
            running ? "bg-mongo-green-base" : "bg-mongo-mist"
          )}
        />
        {running ? "Live" : "Paused"}
      </span>
    </div>
  );
}
