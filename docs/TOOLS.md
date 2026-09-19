# MCP tool reference

This reference describes tools registered by the main `inkscape-mcp` entry point.
The client's `tools/list` response is the authoritative schema for its running
server. Reconnect after an update to load changed operations and parameters.

Most tools group related actions behind an `operation` enum. Responses normally
contain `success`, `message`, and operation-specific `data`; some sampling and
integration tools use a different structured payload. Always check `success`
before using output paths or assuming an edit completed.

## Tool index

| Tool | Purpose |
| --- | --- |
| `inkscape_file` | File validation, metadata, saving, format conversion |
| `inkscape_vector` | SVG construction, path editing, queries, previews |
| `inkscape_analysis` | Document statistics and structural inspection |
| `inkscape_render` | PNG previews and multi-DPI exports |
| `inkscape_validation` | SVG quality and size checks |
| `inkscape_system` | Runtime status, installed actions, live desktop operations |
| `inkscape_fleet` | Handoffs to other graphics applications |
| `inkscape_fab_art` | Fabrication and robotics asset workflows |
| `inkscape_sim_art` | Icon packs, sheets, simulation/VR asset staging |
| `list_local_models` | Local model discovery |
| `llm_ops` | Local model engine management |
| `generate_heraldry` | Preset heraldic SVG |
| `generate_svg` | SVG generation using client sampling |
| `agentic_inkscape_workflow` | Sampling-assisted workflow planning |
| `intelligent_vector_processing` | Sampling-assisted processing plans |
| `conversational_inkscape_assistant` | Sampling-assisted vector graphics guidance |

The four sampling tools are registered when the optional sampling module loads.
Their availability in `tools/list` does not imply that the connected client
supports the required `sampling.tools` capability.

## `inkscape_file`

Parameters: `operation`, `input_path`, `output_path`, `format`.

| Operation | Behavior / relevant parameters |
| --- | --- |
| `load` | Validate and inspect a file at `input_path`; does not open a desktop window |
| `save` | Export `input_path` to `output_path` as SVG |
| `convert` | Export with `input_path`, `output_path`, and `format` |
| `info` | Read file/document metadata |
| `validate` | Check the source using Inkscape |
| `list_formats` | List allowed export formats; no input file needed |

Use explicit paths. `save` is a file-to-file operation, not a request to save the
unsaved desktop document. Call `list_formats` to discover this server's bounded
format list; installing an arbitrary Inkscape extension does not automatically
add it to this API.

## `inkscape_vector`

Common parameters: `operation`, `input_path`, `output_path`, `object_id`,
`object_ids`, `select_all`, `operation_type`, `threshold`, `dpi`, `svg_content`,
`params`, `element_type`. File edits require source and destination paths.

| Operation | Behavior / relevant parameters |
| --- | --- |
| `construct_svg` | Write validated XML using `output_path` and `svg_content`; alternatively `params.body` with optional `header`/`footer` |
| `trace_image` | Trace a bitmap with Inkscape's tracing action |
| `text_to_path` | Convert selected text in a file to paths |
| `apply_boolean` | `operation_type`: `union`, `difference`, `intersection`, `exclusion`; select using `object_ids` or `select_all` |
| `path_inset_outset` | Apply the handler's default inset operation; direction/amount are not currently public MCP parameters |
| `path_simplify` | Simplify paths; Inkscape uses its configured simplification preference |
| `path_clean` | Vacuum unused definitions during export |
| `path_combine` | Combine paths |
| `path_break_apart` | Break apart compound paths |
| `object_to_path` | Convert objects to paths |
| `optimize_svg` | Export SVG with definition cleanup |
| `scour_svg` | Export plain SVG with cleanup; this name does not imply a separate Scour process |
| `measure_object` | Query bounds using `object_id` |
| `query_document` | Query document/object bounds |
| `count_nodes` | Basic node estimate; not a complete path command parser |
| `export_dxf` | Request DXF export; depends on the installed Inkscape export support |
| `layers_to_files` | Internal handler requires an output directory not currently exposed by this MCP wrapper |
| `fit_canvas_to_drawing` | Resize the document canvas to drawing bounds |
| `render_preview` | Export a PNG at `dpi` |
| `generate_laser_dot` | Generate the default laser-dot SVG template |
| `object_raise` | Raise the object identified by `object_id` |
| `object_lower` | Lower the object identified by `object_id` |
| `set_document_units` | Apply the default unit setting; custom units are not currently exposed by this wrapper |
| `generate_barcode_qr` | Legacy placeholder: outputs a text label, not a scannable QR code |
| `create_mesh_gradient` | Enumerated but not implemented |

The Python module also contains object creation, inspection, text-style, font,
and LPE helpers that are not currently in the public MCP operation enum. Use
`construct_svg` for explicit shape/text construction and `insert_svg` for live
insertion. Do not infer agent-accessible operations from internal Python names.

