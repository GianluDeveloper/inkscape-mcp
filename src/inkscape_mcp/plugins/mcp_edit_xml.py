#!/usr/bin/env python3
"""Append SVG through an undoable Inkscape effect, with request correlation.

Adapted from https://github.com/aravindev/inkscape_mcp (mcp_edit_xml.py).

MIT License

Copyright (c) 2026 Aravind EV

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import copy
import fcntl
import json
import math
import os
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import inkex
from lxml import etree

SVG_NS = "http://www.w3.org/2000/svg"
SODIPODI_NS = "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
MAX_BYTES = 10 * 1024 * 1024
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


def exchange_directory() -> Path:
    folder = (
        Path(os.getenv("XDG_CACHE_HOME", str(Path.home() / ".cache")))
        / "inkscape-mcp"
        / "live-extension"
    )
    session_id = os.getenv("INKSCAPE_MCP_SESSION_ID", "desktop")
    if session_id != "desktop":
        if not re.fullmatch(r"mcp_[a-f0-9]{32}", session_id):
            raise ValueError("Invalid live extension session ID")
        folder = folder / "sessions" / session_id
    return folder


@contextmanager
def state_lock(folder: Path):
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (folder / "state.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def atomic_json(path: Path, data: dict) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".result-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def document_identity(root) -> dict:
    docname = root.get(f"{{{SODIPODI_NS}}}docname") or ""
    path = docname if Path(docname).is_absolute() else ""
    return {"root_id": root.get("id") or "", "docname": docname, "path": path}


def validate_target(root, target: dict) -> None:
    if not isinstance(target, dict) or not (target.get("root_id") or target.get("path")):
        raise ValueError("Expected document root_id or absolute path is required")
    expected_session = target.get("session_id", "desktop")
    if expected_session != os.getenv("INKSCAPE_MCP_SESSION_ID", "desktop"):
        raise ValueError("Active application differs from the requested document session")
    actual = document_identity(root)
    for key in ("root_id", "docname", "path"):
        if key not in target:
            continue
        value = target[key]
        if not isinstance(value, str):
            raise ValueError(f"Expected document {key} must be a string")
        if key == "path" and value and not Path(value).is_absolute():
            raise ValueError("Expected document path must be absolute")
        if actual[key] != value:
            raise ValueError(f"Active document {key} differs from the requested document")


def validate_request(spec: dict) -> str:
    if not isinstance(spec, dict):
        raise ValueError("Request must be a JSON object")
    request_id = spec.get("request_id")
    if not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9]{32}", request_id):
        raise ValueError("Invalid request_id")
    expiry = spec.get("expires_at")
    if not isinstance(expiry, (float, int)) or not math.isfinite(expiry) or expiry <= time.time():
        raise ValueError("Request expired before it could be applied")
    if spec.get("operation") != "append_svg":
        raise ValueError("Only append_svg is supported by this extension")
    return request_id


def prepare_append(root, spec: dict):
    """Validate everything on a clone so errors never partly mutate the document."""
    request_id = validate_request(spec)
    validate_target(root, spec.get("target"))
    content = spec.get("svg_content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("A complete SVG document is required")
    if len(content.encode("utf-8")) > MAX_BYTES:
        raise ValueError("SVG exceeds the 10 MiB extension limit")
    if "<!DOCTYPE" in content.upper() or "<!ENTITY" in content.upper():
        raise ValueError("DTD and entity declarations are not supported")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False)
    source = etree.fromstring(content.encode("utf-8"), parser=parser)
    if source.tag != f"{{{SVG_NS}}}svg":
        raise ValueError("SVG root and namespace are required")
    drawable = [
        node
        for node in source.iter()
        if isinstance(node.tag, str)
        and etree.QName(node).namespace == SVG_NS
        and etree.QName(node).localname in DRAWABLE
    ]
    if not drawable:
        raise ValueError("SVG must contain drawable shape or text elements")
    existing_ids = {
        node.get("id") for node in root.iter() if isinstance(node.tag, str) and node.get("id")
    }
    inserted_ids = set()
    for index, node in enumerate(source.iter()):
        if not isinstance(node.tag, str):
            continue
        identifier = node.get("id")
        if identifier:
            if identifier in existing_ids or identifier in inserted_ids:
                raise ValueError(f"SVG object ID already exists or is duplicated: {identifier}")
        else:
            identifier = f"mcp_{request_id}_{index}"
            if identifier in existing_ids:
                raise ValueError("Generated object ID collides with the active document")
            node.set("id", identifier)
        inserted_ids.add(identifier)
    candidate = copy.deepcopy(root)
    # Preserve the source viewport/coordinate system as a nested SVG rather than
    # flattening children and silently changing their dimensions or positions.
    candidate.append(source)
    result = {
        "ok": True,
        "request_id": request_id,
        "operation": "append_svg",
        "active_document": document_identity(root),
        "inserted_ids": [node.get("id") for node in drawable],
        "inserted_root_id": source.get("id"),
        "inserted_count": len(drawable),
    }
    return candidate, result


def claim_request(folder: Path):
    with state_lock(folder):
        request_path = folder / "request.json"
        if not request_path.is_file():
            return None
        if request_path.stat().st_size > 2 * MAX_BYTES:
            raise ValueError("Extension request exceeds its size limit")
        spec = json.loads(request_path.read_text(encoding="utf-8"))
        request_id = spec.get("request_id") if isinstance(spec, dict) else None
        if not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9]{32}", request_id):
            raise ValueError("Invalid request_id")
        claimed = folder / f"processing-{request_id}.json"
        if claimed.exists() or (folder / f"result-{request_id}.json").exists():
            request_path.unlink(missing_ok=True)
            return None
        request_path.replace(claimed)
        return spec, claimed


class McpEditXml(inkex.EffectExtension):
    def effect(self) -> None:
        folder = exchange_directory()
        claimed_request = claim_request(folder)
        if claimed_request is None:
            return
        spec, claimed = claimed_request
        request_id = spec["request_id"]
        original = self.document.getroot()
        result_path = folder / f"result-{request_id}.json"
        try:
            candidate, result = prepare_append(original, spec)
            with state_lock(folder):
                validate_request(spec)
                if (folder / f"cancel-{request_id}").exists():
                    raise ValueError("Request was cancelled before application")
                self.document._setroot(candidate)
                atomic_json(result_path, result)
        except Exception as exc:
            self.document._setroot(original)
            atomic_json(result_path, {"ok": False, "request_id": request_id, "error": str(exc)})
        finally:
            claimed.unlink(missing_ok=True)


if __name__ == "__main__":
    McpEditXml().run()
