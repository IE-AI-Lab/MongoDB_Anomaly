"use client";

import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { ChatMessage } from "@/lib/types";

const DEFAULT_MESSAGES: ChatMessage[] = [
  {
    role: "system",
    content:
      "You are the MongoDB anomaly detection operator assistant. Answer clearly and use the knowledge snippets when available.",
  },
];

function ChatBubble({ role, content }: { role: string; content: string }) {
  const isUser = role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[70%] rounded-2xl px-4 py-3 text-sm shadow-sm ${
          isUser
            ? "bg-mongo-green text-black"
            : "bg-white/90 text-mongo-ink ring-1 ring-mongo-ink/10"
        }`}
      >
        <div className="whitespace-pre-wrap break-words">{content}</div>
      </div>
    </div>
  );
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content:
        "Ask the anomaly assistant anything about machine alerts, diagnostics, or the knowledge corpus.",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sources, setSources] = useState<{ document_id: string; section_title: string }[]>([]);

  const assistantMessages = useMemo(
    () => messages.filter((message) => message.role !== "system"),
    [messages]
  );

  async function sendMessage() {
    const trimmed = input.trim();
    if (!trimmed) return;

    const newMessage: ChatMessage = { role: "user", content: trimmed };
    setMessages((prev) => [...prev, newMessage]);
    setInput("");
    setLoading(true);
    setError(null);

    try {
      const response = await api.chat({
        messages: [...DEFAULT_MESSAGES, ...messages.filter((m) => m.role !== "system"), newMessage],
      });

      setMessages((prev) => [...prev, { role: "assistant", content: response.answer }] );
      setSources(
        response.sources.map((doc) => ({
          document_id: doc.document_id,
          section_title: doc.section_title,
        }))
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send message.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="space-y-6">
      <div className="rounded-3xl border border-mongo-ink/10 bg-white/90 p-6 shadow-lg">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.24em] text-mongo-green">Chatbot</p>
            <h1 className="text-3xl font-semibold text-mongo-ink">Gemini 2.5 Flash assistant</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-mongo-ink/75">
              Ask the anomaly assistant for diagnostics, guidance, or knowledge-base context. It uses the configured Gemini model and the platform&apos;s knowledge corpus to keep answers grounded.
            </p>
          </div>
          <div className="rounded-3xl bg-mongo-ink/5 p-4 text-sm text-mongo-ink">
            <p className="font-medium">Model</p>
            <p className="mt-1">Gemini 2.5 Flash</p>
          </div>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_360px]">
        <div className="space-y-4 rounded-3xl border border-mongo-ink/10 bg-white/90 p-6 shadow-lg">
          <div className="space-y-4">
            {assistantMessages.map((message, index) => (
              <ChatBubble key={`${message.role}-${index}`} role={message.role} content={message.content} />
            ))}
          </div>

          <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center">
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Type your question about the anomaly platform..."
              className="min-h-[120px] w-full rounded-3xl border border-mongo-ink/10 bg-mongo-header/5 px-4 py-3 text-sm text-mongo-ink outline-none transition focus:border-mongo-green/60 focus:ring-2 focus:ring-mongo-green/10"
              disabled={loading}
            />
            <button
              type="button"
              onClick={sendMessage}
              disabled={loading}
              className="inline-flex h-12 shrink-0 items-center justify-center rounded-3xl bg-mongo-green px-6 text-sm font-semibold text-black transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? "Thinking..." : "Send"}
            </button>
          </div>

          {error ? (
            <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          ) : null}
        </div>

        <aside className="space-y-4 rounded-3xl border border-mongo-ink/10 bg-white/90 p-6 shadow-lg">
          <h2 className="text-lg font-semibold text-mongo-ink">Knowledge sources</h2>
          <p className="text-sm leading-6 text-mongo-ink/75">
            The chatbot grounds answers in the most relevant knowledge-base documents retrieved for your latest query.
          </p>
          <div className="space-y-3">
            {sources.length > 0 ? (
              sources.map((source) => (
                <div key={source.document_id} className="rounded-3xl border border-mongo-ink/5 bg-mongo-header/5 p-4">
                  <p className="text-sm font-semibold text-mongo-ink">{source.section_title}</p>
                  <p className="mt-1 text-xs uppercase tracking-[0.24em] text-mongo-ink/40">{source.document_id}</p>
                </div>
              ))
            ) : (
              <div className="rounded-3xl border border-dashed border-mongo-ink/20 bg-mongo-header/5 p-4 text-sm text-mongo-ink/70">
                No sources retrieved yet. Ask a question to surface knowledge snippets.
              </div>
            )}
          </div>
        </aside>
      </div>
    </section>
  );
}
