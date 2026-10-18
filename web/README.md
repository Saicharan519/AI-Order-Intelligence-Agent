# Order Intelligence: web app

The Next.js frontend for the Order Intelligence Agent. It talks only to its own `/api`
routes, which forward eight allow-listed endpoints to the FastAPI backend (see
`src/lib/server/`). The project's main README covers setup and the backend.

| Command | What it does |
|---|---|
| `npm run dev` | Dev server on http://localhost:3000; asks for the access code |
| `npm run dev:local` | Same, but the server reads `ACCESS_CODE` from the project `.env` (only when `API_URL` is localhost); the browser never sees the code |
| `npm run dev:mock` | Dev server plus a mock API that replays recorded answers: no backend, no model calls (access code `mock`) |
| `npm run lint` / `npm run typecheck` / `npm test` / `npm run build` | The checks CI runs |

`API_URL` is read from the environment, then from the project `.env`, defaulting to
`http://127.0.0.1:8000`.

Layout: `src/app/` (page and `/api` route handlers), `src/components/` (workspace, sidebar,
answer card, report, charts, tables, trace drawer), `src/lib/` (types, formatting, API
client, server-only proxy), `src/test/` (Vitest tests and recorded responses in
`fixtures/`; `refused.json` and `clarify.json` are hand-written, the rest were exported from
the trace database).
