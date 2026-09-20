# Upstream integration and design choices

This repository builds on existing open-source Inkscape MCP work. Attribution and
implementation boundaries matter: inherited code, adapted code, and independent
implementations are different relationships.

## Projects consulted

| Project | Relationship |
| --- | --- |
| [sandraschi/inkscape-mcp](https://github.com/sandraschi/inkscape-mcp) | Base project from which this repository continues; retains the FastMCP server, SVG/file tooling, dashboard, and original MIT attribution |
| [aravindev/inkscape_mcp](https://github.com/aravindev/inkscape_mcp) | Studied for its native Inkscape extension and application/session approach; informs the live editing integration |

The reviewed aravindev revision is
[`5a53f76`](https://github.com/aravindev/inkscape_mcp/commit/5a53f76), under its MIT
license, copyright © 2026 Aravind EV. The base project's copyright is retained in
[LICENSE](../LICENSE). Adapted source must retain its upstream notices and be
identified in [NOTICE.md](../NOTICE.md).

## Why a native extension for live edits

A batch CLI export starts from a file on disk. It cannot, by itself, provide a
reliable editing model for an unsaved document already open in the GUI. The live
bridge needs to operate inside Inkscape's document lifecycle and preserve undo.

The extension approach sends a document edit request to an Inkscape/`inkex`
extension and lets Inkscape apply the resulting SVG. This provides a natural
place for exact-coordinate shape/text insertion and an undoable document change.
Request correlation and locking are needed so stale responses and concurrent
requests are not mistaken for the current edit.
Each managed application inherits a session identity and uses its own exchange
directory. A delayed extension invocation cannot claim a different window's
request, including when documents share the same filename and SVG root ID.

Native saves use the window's `document-save` action. The extension reads the
actual filename from Inkscape's `DOCUMENT_PATH`; a registry entry or SVG
`sodipodi:docname` can be stale after **Save As**. Read-only inspection returns
JSON through the exchange directory and emits no SVG to stdout, so Inkscape
does not apply a document edit. These details follow the native
[extension environment](https://gitlab.com/inkscape/inkscape/-/blob/INKSCAPE_1_4_4/src/extension/extension.cpp)
and [script effect lifecycle](https://gitlab.com/inkscape/inkscape/-/blob/INKSCAPE_1_4_4/src/extension/implementation/script.cpp).

A clipboard paste was explored as an initial bridge. It is native and undoable,
but introduces desktop clipboard ownership, focus, insertion position, and
session-specific timing dependencies. The extension integration is intended to
make normal live insertion independent of these clipboard assumptions.

## Document and window targeting

When more than one window is open, selecting a target by focus alone is fragile.
Managed document sessions identify the Inkscape application instance used for a
workflow. Explicit document/session identifiers allow list, open, create, inspect,
save, and close procedures to address the intended drawing.

A managed session is not a claim that any unrelated pre-existing Inkscape process
can be controlled without discovery or session access. Desktop operations still
need the correct user session and should report unavailable or ambiguous targets.

## Installed action discovery

`inkscape_system` / `list_actions` independently implements installed-CLI action
discovery using a read-only command, filtering, and bounded pagination. It does
not copy the upstream implementation. Action catalog entries describe the CLI;
they are not an assertion that every action works through every D-Bus interface
or in headless mode.

## Validation and scope

The integration is developed on Ubuntu 26.04.1 LTS with Inkscape 1.4.4 and
Python 3.12.14. Public MCP schema tests, process cleanup/timeout checks, file
export regressions, and explicit desktop checks cover different boundaries.
The extension installation and managed-session procedures in
[Installation](../INSTALL.md) and [Usage](USAGE.md) describe the integrated API.
Windows/macOS live GUI parity is not inferred from the Linux implementation.

The integration preserves this repository's grouped MCP tools and file-based
workflows. It is not a wholesale merge of another project's server or a promise
that every feature described by either upstream is exposed in this API.
