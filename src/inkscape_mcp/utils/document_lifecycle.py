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
from inkscape_mcp.utils.live_extension import inspect_document

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
        if operation == "close_document" and not target["managed"]:
            raise ValueError(
                "close_document requires a managed session ID from open_document/new_document. "
                "Close ordinary desktop windows through Inkscape."
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

        limit = configured_svg_limit(config)
        if operation == "save_document":
            # DOCUMENT_PATH is supplied by Inkscape itself to the effect. A
            # basename from the SVG or a launch-time registry path cannot tell
            # us where a document is currently saved after a GUI Save As.
            inspection = await inspect_document(target, timeout=min(config.process_timeout, 30))
            native_path = inspection.get("active_document", {}).get("path", "")
            if not native_path or not Path(native_path).is_absolute():
                raise ValueError(
                    "This document has no native filename yet. Use Inkscape File > Save As "
                    "once, or create a named document with new_document. save_copy only writes "
                    "a copy and does not mark the open document as saved."
                )
            destination = document_sessions._document_path(native_path, config)
            if output_path and document_sessions._document_path(output_path, config) != destination:
                raise ValueError(
                    f"save_document saves the open document at {destination}. A different "
                    "output_path is not Save As: use save_copy for a copy, or change the "
                    "filename in Inkscape first. No save was sent."
                )
            before = validate_svg(inspection["svg_content"], max_bytes=limit)
            expected = drawing_fingerprint(before)
        else:
            destination = document_sessions._document_path(output_path, config)
        if not destination.parent.is_dir():
            raise ValueError(f"Destination directory does not exist: {destination.parent}")
        verified_content = None
        if operation == "save_copy":
            # Export directly beside the final path to retain linked image URLs
            # when the copy goes to a different directory. Commit atomically.
            with cli_wrapper._export_target(str(destination), suffix=".svg") as staged:
                before = await _snapshot(cli_wrapper, config, staged, target)
                expected = drawing_fingerprint(before)
            message = "Saved a verified copy. The open document's filename and unsaved state are unchanged"
        else:
            # Inspection emits no SVG back into Inkscape. Do not export the live
            # document here: GUI export state can change the document itself.
            await _window_action(target, "document-save")
            last_normalized_content = None
            normalized_expected = None
            for _ in range(50):
                try:
                    content = destination.read_text(encoding="utf-8")
                    saved = validate_svg(content, max_bytes=limit)
                    if drawing_fingerprint(saved) == expected:
                        break
                    if content != last_normalized_content:
                        # Saving an unmodified document is a native no-op.
                        # Its disk SVG may lack IDs/defaults added on load.
                        # Normalize both sides: the exporter also canonicalizes
                        # colors and default attributes. Keep the page extent
                        # and resource base; never export the live GUI here.
                        last_normalized_content = content
                        with _comparison_snapshot(destination) as normalized_path:
                            await cli_wrapper.export_file(
                                str(destination),
                                str(normalized_path),
                                export_type="svg",
                                export_area="page",
                            )
                            normalized = validate_svg(
                                normalized_path.read_text(encoding="utf-8"), max_bytes=limit
                            )
                        if normalized_expected is None:
                            with (
                                _comparison_snapshot(destination) as live_source,
                                _comparison_snapshot(destination) as live_normalized,
                            ):
                                live_source.write_text(inspection["svg_content"], encoding="utf-8")
                                await cli_wrapper.export_file(
                                    str(live_source),
                                    str(live_normalized),
                                    export_type="svg",
                                    export_area="page",
                                )
                                normalized_expected = drawing_fingerprint(
                                    validate_svg(
                                        live_normalized.read_text(encoding="utf-8"), max_bytes=limit
                                    )
                                )
                        if (
                            drawing_fingerprint(normalized) == normalized_expected
                            and destination.read_text(encoding="utf-8") == content
                        ):
                            verified_content = content
                            break
                except (OSError, ValueError):
                    pass
                await asyncio.sleep(0.1)
            else:
                raise InkscapeExecutionError(
                    "Native save could not be verified at the open document's path. "
                    "Check whether a save dialog is open or the drawing changed during saving."
                )
            message = "Saved the open Inkscape document natively and verified its contents on disk"
        content = destination.read_text(encoding="utf-8")
        saved = validate_svg(content, max_bytes=limit)
        if drawing_fingerprint(saved) != expected and content != verified_content:
            raise InkscapeExecutionError("Saved content differs from the live snapshot")
        if (
            operation == "save_document"
            and target["managed"]
            and target.get("input_path") != str(destination)
        ):
            async with document_sessions._registry() as (path, sessions):
                if session_id in sessions:
                    sessions[session_id]["input_path"] = str(destination)
                    document_sessions._save_registry(path, sessions)
        return {
            "message": message,
            "session_id": session_id,
            "output_path": str(destination),
            "verified": True,
            "saved_copy": operation == "save_copy",
            "live_document_saved": operation == "save_document",
            "bytes": destination.stat().st_size,
        }
