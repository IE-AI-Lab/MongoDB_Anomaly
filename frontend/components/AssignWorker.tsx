"use client";

import { useEffect, useMemo, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type { Anomaly, Staff } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { ROLE_LABEL } from "@/lib/format";

export function AssignWorker({
  anomaly,
  onAssigned,
}: {
  anomaly: Anomaly;
  onAssigned: (updated: Anomaly) => void;
}) {
  const [staff, setStaff] = useState<Staff[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string>(anomaly.recommended_employee_id ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string>();

  useEffect(() => {
    let alive = true;
    api
      .listStaff({ is_on_call: true })
      .then((s) => {
        if (!alive) return;
        setStaff(s);
        // Always select a worker that is actually in the on-call list, otherwise
        // the <select> shows the first option while the state still holds an
        // invalid id (e.g. the agent recommended a now-deleted/off-call worker),
        // and assigning fails with "employee not found".
        const ids = new Set(s.map((x) => x.employee_id));
        setSelected((cur) => {
          if (cur && ids.has(cur)) return cur;
          const rec = anomaly.recommended_employee_id;
          if (rec && ids.has(rec)) return rec;
          return s[0]?.employee_id ?? "";
        });
      })
      .catch((e) => alive && setError((e as Error).message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [anomaly.recommended_employee_id]);

  const recommended = useMemo(
    () => staff.find((s) => s.employee_id === anomaly.recommended_employee_id),
    [staff, anomaly.recommended_employee_id]
  );

  const alreadyAssigned = anomaly.status === "assigned" || anomaly.status === "resolved";

  async function submit() {
    if (!selected) return;
    setSubmitting(true);
    setError(undefined);
    try {
      const updated = await api.assign(anomaly.anomaly_id, selected);
      onAssigned(updated);
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : `Assignment failed: ${(e as Error).message}`
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (alreadyAssigned) {
    return (
      <div className="rounded-lg border border-mongo-border bg-mongo-bg px-4 py-3 text-sm">
        <span className="text-mongo-slate">Assigned to </span>
        <span className="font-medium text-mongo-ink">
          {anomaly.assigned_to_employee_id ?? "—"}
        </span>
      </div>
    );
  }

  if (loading) return <Spinner />;

  return (
    <div className="space-y-3">
      {recommended && (
        <p className="text-xs text-mongo-slate">
          Agent recommends{" "}
          <span className="font-medium text-mongo-green-dark">{recommended.name}</span>{" "}
          ({recommended.specialization.join(", ")}).
        </p>
      )}
      <div className="flex flex-col gap-2">
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          className="w-full min-w-0 rounded-lg border border-mongo-border bg-white px-3 py-2 text-sm focus:border-mongo-green-dark focus:outline-none"
        >
          {staff.length === 0 && <option value="">No staff on call</option>}
          {staff.map((s) => (
            <option key={s.employee_id} value={s.employee_id}>
              {s.name} · {ROLE_LABEL[s.role] ?? s.role} · {s.specialization.join("/")}
              {s.employee_id === anomaly.recommended_employee_id ? "  (recommended)" : ""}
            </option>
          ))}
        </select>
        <Button
          variant="primary"
          onClick={submit}
          disabled={submitting || !selected}
          className="self-start"
        >
          {submitting ? "Assigning…" : "Assign worker"}
        </Button>
      </div>
      {error && <p className="text-sm text-severity-highInk">{error}</p>}
    </div>
  );
}
