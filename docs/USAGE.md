# Usage examples

The JSON blocks below are arguments to the named MCP tool. Use absolute paths
that exist in the server's filesystem, and inspect the structured result after
each call. The [tool reference](TOOLS.md) describes every registered tool family.

## Check the connection

Call `inkscape_system`:

```json
{"operation": "status"}
```

A successful status response means the status request completed. Check
`data.inkscape.available` to determine whether the actual executable probe
succeeded. `diagnostics` checks server configuration; `active_document` tests
access to live drawing content.

## Construct editable SVG

Call `inkscape_vector`:

```json
{
  "operation": "construct_svg",
  "output_path": "/absolute/path/to/card.svg",
  "svg_content": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"480\" height=\"220\" viewBox=\"0 0 480 220\"><rect id=\"card\" x=\"10\" y=\"10\" width=\"460\" height=\"200\" rx=\"24\" fill=\"#2878cc\"/><text id=\"label\" x=\"240\" y=\"122\" text-anchor=\"middle\" font-size=\"32\" fill=\"white\">Hello Inkscape</text></svg>"
}
```

The result is a file with ordinary editable SVG shapes and text. No MCP sampling
or external model server is required. The optional `params` form accepts `body`
and optional `header`/`footer` instead of `svg_content`.

## Inspect and preview

Call `inkscape_analysis`:

```json
{"operation": "objects", "input_path": "/absolute/path/to/card.svg"}
```

Then `inkscape_render`:

```json
{
  "operation": "export_preview",
  "input_path": "/absolute/path/to/card.svg",
  "output_path": "/absolute/path/to/card-preview.png",
  "dpi": 144
}
```

Open the returned PNG artifact with your client's file/image viewer. This preview
reflects the file on disk. Live unsaved content must be inspected using the live
document workflow.

## Export PDF or PNG

Call `inkscape_file`:

```json
{
  "operation": "convert",
  "input_path": "/absolute/path/to/card.svg",
  "output_path": "/absolute/path/to/card.pdf",
  "format": "pdf"
}
```

For PNG, change the destination suffix and `format` to `png`. Call
`{"operation":"list_formats"}` to see this server's allowed export formats.
Managed exports validate the output before replacing an existing destination.

## Apply a boolean operation

Given a file containing at least two compatible shapes with IDs `shape-a` and
`shape-b`, call `inkscape_vector`:

```json
{
  "operation": "apply_boolean",
  "input_path": "/absolute/path/to/shapes.svg",
  "output_path": "/absolute/path/to/combined.svg",
  "operation_type": "union",
  "object_ids": ["shape-a", "shape-b"]
}
```

Use `select_all: true` only when the operation should include the entire drawing.
The other supported boolean types are `difference`, `intersection`, and
`exclusion`. Preserve the source under a separate path while experimenting.

## Verify live drawing

Start from the live setup in [Installation](../INSTALL.md#enable-live-drawing).
A desktop mutation must be an intentional part of the requested workflow.

Install the native effect with `{"operation":"install_live_extension"}` and
restart existing Inkscape windows first. For the ordinary single-window instance,
use the default `desktop` session; for managed drawings, pass the returned ID.

1. Call `inkscape_system` with `{"operation":"active_document","session_id":"desktop"}` and inspect
   the returned document/object details.
2. Call the same tool with `{"operation":"draw_test","session_id":"desktop","text":"Prova MCP OK"}`.
3. Check `data.verified` and the returned inserted object IDs.
4. Inspect the visible editable shape and text in Inkscape.
5. Call `active_document` again to confirm the label appears in the live SVG.
6. Use **Edit → Undo** in the target Inkscape window if the test artwork is no longer needed.

For custom artwork, pass a complete SVG document as `svg_content` and the target
`session_id` to `insert_svg`. The extension appends a nested SVG with its own
coordinates; it does not position the artwork at the mouse cursor. Escape XML text (`&amp;`, `&lt;`) and JSON strings correctly. The
`draw_test` helper escapes its `text` parameter itself.

If an insertion is unverified, inspect the document before repeating it. A
command failure after the desktop received the edit is not proof that no change
occurred. Avoid automatic retries that create duplicate artwork.

## Work with multiple documents

Install the extension before opening managed instances. Each managed document
gets an independent application ID, so several windows can remain open without
making the target depend on keyboard focus.

Create the first drawing with `inkscape_system`:

```json
{"operation": "new_document", "output_path": "/absolute/path/to/drawing-a.svg"}
```

Missing parent directories are created; the `.svg` file must not already exist.
Retain the returned `data.session_id`. To open an existing second drawing:

```json
{"operation": "open_document", "input_path": "/absolute/path/to/drawing-b.svg"}
```

Call `{"operation":"list_documents"}` to see both sessions. Reopening a path
that already has a live managed session reuses it. Use the IDs from responses in
the following requests; `mcp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa` below is an example,
not an ID to invent.

```json
{
  "operation": "draw_test",
  "session_id": "mcp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "text": "Document A"
}
```

Save that drawing to the path it was opened/created with:

```json
{"operation": "save_document", "session_id": "mcp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
```

To export a live SVG copy while keeping the window's filename unchanged:

```json
{
  "operation": "save_copy",
  "session_id": "mcp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "output_path": "/absolute/path/to/drawing-a-copy.svg"
}
```

`save_copy` is a verified snapshot export, not **Save As**. It also works for the
ordinary `desktop` session. `save_document` requires a managed session and
verifies the saved drawing against its live snapshot. If you manually changed
the GUI filename with Save As, the original session path may no longer match;
inspect the result rather than assuming it was saved there.

Finally, after saving:

```json
{"operation": "close_document", "session_id": "mcp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
```

Close uses Inkscape's native unsaved-changes guard. If a save dialog keeps the
window open, the tool reports that condition and does not discard edits. Save or
resolve the dialog, then retry intentionally. `close_document` does not close
unmanaged ordinary desktop windows.

Managed sessions remain discoverable after an MCP restart while their Inkscape
instances are open. Avoid deleting the session registry during ongoing work.

## Discover native Inkscape actions

Call `inkscape_system`:

```json
{"operation": "list_actions", "search": "select", "limit": 25, "offset": 0}
```

The action names come from the installed Inkscape CLI. Availability can differ
between headless operation and the live GUI. After checking the installed action,
normal live commands can be sent with `hands_in_command` and its `action` string.
The internal bridge actions `active-window-start` and `active-window-end` are
rejected because their lifecycle belongs to Inkscape.

## Use HTTP from a Python client

With the server on port `11028`, this read-only check uses FastMCP's client:

```python
import asyncio
from fastmcp import Client

async def main():
    async with Client("http://127.0.0.1:11028/mcp") as client:
        tools = await client.list_tools()
        print([tool.name for tool in tools])
        result = await client.call_tool("inkscape_system", {"operation": "status"})
        print(result.data)

asyncio.run(main())
```

Run it in the project's Python environment. This exercises the real MCP transport
without requiring a desktop MCP application or a language model.
