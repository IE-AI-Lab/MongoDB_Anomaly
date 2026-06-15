import clsx from "clsx";
import type { ReactNode } from "react";

export function Card({
  children,
  className,
  title,
  action,
}: {
  children: ReactNode;
  className?: string;
  title?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section
      className={clsx(
        "rounded-xl border border-mongo-border bg-mongo-surface shadow-card",
        className
      )}
    >
      {(title || action) && (
        <header className="flex items-center justify-between border-b border-mongo-border px-4 py-3">
          {typeof title === "string" ? (
            <h2 className="text-sm font-semibold text-mongo-ink">{title}</h2>
          ) : (
            title
          )}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}
