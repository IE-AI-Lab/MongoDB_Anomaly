import clsx from "clsx";

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={clsx(
        "inline-block h-4 w-4 animate-spin rounded-full border-2 border-mongo-border border-t-mongo-green-dark",
        className
      )}
      role="status"
      aria-label="Loading"
    />
  );
}

export function LoadingRow({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 px-4 py-6 text-sm text-mongo-mist">
      <Spinner />
      {label}
    </div>
  );
}

export function EmptyRow({ label }: { label: string }) {
  return <div className="px-4 py-6 text-center text-sm text-mongo-mist">{label}</div>;
}
