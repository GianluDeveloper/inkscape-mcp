# Inkscape MCP - User Guide and Tutorials

Version 2.6.0. This guide is the companion to system.md. It walks through installing and
configuring the server, then gives concrete tutorials for the workflows people actually run:
loading and editing SVG, converting formats, generating vector art from a prompt, running
the agentic workflows, and handing assets off to the rest of the fleet. Each tutorial names
the tool and operations to call with realistic arguments.

## 1. Introduction

Inkscape MCP turns natural language into SVG and vector operations by driving a local
Inkscape installation through its command-line interface. You ask an assistant to "trace
this logo, simplify it, and export a PNG at 192 DPI" and the server runs the Inkscape CLI to
do it. The same surface is exposed as MCP tools (for AI clients) and as a REST API (for the
bundled web dashboard).

This guide assumes you have Inkscape installed via the classic desktop installer, Python
3.12+, and uv. The Microsoft Store version of Inkscape is sandboxed and cannot run the CLI,
so the server will fail with Access Denied if you point it at the Store build. Use the
classic installer from https://inkscape.org/release/ and, if Inkscape is not on PATH, set
the INKSCAPE_PATH environment variable to the executable.

## 2. Installation and First Run

### 2.1 Verify Inkscape

Confirm the CLI works before anything else:

```powershell
& "C:\Program Files\Inkscape\bin\inkscape.exe" --version
```

If that fails with Access Denied, you have the sandboxed MS Store build. Install the classic
desktop installer instead.

### 2.2 Install the server

```powershell
git clone https://github.com/sandraschi/inkscape-mcp
cd inkscape-mcp
uv sync
```

### 2.3 Run it

For an AI-only MCP server (Claude Desktop / Cursor):

```powershell
uv run inkscape-mcp --mode stdio
```

For the full stack with the web dashboard:

```powershell
uv run inkscape-mcp --mode dual --host 0.0.0.0 --port 11028
```

The dashboard runs on the frontend port and proxies to 11028.

### 2.4 Register in an MCP host

Add to your MCP host config (or use the packaged .mcpb bundle):

```json
"mcpServers": {
  "inkscape-mcp": {
    "command": "uv",
    "args": ["run", "inkscape-mcp", "--mode", "stdio"]
  }
}
```

### 2.5 Verify the server is up

Call inkscape_system with operation=status. It reports whether Inkscape is found and the
server is ready. Then call inkscape_system with operation=execution_mode to see whether you
are in hands-off (pure CLI) or hands-in (GUI watch) mode.

## 3. Configuration Reference

Most settings come from environment variables (see system.md section 4). The ones you are
most likely to change:

- INKSCAPE_PATH: override the Inkscape executable path if it is not on PATH.
- INKSCAPE_SAVE_DIR: where generated SVG files are saved (default
  ~/Documents/inkscape-mcp/generated).
- INKSCAPE_GUI_WATCH: set to 1 to enable Hands-In GUI collaboration.
- OLLAMA_BASE_URL / OLLAMA_MODEL: local LLM for SVG generation.
- GEMINI_API_KEY / ANTHROPIC_API_KEY: cloud fallbacks for generation.

You can also use a YAML config file (config.yaml in the repo or
~/.config/inkscape-mcp/config.yaml) for process timeout, quality, interpolation, and
supported formats.

## 4. Tutorial 1 - Load and Inspect an SVG

Goal: understand a document before editing it.

1. Call inkscape_file with operation=load and input_path to validate the file is editable.
2. Call inkscape_analysis with operation=info or statistics on input_path to get dimensions,
   file size, and object count.
3. Call inkscape_analysis with operation=structure to see the layer/object tree.
4. If you plan to mutate it, call inkscape_render with operation=get_document_summary to get
   a validation snapshot first.

## 5. Tutorial 2 - Convert an SVG to Another Format

Goal: export an SVG as a PNG (or PDF, EPS, webp, etc.).

1. Call inkscape_file with operation=convert, input_path=<file.svg>, output_path=<file.png>,
   and format=png.
2. For raster exports at a specific resolution, use inkscape_render with operation=
   export_preview, dpi=192 instead, which renders a PNG at a validated DPI (36-1200).
