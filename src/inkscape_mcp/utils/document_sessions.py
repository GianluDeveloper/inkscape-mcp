"""Address separate Inkscape GUI documents without depending on desktop focus.

Each managed document owns a native --app-id-tag instance. The registry survives
MCP restarts, while the session bus is the authority on whether it is still open.
Existing untagged desktop windows are discoverable but never silently adopted.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..cli_wrapper import InkscapeCliWrapper
from ..cli_wrapper import InkscapeExecutionError

_SESSION_ID = re.compile(r"mcp_[0-9a-f]{32}\Z")
_REGISTRY_LOCK = asyncio.Lock()
_PROCESSES: dict[str, subprocess.Popen] = {}
_SVG_NS = "http://www.w3.org/2000/svg"
_EMPTY_SVG = (
    f'<svg xmlns="{_SVG_NS}" width="800" height="600" viewBox="0 0 800 600">'
    "<title>New MCP document</title></svg>\n"
)


def _registry_path() -> Path:
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return cache / "inkscape-mcp" / "document-sessions.json"


def _require_desktop() -> None:
    if not sys.platform.startswith("linux") or not shutil.which("gdbus"):
        raise InkscapeExecutionError(
            "Document sessions require Linux with gdbus and a desktop session"
        )


async def _process(args: list[str], timeout: float = 5) -> str:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except BaseException:
        await InkscapeCliWrapper._terminate_and_reap(proc)
        raise
    if proc.returncode:
        raise InkscapeExecutionError(
            stderr.decode(errors="replace").strip() or "D-Bus request failed"
        )
    return stdout.decode("utf-8", errors="replace")


async def _bus_names() -> set[str]:
    output = await _process(
        [
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.freedesktop.DBus",
            "--object-path",
            "/org/freedesktop/DBus",
            "--method",
            "org.freedesktop.DBus.ListNames",
        ]
    )
    return set(re.findall(r"'([A-Za-z0-9_.:-]+)'", output))


def _target(session_id: str) -> dict[str, Any]:
    if session_id == "desktop":
        return {
            "session_id": "desktop",
            "bus_name": "org.inkscape.Inkscape",
            "object_path": "/org/inkscape/Inkscape",
            "app_id_tag": "",
            "managed": False,
        }
    if not _SESSION_ID.fullmatch(session_id):
        raise ValueError("session_id must be 'desktop' or an ID returned by list_documents")
    return {
        "session_id": session_id,
        "bus_name": f"org.inkscape.Inkscape.{session_id}",
        "object_path": f"/org/inkscape/Inkscape/{session_id}",
        "app_id_tag": session_id,
        "managed": True,
    }


async def _windows(target: dict[str, Any]) -> list[int]:
    xml = await _process(
        [
            "gdbus",
            "introspect",
            "--session",
            "--dest",
            target["bus_name"],
            "--object-path",
            f"{target['object_path']}/window",
            "--xml",
        ]
    )
    root = ET.fromstring(xml)
    return sorted(
        int(node.get("name")) for node in root.findall("node") if node.get("name", "").isdecimal()
    )


def _load_registry(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        sessions = payload["sessions"]
        if payload.get("version") != 1 or not isinstance(sessions, dict):
            raise ValueError("unsupported registry format")
        if any(
            not _SESSION_ID.fullmatch(key) or not isinstance(value, dict)
            for key, value in sessions.items()
        ):
            raise ValueError("invalid session record")
        return sessions
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise InkscapeExecutionError(
            f"Cannot read document session registry {path}: {exc}"
        ) from exc


def _save_registry(path: Path, sessions: dict[str, dict[str, Any]]) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as file:
        temporary = Path(file.name)
        try:
            json.dump({"version": 1, "sessions": sessions}, file, indent=2)
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@asynccontextmanager
async def _registry():
    """Serialize launch/deduplication across tasks and separate MCP processes."""
    import fcntl

    async with _REGISTRY_LOCK:
        path = _registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_suffix(".lock").open("a", encoding="utf-8") as lock:
            deadline = asyncio.get_running_loop().time() + 35
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if asyncio.get_running_loop().time() >= deadline:
                        raise InkscapeExecutionError(
                            "Another document session operation is still in progress"
                        ) from None
                    await asyncio.sleep(0.05)
            try:
                yield path, _load_registry(path)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


async def get_session(session_id: str = "desktop", cli_wrapper=None, config=None) -> dict[str, Any]:  # noqa: ARG001 - uniform session API
    """Resolve an existing live session; never fall back to another document."""
    _require_desktop()
    target = _target(session_id or "desktop")
    if target["managed"]:
        async with _registry() as (_, sessions):
            entry = sessions.get(session_id)
        if entry is None:
            raise InkscapeExecutionError(f"Unknown document session: {session_id}")
        target = {**entry, **target}
    if target["bus_name"] not in await _bus_names():
        raise InkscapeExecutionError(f"Document session is not open: {target['session_id']}")
    windows = await _windows(target)
    if len(windows) != 1:
        raise InkscapeExecutionError(
            f"Document session {target['session_id']} has {len(windows)} windows; "
            "exactly one is required for unambiguous live editing"
        )
    return {
        **target,
        "window_id": windows[0],
        "window_path": f"{target['object_path']}/window/{windows[0]}",
    }


async def list_documents(cli_wrapper=None, config=None) -> dict[str, Any]:  # noqa: ARG001 - uniform session API
    """List live managed documents and the user's existing desktop instance."""
    _require_desktop()
    names = await _bus_names()
    async with _registry() as (_, sessions):
        entries = [(session_id, entry) for session_id, entry in sessions.items()]
    if "org.inkscape.Inkscape" in names:
        entries.insert(0, ("desktop", {}))
    documents = []
    for session_id, entry in entries:
        target = {**entry, **_target(session_id)}
        if target["bus_name"] not in names:
            process = _PROCESSES.pop(session_id, None)
            if process is not None:
                process.poll()
            continue
        try:
            windows = await _windows(target)
        except (InkscapeExecutionError, ET.ParseError):
            continue  # A user may close a window while enumeration is running.
        documents.append(
            {
                **target,
                "window_ids": windows,
                "window_count": len(windows),
                "editable": len(windows) == 1,
            }
        )
    return {"documents": documents, "count": len(documents), "registry_path": str(_registry_path())}


