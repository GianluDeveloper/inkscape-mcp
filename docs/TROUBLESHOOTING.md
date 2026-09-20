# Troubleshooting

Start with `inkscape --version`, `uv run python --version`, and the MCP call
`inkscape_system` / `{"operation":"status"}`. A running server and an available
CLI do not by themselves prove the desktop session is reachable.

## Python dependencies fail to build

The project requires Python **3.12+**. On Ubuntu 26.04, errors about `cairo`,
`girepository-2.0`, or PyGObject usually indicate missing native development
packages. Install the dependencies in [Installation](../INSTALL.md#ubuntu-2604),
then rerun:

```bash
uv sync --python 3.12
```

Confirm native dependency discovery with:

```bash
pkg-config --modversion cairo girepository-2.0
```

Use the correct packages for your distribution; older GObject Introspection
libraries may not satisfy the selected Python dependency versions.

## Inkscape is unavailable

Verify the executable directly. Set an absolute `INKSCAPE_PATH` or
`inkscape_executable` in the selected YAML file. The configured executable is
retained during initialization. On Windows, use the classic desktop installer;
the Microsoft Store executable can fail with **Access Denied** for CLI calls.

A desktop-launched MCP client can have a different `PATH` from a terminal. Use
absolute paths to both uv and Inkscape in its server configuration.

## The client hangs, starts HTTP unexpectedly, or shows old parameters

Configure `--mode stdio` explicitly for a stdio client. A server manually started
in a terminal waits for protocol messages; it does not show an interactive
prompt. HTTP mode is selected with `--mode http` or `MCP_TRANSPORT=http`.

Reconnect the MCP client after updating source code. Tool schemas are obtained
when the connection starts; an existing process can continue serving old
operations. Confirm `active_document`, `insert_svg`, and `draw_test` appear in
`inkscape_system`'s operation enum.

## Live drawing cannot reach the window

The bridge requires Linux, Inkscape 1.3+, `gdbus`, and access to the same user
desktop session. Preserve `DISPLAY` or `WAYLAND_DISPLAY`,
`DBUS_SESSION_BUS_ADDRESS`, `XDG_RUNTIME_DIR`, and applicable `XAUTHORITY`. A
service, container, or SSH shell often has different access. Start the client
from the graphical session to compare behavior.

Install the native effect with `inkscape_system` /
`{"operation":"install_live_extension"}`. Check `install_dir` and
`needs_restart`, then restart Inkscape windows opened before installation. The
effect must be installed into the profile used by the target application.
New managed instances load it when they start. No clipboard helper is required.

`INKSCAPE_GUI_WATCH=1` is a mode hint, not an access grant. Avoid launching with
`sudo`, which changes the user/session context. Close modal dialogs and use the
exact `session_id` returned by `list_documents`, `open_document`, or `new_document`.

If the ordinary `desktop` instance has multiple windows, it is intentionally
ambiguous. Use managed sessions to address separate drawings. Each managed
application instance should have one document window; open additional documents
through `open_document`/`new_document` to give them their own target IDs.

If `draw_test` reports an unverified insertion, inspect the target before
repeating it. A dispatched effect may already have changed the document.
`active_document` reads live SVG to help inspect the result. A verified insertion
can be undone through **Edit → Undo**. If only the final view adjustment failed,
`view_warning` is populated but the inserted objects can already be present.

## Saving or closing documents

`save_document` supports managed sessions and the ordinary single-window
`desktop`. It reads the current SVG filename directly from Inkscape and verifies
the saved content there, including after a GUI **Save As**. An unnamed document
must first be named through **File → Save As**, or created using `new_document`.
An `output_path` different from the current filename is rejected before saving.
Resolve any open modal dialog before retrying.

`save_copy` writes a verified live copy to `output_path` without changing the
open document's filename or clearing its unsaved-changes state. Its
`data.live_document_saved` is `false`; a successful `save_document` returns
`true`. Check that field and `data.output_path` when confirming a save. File-based
`inkscape_file.save` exports the existing file on disk and excludes unsaved edits.

`close_document` requires a managed session and invokes the native close action.
An unsaved-changes dialog keeps the window open. The tool reports this rather
than choosing Discard. Save or resolve the dialog, then retry the close.

Unknown or closed session IDs never fall back to another window. Refresh
`list_documents` and use its actual IDs. The registry is in
`~/.cache/inkscape-mcp/document-sessions.json` by default; the live session bus,
not the registry alone, determines whether a session is open.

## Native crash in the active-window bridge

The internal Inkscape actions `active-window-start` and `active-window-end` must
not be called explicitly. The server rejects them in CLI and shell action chains
because Inkscape owns their lifecycle. Use `hands_in_command` with normal editing
actions or the verified live insertion operations.

Desktop calls from one wrapper are serialized. Separate MCP processes or other
clients can still compete for the same GUI. Run a single desktop controller and
use file-based batch operations for independent parallel jobs. Preserve a minimal
SVG and action sequence when reporting a remaining native crash.

Document inspection uses native Inkscape metadata rather than reading window
titles through the AT-SPI accessibility interface. If investigating an
accessibility-related crash, avoid adding AT-SPI title/tree probes to the
reproduction; use the MCP response, Inkscape stderr, and a minimal document.

## A command exits successfully but the operation fails

Inkscape can print an unknown-action, missing-object, or export failure diagnostic
while returning exit code zero. The wrapper treats these diagnostics as failures.
It also checks generated artifacts before publishing managed exports. This avoids
reporting a successful edit when no valid output was produced.

GTK/font warnings are kept out of numeric query results. An existing destination
is preserved when managed export execution, validation, timeout, or cancellation
fails. Review the returned `message`/`error` and stderr instead of relying only on
an exit code.

## Invalid SVG or inaccessible paths

Use a complete SVG document with the namespace
`xmlns="http://www.w3.org/2000/svg"`. Live insertion rejects malformed XML, DTD/entity
declarations, empty drawings, and oversized content before interacting with the
desktop. For file construction, ensure the output is an `.svg` path.

Use absolute paths. Check permissions and `allowed_directories`. File editing
operations require explicit source and destination paths; they do not implicitly
save the active window. Size limits can be configured in YAML.

## Timeouts and slow exports

Set `process_timeout` in YAML, within its 5–300 second range, and restart the
server. Reduce file complexity or `max_concurrent_processes` for heavy jobs.
Live extension and snapshot steps also have their own bounded waits; increasing
the general CLI timeout does not solve missing desktop services.

For native runtime regressions:

```bash
uv run pytest tests/integration/test_inkscape_runtime.py --no-cov -q
```

Raster imports can depend on the system image loader and its D-Bus access.
Compare a normal desktop session if a restrictive environment blocks that loader.

## Sampling and local models

`generate_svg` and the other sampling tools need client support for MCP
`sampling.tools`. FastMCP injects the context; do not send `ctx` in arguments.
A client without this capability can still use `construct_svg` with complete XML,
all ordinary file tools, and live insertion.

The dashboard's Ollama/cloud generation path is separate. Check its provider
settings and endpoint, and use `list_local_models` to inspect reachable model
services. An empty model list does not imply that Inkscape is unavailable.

## HTTP and dashboard connection errors

The default standalone HTTP port is `11027`. The dashboard expects its backend
on `11028` and Vite runs on `11029`. Start the backend explicitly:

```bash
uv run inkscape-mcp --mode http --host 127.0.0.1 --port 11028
```

Use `/mcp` for an MCP client and `/api/health` for the REST health helper. The
`dual` CLI value is an HTTP alias, not simultaneous stdio and HTTP. Check for an
already-running listener if the port is occupied.

## Report a reproducible issue

Use [GitHub Issues](https://github.com/GianluDeveloper/inkscape-mcp/issues). Include
OS/Python/Inkscape versions, the exact tool name and arguments, its structured
response, and a minimal public SVG. For live failures, include the session type,
extension install result, session ID, and number of open Inkscape windows. Remove credentials and
private document content from attachments.