3. To render several resolutions at once, use export_multi_dpi with dpi_list=96,192,384.

## 6. Tutorial 3 - Vectorize a Raster (Trace)

Goal: convert a bitmap logo into editable vector paths.

1. Call inkscape_vector with operation=trace_image, input_path=<raster.png>,
   output_path=<traced.svg>.
2. Call inkscape_vector with operation=path_simplify on the result to reduce path noise.
3. Validate the result with inkscape_validation operation=validate_svg.
4. Export a clean raster at your target DPI with inkscape_render operation=export_preview.

## 7. Tutorial 4 - Edit Paths and Apply Booleans

Goal: combine or subtract shapes.

1. Load the document.
2. Select objects by object_id (or select_all=true) in the target paths.
3. Call inkscape_vector with operation=apply_boolean, operation_type=union (or difference,
   intersection, exclusion).
4. Call operation=path_combine or path_break_apart as needed.
5. Fit the canvas: inkscape_vector operation=fit_canvas_to_drawing.
6. Save or convert.

## 8. Tutorial 5 - Text to Path

Goal: convert editable text into geometric paths (for laser or reliable rendering).

1. Load the document containing the text.
2. Call inkscape_vector with operation=text_to_path, object_id=<text-object>.
3. Optionally set font_family, font_size, font_weight before converting.
4. Export.

## 9. Tutorial 6 - Optimize and QA an SVG

Goal: prepare an SVG for the web or for packing.

1. Call inkscape_vector with operation=optimize_svg or scour_svg on the input.
2. Call inkscape_validation with operation=audit_web_svg to check viewBox, stroke/fill, and
   size limits.
3. Call operation=audit_svg_pack for a pack-specific audit.
4. If checks fail, address the reported issues and re-run.

## 10. Tutorial 7 - Generate SVG from a Prompt

Goal: create vector art from a description.

1. Ensure a local LLM (Ollama) is reachable or set a cloud key.
2. Call generate_svg with style_preset (geometric, organic, technical, heraldic, abstract)
   and width/height between 64 and 8192.
3. The server probes capabilities, samples an SVG, saves it to INKSCAPE_SAVE_DIR, and
   validates it.
4. Open the returned path or continue editing it with the vector tools.

## 11. Tutorial 8 - Conversational Assistance

Goal: ask how to do something without mutating files.

1. Call conversational_inkscape_assistant with your question.
2. It answers read-only over the server's capabilities; it degrades gracefully if sampling
   is unavailable.
3. Use this to plan before running a destructive operation.

## 12. Tutorial 9 - The Agentic Workflow

Goal: accomplish a multi-step vector task autonomously.

1. Call agentic_inkscape_workflow with a goal, e.g. "take logo.svg, trace it if needed,
   simplify, and export a 256px icon".
2. The server plans up to 5 steps and executes them with sampling.
3. Review the per-step results.

## 13. Tutorial 10 - Batch Vector Processing

Goal: process many SVGs at once.

1. Call intelligent_vector_processing with a batch of files and strategy=adaptive (or
   parallel/sequential).
2. The server builds and executes a processing plan.

## 14. Tutorial 11 - Fleet Handoff to GIMP

Goal: hand a raster to the GIMP QA pipeline.

1. Render the SVG to a PNG at a good DPI: inkscape_render operation=export_preview, dpi=192.
2. Call inkscape_fleet with operation=push_gimp_raster, svg_path=<file.svg>,
   png_path=<file.png>.
3. Set skip_validate=false to gate it first.

## 15. Tutorial 12 - Stage for Blender

Goal: hand the SVG to Blender import.

1. Call inkscape_fleet with operation=stage_blender_svg, svg_path=<file.svg>.
2. Set import_to_blender=true if Blender should consume it directly.
3. Use skip_blender_stage=false to ensure the staging step runs.

## 16. Tutorial 13 - Build a Layer Atlas for Unity

Goal: split a multi-layer SVG into a Unity sprite atlas.

1. Call inkscape_fleet with operation=build_layer_atlas, svg_path=<file.svg>.
2. Review the generated atlas output.
3. Optionally push to Unity with push_unity_sprite.

## 17. Tutorial 14 - Fabrication (DXF + Laser)

Goal: prepare vector art for laser cutting.

