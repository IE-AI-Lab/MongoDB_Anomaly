"use client";

// Plant Assistant — a fixed bottom-left chat widget available on every page
// (mounted in app/layout.tsx). It posts to the data layer's POST /chat, which
// answers against a live snapshot of the whole plant (machines, readings,
// thresholds, anomalies, workforce, knowledge base, feedback) via DeepSeek.
//
// Palette note: the design spec uses `mdb-*` class names; this app's Tailwind
// palette is `mongo-*` (tailwind.config.ts), so those are the equivalents used
// here (mdb-navy → mongo-ink, mdb-off-white → mongo-bg, etc.).

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

import { api } from "@/lib/api";

type Msg = { role: "user" | "assistant"; content: string };

// Empty-state prompts, adapted to this platform (one ball mill + its sensors).
const SUGGESTIONS = [
  "What are the current sensor readings across the plant?",
  "Which machines are above their thresholds right now?",
  "Who is on call to handle a high-severity incident?",
  "Summarise the active anomalies.",
];

// Chat-bubble glyph, reused for the closed-toggle icon and the header avatar.
const BubbleIcon = ({ className }: { className: string }) => (
  <svg className={className} fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M12 2C6.477 2 2 6.477 2 12c0 1.89.527 3.66 1.438 5.168L2 22l4.832-1.438A9.954 9.954 0 0012 22c5.523 0 10-4.477 10-10S17.523 2 12 2zm-1 13H7v-2h4v2zm6 0h-4v-2h4v2zm0-4H7V9h10v2z" />
  </svg>
);

export function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const bottomRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const toggleRef = useRef<HTMLButtonElement | null>(null);
  const wasOpen = useRef(false);

  // Auto-scroll to the newest message whenever the thread changes or opens.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, open, loading]);

  // Focus the input when the window opens; hand focus back to the toggle on
  // close (but not on first mount, so we don't steal focus on page load).
  useEffect(() => {
    if (open) inputRef.current?.focus();
    else if (wasOpen.current) toggleRef.current?.focus();
    wasOpen.current = open;
  }, [open]);

  async function send(text?: string) {
    const content = (text ?? input).trim();
    if (!content || loading) return;

    setInput("");
    const next: Msg[] = [...messages, { role: "user", content }];
    setMessages(next);
    setLoading(true);
    try {
      const { reply } = await api.chat({
        message: content,
        // Last 10 turns minus the just-added user message (sent as `message`).
        history: next.slice(-10).slice(0, -1),
      });
      setMessages((prev) => [...prev, { role: "assistant", content: reply }]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Sorry, I couldn't reach the server." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      {/* Window — only mounted when open. */}
      {open && (
        <div
          role="dialog"
          aria-label="Plant Assistant"
          className="fixed bottom-24 left-6 z-40 flex w-80 flex-col overflow-hidden rounded-xl border border-mongo-border bg-white shadow-xl sm:w-96"
          style={{ height: "500px" }}
        >
          {/* Header */}
          <div className="flex shrink-0 items-center gap-3 bg-mongo-ink px-4 py-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-mongo-green-base">
              <BubbleIcon className="h-4 w-4 text-mongo-ink" />
            </div>
            <div>
              <p className="text-sm font-semibold text-white">Plant Assistant</p>
              <p className="text-xs text-white/50">Live sensor &amp; worker data</p>
            </div>
          </div>

          {/* Messages */}
          <div
            role="log"
            aria-live="polite"
            className="flex-1 space-y-3 overflow-y-auto px-4 py-3"
          >
            {messages.length === 0 && !loading ? (
              <>
                <p className="pb-1 pt-2 text-center text-xs text-mongo-slate">
                  Ask me anything about the plant.
                </p>
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    className="w-full rounded-lg border border-mongo-border px-3 py-2 text-left text-xs text-mongo-ink transition-colors hover:bg-mongo-bg"
                  >
                    {s}
                  </button>
                ))}
              </>
            ) : (
              messages.map((m, i) => (
                <div
                  key={i}
                  className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
                >
                  {m.role === "user" ? (
                    <div className="max-w-[88%] rounded-xl rounded-br-sm bg-mongo-ink px-3 py-2 text-sm leading-relaxed text-white">
                      {m.content}
                    </div>
                  ) : (
                    <div className="max-w-[88%] rounded-xl rounded-bl-sm border border-mongo-border bg-mongo-bg px-3 py-2 text-sm leading-relaxed text-mongo-ink">
                      <div className="prose prose-sm max-w-none prose-headings:text-sm prose-headings:text-mongo-ink prose-p:my-1 prose-strong:text-mongo-green-dark prose-ul:my-1 prose-li:my-0">
                        <ReactMarkdown>{m.content}</ReactMarkdown>
                      </div>
                    </div>
                  )}
                </div>
              ))
            )}

            {loading && (
              <div className="flex justify-start">
                <div className="rounded-xl rounded-bl-sm border border-mongo-border bg-mongo-bg px-4 py-3">
                  <span className="flex items-center gap-1">
                    <span
                      className="h-1.5 w-1.5 animate-bounce rounded-full bg-mongo-mist"
                      style={{ animationDelay: "0ms" }}
                    />
                    <span
                      className="h-1.5 w-1.5 animate-bounce rounded-full bg-mongo-mist"
                      style={{ animationDelay: "150ms" }}
                    />
                    <span
                      className="h-1.5 w-1.5 animate-bounce rounded-full bg-mongo-mist"
                      style={{ animationDelay: "300ms" }}
                    />
                  </span>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
            className="flex shrink-0 gap-2 border-t border-mongo-border px-3 py-3"
          >
            <input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about machines, workers, alerts…"
              aria-label="Message"
              className="flex-1 rounded-lg border border-mongo-border bg-mongo-bg px-3 py-2 text-sm text-mongo-ink placeholder-mongo-mist focus:outline-none focus:ring-2 focus:ring-mongo-green-dark"
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              aria-label="Send message"
              className="rounded-lg bg-mongo-green-dark px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-mongo-ink disabled:opacity-40"
            >
              ↑
            </button>
          </form>
        </div>
      )}

      {/* Toggle button */}
      <button
        ref={toggleRef}
        onClick={() => setOpen((o) => !o)}
        title="Plant Assistant"
        aria-label={open ? "Close chat" : "Open chat"}
        aria-expanded={open}
        className="fixed bottom-6 left-6 z-40 flex h-14 w-14 items-center justify-center rounded-full border border-white/10 bg-mongo-ink shadow-lg transition-colors hover:bg-[#112733]"
      >
        {open ? (
          <span className="text-2xl leading-none text-white">×</span>
        ) : (
          <BubbleIcon className="h-6 w-6 text-mongo-green-base" />
        )}
      </button>
    </>
  );
}
