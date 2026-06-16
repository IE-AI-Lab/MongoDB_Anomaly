"use client";

import { useEffect } from "react";
import type { ReactNode } from "react";

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-mongo-ink/40 p-4 pt-16"
      onMouseDown={onClose}
    >
      <div
        className="w-full max-w-lg rounded-xl border border-mongo-border bg-mongo-surface shadow-pop"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-mongo-border px-5 py-3.5">
          <h2 className="text-base font-semibold text-mongo-ink">{title}</h2>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-mongo-mist hover:bg-mongo-bg hover:text-mongo-ink"
            aria-label="Close"
          >
            ✕
          </button>
        </header>
        <div className="px-5 py-4">{children}</div>
        {footer && (
          <footer className="flex justify-end gap-2 border-t border-mongo-border px-5 py-3">
            {footer}
          </footer>
        )}
      </div>
    </div>
  );
}