1. Call inkscape_fab_art with operation=list_presets to see the presets.
2. Call operation=batch_dxf_export with input_dir and output_dir.
3. For laser calibration grids, call operation=batch_laser_dots with laser_preset_id.
4. For robotics schematics, call operation=gazebo_schematic.
5. Combine with run_fab_pipeline and push_gimp for raster QA.

## 18. Tutorial 15 - Simulation UI Icon Packs

Goal: build a UI icon sheet for a sim or VR app.

1. Call inkscape_sim_art with operation=list_presets.
2. Call operation=svg_pack_batch with input_dir, output_dir, and template_id (default
   ui_icon_128).
3. Build a sheet: operation=build_icon_sheet with layout, cell_size, margin_px.
4. Optionally stage for Resonite/VRChat with operation=stage_resonite_ui.

## 19. Tutorial 16 - Hands-In Collaboration

Goal: collaborate with the user editing in the Inkscape GUI.

1. Set INKSCAPE_GUI_WATCH=1 and ensure the GUI is open on the document.
2. Check execution_mode; it should report hands_in.
3. Ask the user to make a tweak in the GUI, then run a headless export against the same
   document. The two operate on one file.

## 20. REST API Reference

The HTTP mode exposes these endpoints under /api:

- GET /api/health: liveness.
- POST /api/generate-svg: generate SVG via Ollama -> Gemini -> Anthropic.
- POST /api/chat: SSE streaming chat (Ollama or LM Studio).
- GET /api/llm/providers: LLM discovery.
- GET /api/capabilities, /api/skills, /api/help: discoverability.
- GET /api/logs (and stats/export/clear): ring-buffer logging.
- GET /api/docs/{path}.md: documentation (path-traversal guarded).
- GET /api/v1/diagnostics, /api/v1/system/info: diagnostics.
- POST /v1/tool: MCP-tool bridge.
- GET /metrics and /api/metrics: Prometheus metrics (port 9074).

## 21. Troubleshooting

- Access Denied on inkscape: you have the sandboxed MS Store build. Install the classic
  desktop installer and set INKSCAPE_PATH if needed.
- CLI hangs: the server uses --no-remote-resources and a timeout; a hang is killed and
  reported. Check for external-resource references in the document.
- execution_mode stays hands_off: you are not in GUI watch mode. Set INKSCAPE_GUI_WATCH=1.
- Local LLM unreachable: set a cloud key (GEMINI or ANTHROPIC) or fix Ollama; list_local_models
  reports which providers are down.
- generate_barcode_qr gives a placeholder: it is not a real scannable QR. Use a QR library.
- create_mesh_gradient not implemented: build the gradient manually or use construct_svg.
- Port confusion: code may report old ports; use 11028 (MCP/REST), 11029 (frontend), 11062
  (logging).

## 22. FAQ

- Do I need Inkscape installed? Yes, the classic desktop installer.
- Can I edit existing files? Yes: load, edit, convert.
- Can it generate SVG? Yes, via generate_svg and /api/generate-svg.
- Does it need an LLM? Core tools no; agentic tools and chat yes (local or cloud).
- What exports are supported? svg, pdf, png, jpeg, jpg, webp, eps, ps, ai, cdr, wmf, emf,
  xaml, plus DXF.
- How do I hand off to the fleet? push_gimp_raster, stage_blender_svg, push_unity_sprite,
  build_layer_atlas, and the fab/sim pipelines.

## 23. Working with the inkscape_vector Tool in Depth

The inkscape_vector tool is the largest and most capable of the server. It carries many
operations, each with its own parameters. Here is more detail on the important ones.

- apply_boolean: pass operation_type=union, difference, intersection, or exclusion, and
  select the two or more objects to combine with object_ids or select_all. The server runs
  the corresponding Inkscape path action.
- path_simplify / path_clean: reduce node count or clean path data. Pass the object_id, or
  none to operate on the selection.
- path_inset_outset: shrink or expand a path; use the amount parameter.
- path_combine / path_break_apart: merge paths into a compound path or split them.
- object_to_path: convert a shape or text object into a path.
- text_to_path: convert text to paths, honoring font_family, font_size, font_weight.
- measure_object / query_document / count_nodes: geometry and structure inspection.
- export_dxf: export to DXF for CAD and laser use; set dpi and output_dir.
- optimize_svg / scour_svg: reduce file size and clean structure.
- generate_laser_dot: emit a laser calibration dot grid; set preset_id.
- set_document_units: change document units (px, mm, in, etc.).
- fit_canvas_to_drawing: resize the viewBox to the drawing bounds.