## `inkscape_analysis`

Required parameters: `operation`, `input_path`.

| Operation | Purpose |
| --- | --- |
| `quality` | Heuristic quality assessment |
| `statistics` | Document statistics |
| `validate` | Document validation |
| `objects` | Object enumeration |
| `dimensions` | Document dimensions |
| `structure` | Structural inspection |

These operations inspect the file on disk. For unsaved desktop content, use
`inkscape_system` / `active_document`.

## `inkscape_render`

Parameters: `operation`, `input_path`, optional `output_path`, `dpi` (default
`96`), `dpi_list` (comma-separated values).

| Operation | Purpose |
| --- | --- |
| `export_preview` | PNG export for an agent's visual review; creates a temporary output path if omitted |
| `export_multi_dpi` | Render several DPI variants; default `96,192,384` |
| `get_document_summary` | Combine statistics and validation information |

The tool reports artifact paths. Whether images are displayed inline depends on
the MCP client and how it opens those files.

## `inkscape_validation`

Parameters: `operation`, `input_path`, `max_file_size_mb` (default `10`),
`max_dimension` (default `16384`).

| Operation | Purpose |
| --- | --- |
| `validate_svg` | Parse/validate SVG |
| `check_viewbox` | Check the root viewBox |
| `check_stroke_fill` | Check stroke/fill usage |
| `check_size_limits` | Check file size and dimensions |
| `audit_web_svg` | Combine checks for web assets |
| `audit_svg_pack` | Audit a directory passed as `input_path` |

Quality checks are not a browser sanitization service or a guarantee that an SVG
is safe in every embedding context.

## `inkscape_system`

| Operation | Purpose |
| --- | --- |
| `status` | Report server state and probe the Inkscape CLI version |
| `help` | General operation guidance |
| `diagnostics` | Configuration and wrapper readiness checks |
| `version` | Version/protocol information |
| `config` | Inspect loaded configuration |
| `execution_mode` | Report hands-in/hands-off guidance |
| `list_actions` | Read installed Inkscape action names/descriptions; filter with `search`, paginate with `limit` and `offset` |
| `hands_in_command` | Send semicolon-separated `action` commands to the application addressed by `session_id` |
| `install_live_extension` | Install the bundled inkex effect; reports whether existing windows need a restart |
| `list_documents` | List managed sessions and the ordinary desktop instance |
| `open_document` | Open existing SVG `input_path` in an addressed managed instance; reuse a live session for the same path |
| `new_document` | Create a new 800×600 SVG at `output_path` and open a managed instance; refuse overwrite |
| `active_document` | Read live SVG and object details from `session_id`, including unsaved content |
| `insert_svg` | Apply the native extension to `session_id` with complete `svg_content`; verify inserted objects |
| `draw_test` | Insert a rectangle and editable `text` label in `session_id`; default `Prova MCP OK` |
| `save_document` | Save a managed `session_id` to its original path and verify live/disk content |
| `save_copy` | Save live SVG from `session_id` to `output_path`; preserve the GUI filename |
| `close_document` | Request a managed session's native document close; never discard unsaved edits automatically |
| `list_extensions` | Discover `.inx` extension metadata |
| `execute_extension` | Reserved interface; generic extension execution is disabled |
| `self_terminate` | Request server shutdown; disconnects the client |

`list_actions` defaults to `limit=100`, `offset=0`, with a maximum page size of
`500`. Its source is the installed CLI's action catalog. Presence there does not
prove the action is available in a particular window, D-Bus interface, or
headless mode. Internal active-window lifecycle actions are rejected by the
command bridge.

`session_id` defaults to `desktop`. Use IDs returned by `open_document`,
`new_document`, or `list_documents` to target managed instances. The ordinary
`desktop` instance must have one window. `save_document` and `close_document`
require a managed session; `save_copy` also works with `desktop`.

`insert_svg` rejects malformed XML, DTD/entity declarations, empty artwork, and
oversized payloads. The native effect rejects object-ID collisions rather than
silently rebinding references to existing artwork. Use fresh IDs or omit them for
generation. The extension exchange has a 10 MiB payload limit in addition to
configured file limits. Inserted XML is appended as a nested SVG, preserving its
own coordinates/viewBox and editable elements.

The live workflow is documented in [Installation](../INSTALL.md) and
[Usage](USAGE.md). Desktop operations act on unsaved content, unlike file-based
exports. A mode hint or available CLI does not establish desktop connectivity.

## `inkscape_fleet`

| Operation | Purpose |
| --- | --- |
| `push_gimp_raster` | Hand a raster artifact to a GIMP service |
| `stage_blender_svg` | Stage SVG for Blender; optionally request import |
| `push_unity_sprite` | Stage/push a Unity sprite |
| `build_layer_atlas` | Build an atlas from layers |
| `run_pipeline` | Combine selected validation, staging, and handoff steps |
| `list_staging` | List staged artifacts |

