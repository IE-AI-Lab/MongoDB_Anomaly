"use client";

import clsx from "clsx";

import type { AgentLog } from "@/lib/types";
import { formatDateTime } from "@/lib/format";

export function AgentTrace({ logs }: { logs: AgentLog[] }) {
  if (logs.length === 0) {
    return (
      <p className="px-4 py-6 text-sm text-mongo-mist">
        No agent run recorded yet for this anomaly.
      </p>
    );
  }

  return (
    <div className="space-y-5 px-4 py-4">
      {logs.map((log) => (
        <div key={log.run_id}>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span
              className={clsx(
                "rounded-full px-2 py-0.5 text-xs font-medium capitalize",
                log.status === "completed"
                  ? "bg-mongo-green-tint text-mongo-green-dark"
                  : log.status === "failed"
                    ? "bg-severity-high text-severity-highInk"
                    : "bg-severity-low text-severity-lowInk"
              )}
            >
              {log.status}
            </span>
            <span className="font-medium text-mongo-ink">
              {log.agent_name ?? "agent"}
            </span>
            {log.model_id && (
              <span className="font-mono text-xs text-mongo-mist">{log.model_id}</span>
            )}
            <span className="ml-auto text-xs text-mongo-mist">
              {formatDateTime(log.started_at)}
            </span>
          </div>

          {log.final_action_taken && (
            <p className="mt-1.5 text-sm text-mongo-slate">{log.final_action_taken}</p>
          )}

          {log.execution_steps && log.execution_steps.length > 0 && (
            <ol className="mt-3 space-y-2 border-l-2 border-mongo-border pl-4">
              {log.execution_steps.map((step) => (
                <li key={step.step_index} className="relative text-sm">
                  <span className="absolute -left-[21px] top-1 inline-block h-2.5 w-2.5 rounded-full border-2 border-white bg-mongo-green-dark" />
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-mongo-ink">
                      {step.tool_name}
                    </span>
                    {step.success === false && (
                      <span className="text-xs text-severity-highInk">failed</span>
                    )}
                    {typeof step.latency_ms === "number" && (
                      <span className="text-xs text-mongo-mist">{step.latency_ms}ms</span>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          )}

          {log.tokens_used && (
            <p className="mt-2 text-xs text-mongo-mist">
              tokens: {log.tokens_used.total} total ({log.tokens_used.prompt}p /{" "}
              {log.tokens_used.completion}c)
            </p>
          )}
          {log.error?.message && (
            <p className="mt-2 text-xs text-severity-highInk">error: {log.error.message}</p>
          )}
        </div>
      ))}
    </div>
  );
}
