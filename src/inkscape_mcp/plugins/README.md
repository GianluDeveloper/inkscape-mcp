# Native Inkscape extensions

This directory packages the native live-edit effect and four older experimental
extensions. Each extension pairs an `.inx` descriptor with an `inkex` Python
script. Public MCP operations are defined by the server's registered tool schema.

## Live SVG insertion

[`mcp_edit_xml.py`](mcp_edit_xml.py) and [its descriptor](mcp_edit_xml.inx)
implement the effect used by `inkscape_system` operations `insert_svg` and
`draw_test`. It appends editable SVG to an addressed live document, preserving
Inkscape's native undo history. The server verifies the inserted objects by
reading the live document back.

Install it through this explicit MCP call:

```json
{"operation": "install_live_extension"}
```

Restart existing Inkscape windows after installation or an extension update.
New managed instances launched afterward load the installed effect. The default
Linux destination is
`~/.config/inkscape/extensions/inkscape_mcp_live/`; `XDG_CONFIG_HOME` or
`INKSCAPE_PROFILE_DIR` can select another profile.

The bridge uses the current user's D-Bus session and a correlated, locked request
exchange. An insertion accepts at most 10 MiB, rejects conflicting element IDs,
and runs once. An uncertain result requires inspecting the document before
retrying. Ordinary server startup does not install the effect.

See [live setup](../../../INSTALL.md#enable-live-drawing),
[managed document examples](../../../docs/USAGE.md), and
[the live bridge implementation](../utils/live_extension.py).

## Other bundled scripts

These legacy extension sources are retained for development. They are not
installed by `install_live_extension` or automatically registered as MCP tools.

| Files | Current scope |
| --- | --- |
| `ag_batch_trace.py/.inx` | Experimental batch conversion; its color parameter is unused and it does not establish a reliable bitmap-tracing contract |
| `ag_color_quantize.py/.inx` | Maps path fill/stroke colors to a supplied or basic palette; dithering is not implemented |
| `ag_layer_animation.py/.inx` | Generates CSS from layers; requires a compatible SVG viewer for animation |
| `ag_unity_prep.py/.inx` | Experimental group, viewBox, and metadata transforms; visual preservation needs independent verification |

`extension_manager.py` is a legacy internal helper. Its presence does not imply
a general extension execution API. `inkscape_system(operation="list_extensions")`
reports installed descriptors; inspect the actual tool schema before attempting
an operation.

## Development and attribution

Validate the live bridge with the focused tests from the repository root:

```bash
uv run pytest tests/unit/test_live_extension.py tests/unit/test_live_system.py --no-cov -q
```

The explicit desktop acceptance procedure is in
[Development](../../../docs/DEVELOPMENT.md#tests). It creates and edits managed
test documents.

The native effect is adapted from
[Aravind EV's inkscape_mcp](https://github.com/aravindev/inkscape_mcp), with its
MIT notice retained in the source and [NOTICE.md](../../../NOTICE.md).
See [upstream integration notes](../../../docs/UPSTREAM_INTEGRATION.md) for the
relationship to that project and the Sandra Schipal base repository.
