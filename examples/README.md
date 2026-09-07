# SVG Examples Catalog

Production-grade SVG vector files for testing, demonstration, and automated workflow validation with `inkscape-mcp`.

## Examples Included

| File | Purpose | Key SVG Features / Layers | Test Operations |
|---|---|---|---|
| [`logo_badge.svg`](file:///d:/Dev/repos/inkscape-mcp/examples/logo_badge.svg) | Brand badge / Emblem | Radial & linear gradients, `<textPath>`, drop shadows, layer hierarchy (`Background`, `Emblem`, `Text & Banner`) | `render_preview`, `text_to_path`, `export_dxf` |
| [`technical_diagram.svg`](file:///d:/Dev/repos/inkscape-mcp/examples/technical_diagram.svg) | Architecture & Flowchart | Labeled nodes, marker arrows, dashed stroke connectors, structured layers (`Grid`, `Connectors`, `Nodes`) | `query_document`, `measure_object`, `objects` |
| [`laser_cut_template.svg`](file:///d:/Dev/repos/inkscape-mcp/examples/laser_cut_template.svg) | CNC / Laser Cut Pattern | Red vector cut strokes (`#FF0000`), blue vector scoring (`#0000FF`), black raster engraving (`#000000`), crosshair registration marks | `layers_to_files`, `export_dxf`, `set_document_units` |
| [`ui_icons.svg`](file:///d:/Dev/repos/inkscape-mcp/examples/ui_icons.svg) | Clean Vector Icon Set | Grid-aligned UI icons (`icon_settings`, `icon_vector_pen`, `icon_trace`, `icon_qr_code`) with simplified paths | `path_simplify`, `optimize_svg`, `scour_svg` |
| [`layered_illustration.svg`](file:///d:/Dev/repos/inkscape-mcp/examples/layered_illustration.svg) | Multi-Layer Landscape Art | 4-layer Z-stack (`Background Sky`, `Far Mountains`, `Midground Hills`, `Foreground Silhouette`) | `object_raise`, `object_lower`, `layers_to_files`, `render_preview` |

---

## Quick Testing Commands

### 1. Render High-DPI Preview PNG
```bash
uv run inkscape-mcp --mode stdio
# Tool: inkscape_vector
# Params: operation="render_preview", input_path="examples/logo_badge.svg", output_path="badge_preview.png", dpi=300
```

### 2. Export Layers to Separate Vector Files
```bash
# Tool: inkscape_vector
# Params: operation="layers_to_files", input_path="examples/layered_illustration.svg", output_dir="output_layers"
```

### 3. Convert Text Elements to Paths
```bash
# Tool: inkscape_vector
# Params: operation="text_to_path", input_path="examples/logo_badge.svg", output_path="logo_badge_paths.svg"
```

### 4. Export CAD DXF File
```bash
# Tool: inkscape_vector
# Params: operation="export_dxf", input_path="examples/laser_cut_template.svg", output_path="laser_template.dxf"
```

### 5. Automated Gallery Generation
Run the included build tool to generate PNG thumbnails and update the interactive gallery:
```bash
uv run python scripts/build/generate_example_gallery.py
```
