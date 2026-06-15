"use client";

// WS-shaped contract: this is the polling stand-in for the future /ws EventBus.
// When the backend WebSocket lands, swap these internals to subscribe to
// reading/anomaly/staff/simulation events; the returned shape can stay the same.

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type {
  Anomaly,
  Reading,
  Sensor,
  Staff,
  SystemMetadata,
} from "@/lib/types";
import { usePolling } from "./usePolling";

const READINGS_MS = 4000;
const ANOMALIES_MS = 4000;
const STAFF_MS = 8000;
const SIM_MS = 5000;
const READINGS_WINDOW_MIN = 30;

export interface DashboardData {
  sensors: Sensor[];
  readingsBySensor: Record<string, Reading[]>;
  thresholds: SystemMetadata[];
  anomalies: Anomaly[];
  staff: Staff[];
  simRunning: boolean;
  loading: boolean;
  error?: Error;
  controls: {
    start: () => Promise<void>;
    stop: () => Promise<void>;
    reset: () => Promise<void>;
  };
  refreshAll: () => void;
}

export function useDashboardData(): DashboardData {
  const sensorsQ = usePolling(() => api.listSensors(), 0); // static-ish; fetch once
  const thresholdsQ = usePolling(
    () => api.getSystemMetadata({ config_type: "anomaly_thresholds" }),
    0
  );
  const anomaliesQ = usePolling(() => api.listAnomalies({ limit: 100 }), ANOMALIES_MS);
  const staffQ = usePolling(() => api.listStaff(), STAFF_MS);
  const simQ = usePolling(() => api.simStatus(), SIM_MS);

  const sensors = sensorsQ.data ?? [];

  // Readings: fan out one request per sensor on a shared interval.
  const [readingsBySensor, setReadingsBySensor] = useState<Record<string, Reading[]>>({});
  const aliveRef = useRef(true);

  const sensorIds = sensors.map((s) => s.sensor_id).join(",");

  const pullReadings = useCallback(async () => {
    if (!sensorIds) return;
    const ids = sensorIds.split(",");
    const entries = await Promise.all(
      ids.map(async (id) => {
        try {
          const r = await api.getReadings(id, { minutes: READINGS_WINDOW_MIN, limit: 500 });
          return [id, r] as const;
        } catch {
          return [id, [] as Reading[]] as const;
        }
      })
    );
    if (aliveRef.current) {
      setReadingsBySensor(Object.fromEntries(entries));
    }
  }, [sensorIds]);

  useEffect(() => {
    aliveRef.current = true;
    pullReadings();
    const interval = setInterval(pullReadings, READINGS_MS);
    return () => {
      aliveRef.current = false;
      clearInterval(interval);
    };
  }, [pullReadings]);

  const controls = {
    start: async () => {
      await api.simStart();
      simQ.refresh();
    },
    stop: async () => {
      await api.simStop();
      simQ.refresh();
    },
    reset: async () => {
      await api.simReset();
      anomaliesQ.refresh();
      staffQ.refresh();
      setReadingsBySensor({});
    },
  };

  return {
    sensors,
    readingsBySensor,
    thresholds: thresholdsQ.data ?? [],
    anomalies: anomaliesQ.data ?? [],
    staff: staffQ.data ?? [],
    simRunning: simQ.data?.running ?? true,
    loading: sensorsQ.loading || anomaliesQ.loading,
    error: sensorsQ.error || anomaliesQ.error,
    controls,
    refreshAll: () => {
      sensorsQ.refresh();
      anomaliesQ.refresh();
      staffQ.refresh();
      simQ.refresh();
      pullReadings();
    },
  };
}
