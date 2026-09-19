# Inkscape MCP agent reference

This project resource is served at `resource://inkscape/skills`. Use the running
server's `tools/list` response to discover exact arguments. Most tools group
operations behind an `operation` parameter and return structured results with
`success`, `message`, and operation-specific data.

The complete [tool reference](../../../docs/TOOLS.md) documents the public
contract. Internal Python helpers and installed Inkscape extensions are not
automatically exposed as MCP tools.

## Create and inspect SVG files

Use `inkscape_vector(operation="construct_svg")` with an absolute
`output_path` and complete `svg_content` containing the SVG namespace. This
works without client sampling or a separate model service.

Use `inkscape_analysis` operations `objects`, `dimensions`, `statistics`,
`structure`, `quality`, or `validate` to inspect a file. File operations read
saved content; they do not describe unsaved changes in an open window.

For PNG previews, call `inkscape_render(operation="export_preview")` with
`input_path`, `output_path`, and optional `dpi`. For format conversion, call
`inkscape_file(operation="convert")` with `input_path`, `output_path`, and
`format`. Discover supported export formats with `list_formats`.

## Draw in a live Inkscape window

The native live bridge requires a Linux desktop session, Inkscape, D-Bus, and
the bundled inkex effect. Call `inkscape_system` for this workflow:

1. `install_live_extension` installs the effect. Restart windows that were open
   during installation or an extension update.
2. `list_documents` lists available targets. `desktop` addresses the ordinary
   Inkscape instance only when it has exactly one document window.
3. For independent drawings, use `new_document(output_path=...)` or
   `open_document(input_path=...)`. Retain the returned `session_id`.
4. Inspect `active_document(session_id=...)`, then insert complete SVG with
   `insert_svg(svg_content=..., session_id=...)` or use
   `draw_test(text="Prova MCP OK", session_id=...)`.
5. Require the successful response's `data.verified` and inspect its object IDs.
   A failed or uncertain insertion must not be retried automatically.
6. `save_document(session_id=...)` saves a managed document to its named path.
   `save_copy(session_id=..., output_path=...)` exports a snapshot without
   changing the live document's filename.
7. `close_document(session_id=...)` closes a managed instance through Inkscape's
   guarded quit action; an unsaved-changes dialog is not force-dismissed.

Live edits remain undoable in Inkscape. `insert_svg` appends a nested SVG with
its own coordinates and a maximum 10 MiB payload. It does not save the document
automatically. The larger configured document limit applies to live inspection
and save verification.

Use [the examples](../../../docs/USAGE.md) for JSON calls and multi-window
workflows. Choose the target from the user's intended document, not from
whichever window happens to have keyboard focus.

## File edits and limitations

`inkscape_vector` supports path edits, boolean operations, text-to-path
conversion, queries, and exports. For boolean operations use `operation_type`
and `object_ids`, or `select_all` when the whole drawing is intended.

Preserve source files through separate output paths when the task calls for a
derived result. Check `success` and returned output paths after each operation.

Some enumerated legacy operations have limited contracts:
`generate_barcode_qr` produces a label rather than a scannable code;
`create_mesh_gradient` is unimplemented; `layers_to_files` needs a directory
argument not currently exposed by the MCP wrapper. Use the documented public
arguments instead of passing internal `**kwargs`.

## Other tool families

| Tools | Purpose |
| --- | --- |
| `inkscape_system` | Status, executable version, diagnostics, installed actions, live documents |
| `inkscape_validation` | SVG quality and size checks |
| `inkscape_fleet` | Explicit handoffs to other graphics applications |
| `inkscape_fab_art`, `inkscape_sim_art` | Fabrication, icon/sheet, and simulation asset workflows |
| `generate_heraldry` | Fixed `trumponia` SVG preset |
| `list_local_models`, `llm_ops` | Optional local model discovery and engine management |

`inkscape_system(operation="list_actions")` searches the installed CLI action
catalog. An action appearing there is not proof that it works in every headless
or live context.

## Optional client sampling

`generate_svg` accepts `description`, `style_preset`, `dimensions`,
`quality`, and optional generation controls; it returns generated SVG and a
saved path. The connected client must support MCP sampling, including
`sampling.tools`. FastMCP injects context; never provide `ctx` in JSON.

`agentic_inkscape_workflow`, `intelligent_vector_processing`, and
`conversational_inkscape_assistant` return plans or guidance. Execute requested
edits through the normal tools after checking their schemas. These planning
helpers do not automatically carry out all operations in their responses.

Client sampling and the dashboard's optional model-provider settings are separate
paths. If sampling is unavailable, use `construct_svg` and explicit tool calls.
See [sampling guidance](../../../docs/AI_SAMPLING.md).

## Connection checks

`inkscape_system(operation="status")` reports availability under
`data.inkscape.available`; a successful status request alone does not prove
Inkscape is available. Use `active_document` to check live desktop access.

The default transport is stdio. HTTP uses `/mcp` and defaults to port `11027`.
The optional dashboard setup explicitly uses backend `11028` and frontend
`11029`. Follow [Installation](../../../INSTALL.md) for dependencies and client
configuration.
