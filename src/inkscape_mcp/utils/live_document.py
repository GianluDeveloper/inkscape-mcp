"""Verified, undoable insertion into an existing Linux Inkscape desktop.

Native inkex effects keep unsaved content and Inkscape's undo history.
Managed session IDs route each workflow to its own application instance.
"""

from __future__ import annotations

import asyncio
import math
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

from inkscape_mcp.cli_wrapper import InkscapeCliWrapper
from inkscape_mcp.cli_wrapper import InkscapeExecutionError
from inkscape_mcp.utils.document_sessions import get_session
from inkscape_mcp.utils.live_extension import MAX_BYTES as MAX_INSERTION_BYTES
from inkscape_mcp.utils.live_extension import append_svg

SVG_NS = "http://www.w3.org/2000/svg"
MARKER = "data-inkscape-mcp"
DRAWABLE = {
    "rect",
    "circle",
    "ellipse",
    "path",
    "polygon",
    "polyline",
    "line",
    "text",
    "image",
    "use",
}
DRAWABLE_TAGS = {f"{{{SVG_NS}}}{name}" for name in DRAWABLE}


def configured_svg_limit(config) -> int:
    """Use the configured document limit, bounded like InkscapeConfig (1–1000 MiB)."""
    max_mb = getattr(config, "max_file_size_mb", 10)
    if (
        isinstance(max_mb, bool)
        or not isinstance(max_mb, (int, float))
        or (isinstance(max_mb, float) and not math.isfinite(max_mb))
        or max_mb <= 0
    ):
        max_mb = 10
    return int(min(max(max_mb, 1), 1000) * 1024 * 1024)


def validate_svg(svg_content: str, max_bytes: int = 10 * 1024 * 1024) -> ET.Element:
    if not isinstance(svg_content, str) or not svg_content.strip():
        raise ValueError("svg_content must contain a complete SVG document")
    if len(svg_content.encode("utf-8")) > max_bytes:
        raise ValueError(f"SVG exceeds the size limit of {max_bytes / (1024 * 1024):g} MiB")
    if "<!DOCTYPE" in svg_content.upper() or "<!ENTITY" in svg_content.upper():
        raise ValueError("DTD and entity declarations are not supported")
    try:
        root = ET.fromstring(svg_content)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid SVG XML: {exc}") from exc
    if root.tag != f"{{{SVG_NS}}}svg":
        raise ValueError("Root must be svg with the SVG namespace")
    return root


def build_test_svg(text: str = "Prova MCP OK") -> str:
    """Build editable geometry and text, escaping user text through XML."""
    if not isinstance(text, str) or not text.strip() or len(text) > 200:
        raise ValueError("text must contain between 1 and 200 characters")
    root = ET.Element(
        "svg",
        xmlns=SVG_NS,
        width="80%",
        height="40%",
        x="10%",
        y="20%",
        viewBox="0 0 480 220",
        preserveAspectRatio="xMidYMid meet",
    )
    ET.SubElement(root, "rect", x="10", y="10", width="460", height="200", rx="24", fill="#2878cc")
    label = ET.SubElement(
        root,
        "text",
        {
            "x": "240",
            "y": "122",
            "text-anchor": "middle",
            "font-family": "DejaVu Sans, sans-serif",
            "font-size": str(min(32, 680 / max(1, len(text)))),
            "fill": "#ffffff",
        },
    )
    label.text = text
    return ET.tostring(root, encoding="unicode")


async def _process(args: list[str], timeout: float = 10) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except BaseException:
        await InkscapeCliWrapper._terminate_and_reap(proc)
        raise
    if proc.returncode:
        raise InkscapeExecutionError(err.decode(errors="replace").strip() or f"{args[0]} failed")
    return out


async def _window_action(target: dict, action: str) -> None:
    await _process(
        [
            "gdbus",
            "call",
            "--session",
            "--dest",
            target["bus_name"],
            "--object-path",
            target["window_path"],
            "--method",
            "org.gtk.Actions.Activate",
            action,
            "[]",
            "{}",
        ]
    )


def _live_command(cli_wrapper, config, target: dict, action: str):
    args = [str(config.inkscape_executable), "--active-window"]
    if target.get("app_id_tag"):
        args.append(f"--app-id-tag={target['app_id_tag']}")
    args.extend(["--actions", action])
    return cli_wrapper._run_command(args, min(config.process_timeout, 15))


