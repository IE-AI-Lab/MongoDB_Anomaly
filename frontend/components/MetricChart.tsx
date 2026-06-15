"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Reading } from "@/lib/types";
import { formatTime, metricColor, metricLabel, metricUnit } from "@/lib/format";

interface Props {
  readings: Reading[];
  metrics: string[];
  thresholds: Record<string, { max?: number; min?: number }>;
  height?: number;
}

export function MetricChart({ readings, metrics, thresholds, height = 160 }: Props) {
  // Flatten readings into chart rows: { t, <metric>: value, ... }
  const rows = readings.map((r) => {
    const row: Record<string, number | string> = { t: formatTime(r.timestamp_utc) };
    for (const m of metrics) {
      const v = r.reading?.[m];
      if (typeof v === "number") row[m] = v;
    }
    return row;
  });

  if (rows.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-xs text-mongo-mist"
        style={{ height }}
      >
        No readings in window
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={rows} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#EEF2F1" vertical={false} />
        <XAxis
          dataKey="t"
          tick={{ fontSize: 10, fill: "#889397" }}
          minTickGap={32}
          axisLine={{ stroke: "#E8EDEB" }}
          tickLine={false}
        />
        <YAxis
          tick={{ fontSize: 10, fill: "#889397" }}
          width={42}
          axisLine={false}
          tickLine={false}
          domain={["auto", "auto"]}
        />
        <Tooltip
          contentStyle={{
            fontSize: 12,
            borderRadius: 8,
            border: "1px solid #E8EDEB",
            boxShadow: "0 8px 24px rgba(0,30,43,0.18)",
          }}
          formatter={(value: number, name: string) => [
            `${value} ${metricUnit(name)}`,
            metricLabel(name),
          ]}
        />
        {metrics.map((m, i) => (
          <Line
            key={m}
            type="linear"
            dataKey={m}
            name={m}
            stroke={metricColor(m, i)}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
            connectNulls
          />
        ))}
        {metrics.flatMap((m) => {
          const th = thresholds[m];
          if (!th) return [];
          const lines = [];
          if (th.max !== undefined) {
            lines.push(
              <ReferenceLine
                key={`${m}-max`}
                y={th.max}
                stroke="#DB3030"
                strokeDasharray="4 4"
                strokeWidth={1}
              />
            );
          }
          if (th.min !== undefined) {
            lines.push(
              <ReferenceLine
                key={`${m}-min`}
                y={th.min}
                stroke="#DB3030"
                strokeDasharray="4 4"
                strokeWidth={1}
              />
            );
          }
          return lines;
        })}
      </LineChart>
    </ResponsiveContainer>
  );
}
