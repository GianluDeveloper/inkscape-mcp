# Inkscape MCP - System Prompt and Capability Reference

Version 2.6.0. FastMCP >= 3.4.4,<4. Python 3.12+. The wrappee is Inkscape, driven headless
through its CLI (`--batch-process`, `--export-type`, `--query-*`).

## 1. What This Server Is

Inkscape MCP is a FastMCP server that turns natural language into SVG and vector
operations by driving a local Inkscape installation through its command-line interface. It
is not a replacement for Inkscape; it is an automation and integration layer. Through
portmanteau tools it can load, edit, convert, analyze, render, validate, and export SVG
documents, and hand assets off to other fleet servers (GIMP, Blender, Unity, Gazebo,
Resonite, VRChat). It also includes agentic, sampling-based SVG generation that produces
vector artwork from a text or style prompt.

The key architectural decision is that Inkscape runs **headless** via its CLI. The primary
invocation is `inkscape --batch-process --actions="<action1>;<action2>"`, which runs a
sequence of actions without opening a window. Exports use `--export-type=...` and
`--export-filename=...`, geometry queries use `--query-id`/`--query-bbox`/`--query-all`, and
legacy verbs use `--verb`. The CLI is launched with `--no-remote-resources` to avoid hangs on
external-resource lookups, under a per-process timeout, with the process killed if it exceeds
the limit.

There is an optional **Hands-In mode** (set `INKSCAPE_GUI_WATCH=1`): the user edits in the
Inkscape GUI while the agent runs headless CLI exports against the same open document, so
the two collaborate on one file. The `execution_mode` operation reports whether the server
is in `hands_in` (GUI process present) or `hands_off` (pure CLI automation). This matters:
some workflows are best served by asking the user to make a GUI tweak while the agent handles
the mechanical export.

## 2. Transports, Entry Point, and CLI

The server supports three transports, set by `--mode` or the `MCP_TRANSPORT` environment
variable:

- stdio: JSON-RPC over stdin/stdout, used by Claude Desktop and other MCP hosts.
- http: FastMCP Streamable HTTP plus a FastAPI REST bridge mounted at `/api/*`. The MCP
  endpoint is served at `/mcp`.
- dual (default): both, via `uv run inkscape-mcp --mode dual`.

CLI flags: `--config PATH`, `--mode {stdio,http,dual}`, `--port` (default 11027 in code,
11028 in the fleet registry), `--host` (0.0.0.0), `--log-level`. When `--mode` is given it
sets `MCP_TRANSPORT`/`MCP_PORT`; otherwise the external `MCP_TRANSPORT` env is honored and
stdio is the fallback.

## 3. Network Ports

The canonical fleet-registered ports (WEBAPP_PORTS.md) are:

- 11028 TCP: the MCP HTTP listener + REST bridge (`/mcp`, `/api/*`).
- 11029 TCP: the Vite frontend, which proxies `/api` and `/mcp` to 11028.
- 11062 TCP: the logging backend (FastAPI ring-buffer log query/stats/export/clear).
- 9074 TCP: Prometheus metrics scrape (PROMETHEUS_PORT).
- 11434 TCP: Ollama (external) used for local SVG generation.
- 1234 TCP: LM Studio (external), discovered for provider selection.

Some code paths still mention 11027, 10873, 10900, and 10899; treat 11028 as canonical and
the registry source of truth.

## 4. Configuration

Configuration comes from environment variables and an optional YAML config file.

Environment variables: MCP_TRANSPORT, MCP_PORT, MCP_HOST, INKSCAPE_PATH (override the
Inkscape executable path), INKSCAPE_SAVE_DIR (where generated SVGs are saved, default
`~/Documents/inkscape-mcp/generated`), INKSCAPE_GUI_WATCH (1 enables Hands-In GUI watch),
INKSCAPE_TAURI (set by the Tauri launcher for desktop CORS), OLLAMA_BASE_URL
(default `http://localhost:11434`), OLLAMA_MODEL (default `qwen2.5-coder:latest`),
GEMINI_API_KEY and ANTHROPIC_API_KEY (cloud fallbacks for SVG generation),
PROMETHEUS_PORT, INKSCAPE_MCP_METRICS_ENABLED.

