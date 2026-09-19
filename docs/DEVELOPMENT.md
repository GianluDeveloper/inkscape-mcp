# Development

## Environment

Follow the native dependency steps in [Installation](../INSTALL.md), then:

```bash
uv sync --python 3.12 --group dev
uv run inkscape-mcp --help
```

The checked setup uses Ubuntu 26.04.1 LTS, Python 3.12.14, and Inkscape 1.4.4.
Use the development dependency group, `--group dev`, for the current toolchain.
The older optional `[dev]` extra is also present in package metadata.

## Run the server

```bash
uv run inkscape-mcp --mode stdio
uv run inkscape-mcp --mode http --host 127.0.0.1 --port 11028
```

Choose one command for the transport under test. Logs belong on stderr so stdio
remains an MCP channel. The legacy `run_server.py`, `mcpb/run_server.py`, and
`inkscape_mcp.server` entry points delegate to the same main implementation.

For the optional frontend, start the HTTP backend on `11028`, then in a second
terminal:

```bash
cd web_sota
bun install --frozen-lockfile
bun run dev
```

The Vite UI is on `11029`. `bun run build` performs the TypeScript and frontend
build. The repository's `justfile` uses PowerShell; use the direct commands in
this guide on Linux instead of assuming every recipe is portable.

## Tests

Full configured suite, including the repository coverage gate:

```bash
uv run pytest
```

Focused regressions without an unrelated whole-project coverage requirement:

```bash
uv run pytest tests/unit/test_live_system.py --no-cov -q
uv run pytest tests/unit/test_construct_svg_mcp.py tests/unit/test_cli_hardening.py --no-cov -q
uv run pytest tests/unit/test_entrypoint_transport.py tests/unit/test_server_compat.py --no-cov -q
```

Real Inkscape runtime checks:

```bash
uv run pytest tests/integration/test_inkscape_runtime.py --no-cov -q
```

Runtime tests skip when Inkscape cannot be found. They exercise file operations;
mocked live unit tests do not change a running document. For the explicit manual
live drawing procedure, see [Usage](USAGE.md#verify-live-drawing). Some native
raster loaders require a usable desktop/D-Bus environment even for a CLI test.

The desktop acceptance script connects through stdio MCP, creates two managed
Inkscape instances, inserts different editable labels, checks isolation and
unsaved state, saves copies and originals, renders both PNGs, and closes the
saved documents. Run it in your desktop session:

```bash
uv run python scripts/desktop_smoke.py --output-dir /tmp/inkscape-desktop-smoke
```

Use `--keep-open` to inspect its drawings. The script installs the bundled
extension explicitly and writes SVG, PNG, and `report.json` artifacts in a new
subdirectory. A failed run retains its report and documents for diagnosis.
For a disposable display and session bus, install `xvfb`, `xauth`, and
`dbus-x11`, then use the same command as CI:

```bash
xvfb-run -a -s "-screen 0 1280x800x24" dbus-run-session -- \
  uv run python scripts/desktop_smoke.py --output-dir /tmp/inkscape-desktop-smoke
```

The [CI workflow](../.github/workflows/ci.yml) runs Python 3.12 and 3.13 in
Ubuntu 26.04 with real Inkscape. Its GUI step also isolates XDG profile/cache
directories and sets Glycin's upstream `GLYCIN_DISABLE_SANDBOX=i-know-the-risks`
test option because nested image-loader sandboxing is unavailable in that
container. This override is scoped to the disposable CI GUI process.

Check only touched files while iterating, then assess broader results:

```bash
uv run ruff check src/inkscape_mcp/utils/live_document.py tests/unit/test_live_system.py
uv run ruff format --check src/inkscape_mcp/utils/live_document.py tests/unit/test_live_system.py
uv build
```

State the command and outcome when reporting validation. Do not describe skipped
tests as passed or infer cross-platform support from Linux unit tests.

## Source map

| Path | Responsibility |
| --- | --- |
| `src/inkscape_mcp/main.py` | Main server lifecycle and public MCP wrappers |
| `src/inkscape_mcp/mcp_tool_types.py` | Enumerated public operation names |
| `src/inkscape_mcp/tools/` | Operation handlers and result models |
| `src/inkscape_mcp/cli_wrapper.py` | CLI execution, validation, export staging, process cleanup |
| `src/inkscape_mcp/shell_wrapper.py` | Persistent Inkscape shell sessions |
| `src/inkscape_mcp/utils/live_document.py` | Targeted live SVG snapshots and readback verification |
| `src/inkscape_mcp/utils/live_extension.py` | Explicit extension installation and correlated edit requests |
| `src/inkscape_mcp/utils/document_sessions.py` | Managed application instances and persistent session registry |
| `src/inkscape_mcp/utils/document_lifecycle.py` | Native saves, snapshot copies, guarded close |
| `src/inkscape_mcp/plugins/mcp_edit_xml.py` | Bundled native inkex edit effect |
| `src/inkscape_mcp/config.py` | YAML configuration and executable discovery |
| `src/inkscape_mcp/transport.py` | stdio and HTTP transport startup |
| `src/inkscape_mcp/app.py` | Optional REST bridge and dashboard routes |
| `src/inkscape_mcp/agentic.py` | Client sampling helpers |
| `src/inkscape_mcp/prompts_resources.py` | MCP prompts and resources |
| `tests/unit/`, `tests/integration/` | Isolated regressions and real-runtime tests |
| `web_sota/` | React/Vite dashboard |
| `mcpb/`, `native/` | Bundle and desktop packaging source |

## Add an MCP operation

1. Add or update its typed handler and structured success/error responses.
2. Update the operation alias in `mcp_tool_types.py`.
3. Expose every intended argument in the corresponding wrapper in `main.py`.
4. Forward those arguments explicitly; avoid hidden dependencies on `**kwargs`.
5. Update tool discovery metadata where relevant.
6. Test `Client(server.mcp).list_tools()` and an actual `call_tool` round trip.
7. Update [TOOLS.md](TOOLS.md) and a usage example.

FastMCP injects `Context`; clients must not be asked to supply it in JSON. Keep
headless file edits separate from live desktop dispatch. Do not use Inkscape's
internal `active-window-start` or `active-window-end` actions.

## Packaging

`uv build` produces Python distributions in `dist/`. MCPB and native desktop
build scripts are retained for their respective platforms; they are not required
for source use. Build outputs, logs, local configuration, generated test artifacts,
and private document captures should stay out of commits unless deliberately
added as small public examples.