async def _snapshot(cli_wrapper, config, path: Path, target: dict) -> ET.Element:
    if any(c in str(path) for c in ";\r\n\x00"):
        raise ValueError("Temporary directory contains unsupported action delimiters")
    path.unlink(missing_ok=True)
    await _live_command(
        cli_wrapper,
        config,
        target,
        "export-type:svg;export-text-to-path:false;export-plain-svg:false;"
        "export-id:;export-id-only:false;export-area-page;"
        f"export-filename:{path};export-do",
    )
    limit = configured_svg_limit(config)
    # The remote GTK application can finish after its CLI sender has exited.
    for _ in range(50):
        if path.is_file() and path.stat().st_size:
            if path.stat().st_size > limit:
                raise ValueError(
                    f"Live document exceeds the configured size limit of {limit / (1024 * 1024):g} MiB"
                )
            try:
                return validate_svg(path.read_text(encoding="utf-8"), max_bytes=limit)
            except (ValueError, OSError):
                pass
        await asyncio.sleep(0.05)
    raise InkscapeExecutionError(
        "The active window did not produce a valid SVG snapshot; check the desktop session and dialogs"
    )


def _summary(root: ET.Element) -> dict:
    objects = [
        {
            "id": el.get("id"),
            "type": el.tag.rsplit("}", 1)[-1],
            **({"text": "".join(el.itertext())} if el.tag == f"{{{SVG_NS}}}text" else {}),
        }
        for el in root.iter()
        if el.tag in DRAWABLE_TAGS
    ]
    return {
        "document_id": root.get("id"),
        "width": root.get("width"),
        "height": root.get("height"),
        "viewBox": root.get("viewBox"),
        "objects": objects,
        "object_count": len(objects),
    }


async def active_document(cli_wrapper, config, session_id: str = "desktop") -> dict:
    """Inspect unsaved live content; no file-save or document-open action is used."""
    async with cli_wrapper._gui_lock:
        target = await get_session(session_id, cli_wrapper, config)
        with tempfile.TemporaryDirectory(prefix="inkscape-mcp-live-") as folder:
            root = await _snapshot(cli_wrapper, config, Path(folder) / "active.svg", target)
            return {
                **_summary(root),
                "svg_content": ET.tostring(root, encoding="unicode"),
                "session_id": target["session_id"],
                "verified": True,
            }


async def insert_svg(svg_content: str, cli_wrapper, config, session_id: str = "desktop") -> dict:
    """Run one undoable effect, then verify the new objects in the intended document."""
    limit = min(configured_svg_limit(config), MAX_INSERTION_BYTES)
    source = validate_svg(svg_content, limit)
    token = uuid4().hex
    count = 0
    for node in source.iter():
        if node.tag in DRAWABLE_TAGS:
            node.set(MARKER, token)
            count += 1
    if not count:
        raise ValueError("SVG must contain at least one drawable shape or text object")
    payload = ET.tostring(source, encoding="unicode")
    # Verification markers and namespace serialization can enlarge valid input.
    # Reject it before reading or activating a desktop window.
    if len(payload.encode("utf-8")) > MAX_INSERTION_BYTES:
        raise ValueError("Prepared live insertion exceeds the 10 MiB extension size limit")
    async with cli_wrapper._gui_lock:
        target = await get_session(session_id, cli_wrapper, config)
        with tempfile.TemporaryDirectory(prefix="inkscape-mcp-live-") as folder:
            path = Path(folder) / "active.svg"
            before = await _snapshot(cli_wrapper, config, path, target)
            before_ids = {el.get("id") for el in before.iter() if el.get("id")}
            identity = {
                **target,
                "root_id": before.get("id", ""),
                "docname": before.get(
                    "{http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd}docname", ""
                ),
            }
            effect = await append_svg(payload, identity, timeout=min(config.process_timeout, 30))
            if not effect.get("success", effect.get("ok", False)):
                raise InkscapeExecutionError(effect.get("error") or "Live extension failed")
            for _ in range(20):
                after = await _snapshot(cli_wrapper, config, path, target)
                added = [el for el in after.iter() if el.get(MARKER) == token]
                if len(added) >= count:
                    break
                await asyncio.sleep(0.1)
            else:
                raise InkscapeExecutionError(
                    "The extension ran but insertion was not verified. Inspect the target document "
                    "before retrying; the operation may already have changed it."
                )
            after_ids = {el.get("id") for el in after.iter() if el.get("id")}
            if after.get("id") != before.get("id") or not before_ids.issubset(after_ids):
                raise InkscapeExecutionError(
                    "The active document changed during insertion; inspect the window"
                )
            # Keep the inserted artwork visible. Failure here must not invite duplicate insertion.
            view_warning = ""
            try:
                await _window_action(target, "canvas-zoom-drawing")
            except Exception as exc:
                view_warning = str(exc)
            return {
                "verified": True,
                "document_id": after.get("id"),
                "window": target["window_path"],
                "session_id": target["session_id"],
                "inserted_ids": [el.get("id") for el in added],
                "inserted_count": len(added),
                "objects_before": _summary(before)["object_count"],
                "objects_after": _summary(after)["object_count"],
                "undo": "Use Edit > Undo in Inkscape to undo the insertion",
                "backend": "inkex-extension",
                "view_warning": view_warning,
            }
