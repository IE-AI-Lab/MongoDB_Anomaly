"use client";

import { useState } from "react";
import clsx from "clsx";

import { api, ApiError } from "@/lib/api";
import type { Anomaly } from "@/lib/types";
import { Button } from "@/components/ui/Button";

type Outcome = "fixed" | "false_positive" | "deferred";

const OUTCOMES: { value: Outcome; label: string; hint: string }[] = [
  { value: "fixed", label: "Fixed", hint: "Resolved — notes feed back into the knowledge base" },
  { value: "false_positive", label: "False positive", hint: "Not a real issue" },
  { value: "deferred", label: "Deferred", hint: "Acknowledged, action postponed" },
];

export function FeedbackForm({
  anomaly,
  onResolved,
}: {
  anomaly: Anomaly;
  onResolved?: () => void;
}) {
  const [outcome, setOutcome] = useState<Outcome>("fixed");
  const [notes, setNotes] = useState("");
  const [resolvedBy, setResolvedBy] = useState(anomaly.assigned_to_employee_id ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string>();
  const [result, setResult] = useState<{ knowledge_document_id?: string } | null>(null);

  const alreadyResolved = anomaly.status === "resolved";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!notes.trim()) {
      setError("Resolution notes are required.");
      return;
    }
    setSubmitting(true);
    setError(undefined);
    try {
      const res = await api.resolve(anomaly.anomaly_id, {
        outcome,
        resolution_notes: notes.trim(),
        resolved_by: resolvedBy || undefined,
      });
      setResult(res);
      onResolved?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  if (result || alreadyResolved) {
    return (
      <div className="rounded-lg border border-mongo-green-light bg-mongo-green-tint px-4 py-4 text-sm">
        <p className="font-medium text-mongo-green-dark">
          ✓ Anomaly resolved. The assigned worker is back on call.
        </p>
        {result?.knowledge_document_id && (
          <p className="mt-2 text-mongo-slate">
            Your notes were embedded into the knowledge base as{" "}
            <span className="font-mono text-mongo-ink">{result.knowledge_document_id}</span>{" "}
            (pending curator approval before the agent retrieves it).
          </p>
        )}
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <label className="text-xs font-medium uppercase tracking-wide text-mongo-mist">
          Outcome
        </label>
        <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
          {OUTCOMES.map((o) => (
            <button
              key={o.value}
              type="button"
              onClick={() => setOutcome(o.value)}
              className={clsx(
                "rounded-lg border px-3 py-2 text-left text-sm transition-colors",
                outcome === o.value
                  ? "border-mongo-green-dark bg-mongo-green-tint"
                  : "border-mongo-border hover:border-mongo-mist"
              )}
            >
              <span className="block font-medium text-mongo-ink">{o.label}</span>
              <span className="mt-0.5 block text-xs text-mongo-mist">{o.hint}</span>
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="text-xs font-medium uppercase tracking-wide text-mongo-mist">
          Resolution notes
        </label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={5}
          placeholder="What did you find and do? Be specific — these notes train the agent's retrieval when the outcome is 'fixed'."
          className="mt-2 w-full rounded-lg border border-mongo-border bg-white px-3 py-2 text-sm focus:border-mongo-green-dark focus:outline-none"
        />
      </div>

      <div>
        <label className="text-xs font-medium uppercase tracking-wide text-mongo-mist">
          Resolved by (employee id)
        </label>
        <input
          value={resolvedBy}
          onChange={(e) => setResolvedBy(e.target.value)}
          placeholder={anomaly.assigned_to_employee_id ?? "EMP-00X"}
          className="mt-2 w-full rounded-lg border border-mongo-border bg-white px-3 py-2 text-sm focus:border-mongo-green-dark focus:outline-none"
        />
        <p className="mt-1 text-xs text-mongo-mist">
          Defaults to the assigned worker ({anomaly.assigned_to_employee_id ?? "none"}).
        </p>
      </div>

      {error && <p className="text-sm text-severity-highInk">{error}</p>}

      <Button type="submit" variant="primary" disabled={submitting}>
        {submitting ? "Submitting…" : "Submit feedback & resolve"}
      </Button>
    </form>
  );
}
