# Installation

The supported source entry point is `uv run inkscape-mcp`. Install the repository
and configure an MCP client to launch it over stdio, or run an HTTP listener.
A browser dashboard and local model service are optional.

## Requirements

- Python **3.12 or later**. Python 3.12 is the tested baseline.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git.
- Inkscape with a working CLI. Inkscape **1.3+** is required for the live desktop
  bridge; **1.4.4** is the verified version.
- An MCP client for agent use. HTTP and direct Python clients are also supported.

The verified environment is **Ubuntu 26.04.1 LTS**, **Python 3.12.14**, and
**Inkscape 1.4.4**. CLI code includes Windows and macOS support; the live insertion
bridge currently targets Linux desktop sessions.

## Ubuntu 26.04

Install the native dependencies before syncing Python packages:

```bash
sudo apt update
sudo apt install inkscape git build-essential pkg-config python3-dev \
  libcairo2-dev libgirepository-2.0-dev gir1.2-gtk-3.0 \
  libmagic1t64 libglib2.0-bin python3-numpy python3-lxml python3-scour \
  python3-cssselect python3-platformdirs
```

`inkex` pulls in PyGObject/Cairo dependencies, which may be built from source.
`libgirepository-2.0-dev`, `libcairo2-dev`, and `pkg-config` satisfy their native
build requirements on the tested Ubuntu release. Older distributions may need
different package names or newer native libraries.

Inkscape runs extensions with its system Python. The `python3-numpy`,
`python3-lxml`, `python3-scour`, `python3-cssselect`, and `python3-platformdirs`
packages support that interpreter independently of the MCP virtual environment.
Omitting them in a minimal `--no-install-recommends` installation can open an
extension traceback dialog and make a live operation time out.

After installing uv:

```bash
git clone https://github.com/GianluDeveloper/inkscape-mcp.git
cd inkscape-mcp
uv sync --python 3.12
inkscape --version
uv run python --version
uv run inkscape-mcp --help
```

`uv sync` creates `.venv` and installs the project. It can provision the requested
Python version, so it does not depend on Ubuntu's default Python being 3.12.
There is no need to run a second editable install afterward.

## Windows

