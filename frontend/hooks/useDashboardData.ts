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
// "Static-ish" config is still polled slowly (not fetched once) so a transient
// API failure at mount self-heals instead of leaving the dashboard permanently
// empty until a full page reload.
const SENSORS_MS = 30000;
const THRESHOLDS_MS = 60000;
const READINGS_WINDOW_MIN = 30;

export interface DashboardData {
  sensors: Sensor[];
  readingsBySensor: Record<string, Reading[]>;
  thresholds: SystemMetadata[];
  anomalies: Anomaly[];
  staff: Staff[];
  loading: boolean;
  error?: Error;
}

// Sim run/pause state is owned by <SimControls/>, which polls /simulation/status
// itself — so it is intentionally NOT fetched here (avoids a duplicate poll and a
// second source of truth).
export function useDashboardData(): DashboardData {
  const sensorsQ = usePolling(() => api.listSensors(), SENSORS_MS);
  const thresholdsQ = usePolling(
    () => api.getSystemMetadata({ config_type: "anomaly_thresholds" }),
    THRESHOLDS_MS
  );
  const anomaliesQ = usePolling(() => api.listAnomalies({ limit: 100 }), ANOMALIES_MS);
  const staffQ = usePolling(() => api.listStaff(), STAFF_MS);

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

  return {
    sensors,
    readingsBySensor,
    thresholds: thresholdsQ.data ?? [],
    anomalies: anomaliesQ.data ?? [],
    staff: staffQ.data ?? [],
    loading: sensorsQ.loading || anomaliesQ.loading,
    error: sensorsQ.error || anomaliesQ.error,
  };
}