YAML config file search order: `./config.yaml`, `./inkscape-mcp.yaml`,
`~/.inkscape-mcp/config.yaml`, `~/.config/inkscape-mcp/config.yaml`. The loader also
auto-creates `~/.config/inkscape-mcp/config.yaml`. The config model includes:
inkscape_executable, max_concurrent_processes (3), process_timeout (30s), temp_directory,
max_file_size_mb (100), preserve_metadata, auto_cleanup, cleanup_interval, default_quality
(95), default_interpolation (lanczos), supported_formats
(svg,pdf,png,jpeg,jpg,webp,eps,ps,ai,cdr,wmf,emf), enable_batch_operations,
enable_extensions, extension_dirs, disabled_extensions, extension_config,
batch_size_limit (50), log_level, enable_performance_logging, enable_file_validation, and
allowed_directories. Validators enforce a writable temp directory, a valid interpolation
value, and a valid log level.

## 5. Tool Surface by Subsystem

The production entry point registers ten portmanteau master tools plus agentic tools and a
few discrete tools. Each master tool takes an `operation` Literal and a variable set of
domain parameters. Errors are returned as structured dicts with success, operation, message,
data, execution_time_ms, error, error_type, and recovery hints plus next_steps.

### 5.1 inkscape_file - File I/O

Operations: load, save, convert, info, validate, list_formats.

- load: validate a path for editing.
- save: persist an SVG, honoring path policy.
- convert: convert SVG to pdf/png/jpeg/webp/eps/ps/ai/cdr/wmf/emf/xaml via output_path and
  format.
- info: metadata and dimensions.
- validate: CLI structural check.
- list_formats: bounded list of supported formats (no disk read).

Parameters: operation, input_path, output_path, format.

### 5.2 inkscape_vector - Vector editing

The richest tool, with many operations. Parameters include operation, input_path,
output_path, object_id, object_ids, select_all, operation_type, barcode_data, preset_id, x,
y, threshold, dpi, units, shape, params, element_type, direction, amount, output_dir, lpe_id,
text, font_family, font_size, font_weight, fill, and text_anchor.

Key operations:
- trace_image: vectorize a raster via potrace.
- generate_barcode_qr: NOTE - currently a placeholder SVG, not a real scannable QR.
- text_to_path: convert text to paths.
- construct_svg: build an SVG from parameters.
- apply_boolean: union / difference / intersection / exclusion via operation_type.
- path_inset_outset, path_simplify, path_clean, path_combine, path_break_apart,
  object_to_path: path geometry transforms.
- optimize_svg, scour_svg: size and structure optimization.
- measure_object, query_document, count_nodes: geometry and document inspection.
- export_dxf: DXF export for laser/CAD.
- layers_to_files: split layers into separate files.
- fit_canvas_to_drawing: resize canvas to the drawing bounds.
- render_preview: render a preview image.
- generate_laser_dot: generate a laser calibration dot.
- object_raise, object_lower: z-order changes.
- set_document_units: change document units.

Note: create_mesh_gradient is present in the schema but raises NotImplementedError; use a
construct_svg approach instead.

### 5.3 inkscape_analysis - Read-only document inspection

Operations: quality, statistics, validate, objects, dimensions, structure. All operate on
input_path and are annotated read-only. Use these before mutating a document to understand
its size, object count, dimensions, and structural validity.

### 5.4 inkscape_render - Agent vision

Operations: export_preview, export_multi_dpi, get_document_summary.

- export_preview: render the document to PNG at a DPI in the validated range 36-1200.
- export_multi_dpi: batch render at multiple DPIs (default 96,192,384, or a CSV list).
- get_document_summary: stats plus validation snapshot, useful before a mutating operation.

Parameters: operation, input_path, output_path, dpi, dpi_list.