Each operation returns success, message, data, and execution_time_ms, so an agent can
confirm the effect and time cost.

## 24. Understanding execution_mode

The server reports how it is running:

- hands_off: pure CLI automation. Inkscape runs headless via --batch-process. This is the
  default and the safest for unattended work.
- hands_in: the Inkscape GUI is open with INKSCAPE_GUI_WATCH=1. The user can edit live while
  the agent runs exports against the same document.

Check execution_mode before starting a workflow that depends on the GUI. If you want hands-in
collaboration, tell the user to set INKSCAPE_GUI_WATCH=1 and open the document, then re-check.

## 25. REST API Worked Examples

The REST bridge gives the same capabilities over HTTP. Examples:

Generate an SVG:

```
POST http://127.0.0.1:11028/api/generate-svg
Content-Type: application/json

{ "prompt": "a minimalist geometric fox logo", "style": "geometric", "width": 512, "height": 512 }
```

Stream a chat:

```
POST http://127.0.0.1:11028/api/chat
Content-Type: application/json

{ "messages": [{ "role": "user", "content": "How do I export a PNG?" }] }
```

List providers:

```
GET http://127.0.0.1:11028/api/llm/providers
```

Query logs:

```
GET http://127.0.0.1:11028/api/logs?limit=50
```

Read documentation:

```
GET http://127.0.0.1:11028/api/docs/TOOLS.md
```

Metrics:

```
GET http://127.0.0.1:9074/metrics
```

The OpenAPI interactive docs are served by the FastAPI app; use /docs to explore every route.

## 26. End-to-End Example: Logo Refresh

A single narrative that exercises many tools:

1. inkscape_file operation=load input_path=old-logo.svg.
2. inkscape_analysis operation=statistics input_path=old-logo.svg.
3. inkscape_render operation=export_preview input_path=old-logo.svg dpi=96 to see it.
4. inkscape_vector operation=text_to_path on the wordmark.
5. inkscape_vector operation=path_simplify to clean the vector.
6. inkscape_vector operation=fit_canvas_to_drawing.
7. inkscape_validation operation=audit_web_svg.
8. inkscape_file operation=convert format=png output_path=new-logo.png.
9. inkscape_render operation=export_multi_dpi dpi_list=96,192,384.
10. inkscape_fleet operation=push_gimp_raster for raster QA.

## 27. End-to-End Example: Icon Sheet for a Sim

1. inkscape_sim_art operation=list_presets.
2. Prepare input SVGs in a directory.
3. inkscape_sim_art operation=svg_pack_batch input_dir=<svgs> output_dir=<out>.
4. inkscape_sim_art operation=build_icon_sheet layout=2x2 cell_size=128 margin_px=8.
5. inkscape_sim_art operation=audit_svg_pack.
6. inkscape_sim_art operation=stage_resonite_ui to hand off.
7. Optionally push a texture sheet to GIMP with operation=push_gimp_texture_sheet.

## 28. End-to-End Example: Fabrication Run

1. inkscape_fab_art operation=list_presets.
2. inkscape_fab_art operation=batch_dxf_export input_dir=<parts> output_dir=<dxf>.
3. inkscape_fab_art operation=batch_laser_dots for calibration.
4. inkscape_fab_art operation=gazebo_schematic for a robotics schematic.
5. inkscape_fab_art operation=stage_for_robotics staging_dir=<stage>.
6. inkscape_fab_art operation=run_fab_pipeline to combine.

## 29. Tips for Good Results

- Always inspect before mutating: run analysis.statistics and render.export_preview first.
- Validate before handing off: run audit_web_svg or audit_svg_pack before push_gimp_raster or
  a pack pipeline.
- Use export_multi_dpi when you need several resolutions, rather than repeated single
  exports.
- Prefer the portmanteau operations over raw CLI calls; they validate arguments and return
  structured results.
