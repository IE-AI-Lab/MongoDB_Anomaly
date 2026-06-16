"use client";

import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import type { KnowledgeDoc } from "@/lib/types";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  /** When set, the modal edits this doc; otherwise it creates a new one. */
  editing?: KnowledgeDoc | null;
}

export function KnowledgeEditor({ open, onClose, onSaved, editing }: Props) {
  const [sectionTitle, setSectionTitle] = useState(editing?.section_title ?? "");
  const [textContent, setTextContent] = useState(editing?.text_content ?? "");
  const [equipmentType, setEquipmentType] = useState(editing?.equipment_type ?? "");
  const [errorCodes, setErrorCodes] = useState(
    (editing?.associated_error_codes ?? []).join(", ")
  );
  const [isActive, setIsActive] = useState(editing?.is_active ?? true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();

  async function save() {
    if (!sectionTitle.trim() || !textContent.trim()) {
      setError("Section title and content are required.");
      return;
    }
    setSaving(true);
    setError(undefined);
    const payload = {
      section_title: sectionTitle.trim(),
      text_content: textContent.trim(),
      equipment_type: equipmentType.trim() || undefined,
      associated_error_codes: errorCodes
        .split(",")
        .map((c) => c.trim())
        .filter(Boolean),
      is_active: isActive,
    };
    try {
      if (editing) await api.patchKnowledge(editing.document_id, payload);
      else await api.createKnowledge(payload);
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={editing ? "Edit knowledge entry" : "Add knowledge entry"}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button variant="primary" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <LabeledInput label="Section title" value={sectionTitle} onChange={setSectionTitle} />
        <div>
          <label className="text-xs font-medium uppercase tracking-wide text-mongo-mist">
            Content (indexed for retrieval)
          </label>
          <textarea
            value={textContent}
            onChange={(e) => setTextContent(e.target.value)}
            rows={6}
            className="mt-1.5 w-full rounded-lg border border-mongo-border bg-white px-3 py-2 text-sm focus:border-mongo-green-dark focus:outline-none"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <LabeledInput
            label="Equipment type"
            value={equipmentType}
            onChange={setEquipmentType}
            placeholder="centrifugal_pump"
          />
          <LabeledInput
            label="Error codes (comma-sep)"
            value={errorCodes}
            onChange={setErrorCodes}
            placeholder="VIBRATION_HIGH, BEARING_WEAR"
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-mongo-ink">
          <input
            type="checkbox"
            checked={isActive}
            onChange={(e) => setIsActive(e.target.checked)}
            className="h-4 w-4 accent-mongo-green-dark"
          />
          Active (retrievable by the agent)
        </label>
        {error && <p className="text-sm text-severity-highInk">{error}</p>}
      </div>
    </Modal>
  );
}

function LabeledInput({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div>
      <label className="text-xs font-medium uppercase tracking-wide text-mongo-mist">
        {label}
      </label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="mt-1.5 w-full rounded-lg border border-mongo-border bg-white px-3 py-2 text-sm focus:border-mongo-green-dark focus:outline-none"
      />
    </div>
  );
}
