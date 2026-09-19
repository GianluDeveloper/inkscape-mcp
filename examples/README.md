# SVG examples

These editable SVG files are small fixtures for inspection, rendering, and
file-editing workflows. Open them directly in Inkscape or use the
[documented MCP tools](../docs/TOOLS.md).

| File | Contents |
| --- | --- |
| [live-demo.svg](live-demo.svg) | Native desktop acceptance output with an editable rectangle and Unicode text |
| [logo_badge.svg](logo_badge.svg) | Gradients, text on a path, a shadow filter, and named layers |
| [technical_diagram.svg](technical_diagram.svg) | Labeled nodes, arrow markers, connectors, and a grid |
| [laser_cut_template.svg](laser_cut_template.svg) | Color-coded outlines, engraving artwork, and registration marks |
| [ui_icons.svg](ui_icons.svg) | Four grouped icons with object IDs |
| [layered_illustration.svg](layered_illustration.svg) | A landscape separated into four Inkscape layers |

The [live demo preview](../docs/images/live-demo.png) was exported by Inkscape.
The remaining files are illustrative fixtures; labels in their artwork are not
test results or compatibility guarantees.

## Render a file

From the repository root, with the native Inkscape executable installed:

```bash
inkscape examples/logo_badge.svg --export-type=png --export-filename=/tmp/inkscape-logo-badge.png
```

Through MCP, send this to `inkscape_render`, replacing both paths with absolute
paths accessible to the server:

```json
{
  "operation": "export_preview",
  "input_path": "/absolute/path/to/inkscape-mcp/examples/logo_badge.svg",
  "output_path": "/absolute/path/to/badge-preview.png",
  "dpi": 144
}
```

## Inspect objects

Send this to `inkscape_analysis`:

```json
{
  "operation": "objects",
  "input_path": "/absolute/path/to/inkscape-mcp/examples/technical_diagram.svg"
}
```

Use returned IDs for subsequent object-specific operations. For a PDF, call
`inkscape_file` with `operation: "convert"`, source and destination paths, and
`format: "pdf"`.

For live drawing, saving, and separate managed windows, follow
[Usage](../docs/USAGE.md). Reproduce the two-document acceptance workflow with
[the desktop smoke script](../scripts/desktop_smoke.py), as described in
[Development](../docs/DEVELOPMENT.md#tests).