### 5.5 inkscape_validation - SVG QA

Operations: validate_svg, check_viewbox, check_stroke_fill, check_size_limits,
audit_web_svg, audit_svg_pack. Parameters include max_file_size_mb (10) and
max_dimension (16384). Use to gate an SVG before it is used on the web, packed, or handed
off.

### 5.6 inkscape_fleet - Cross-repo handoff

Operations: push_gimp_raster, stage_blender_svg, push_unity_sprite, build_layer_atlas,
run_pipeline, list_staging. Parameters include svg_path, png_path, project_path, output_dir,
staging_dir, dpi (192), gimp_url, blender_url, unity_url, import_to_blender, skip_validate,
skip_gimp, skip_blender_stage (default True), skip_unity, and target_platform. This is how
SVG art moves to the GIMP raster-QA pipeline, Blender SVG staging, Unity sprite import, and
layer atlases.

### 5.7 inkscape_fab_art - DXF / laser fabrication

Operations: list_presets, batch_dxf_export, batch_laser_dots, gazebo_schematic,
stage_for_robotics, run_fab_pipeline. Parameters include input_dir, output_dir, svg_path,
png_path, preset_id (default `gazebo_model_doc_192`), laser_preset_id
(`fab_calibration_grid`), staging_dir, robotics_url, gimp_url, dpi, and push_gimp. This
bridges vector art to laser-cutting and robotics schematic use.

### 5.8 inkscape_sim_art - Icon packs and simulation UI

Operations: list_presets, svg_pack_batch, build_icon_sheet, audit_svg_pack,
ai_svg_refine_loop, push_gimp_texture_sheet, stage_resonite_ui, run_sim_pipeline.
Parameters include input_dir, output_dir, output_path, template_id (default `ui_icon_128`),
layout (default 2x2), cell_size (128), margin_px, bleed_px, staging_dir, gimp_url,
target_platform, validate (True), goal, and dpi. Use for UI icon packs, texture sheets, and
Resonite/VRChat UI staging.

### 5.9 inkscape_system - Introspection and operations

Operations: status, execution_mode, help, diagnostics, version, config, list_extensions,
execute_extension, self_terminate.

- status: server and Inkscape availability.
- execution_mode: hands_in vs hands_off.
- diagnostics: subsystem health.
- config: current effective config.
- list_extensions: scan for .inx extension descriptors.
- execute_extension: run an extension (note the wrapper does not expose all params; prefer
  list_extensions first).
- self_terminate: shut the server down.

### 5.10 list_local_models

Read-only: discovers Ollama (`/api/tags`) and LM Studio (`http://127.0.0.1:1234/v1/models`)
model IDs. Returns empty lists with diagnostics if both are unreachable.

### 5.11 Agentic tools

Registered in initialize():

- generate_svg: a SEP-1577 multi-step loop using ctx.sample(); style_preset is one of
  geometric, organic, technical, heraldic, abstract; validates 64 <= width,height <= 8192;
  requires a sampling-capable client.
- agentic_inkscape_workflow: autonomous multi-step plan (max_steps=5).
- intelligent_vector_processing: batch SVG processing plan (strategy adaptive, parallel, or
  sequential).
- conversational_inkscape_assistant: read-only Q&A, graceful fallback when sampling is
  unavailable.

### 5.12 Heraldry

generate_heraldry with operation trumponia (implemented) or custom (not implemented).
Produces heraldic/crest SVG.

## 6. SVG Generation Pipeline

The REST endpoint POST /api/generate-svg drives a provider chain: Ollama (primary), then
Gemini, then Anthropic. The generated SVG is normalized and validated through the Inkscape
CLI (`--export-type=svg --export-plain-svg`) and saved to INKSCAPE_SAVE_DIR. The agentic
generate_svg tool is the MCP-side equivalent: it probes the server's capabilities, emits a
full SVG via sampling, saves it, and validates it.

## 7. Fleet Handoff Pipelines

Vector art from Inkscape feeds the rest of the fleet:

