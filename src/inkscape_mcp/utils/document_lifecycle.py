"""Native saves and non-destructive close operations for addressed documents."""

from __future__ import annotations

import asyncio
import copy
import tempfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path

from inkscape_mcp.cli_wrapper import InkscapeExecutionError
from inkscape_mcp.utils import document_sessions
from inkscape_mcp.utils.live_document import _snapshot
from inkscape_mcp.utils.live_document import _window_action
from inkscape_mcp.utils.live_document import configured_svg_limit
from inkscape_mcp.utils.live_document import validate_svg

SODIPODI = "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
INKSCAPE = "http://www.inkscape.org/namespaces/inkscape"


def drawing_fingerprint(root: ET.Element) -> str:
    """Compare saved content while ignoring filename/export and viewport hints."""
    root = copy.deepcopy(root)
    root.attrib.pop(f"{{{SODIPODI}}}docname", None)
    root.attrib.pop(f"{{{INKSCAPE}}}version", None)

    def normalize(node, inside_text=False):
        text_content = inside_text or node.tag == "{http://www.w3.org/2000/svg}text"
        for key in list(node.attrib):
            if key.startswith(f"{{{INKSCAPE}}}export-"):
                del node.attrib[key]
        if node.tag == f"{{{SODIPODI}}}namedview":
            for key in list(node.attrib):
                local = key.rsplit("}", 1)[-1]
                if local in {"zoom", "cx", "cy", "current-layer"} or local.startswith("window-"):
                    del node.attrib[key]
        # Inkscape pretty-print indentation is not drawing data; text content is.
        if not text_content and node.text and not node.text.strip():
            node.text = None
        for child in node:
            normalize(child, text_content)
            if not text_content and child.tail and not child.tail.strip():
                child.tail = None

    normalize(root)
    return ET.canonicalize(ET.tostring(root, encoding="unicode"))


@contextmanager
def _comparison_snapshot(destination: Path):
    # SVG exports rebase linked resources relative to their output directory.
    # Use the destination's own directory, not a temporary subdirectory.
    with tempfile.NamedTemporaryFile(
        prefix="inkscape-mcp-snapshot-", suffix=".svg", dir=destination.parent, delete=False
    ) as temporary:
        path = Path(temporary.name)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


async def _closed(target: dict) -> bool:
    if target["bus_name"] not in await document_sessions._bus_names():
        return True
    try:
        return not await document_sessions._windows(target)
    except InkscapeExecutionError:
        # The application can disappear after ListNames but before introspect.
        if target["bus_name"] not in await document_sessions._bus_names():
            return True
        raise


async def document_lifecycle(operation, session_id, output_path, cli_wrapper, config) -> dict:
    if cli_wrapper is None or config is None:
        raise ValueError("Inkscape CLI is not configured")
    if operation not in {"save_document", "save_copy", "close_document"}:
        raise ValueError(f"Unknown document lifecycle operation: {operation}")
    async with cli_wrapper._gui_lock:
        target = await document_sessions.get_session(session_id, cli_wrapper, config)
        if operation != "save_copy" and not target["managed"]:
            raise ValueError(
                f"{operation} requires a managed session ID. Use save_copy for an existing desktop "
                "document, or open_document/new_document for independently addressed workflows."
            )
        if operation == "close_document":
            # Closing the last document creates a new blank document in the same
            # Inkscape window. The managed app owns exactly one window, so use
            # its guarded quit action: it asks before discarding unsaved changes.
            # Never use quit-immediate/window-close, which bypass that guard.
            application = {**target, "window_path": target["object_path"]}
            try:
                await _window_action(application, "quit")
            except InkscapeExecutionError:
                if not await _closed(target):
                    raise
            for _ in range(40):
                if await _closed(target):
                    break
                await asyncio.sleep(0.05)
            else:
                raise InkscapeExecutionError(
                    "The window is still open, possibly waiting for an unsaved-changes dialog. "
                    "Save the document and close it again; no changes were discarded."
                )
            async with document_sessions._registry() as (path, sessions):
                sessions.pop(session_id, None)
                document_sessions._save_registry(path, sessions)
            process = document_sessions._PROCESSES.pop(session_id, None)
            if process is not None:
                process.poll()
            return {
                "message": "Closed the managed document",
                "session_id": session_id,
                "closed": True,
            }

        destination = document_sessions._document_path(
            output_path if operation == "save_copy" else target.get("input_path", ""), config
        )
        if not destination.parent.is_dir():
            raise ValueError(f"Destination directory does not exist: {destination.parent}")
        verified_content = None
        limit = configured_svg_limit(config)
        if operation == "save_copy":
            # Export directly beside the final path to retain linked image URLs
            # when the copy goes to a different directory. Commit atomically.
            with cli_wrapper._export_target(str(destination), suffix=".svg") as staged:
                before = await _snapshot(cli_wrapper, config, staged, target)
                expected = drawing_fingerprint(before)
            message = "Saved a verified copy of the live document"
        else:
            with _comparison_snapshot(destination) as snapshot:
                before = await _snapshot(cli_wrapper, config, snapshot, target)
                expected = drawing_fingerprint(before)
                await _window_action(target, "document-save")
                last_normalized_content = None
                for _ in range(50):
                    try:
                        content = destination.read_text(encoding="utf-8")
                        saved = validate_svg(content, max_bytes=limit)
                        if drawing_fingerprint(saved) == expected:
                            break
                        if content != last_normalized_content:
                            # Saving an unmodified document is a native no-op.
                            # Its disk SVG may lack IDs/namedview/defs added on
                            # load. Normalize a read-only copy with Inkscape to
                            # compare equivalent documents without overwriting.
                            last_normalized_content = content
                            with _comparison_snapshot(destination) as normalized_path:
                                await cli_wrapper.export_file(
                                    str(destination), str(normalized_path), export_type="svg"
                                )
                                normalized = validate_svg(
                                    normalized_path.read_text(encoding="utf-8"), max_bytes=limit
                                )
                            if (
                                drawing_fingerprint(normalized) == expected
                                and destination.read_text(encoding="utf-8") == content
                            ):
                                verified_content = content
                                break
                    except (OSError, ValueError):
                        pass
                    await asyncio.sleep(0.1)
                else:
                    raise InkscapeExecutionError(
                        "Native save could not be verified at the session's original path. "
                        "Check whether the GUI filename changed or a save dialog is open."
                    )
            message = "Saved the managed document and verified its contents on disk"
        content = destination.read_text(encoding="utf-8")
        saved = validate_svg(content, max_bytes=limit)
        if drawing_fingerprint(saved) != expected and content != verified_content:
            raise InkscapeExecutionError("Saved content differs from the live snapshot")
        return {
            "message": message,
            "session_id": session_id,
            "output_path": str(destination),
            "verified": True,
            "saved_copy": operation == "save_copy",
            "bytes": destination.stat().st_size,
        }
