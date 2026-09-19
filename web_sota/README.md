# Inkscape MCP dashboard

Optional React, TypeScript, and Vite frontend for the Inkscape MCP HTTP backend.
It provides status and logs, tool discovery, SVG workflows, help, and optional
model-provider settings. The MCP server also works independently through stdio.

## Run locally

Complete the Python and native Inkscape setup in
[Installation](../INSTALL.md). Start the backend from the repository root:

```bash
uv run inkscape-mcp --mode http --host 127.0.0.1 --port 11028
```

In a second terminal, use Bun 1.3.14, as pinned by `packageManager`:

```bash
cd web_sota
bun install --frozen-lockfile
bun run dev
```

Open `http://127.0.0.1:11029`. The
[Vite configuration](vite.config.ts) proxies `/api`, `/v1`, and `/mcp` to
`http://127.0.0.1:11028`. The backend command sets this port explicitly;
the server's general HTTP default is `11027`.

Local model services are optional. Configure a provider in the dashboard only
for features that need one. These settings do not enable MCP client sampling;
see [Sampling](../docs/AI_SAMPLING.md).

## Checks and build

Run from this directory:

```bash
bun run lint
bun run build
```

The build runs TypeScript checks and writes Vite assets to `dist/`.
`bun run preview` previews those assets locally. A separate deployment must
route backend requests appropriately; the development proxy is not a production
reverse-proxy configuration.

An optional browser smoke test checks backend health and frontend loading:

```bash
bunx playwright install chromium
bunx playwright test e2e/smoke.spec.ts
```

[Playwright configuration](playwright.config.ts) starts the backend and frontend
when their ports are available, or reuses existing servers. It requires the
Python setup and Bun on `PATH`. Frontend lint and build run in
[CI](../.github/workflows/ci.yml); browser tests are a separate check.

## Source map

| Path | Responsibility |
| --- | --- |
| `src/pages/` | Dashboard screens and workflow forms |
| `src/components/` | Layout, dialogs, and reusable UI |
| `src/api/`, `src/lib/` | Backend requests, settings, and shared helpers |
| `e2e/` | Playwright smoke and demonstration scripts |
| `../src/inkscape_mcp/app.py` | Backend REST routes |
| `../native/` | Separate Tauri desktop wrapper source |

The authoritative agent-accessible tool contract is
[TOOLS.md](../docs/TOOLS.md). Dashboard-only REST helpers, including layer and
animation routes, are not standalone MCP tools. See
[Development](../docs/DEVELOPMENT.md) for server and native desktop validation.