- Use hands-in mode only when a human genuinely needs to make a GUI tweak mid-flow; otherwise
  hands-off is faster and unattended.
- Check execution_mode at the start of a GUI-dependent workflow.

## 30. More FAQ

- Can I run it without a webapp? Yes, --mode stdio runs MCP only.
- What if Inkscape is missing? status/execution_mode report it; set INKSCAPE_PATH or install
  the classic build.
- Can I process files that live elsewhere? Use allowed_directories config and provide paths
  the server may access.
- Does it support SVG animations? Not through the production entry point; the animation tool
  group is not registered by main.py. Use static SVG workflows.
- Is there a preview? Yes, render.export_preview produces a PNG you can view.
- How do I reset a stuck Inkscape process? The server kills on process_timeout; if the GUI
  hangs, close it and restart the server.

## 31. Operation Quick Reference

This section summarizes the operations grouped by tool, for quick lookup.

inkscape_file: load, save, convert, info, validate, list_formats.
inkscape_vector: trace_image, generate_barcode_qr (placeholder), text_to_path, construct_svg,
  apply_boolean, path_inset_outset, path_simplify, path_clean, path_combine, path_break_apart,
  object_to_path, optimize_svg, scour_svg, measure_object, query_document, count_nodes,
  export_dxf, layers_to_files, fit_canvas_to_drawing, render_preview, generate_laser_dot,
  object_raise, object_lower, set_document_units.
inkscape_analysis: quality, statistics, validate, objects, dimensions, structure.
inkscape_render: export_preview, export_multi_dpi, get_document_summary.
inkscape_validation: validate_svg, check_viewbox, check_stroke_fill, check_size_limits,
  audit_web_svg, audit_svg_pack.
inkscape_fleet: push_gimp_raster, stage_blender_svg, push_unity_sprite, build_layer_atlas,
  run_pipeline, list_staging.
inkscape_fab_art: list_presets, batch_dxf_export, batch_laser_dots, gazebo_schematic,
  stage_for_robotics, run_fab_pipeline.
inkscape_sim_art: list_presets, svg_pack_batch, build_icon_sheet, audit_svg_pack,
  ai_svg_refine_loop, push_gimp_texture_sheet, stage_resonite_ui, run_sim_pipeline.
inkscape_system: status, execution_mode, help, diagnostics, version, config,
  list_extensions, execute_extension, self_terminate.

## 32. Vector Parameters Cheat Sheet

The inkscape_vector tool accepts many optional parameters. Know which apply to which
operation:

- object_id / object_ids / select_all: choose which objects to act on. Essential for
  apply_boolean, text_to_path, object_to_path, path_* operations.
- operation_type: used by apply_boolean (union, difference, intersection, exclusion).
- x, y: coordinates for placement operations.
- threshold: used by trace_image to control the trace sensitivity.
- dpi: resolution for export_dxf and render-related output.
- units: document units for set_document_units.
- shape, params: passed to construct_svg.
- element_type, direction, amount: geometry operations.
- lpe_id: live path effect selection.
- text, font_family, font_size, font_weight, fill, text_anchor: text operations.
- preset_id: preset for generate_laser_dot.
- output_dir: where multi-file outputs go.

Use these deliberately; an operation that does not consume a given parameter will ignore it.

## 33. Validation Workflow for Web-Ready SVG

Before shipping an SVG to the web, run this gate:

1. inkscape_validation operation=validate_svg input_path=<file.svg>.
2. operation=check_viewbox to confirm a sane viewBox.
3. operation=check_stroke_fill for unresolved strokes or fills.
4. operation=check_size_limits to catch oversized files.
5. operation=audit_web_svg for a combined web audit.
6. Fix any findings, then inkscape_vector operation=optimize_svg and re-audit.

## 34. Local LLM Setup for Generation

To use generate_svg and the REST generation pipeline:

1. Run Ollama and pull a model, e.g. qwen2.5-coder.
2. Set OLLAMA_BASE_URL=http://localhost:11434 and OLLAMA_MODEL=qwen2.5-coder:latest (the
  defaults).
3. Optionally set GEMINI_API_KEY or ANTHROPIC_API_KEY as cloud fallback.
4. Verify with list_local_models, which lists Ollama and LM Studio models and reports which
  providers are unreachable.