Install Inkscape using the **classic desktop installer** from the
[official release page](https://inkscape.org/release/). The Microsoft Store package
is sandboxed and is unsuitable for this server's CLI calls.

In PowerShell, verify the actual executable:

```powershell
& "C:\Program Files\Inkscape\bin\inkscape.exe" --version
```

Install Git and uv, then clone and sync the repository as above. For a custom
installation path:

```powershell
$env:INKSCAPE_PATH = "C:\Program Files\Inkscape\bin\inkscape.exe"
uv run inkscape-mcp --mode stdio
```

Use forward slashes or escaped backslashes in JSON configuration. Python native
dependencies can require additional platform build tools; the Ubuntu procedure
above is the fully exercised setup. Linux-only `insert_svg` and `draw_test` do not
provide Windows desktop control.

## macOS

Install the desktop application from the
[official release page](https://inkscape.org/release/) and verify its CLI:

```bash
/Applications/Inkscape.app/Contents/MacOS/inkscape --version
export INKSCAPE_PATH=/Applications/Inkscape.app/Contents/MacOS/inkscape
```

Install uv and Git, then clone and sync the project. Cairo/GObject development
libraries may be needed to build Python dependencies. This platform's installation
and live desktop behavior have not been verified in the Ubuntu test session.

## Connect a local MCP client

For clients accepting the `mcpServers` format:

```json
{
  "mcpServers": {
    "inkscape-mcp": {
      "command": "/absolute/path/to/uv",
      "args": [
        "--directory", "/absolute/path/to/inkscape-mcp",
        "run", "inkscape-mcp", "--mode", "stdio"
      ],
      "env": {
        "INKSCAPE_PATH": "/usr/bin/inkscape"
      }
    }
  }
}
```

Replace both paths. Use the appropriate server block if your client has a
different configuration schema. The client starts the process; you do not need
to keep a separate stdio server running. A stdio process started in a terminal
waits for MCP messages and is not an interactive command prompt.

Reconnect the client after changing the code or server configuration. Call
`inkscape_system` with `{"operation":"status"}` and verify
`data.inkscape.available` is true. `{"operation":"diagnostics"}` checks the
server configuration and wrapper setup; it is not a live desktop insertion test.

## Enable live drawing

1. Start the MCP client/server in your graphical user session, with `gdbus`
   available (`libglib2.0-bin` on Ubuntu).
2. Call `inkscape_system` with `{"operation":"install_live_extension"}`.
3. Restart any existing Inkscape windows once. Newly launched managed instances
   load the installed extension automatically.
4. For an existing single-window desktop instance, use `session_id: "desktop"`.
   For several documents, call `new_document` or `open_document` and retain each
   returned `session_id`.
5. Call `active_document` for the target, followed by `draw_test` with a test label.
6. Check `data.verified` and inspect the rectangle/text in the intended window.
   **Edit → Undo** reverses the insertion.

The extension is installed under
`~/.config/inkscape/extensions/inkscape_mcp_live/` by default. `XDG_CONFIG_HOME` or
`INKSCAPE_PROFILE_DIR` can change that location. The installer reports
`install_dir`, `files_changed`, and `needs_restart`; it writes only the bundled
extension files. Install into the same profile used by your target Inkscape
instances. To remove it, delete that specific extension directory and restart
Inkscape.

The live editing extension is a separate step from installing the Python MCP
server. Native insertion does not require a clipboard helper. The server needs
the desktop session's `DISPLAY` or `WAYLAND_DISPLAY`, `DBUS_SESSION_BUS_ADDRESS`,
`XDG_RUNTIME_DIR`, and `XAUTHORITY` as applicable. An SSH session, container,
service, or client launched outside the desktop may not inherit them.
`INKSCAPE_GUI_WATCH=1` changes mode guidance; it does not grant desktop access.
Do not run the server with `sudo` to work around this.

`new_document` requires a new `.svg` path and refuses to overwrite an existing
file. `open_document` requires an existing SVG. Managed document sessions are
listed by `list_documents` and survive MCP restarts while their Inkscape instances
remain open. See the [multi-document workflow](docs/USAGE.md#work-with-multiple-documents).

## HTTP and dashboard

```bash
uv run inkscape-mcp --mode http --host 127.0.0.1 --port 11028
```

- MCP endpoint: `http://127.0.0.1:11028/mcp`.
- REST health helper: `http://127.0.0.1:11028/api/health`.
- Browser frontend: `http://127.0.0.1:11029`, after running the commands below.

```bash
cd web_sota
bun install --frozen-lockfile
bun run dev
```

Use Bun 1.3.14, matching the frontend package manager declaration. The
frontend is optional and does not need to be built for stdio MCP use. Keep HTTP
on loopback unless you have configured an appropriate authenticated deployment.

## Docker HTTP service

Build the local image, then start the batch HTTP server:

```bash
docker build --network=host --target production -t inkscape-mcp:local .
docker compose up -d --no-build inkscape-mcp
curl http://127.0.0.1:10900/api/health
```

The MCP endpoint is `http://127.0.0.1:10900/mcp`; metrics are published at
`http://127.0.0.1:9074/metrics`. Compose binds all published ports to loopback.
The image uses Ubuntu 26.04, pinned uv/Python versions, and dependencies from
`uv.lock`. It runs as UID **10001**, with persistent `/data` and `/app/logs`
volumes. Use container paths such as `/data/drawing.svg` in tool calls; for
example, `docker cp drawing.svg inkscape-mcp:/data/drawing.svg` supplies an input.
This container does not connect to the host's Inkscape desktop session.

The optional monitoring stack is retained:

```bash
docker compose --profile monitoring up -d --no-build
docker compose logs inkscape-mcp
docker compose --profile monitoring down
```

Prometheus, Loki, and Grafana use loopback ports `9092`, `3102`, and `3002`.
`docker compose down` retains the named data volumes; removing volumes is a
separate Docker operation.

## Update and uninstall

To update a clean checkout, stop its MCP process, pull the repository changes,
run `uv sync`, and restart/reconnect the MCP client. Preserve local edits before
pulling. Client tool schemas are refreshed when the connection restarts.

To uninstall this source setup, remove its MCP server configuration, stop the
server, and remove the checkout/virtual environment when no longer needed.
Generated SVGs and exports are ordinary files; retain or remove them separately.

Packaging scripts for MCPB and the desktop app are included in the repository.
This guide does not require a published installer or a PyPI release; install from
this checkout to obtain the fixes documented here.

Continue with [Configuration](docs/CONFIGURATION.md),
[Examples](docs/USAGE.md), or [Troubleshooting](docs/TROUBLESHOOTING.md).
