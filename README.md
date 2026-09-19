# Inkscape MCP — AI-powered vector graphics

AI agents create, edit, layer, animate, and export SVG files using Inkscape. Works as an MCP server (stdio/HTTP), Claude Desktop `.mcpb` bundle, webapp dashboard, or Windows desktop app.

## Preview

| Dashboard | Animation Studio | Layer Manager |
|-----------|-----------------|---------------|
| ![Dashboard](docs/screenshots/dashboard.png) | ![Animation Studio](docs/screenshots/animation-studio.png) | ![Layer Manager](docs/screenshots/layer-manager.png) |

*Animated SVG presets render live in the browser — no Inkscape CLI needed.*

## How it runs

| Mode | Inkscape | When |
|------|----------|------|
| **Headless (default)** | CLI via `inkscape --actions` | Batch processing, export, validation, fleet pipelines |
| **Live GUI (optional)** | Open Inkscape manually + `--active-window` | Interactive editing with agent co-pilot |

> **Headless by default** — no GUI needed for most operations.

## Features
- Create and edit SVG files (shapes, text, paths, booleans)
- Layer management — list, create, rename, hide, lock, reorder
- SMIL animation — bounce, fade, slide, rotate, pulse, shake presets
- Live Path Effects — bend, roughen, envelope, spiro, power stroke
- Export to PNG, PDF, EPS, DXF
- Fleet pipeline — hand off to GIMP, Blender, Unity, Resonite
- LPEs, text operations, object inspection, hands-in control

## Quick Install

**Claude Desktop:** download the `.mcpb` from [Releases](https://github.com/sandraschi/inkscape-mcp/releases) and drag it onto Claude.

**Windows desktop app:** download the NSIS installer from [Releases](https://github.com/sandraschi/inkscape-mcp/releases) and run it.

**Manual:** `git clone`, `uv sync`, `just serve`. See [INSTALL.md](INSTALL.md) for all methods.

## What You Can Do

> "Create a bouncing circle animation with a pink fill and 2-second duration, then export as PNG."

> "List all layers in my SVG, hide the background layer, and rename the top layer to 'Hero'."

> "Convert this text element to paths, then apply a roughen LPE with medium intensity."

### Create an SVG without sampling

Call `inkscape_vector` with `operation="construct_svg"`, an `output_path`, and
`svg_content` containing the complete SVG XML. Alternatively, pass a `params`
object with `body` and optional `header`/`footer` strings. For example:

```json
{
  "operation": "construct_svg",
  "output_path": "/home/ubuntu/Downloads/sun.svg",
  "svg_content": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 100 100\"><circle cx=\"50\" cy=\"50\" r=\"30\" fill=\"gold\"/></svg>"
}
```

The server validates the XML before writing. Missing content, invalid XML, an
invalid output extension, and configured directory/size limits produce a structured
error. `generate_svg` instead requires client support for MCP `sampling.tools`;
its `Context` is injected by FastMCP and must not be supplied as a JSON argument.

To open a saved file in a running Inkscape window, call `inkscape_system` with
`operation="hands_in_command"` and
`action="file-open:/absolute/path/sun.svg;window-open"`. On Linux, the MCP server
must inherit the desktop session's `DISPLAY`/`WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR`,
`DBUS_SESSION_BUS_ADDRESS`, and `XAUTHORITY` variables as applicable.

After updating the server code, restart or reconnect the MCP connection so the
client reloads the tool schemas.

## Documentation

| Doc | Contents |
|-----|----------|
| [Installation](INSTALL.md) | All install methods, prerequisites |
| [Configuration](docs/CONFIGURATION.md) | Env vars, Ollama, Tauri desktop mode |
| [Tool Reference](docs/TOOLS.md) | All 17 tools, 60+ operations |
| [Development](docs/DEVELOPMENT.md) | Contributing, local setup, building |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | Common issues |

## Requirements

- **Windows**, macOS, or Linux
- **Inkscape 1.0+** (1.2+ recommended for Actions API)
- **Python 3.12+** with [uv](https://docs.astral.sh/uv/)
- Optional: Ollama for AI-assisted SVG generation

## License

MIT — see [LICENSE.md](LICENSE.md).