- push_gimp_raster: hand a PNG to GIMP for raster QA.
- stage_blender_svg: stage the SVG for Blender import.
- push_unity_sprite: import a sprite into Unity.
- build_layer_atlas: build a texture atlas from layers.
- fab pipeline: DXF export, laser dot grids, Gazebo schematics, robotics staging.
- sim pipeline: icon packs, texture sheets, Resonite/VRChat UI staging.

Each pipeline honors skip_* gates (skip_validate, skip_gimp, skip_blender_stage,
skip_unity) so you can run only the stages you have tooling for.

## 8. Safety and Scoping

- Execution gating: hands-off CLI runs are isolated via --batch-process; hands-in requires
  explicit INKSCAPE_GUI_WATCH=1 and a running GUI. When an output path is given,
  execute_actions always appends export-do.
- Subprocess safety: UTF-8 env (LANG/LC_ALL=C.UTF-8), process_timeout, kill-on-timeout, and
  --no-remote-resources to avoid external-resource hangs.
- Validation: config validators; validate_file_size against max_file_size_mb;
  allowed_directories (declared, not enforced in dispatch); render DPI range 36-1200; sim
  pack validate flag; skip_* gates on fleet/fab/sim pipelines.
- Tool annotations: readOnlyHint, destructiveHint, idempotentHint, and openWorldHint are set
  appropriately; analysis/validation/list_local_models are read-only.
- REST safety: /api/docs rejects non-.md paths, `..`, and leading `/`; CORS locked to
  localhost/Tauri/Tailscale origins.
- Honesty: operations that are placeholders or unimplemented return explicit errors or
  structured results rather than fabricated success. generate_barcode_qr is a placeholder
  (not a real scannable QR); create_mesh_gradient and heraldry custom raise or return
  not-implemented; execute_extension lacks full params on the wrapper.

## 9. SVG and Inkscape Domain Glossary

To use these tools well an agent should understand the core concepts the server manipulates.

- SVG: Scalable Vector Graphics, the XML-based format Inkscape edits. Text-based, so it is
  the natural interchange for AI-generated and AI-edited vector art.
- Document: a loaded .svg file, containing a root element, defs, layers, objects, and view
  box metadata.
- Layer: a named grouping container. SVG art is organized into layers; layers_to_files and
  build_layer_atlas operate on this structure.
- Path: a sequence of vector curves. Many vector operations (path_simplify, path_combine,
  path_break_apart, path_inset_outset, object_to_path, text_to_path) transform paths.
- Object: any element (path, rect, circle, text, group) that can be selected by object_id.
- ViewBox: the coordinate space and visible area of the document; check_viewbox and
  fit_canvas_to_drawing deal with it.
- DPI: dots per inch, the resolution at which a vector is rasterized on export. The render
  tool validates DPI within 36-1200.
- Potrace: the tracer used by trace_image to convert a raster bitmap into vector paths.
- Boolean operation: union, difference, intersection, or exclusion applied to overlapping
  objects (apply_boolean with operation_type).
- Export format: the output raster or document type (svg, pdf, png, jpeg, webp, eps, ps,
  ai, cdr, wmf, emf, xaml). inkscape_file convert handles these.
- DXF: a CAD interchange format for laser cutting and fabrication; export_dxf and the
  fab-art pipeline produce it.
- Hands-in vs hands-off: execution mode describing whether the user has the Inkscape GUI
  open for live edits (hands_in) or the server is driving the CLI headless (hands_off).
- Extension: an Inkscape add-on described by a .inx file; list_extensions scans for them.
- Style preset: a named aesthetic direction for SVG generation (geometric, organic,
  technical, heraldic, abstract) used by generate_svg. Each preset biases the generated
  artwork toward a particular visual language, from precise technical diagrams to flowing
  organic shapes.

## 10. Workflow Patterns

The server composes these tools into repeatable workflows:

- Ingest-and-normalize: load a source SVG (or import a raster), trace or convert it, then
  validate it before use. For a raster: trace_image to vectorize, then validate_svg.