def _document_path(value: str, config) -> Path:
    if not value or not isinstance(value, str):
        raise ValueError("An SVG file path is required")
    path = Path(value).expanduser().resolve()
    if path.suffix.lower() != ".svg":
        raise ValueError("Managed documents require an .svg path to avoid import dialogs")
    allowed = getattr(config, "allowed_directories", None) or []
    if allowed and not any(
        path.is_relative_to(Path(base).expanduser().resolve()) for base in allowed
    ):
        raise ValueError("Document path is outside allowed_directories")
    return path


def _managed_process_running(session_id: str, entry: dict[str, Any]) -> bool:
    """Recognize a still-starting instance without trusting a potentially reused PID."""
    process = _PROCESSES.get(session_id)
    if process is not None and process.poll() is None:
        return True
    pid = entry.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        arguments = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    return f"--app-id-tag={session_id}".encode() in arguments


async def open_document(input_path: str, cli_wrapper=None, config=None) -> dict[str, Any]:  # noqa: ARG001 - uniform session API
    """Open a named SVG in one independently addressable Inkscape instance."""
    _require_desktop()
    if config is None or not config.inkscape_executable:
        raise InkscapeExecutionError("Inkscape CLI is unavailable; configure INKSCAPE_PATH first")
    path = _document_path(input_path, config)
    if not path.is_file():
        raise FileNotFoundError(f"SVG file does not exist: {path}")
    if not config.validate_file_size(path):
        raise ValueError("Document exceeds max_file_size_mb")
    content = path.read_text(encoding="utf-8")
    if "<!DOCTYPE" in content.upper() or "<!ENTITY" in content.upper():
        raise ValueError("SVG documents with DTD or entity declarations are unsupported")
    if ET.fromstring(content).tag != f"{{{_SVG_NS}}}svg":
        raise ValueError("Document root must be svg in the SVG namespace")

    async with _registry() as (registry_path, sessions):
        names = await _bus_names()
        for session_id, entry in sessions.items():
            target = {**entry, **_target(session_id)}
            if entry.get("input_path") == str(path) and target["bus_name"] in names:
                windows = await _windows(target)
                return {
                    **target,
                    "reused": True,
                    "window_ids": windows,
                    "window_count": len(windows),
                }
            if entry.get("input_path") == str(path) and _managed_process_running(session_id, entry):
                raise InkscapeExecutionError(
                    f"Document session {session_id} is still starting; use list_documents before retrying"
                )

        session_id = f"mcp_{uuid4().hex}"
        target = _target(session_id)
        logfile = registry_path.parent / f"{session_id}.log"
        entry = {
            "input_path": str(path),
            "pid": None,
            "created_at": time.time(),
            "log_path": str(logfile),
        }
        sessions[session_id] = entry
        # Persist the deterministic bus address before creating a GUI. If disk
        # writes fail, never leave a new window that the registry cannot find.
        _save_registry(registry_path, sessions)
        with logfile.open("ab") as log:
            process = subprocess.Popen(
                [
                    str(config.inkscape_executable),
                    f"--app-id-tag={session_id}",
                    "--with-gui",
                    str(path),
                ],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                env={
                    **os.environ,
                    "INKSCAPE_MCP_SESSION_ID": session_id,
                    # The constructor's version probe runs before CLI options.
                    # Give it the managed identity immediately to avoid races
                    # with other independently launched Inkscape processes.
                    "INKSCAPE_APP_ID_TAG": session_id,
                },
                start_new_session=True,
            )
        _PROCESSES[session_id] = process
        entry["pid"] = process.pid
        _save_registry(registry_path, sessions)
        deadline = asyncio.get_running_loop().time() + min(config.process_timeout, 30)
        while asyncio.get_running_loop().time() < deadline:
            if process.poll() is not None:
                raise InkscapeExecutionError(
                    f"Inkscape session {session_id} exited; inspect {logfile}"
                )
            if target["bus_name"] in await _bus_names():
                try:
                    windows = await _windows(target)
                    if len(windows) == 1:
                        return {
                            **entry,
                            **target,
                            "reused": False,
                            "window_ids": windows,
                            "window_count": 1,
                        }
                except (InkscapeExecutionError, ET.ParseError):
                    pass
            await asyncio.sleep(0.1)
        raise InkscapeExecutionError(
            f"Session {session_id} did not become ready; inspect {logfile}. "
            "Use list_documents before retrying; its window may still be starting."
        )


async def new_document(output_path: str, cli_wrapper=None, config=None) -> dict[str, Any]:
    """Create a new named SVG without replacing any existing file, then open it."""
    _require_desktop()
    if config is None or not config.inkscape_executable:
        raise InkscapeExecutionError("Inkscape CLI is unavailable; configure INKSCAPE_PATH first")
    path = _document_path(output_path, config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as file:
        temporary = Path(file.name)
        file.write(_EMPTY_SVG)
        file.flush()
        os.fsync(file.fileno())
    try:
        os.link(temporary, path)  # Atomic create-if-absent, including concurrent calls.
    finally:
        temporary.unlink(missing_ok=True)
    result = await open_document(str(path), cli_wrapper=cli_wrapper, config=config)
    return {**result, "created": True}
