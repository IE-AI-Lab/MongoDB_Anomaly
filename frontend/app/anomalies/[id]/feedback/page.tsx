"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { Anomaly } from "@/lib/types";
import { Card } from "@/components/ui/Card";
import { LoadingRow } from "@/components/ui/Spinner";
import { FeedbackForm } from "@/components/FeedbackForm";
import { formatDateTime } from "@/lib/format";

export default function FeedbackPage({ params }: { params: { id: string } }) {
  const { id } = params;
  const [anomaly, setAnomaly] = useState<Anomaly>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();

  useEffect(() => {
    let alive = true;
    api
      .getAnomaly(id)
      .then((a) => alive && setAnomaly(a))
      .catch((e) => alive && setError((e as Error).message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [id]);

  if (loading) return <LoadingRow label="Loading…" />;
  if (error || !anomaly)
    return (
      <div className="rounded-lg border border-severity-high bg-severity-high/30 px-4 py-3 text-sm text-severity-highInk">
        {error ?? "Anomaly not found."}
      </div>
    );

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div className="flex items-center gap-2 text-sm text-mongo-mist">
        <Link href="/" className="hover:text-mongo-ink">
          Dashboard
        </Link>
        <span>/</span>
        <Link href={`/anomalies/${id}`} className="hover:text-mongo-ink">
          {id}
        </Link>
        <span>/</span>
        <span className="text-mongo-ink">Feedback</span>
      </div>

      <Card title="Worker feedback">
        <div className="space-y-4 px-5 py-5">
          <div className="rounded-lg border border-mongo-border bg-mongo-bg px-4 py-3 text-sm">
            <p className="font-medium text-mongo-ink">
              {anomaly.equipment_id ?? anomaly.sensor_id} ·{" "}
              <span className="font-mono text-xs">{anomaly.error_code}</span>
            </p>
            <p className="mt-0.5 text-xs text-mongo-mist">
              {anomaly.severity_type} severity · detected {formatDateTime(anomaly.timestamp_utc)} ·
              assigned to {anomaly.assigned_to_employee_id ?? "—"}
            </p>
          </div>

          <FeedbackForm anomaly={anomaly} />
        </div>
      </Card>
    </div>
  );
}