- Edit-and-export: load, apply path/boolean/text operations, fit the canvas, then convert
  to the target format. For a laser job: export_dxf or the fab pipeline. For a web asset:
  optimize_svg or scour_svg then export_preview at the needed DPI.
- Generate-from-prompt: call generate_svg with a style_preset and dimensions; the server
  emits, saves, and validates the SVG. For conversational help, use
  conversational_inkscape_assistant.
- QA-gate-before-handoff: before handing an asset to another fleet server, run the
  validation tool (audit_web_svg / audit_svg_pack) and render a preview to confirm it looks
  right.
- Fleet handoff: push_gimp_raster (raster QA), stage_blender_svg (Blender), push_unity_sprite
  (Unity), build_layer_atlas (texture atlas), and the run_pipeline combined flow. Each
  honors skip_* gates.
- Fabrication: the fab pipeline exports DXF batches and laser dot grids, builds Gazebo
  schematics, and stages for robotics.
- Simulation UI: the sim pipeline builds icon packs, texture sheets, and stages UI for
  Resonite/VRChat.
- Hands-in collaboration: with INKSCAPE_GUI_WATCH=1, ask the user to tweak in the GUI while
  you run headless CLI exports against the same document; check execution_mode first.

## 11. Return Format and Error Handling

Each master tool returns a structured dict. On success it includes success (true),
operation, message, data, and execution_time_ms. On failure it includes success (false),
error, error_type, recovery hints, and next_steps. Agents should parse these fields rather
than assume the message text.

- Success data varies by operation: file.info returns metadata and dimensions;
  analysis.statistics returns dimensions, file size, and object count; render returns the
  output path and DPI(s); fleet/fab/sim pipelines return a per-step report.
- Validation tools return pass/fail booleans with specific findings (e.g. missing viewBox,
  stroke/fill issues, size limits).
- list_local_models returns available model IDs or empty lists with diagnostics when the
  local LLM is down.
- Honest failures: a placeholder (generate_barcode_qr) or unimplemented operation
  (create_mesh_gradient, heraldry custom, execute_extension without params) returns an
  explicit error/not-implemented rather than a fabricated success. Treat these as real
  conditions and route around them with a supported operation.

## 12. REST API Surface

The HTTP mode mounts a FastAPI REST bridge at `/api/*` alongside the MCP endpoint at
`/mcp`. Key routes:

- GET /api/health: liveness.
- POST /api/generate-svg: provider-chain SVG generation (Ollama -> Gemini -> Anthropic).
- POST /api/chat: SSE streaming chat (Ollama or LM Studio).
- GET /api/llm/providers: auto-discovery of LLM providers.
- GET /api/capabilities: capability string used by the agentic sampler.
- GET /api/skills, /api/help: discoverability.
- GET /api/logs (+ stats/export/clear): ring-buffer logging.
- GET /api/docs/{path}.md: documentation, path-traversal guarded (rejects non-.md, `..`,
  and leading `/`).
- GET /api/v1/diagnostics, GET /api/v1/system/info: diagnostics and system info.
- POST /v1/tool: MCP-tool bridge for the REST side.
- GET /metrics and /api/metrics: Prometheus metrics (standalone server on 9074).

CORS origins are restricted to localhost, the Tauri desktop shell, and Tailscale addresses.

## 13. Agentic Detail

The agentic tools use FastMCP sampling (ctx.sample) and therefore need a sampling-capable
client. They probe the server's capability string to learn which file/vector/heraldic/style
and generation approaches are available, then emit SVG and validate it.

- generate_svg(style_preset, width, height): the primary generator. style_preset is one of
  geometric, organic, technical, heraldic, abstract; width/height must be between 64 and
  8192. Saves to INKSCAPE_SAVE_DIR and validates the result.
- agentic_inkscape_workflow(goal): plans and executes up to 5 autonomous steps toward a
  vector-art goal.
