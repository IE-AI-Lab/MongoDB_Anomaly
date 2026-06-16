"use client";

import { useCallback, useEffect, useState } from "react";
import clsx from "clsx";

import { api } from "@/lib/api";
import type { KnowledgeDoc, KnowledgeSource } from "@/lib/types";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { EmptyRow, LoadingRow } from "@/components/ui/Spinner";
import { KnowledgeEditor } from "@/components/KnowledgeEditor";
import { formatDateTime } from "@/lib/format";

type Tab = "all" | "seed" | "manual" | "review";

const TABS: { key: Tab; label: string }[] = [
  { key: "all", label: "All active" },
  { key: "seed", label: "Seed" },
  { key: "manual", label: "Manual" },
  { key: "review", label: "Review queue" },
];

function queryForTab(tab: Tab): {
  is_active?: boolean;
  source?: KnowledgeSource;
} {
  switch (tab) {
    case "seed":
      return { source: "seed", is_active: true };
    case "manual":
      return { source: "manual", is_active: true };
    case "review":
      return { source: "feedback", is_active: false };
    default:
      return { is_active: true };
  }
}

function sourceOf(id: string): string {
  if (id.startsWith("seed-")) return "seed";
  if (id.startsWith("fb-")) return "feedback";
  if (id.startsWith("kb-")) return "manual";
  return "—";
}

export default function KnowledgePage() {
  const [tab, setTab] = useState<Tab>("all");
  const [docs, setDocs] = useState<KnowledgeDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<KnowledgeDoc | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.listKnowledge({ ...queryForTab(tab), limit: 200 });
      setDocs(res);
    } finally {
      setLoading(false);
    }
  }, [tab]);

  useEffect(() => {
    load();
  }, [load]);

  const isReview = tab === "review";

  async function approve(doc: KnowledgeDoc) {
    setBusy(doc.document_id);
    try {
      await api.patchKnowledge(doc.document_id, { is_active: true });
      await load();
    } finally {
      setBusy(null);
    }
  }

  async function remove(doc: KnowledgeDoc) {
    if (!window.confirm(`Delete "${doc.section_title}"? This cannot be undone.`)) return;
    setBusy(doc.document_id);
    try {
      await api.deleteKnowledge(doc.document_id);
      await load();
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-mongo-ink">Knowledge base</h1>
          <p className="text-sm text-mongo-mist">
            The corpus the agent retrieves from. Feedback lands here pending review.
          </p>
        </div>
        <Button
          variant="primary"
          onClick={() => {
            setEditing(null);
            setEditorOpen(true);
          }}
        >
          + Add entry
        </Button>
      </div>

      <div className="flex gap-1 border-b border-mongo-border">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={clsx(
              "relative px-3 py-2 text-sm transition-colors",
              tab === t.key
                ? "font-semibold text-mongo-green-dark"
                : "text-mongo-slate hover:text-mongo-ink"
            )}
          >
            {t.label}
            {tab === t.key && (
              <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-mongo-green-dark" />
            )}
          </button>
        ))}
      </div>

      <Card>
        {loading ? (
          <LoadingRow />
        ) : docs.length === 0 ? (
          <EmptyRow label={isReview ? "Review queue is empty." : "No entries."} />
        ) : (
          <ul className="divide-y divide-mongo-border">
            {docs.map((doc) => (
              <li key={doc.document_id} className="px-4 py-3.5">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-medium text-mongo-ink">{doc.section_title}</p>
                      <span className="rounded bg-mongo-bg px-1.5 py-0.5 text-[11px] text-mongo-slate">
                        {sourceOf(doc.document_id)}
                      </span>
                      {doc.equipment_type && (
                        <span className="rounded bg-mongo-green-tint px-1.5 py-0.5 text-[11px] text-mongo-green-dark">
                          {doc.equipment_type}
                        </span>
                      )}
                      {!doc.is_active && (
                        <span className="rounded bg-severity-low px-1.5 py-0.5 text-[11px] text-severity-lowInk">
                          pending
                        </span>
                      )}
                    </div>
                    <p className="mt-1 line-clamp-2 text-sm text-mongo-slate">
                      {doc.text_content}
                    </p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-mongo-mist">
                      <span className="font-mono">{doc.document_id}</span>
                      {doc.associated_error_codes?.length > 0 && (
                        <span>· {doc.associated_error_codes.join(", ")}</span>
                      )}
                      {doc.ingested_at_utc && <span>· {formatDateTime(doc.ingested_at_utc)}</span>}
                    </div>
                  </div>

                  <div className="flex shrink-0 gap-2">
                    {isReview ? (
                      <>
                        <Button
                          variant="primary"
                          size="sm"
                          disabled={busy === doc.document_id}
                          onClick={() => approve(doc)}
                        >
                          Approve
                        </Button>
                        <Button
                          variant="danger"
                          size="sm"
                          disabled={busy === doc.document_id}
                          onClick={() => remove(doc)}
                        >
                          Reject
                        </Button>
                      </>
                    ) : (
                      <>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => {
                            setEditing(doc);
                            setEditorOpen(true);
                          }}
                        >
                          Edit
                        </Button>
                        <Button
                          variant="danger"
                          size="sm"
                          disabled={busy === doc.document_id}
                          onClick={() => remove(doc)}
                        >
                          Delete
                        </Button>
                      </>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {editorOpen && (
        <KnowledgeEditor
          open={editorOpen}
          editing={editing}
          onClose={() => setEditorOpen(false)}
          onSaved={load}
        />
      )}
    </div>
  );
}
