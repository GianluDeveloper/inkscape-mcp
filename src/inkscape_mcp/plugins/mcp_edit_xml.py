#!/usr/bin/env python3
"""Inspect a live document or append SVG with correlated, undoable requests.

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
from urllib.parse import quote
from urllib.parse import unquote
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

import inkex
from lxml import etree

SVG_NS = "http://www.w3.org/2000/svg"
SODIPODI_NS = "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
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


def validate_target(root, target: dict, require_identity: bool = True) -> None:
    if not isinstance(target, dict):
        raise ValueError("Expected document target must be an object")
    if require_identity and not (target.get("root_id") or target.get("path")):
        raise ValueError("Expected document root_id or absolute path is required")
    expected_session = target.get("session_id", "desktop")
    if not require_identity and "session_id" not in target:
        raise ValueError("Inspection requires an explicit document session ID")
    if not isinstance(expected_session, str) or (
        expected_session != "desktop" and not re.fullmatch(r"mcp_[a-f0-9]{32}", expected_session)
    ):
        raise ValueError("Invalid live extension session ID")
    if expected_session != os.getenv("INKSCAPE_MCP_SESSION_ID", "desktop"):
        raise ValueError("Active application differs from the requested document session")
    actual = document_identity(root)
    if not require_identity:
        actual["path"] = os.environ.get("DOCUMENT_PATH", "")
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
    if spec.get("operation") not in {"append_svg", "inspect"}:
        raise ValueError("Only append_svg and inspect are supported by this extension")
    return request_id


def restore_document_links(root, input_file: str | None, native_path: str):
    """Undo Inkscape's temporary-file href rebasing on an independent clone.

    Inkscape's repr-io.cpp calls rebase_href_attrs for every element while
    serializing its extension input. Match that helper's attribute priority
    and exclusions. CSS URLs and xml:base are not rewritten by that serializer.
    Extension output is then merged into the original document without rebasing.
    """
    candidate = copy.deepcopy(root)
    if not input_file:
        return candidate
    input_uri = urlsplit(str(input_file))
    temporary_path = unquote(input_uri.path) if input_uri.scheme == "file" else str(input_file)
    temporary_directory = Path(temporary_path).absolute().parent
    native_directory = Path(native_path).parent if native_path else None
    for node in candidate.iter():
        if not isinstance(node.tag, str):
            continue
        key = "href" if "href" in node.attrib else XLINK_HREF
        href = node.get(key)
        if not href or href.startswith(("#", "?", "/")):
            continue
        # GLib's native serializer compares the original scheme case exactly;
        # urlsplit lowercases it, so retain that distinction before parsing.
        scheme = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", href)
        if scheme and scheme.group() != "file:":
            continue
        uri = urlsplit(href)
        if uri.scheme not in ("", "file") or uri.netloc:
            continue
        filename = unquote(uri.path, errors="surrogateescape")
        absolute = os.path.normpath(temporary_directory / filename)
        if native_directory is None:
            restored = urlsplit(Path(absolute).as_uri())
            value = urlunsplit(
                (restored.scheme, restored.netloc, restored.path, uri.query, uri.fragment)
            )
        else:
            relative = os.path.relpath(absolute, native_directory)
            path = quote(relative, safe="/@!$&'()*+,;=-._~", errors="surrogateescape")
            value = urlunsplit(("", "", path, uri.query, uri.fragment))
        node.set(key, value)
    return candidate


def prepare_inspection(root, spec: dict, input_file: str | None = None) -> dict:
    """Return live XML and Inkscape's native filename without changing the XML."""
    request_id = validate_request(spec)
    if spec["operation"] != "inspect":
        raise ValueError("An inspect request is required")
    validate_target(root, spec.get("target"), require_identity=False)
    # Inkscape supplies its actual SPDocument filename here, independently of
    # sodipodi:docname (which may be stale or contain only a basename).
    if "DOCUMENT_PATH" not in os.environ:
        raise ValueError("Inkscape did not provide the native DOCUMENT_PATH")
    path = os.environ["DOCUMENT_PATH"]
    if path and not Path(path).is_absolute():
        raise ValueError("Native DOCUMENT_PATH is not absolute")
    return {
        "ok": True,
        "request_id": request_id,
        "operation": "inspect",
        "active_document": {
            **document_identity(root),
            "path": path,
            "path_source": "DOCUMENT_PATH",
        },
        "svg_content": etree.tostring(
            restore_document_links(root, input_file, path), encoding="unicode"
        ),
    }


def prepare_append(root, spec: dict, input_file: str | None = None):
    """Validate everything on a clone so errors never partly mutate the document."""
    request_id = validate_request(spec)
    if spec["operation"] != "append_svg":
        raise ValueError("An append_svg request is required")
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
    # Only existing content was rebased into Inkscape's temporary input file.
    # The newly supplied SVG already uses the original document's base.
    candidate = restore_document_links(root, input_file, os.environ.get("DOCUMENT_PATH", ""))
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
    def run(self, *args, **kwargs):
        # inkex falls back to its temporary input filename when DOCUMENT_PATH
        # is absent. Record native provenance before that fallback runs.
        self._native_document_path_provided = "DOCUMENT_PATH" in os.environ
        return super().run(*args, **kwargs)

    def effect(self) -> None:
        self._emit_svg = False
        folder = exchange_directory()
        claimed_request = claim_request(folder)
        if claimed_request is None:
            return
        spec, claimed = claimed_request
        request_id = spec["request_id"]
        original = self.document.getroot()
        input_file = getattr(getattr(self, "options", None), "input_file", None)
        if not isinstance(input_file, (str, os.PathLike)):
            input_file = self.document.docinfo.URL
        result_path = folder / f"result-{request_id}.json"
        try:
            if spec.get("operation") == "inspect":
                if not getattr(
                    self, "_native_document_path_provided", "DOCUMENT_PATH" in os.environ
                ):
                    raise ValueError("Inkscape did not provide the native DOCUMENT_PATH")
                candidate = None
                result = prepare_inspection(original, spec, input_file)
            else:
                candidate, result = prepare_append(original, spec, input_file)
            with state_lock(folder):
                validate_request(spec)
                if (folder / f"cancel-{request_id}").exists():
                    raise ValueError("Request was cancelled before application")
                if candidate is not None:
                    self.document._setroot(candidate)
                atomic_json(result_path, result)
                self._emit_svg = candidate is not None
        except Exception as exc:
            self.document._setroot(original)
            atomic_json(result_path, {"ok": False, "request_id": request_id, "error": str(exc)})
        finally:
            claimed.unlink(missing_ok=True)

    def save(self, stream) -> None:
        # Native Script::_change_extension returns before document rebase when
        # stdout is empty. Inspect, rejected, and absent requests must therefore
        # never serialize the input SVG, even if inkex normalizes it on load.
        if getattr(self, "_emit_svg", False):
            super().save(stream)


if __name__ == "__main__":
    McpEditXml().run()
