# Configuration

## Launch and transport

The executable entry point is `inkscape-mcp`, provided by `uv run inkscape-mcp`.
Use `--help` for the accepted CLI arguments.

| Setting | Default at the main entry point | Meaning |
| --- | --- | --- |
| `--mode` / `MCP_TRANSPORT` | `stdio` | `stdio` or `http`; CLI `dual` is an HTTP alias |
| `--host` / `MCP_HOST` | `127.0.0.1` | HTTP bind address |
| `--port` / `MCP_PORT` | `11027` | HTTP port |
| `--config` | Automatic search | YAML configuration path |
| `--log-level` | `INFO` | CLI logging level, e.g. `DEBUG` |

Explicit CLI arguments override environment variables. Omitting `--mode` respects
`MCP_TRANSPORT`; otherwise the default is stdio. HTTP MCP is served at `/mcp`.
The transport helper contains legacy SSE settings, but the public CLI documented
here uses stdio or Streamable HTTP.

```bash
MCP_TRANSPORT=http MCP_PORT=11028 uv run inkscape-mcp
```

The dashboard's Vite development server runs on `11029` and proxies API/MCP calls
to `11028`. Pass `--port 11028` when starting its backend. These two explicit
ports are independent of the standalone CLI HTTP default.

## YAML configuration

The main server searches, in order:

1. `config.yaml` in the working directory.
2. `inkscape-mcp.yaml` in the working directory.
3. `~/.inkscape-mcp/config.yaml`.
4. `~/.config/inkscape-mcp/config.yaml`.

Use `--config /absolute/path/config.yaml` to select a file explicitly. The
`--directory` argument to uv determines the working directory in client examples.
A file selected explicitly must exist and contain valid configuration.

```yaml
inkscape_executable: /usr/bin/inkscape
process_timeout: 30
max_concurrent_processes: 3
temp_directory: /tmp/inkscape-mcp
max_file_size_mb: 100
allowed_directories:
  - /home/your-user/Documents/vector-projects
log_level: INFO
```

| Key | Default | Bounds / purpose |
| --- | --- | --- |
| `inkscape_executable` | Auto-detected | Explicit executable path is retained during initialization |
| `process_timeout` | `30` seconds | `5`–`300`; command timeout |
| `max_concurrent_processes` | `3` | `1`–`10`; managed CLI process concurrency |
| `temp_directory` | OS temporary directory | Must be writable; missing directory is created |
| `max_file_size_mb` | `100` | `1`–`1000`; managed file size limit |
| `allowed_directories` | `[]` | Restrict paths in operations using the managed file validators |
| `default_quality` | `95` | `1`–`100` |
| `default_interpolation` | `lanczos` | `none`, `linear`, `cubic`, `lanczos` |
| `log_level` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

See [config.py](../src/inkscape_mcp/config.py) for additional fields. Directory
restrictions are application checks, not an OS sandbox. Optional helpers and
external services have their own file behavior; do not treat this setting as an
isolation boundary for untrusted clients.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `INKSCAPE_PATH` | Auto-detection | Inkscape executable when no explicit configured path is used |
| `INKSCAPE_GUI_WATCH` | Unset | `1`/`true`/`yes` enables hands-in mode guidance |
| `INKSCAPE_MCP_LOG_FORMAT` | Default logging | Set to `json` for structured CLI logs |
| `INKSCAPE_MCP_METRICS_ENABLED` | `true` | Enable optional metrics listener when metrics dependencies exist |
| `PROMETHEUS_PORT` | `9074` | Optional metrics listener port |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Dashboard/local model provider endpoint |
| `OLLAMA_MODEL` | `qwen2.5-coder:latest` | Dashboard SVG generation default model |
| `INKSCAPE_SAVE_DIR` | `~/Documents/inkscape-mcp/generated` | Dashboard-generated SVG destination |
| `GEMINI_API_KEY` | Unset | Optional dashboard generation cloud fallback |
| `ANTHROPIC_API_KEY` | Unset | Optional dashboard generation cloud fallback |

Ollama, cloud keys, and a GPU are not required to construct, inspect, export, or
insert SVG. MCP sampling tools use the connected client's model; they are a
separate path from the dashboard's generation providers.

The source-tree `generate_svg` sampling helper writes beneath `generated_svgs/`
in its working directory. It does not use the dashboard's `INKSCAPE_SAVE_DIR`.

## Desktop session access

Live operations must reach the running Inkscape application in the same user
session. Preserve the environment provided by that session:

- `DISPLAY` for X11 or XWayland access.
- `WAYLAND_DISPLAY` and `XDG_RUNTIME_DIR` for native Wayland access.
- `DBUS_SESSION_BUS_ADDRESS` for Inkscape's session D-Bus application.
- `XAUTHORITY` where required for X11 authentication.

Do not copy another user's session credentials or launch the MCP process as root.
`INKSCAPE_GUI_WATCH` reports a preference; it cannot create a session, start
Inkscape, or make an inaccessible window controllable. Use the `session_id` returned by `open_document` or `new_document` to address a
managed drawing. The special `desktop` session requires one window in the
ordinary Inkscape instance; it does not select among several windows by focus.
Calls from one wrapper are serialized, and extension exchange uses cross-process
locks. Other applications and manual edits can still change a document.

## Live extension and session state

`install_live_extension` explicitly installs the bundled effect. It is not
installed as a hidden server-startup side effect. Default locations:

| State | Default location |
| --- | --- |
| Installed effect | `~/.config/inkscape/extensions/inkscape_mcp_live/` |
| Managed document registry | `~/.cache/inkscape-mcp/document-sessions.json` |
| Correlated extension requests/results | `~/.cache/inkscape-mcp/live-extension/` |

`XDG_CONFIG_HOME` and `XDG_CACHE_HOME` change their respective roots.
`INKSCAPE_PROFILE_DIR`, when set, directs extension installation to that
profile's `extensions/inkscape_mcp_live/` directory. The target Inkscape process
must use the same profile. Restart existing windows after an installation/update
when `needs_restart` is true.

The session registry records managed application IDs and their known SVG paths.
Saving uses the current filename reported by Inkscape; a GUI **Save As** takes
precedence over a stale registry path.
The session bus determines whether an instance is still open; a stale registry
entry is not proof of a live document. Do not edit/delete exchange files while a
live operation is pending.

## Operational checks

Call `inkscape_system` with `status`, `config`, or `diagnostics` to inspect the
loaded configuration. For desktop access, call `active_document`. After any
configuration change, restart the server and reconnect the MCP client.