5. Call generate_svg with a style_preset.

## 35. Prompts That Work Well

- "Trace logo.png, simplify the paths, and export a 192 DPI PNG."
- "Load icon.svg, convert the text to paths, then save."
- "Generate a geometric logo, 512x512."
- "Audit this SVG for web use and report any viewBox or size issues."
- "Push this logo to GIMP for raster QA."
- "Build an icon sheet from the SVGs in folder, 2x2, 128px cells."
- "Export all parts in folder to DXF for laser cutting."

## 36. Best Practices Summary

- Inspect before you mutate: analysis + render preview first.
- Validate before you hand off or ship.
- Use export_multi_dpi for multiple resolutions.
- Use hands-in only when a human GUI tweak is genuinely needed.
- Prefer portmanteau operations over raw CLI.
- Treat placeholder/not-implemented operations as real signals and route around them.

## 37. Agentic Tools in Depth

The agentic tools use FastMCP sampling and require a sampling-capable client (Claude Desktop,
a capable host). They probe the server capability string to learn which file/vector/heraldic/
style and generation approaches are available.

- generate_svg(style_preset, width, height): the primary generator. It samples a full SVG,
  saves it to INKSCAPE_SAVE_DIR, and validates it. width and height must be between 64 and
  8192. style_preset is geometric, organic, technical, heraldic, or abstract.
- agentic_inkscape_workflow(goal): a planner that breaks a vector task into up to 5 steps and
  executes them, reasoning between steps.
- intelligent_vector_processing(batch, strategy): processes a set of SVGs using an adaptive,
  parallel, or sequential strategy. Good for library-wide cleanup.
- conversational_inkscape_assistant(question): read-only Q&A. Falls back to a static answer
  when sampling is unavailable.

If sampling is unavailable, these tools degrade gracefully instead of failing hard. Call
inkscape_system operation=diagnostics if you suspect sampling is not wired up.

## 38. Deep Dive: File Conversion

The inkscape_file convert operation is the primary format bridge. It accepts input_path,
output_path, and format.

Supported formats include svg, pdf, png, jpeg, jpg, webp, eps, ps, ai, cdr, wmf, emf, and
xaml. The conversion runs through the Inkscape CLI:

- To raster formats (png, jpeg, jpg, webp), pass an output_path with the right extension and
  the server renders at the document resolution, or use export_preview/export_multi_dpi for
  explicit DPI control.
- To vector formats (pdf, eps, ps, ai, cdr, wmf, emf, xaml), the document is re-exported as
  that vector type.
- To DXF for CAD/laser, use inkscape_vector operation=export_dxf instead.

For predictable results, validate the source SVG first (inkscape_validation
operation=validate_svg), then convert, then render a preview to confirm the output looks
correct.

## 39. Deep Dive: Working with Layers

SVG documents are organized into layers. Use these tools on layer structure:

- inkscape_analysis operation=structure to list the layer/object tree.
- inkscape_vector operation=layers_to_files to export each layer as its own SVG file.
- inkscape_fleet operation=build_layer_atlas to combine layers into a texture atlas.
- inkscape_vector operation=object_raise / object_lower to change z-order within or across
  layers.

Layers are important for handoff: Blender and Unity imports often care about layer
separation, and layer atlases are a common game-art workflow.

## 40. Advanced Narrative: Automated Asset Pipeline

A realistic end-to-end scenario that shows the fleet handoff value:

1. A designer exports source art as SVG files into a staging directory.
2. The agent runs inkscape_sim_art operation=svg_pack_batch to normalize them into an icon
   pack.
3. It runs operation=build_icon_sheet to produce a texture sheet.
4. It runs operation=audit_svg_pack to gate quality.
5. It hands the sheet to GIMP via operation=push_gimp_texture_sheet for raster QA.
6. It stages the result for Resonite/VRChat via operation=stage_resonite_ui.
7. It reports the final paths and any failing files.

The same pattern applies to fabrication (fab pipeline) and Blender/Unity handoff (fleet
pipeline). The skip_* gates let you run only the stages you have tooling for.

## 41. Performance and Resource Notes

- Inkscape CLI launches are process-bound; max_concurrent_processes (default 3) limits how
  many run at once. For large batches, prefer intelligent_vector_processing with a
  sequential or adaptive strategy over firing many single operations.