Path parameters: `svg_path`, `png_path`, `project_path`, `output_dir`,
`staging_dir`. Endpoint parameters: `gimp_url`, `blender_url`, `unity_url`.
Controls: `dpi` (default `192`), `import_to_blender`, `skip_validate`, `skip_gimp`,
`skip_blender_stage` (default `true`), `skip_unity`, `target_platform`.

Remote steps require those applications/services and their own configuration.
Local staging does not imply a successful import into another application.

## `inkscape_fab_art`

| Operation | Purpose |
| --- | --- |
| `list_presets` | List fabrication presets |
| `batch_dxf_export` | Batch DXF conversion |
| `batch_laser_dots` | Generate laser-dot template assets |
| `gazebo_schematic` | Produce a schematic artifact |
| `stage_for_robotics` | Stage assets for robotics tooling |
| `run_fab_pipeline` | Run the selected fabrication workflow |

Parameters: `input_dir`, `output_dir`, `svg_path`, `png_path`, `preset_id`,
`laser_preset_id`, `staging_dir`, `robotics_url`, `gimp_url`, `dpi`, `push_gimp`.
Use `list_presets` instead of guessing preset IDs. Manufacturing suitability is
not established by a successful file conversion.

## `inkscape_sim_art`

| Operation | Purpose |
| --- | --- |
| `list_presets` | List simulation/UI presets |
| `svg_pack_batch` | Generate a pack from a template |
| `build_icon_sheet` | Assemble an SVG icon sheet |
| `audit_svg_pack` | Inspect a generated pack |
| `ai_svg_refine_loop` | Run the available refinement workflow |
| `push_gimp_texture_sheet` | Hand a texture sheet to GIMP |
| `stage_resonite_ui` | Stage UI assets for Resonite |
| `run_sim_pipeline` | Combine the simulation-art steps |

Parameters: `input_dir`, `output_dir`, `output_path`, `template_id`, `layout`,
`cell_size`, `margin_px`, `bleed_px`, `staging_dir`, `gimp_url`, `target_platform`,
`validate`, `goal`, `dpi`.

## Local model tools

`list_local_models` takes no arguments and queries local Ollama/LM Studio
endpoints. It returns model IDs and bounded diagnostics for unreachable services.

`llm_ops` accepts `operation`, `provider` (default `ollama`), `model`, and
`endpoint`:

| Operation | Purpose |
| --- | --- |
| `list_models` | Discover model IDs |
| `loaded` | Inspect resident Ollama models |
| `switch_model` | Evict other resident models and warm the requested Ollama `model` |
| `unload_all` | Evict resident Ollama models |
| `vram` | Inspect available GPU memory telemetry |

Model loading/unloading changes the local model service's state. Engine support
varies; unsupported combinations return structured errors.

## Heraldry

`generate_heraldry` accepts `operation` and optional `output_path`. The
`trumponia` operation writes a fixed preset SVG. `custom` is not implemented.
The default output is in the configured temporary directory.

## Sampling tools

These tools require the connected client's MCP sampling support, including
`sampling.tools`. `Context` is injected by FastMCP and is not a JSON parameter.
They do not require the dashboard's Ollama settings.

| Tool | Parameters and output |
| --- | --- |
| `generate_svg` | `description`, `style_preset`, `dimensions`, `quality`, `reference_svgs`, `post_processing`, `max_steps`; returns generated XML and a saved path |
| `agentic_inkscape_workflow` | Required `workflow_prompt`; optional `available_operations`, `max_steps`; returns a proposed workflow |
| `intelligent_vector_processing` | Required `documents`, `processing_goal`, `available_operations`; optional `processing_strategy`, `max_steps`; returns a processing plan |
| `conversational_inkscape_assistant` | Required `user_query`; optional `context_level`, `max_steps`; returns guidance |

The workflow/planning helpers consult capability probes; they do not automatically
execute every operation described in their response. Validate generated SVG and
use the registered editing tools to perform the desired changes. For client-
independent SVG creation, use `inkscape_vector` / `construct_svg`.

## Prompts, resources, and REST helpers

The server registers workflow prompts named:

- `prompt://inkscape/svg-file-workflow`
- `prompt://inkscape/vector-editing-workflow`
- `prompt://inkscape/analysis-workflow`
- `prompt://inkscape/sampling-agentic-workflow`
- `prompt://inkscape/heraldry-workflow`

Resources are `resource://inkscape/capabilities` and `resource://inkscape/skills`.
Use the live tool schema to resolve any difference between prose guidance and
available arguments.

The optional HTTP dashboard exposes additional Python/REST helpers, including
layer and animation operations. `inkscape_layers` and `inkscape_animation` are
not standalone tools registered by the main MCP entry point in this revision.
The REST bridge is implemented in [app.py](../src/inkscape_mcp/app.py).
