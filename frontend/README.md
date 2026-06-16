# Anomaly Platform — operator frontend

MongoDB Atlas–styled Next.js console for the anomaly-detection data layer. It is
an **external HTTP-API consumer** — it imports nothing from the Python services
and talks only to the data layer over HTTP.

## Stack

- **Next 14.2** (App Router) + TypeScript
- **Tailwind 3.4** with a `tailwind.config.ts` MongoDB "LeafyGreen" (light) palette
  — do not upgrade to Tailwind 4 (it moved config to CSS)
- **Recharts** for live time-series charts
- No auth (out of scope), no WebSocket yet — polling stands in for the future `/ws`

## How it talks to the backend

All browser → API calls go to `/backend/*`, which Next rewrites to the data layer
(`next.config.mjs`). This keeps requests same-origin (no CORS) and the backend URL
server-side. Set the target with `DATA_LAYER_BASE_URL` (default
`http://127.0.0.1:8000` — use `127.0.0.1`, not `localhost`, on Windows).

```bash
cp .env.local.example .env.local   # optional; defaults work for local dev
npm install
npm run dev                         # http://localhost:3000
```

The data layer must be running (`uvicorn ingestor_service.app:app --port 8000`,
or `honcho start` for the whole stack). Seed first with `python -m scripts.init_db`.

## Pages

| Route | Purpose |
|---|---|
| `/` | Dashboard: scrollable live machine charts, worker availability, current alerts, Start/Stop/Reset, new-alert toasts |
| `/anomalies/[id]` | Agent report (analysis + RAG cases + execution trace) and worker assignment |
| `/anomalies/[id]/feedback` | Worker resolution feedback (closes the RAG loop) |
| `/feedback` | Index of assigned anomalies awaiting feedback |
| `/knowledge` | Knowledge CRUD + feedback review queue (approve/reject) |

## Structure

```
app/         routes (App Router)
components/  TopBar, SimControls, MachineCard, MetricChart, WorkerPanel,
             AlertsPanel, AlertToast, AssignWorker, AgentTrace, FeedbackForm,
             KnowledgeEditor, ui/ primitives
hooks/       usePolling (generic), useDashboardData (WS-shaped polling stand-in)
lib/         api.ts (typed client), types.ts (Mongo contract mirrors), format.ts
```