- process_timeout (default 30s) guards against hangs; documents referencing external
  resources can exceed it. Run with --no-remote-resources handling already applied by the
  server.
- Rendering many DPIs in one export_multi_dpi call is cheaper than repeated single exports.
- Validation is cheap; run it before expensive handoff or conversion steps.
- Metrics are exposed on port 9074 if INKSCAPE_MCP_METRICS_ENABLED is true (default).

## 42. Getting Started in Ten Calls

A compact onboarding sequence that exercises the main tools:

1. inkscape_system operation=status - confirm Inkscape + server ready.
2. inkscape_system operation=execution_mode - hands_off or hands_in.
3. inkscape_file operation=list_formats - see supported formats.
4. inkscape_file operation=load input_path=example.svg.
5. inkscape_analysis operation=statistics input_path=example.svg.
6. inkscape_render operation=export_preview input_path=example.svg dpi=96.
7. inkscape_vector operation=path_simplify on an object.
8. inkscape_file operation=convert format=png output_path=example.png.
9. inkscape_validation operation=audit_web_svg input_path=example.svg.
10. inkscape_system operation=diagnostics.

This gives you the tool feel and confirms end-to-end function.

## 43. Working with Extensions

Inkscape extensions are add-ons described by .inx files.

- inkscape_system operation=list_extensions scans for and lists available .inx extension
  descriptors.
- inkscape_system operation=execute_extension runs one; note the wrapper does not expose all
  parameters, so prefer list_extensions first to learn what is available, and rely on the
  core operations for the common cases.

Extensions are configured through the YAML config (enable_extensions, extension_dirs,
disabled_extensions, extension_config). If an extension is not listed, check that its
extension_dir is included.

## 44. Extending with the Webapp

The bundled webapp gives a visual surface over the same tools. It proxies /api and /mcp to
the backend on 11028, and the frontend runs on 11029. Through the webapp you can:

- Watch the ring-buffer logs (/api/logs).
- Trigger generation from the prompt builder.
- Browse capabilities, skills, and help.
- See health and diagnostics.

For pure agent use you can run --mode stdio and skip the webapp entirely.

## 45. Security Notes

- The server binds to 0.0.0.0 by default in HTTP/dual mode; restrict it to 127.0.0.1 unless
  you intend network access.
- CORS origins are locked to localhost, the Tauri shell, and Tailscale addresses.
- allowed_directories is declared in config; keep paths scoped to directories the server may
  touch.
- /api/docs rejects non-.md paths, .., and leading / (path-traversal guarded).
- self_terminate is a system operation; do not expose it to untrusted clients.
- Keep cloud keys (GEMINI_API_KEY, ANTHROPIC_API_KEY) out of source control.

## 46. Troubleshooting Scenarios

- Status says Inkscape not found: set INKSCAPE_PATH, or install the classic build. The MS
  Store build fails with Access Denied on the CLI.
- Convert output is missing or empty: validate the source SVG first, ensure output_path has
  the correct extension, and check the log for a failed action.
- export_preview rejects a DPI: DPI must be within 36-1200. Use a value in that range.
- generate_svg fails with sampling error: your host does not support sampling; use
  conversational_inkscape_assistant instead, or set a cloud key and use the REST endpoint.
- A batch job times out: reduce max_concurrent_processes or split the batch; large
  multi-file jobs can exceed process_timeout.
- The webapp cannot reach the backend: confirm the backend is on 11028 and the frontend on
  11029; check CORS if you changed the host.
- Logs are empty: confirm INKSCAPE_MCP_METRICS_ENABLED and the logging backend on 11062.
- An operation returns not_implemented: that operation is a placeholder (e.g.
  create_mesh_gradient, generate_barcode_qr as a real QR). Use a supported operation instead.

## 47. Getting Help

- For per-tool help, call inkscape_system operation=help, or read docs/TOOLS.md and
  docs/CONFIGURATION.md in the repo.
- For live answers without mutating files, call conversational_inkscape_assistant.
- Check the ring-buffer logs (/api/logs) for failed actions and their error_type.
- File an issue on the repo if a documented operation misbehaves, including the error_type
  and the operation that failed.