- intelligent_vector_processing(batch, strategy): processes a batch of SVGs with an
  adaptive, parallel, or sequential strategy.
- conversational_inkscape_assistant(question): read-only Q&A over the server's capabilities;
  falls back gracefully when sampling is unavailable.

When sampling is unavailable, the tools degrade gracefully rather than failing hard.

## 14. Configuration Scenarios

- Claude Desktop (stdio): register the server with uv; use the .mcpb bundle or
  `uv run inkscape-mcp --mode stdio`.
- HTTP/remote (agent lab): `uv run inkscape-mcp --mode http --host 0.0.0.0 --port 11028`;
  clients connect to http://host:11028/mcp and the REST bridge at /api.
- Dual: `--mode dual` serves both.
- Local LLM: set OLLAMA_BASE_URL and OLLAMA_MODEL for local SVG generation; set
  GEMINI_API_KEY or ANTHROPIC_API_KEY for cloud fallback.
- Custom Inkscape path: set INKSCAPE_PATH if Inkscape is not on PATH.
- Hands-in: set INKSCAPE_GUI_WATCH=1 and keep the GUI open for collaborative editing.
- Save location: set INKSCAPE_SAVE_DIR to control where generated SVG files land.

## 15. Troubleshooting

- Inkscape not found or Access Denied: set INKSCAPE_PATH to the executable. The MS Store
  build is sandboxed and its inkscape.exe cannot run the CLI; install the classic desktop
  installer from https://inkscape.org/release/.
- CLI hangs: the server runs with --no-remote-resources and a process_timeout; a hang is
  killed and reported. Check for documents that reference external resources.
- Hands-in not detected: execution_mode stays hands_off unless INKSCAPE_GUI_WATCH=1 and a
  GUI Inkscape is running.
- Local LLM unreachable: generate_svg falls back to Gemini then Anthropic if keys are set;
  list_local_models reports which providers are down.
- Placeholder QR: generate_barcode_qr returns a placeholder SVG, not a scannable code. Use
  a dedicated QR tool or library for real scannable output.
- create_mesh_gradient not implemented: use construct_svg or build the gradient manually.
- Port confusion: code may report 11027/10873/10900/10899; use 11028 (MCP/REST), 11029
  (frontend), 11062 (logging) per the fleet registry.

## 16. FAQ

- Does this need Inkscape installed? Yes. The classic desktop installer is required; the
  MS Store build cannot run the CLI.
- Can it edit files I already have? Yes, via inkscape_file load, then the vector/analysis/
  render tools, then save or convert.
- Can it generate SVG from a prompt? Yes, via generate_svg (style_preset + dimensions) and
  the /api/generate-svg REST endpoint.
- Does it need an LLM? The core tools do not. Agentic tools (generate_svg, workflows) and
  REST chat need a local Ollama/LM Studio or a cloud key.
- What formats can it export? svg, pdf, png, jpeg, jpg, webp, eps, ps, ai, cdr, wmf, emf,
  and xaml via convert; DXF via export_dxf.
- How does it hand off to the fleet? push_gimp_raster, stage_blender_svg,
  push_unity_sprite, build_layer_atlas, and the fab/sim pipelines.
- Is generate_barcode_qr scannable? No, it is a placeholder SVG. Use a real QR tool.
- Hands-in or hands-off? The server reports execution_mode; hands-off is pure CLI,
  hands-in (INKSCAPE_GUI_WATCH=1) lets the user edit live in the GUI.
- Where does generated SVG go? To INKSCAPE_SAVE_DIR (default
  ~/Documents/inkscape-mcp/generated), normalized through the Inkscape CLI.

## 17. Version Notes

Package version 2.6.0. Deps: fastmcp>=3.4.4,<4, prefab-ui>=0.14, fastapi, uvicorn, httpx,
pillow, numpy, psutil, inkex, and optional prometheus-client. Some help/config strings still
reference older port numbers; treat the fleet registry (11028/11029/11062) and the current
package version as authoritative. The production entry point is `inkscape_mcp.main:main`.
