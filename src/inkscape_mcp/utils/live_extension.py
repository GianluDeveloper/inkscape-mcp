"""Explicit installation and correlated invocation of the live SVG effect.

The undoable inkex transport is adapted conceptually from Aravind EV's MIT
inkscape-mcp project. The bundled standalone plugin retains its full MIT notice.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

from inkscape_mcp.cli_wrapper import InkscapeCliWrapper
from inkscape_mcp.cli_wrapper import InkscapeExecutionError

try:
    import fcntl
except ImportError:  # Windows can still import the server's other tools.
    fcntl = None

EXTENSION_ACTION = "org.inkscape.inkscape-mcp.edit-xml.noprefs"
MAX_BYTES = 10 * 1024 * 1024


def exchange_directory() -> Path:
    return (
        Path(os.getenv("XDG_CACHE_HOME", str(Path.home() / ".cache")))
        / "inkscape-mcp"
        / "live-extension"
    )


def extension_directory() -> Path:
    if profile := os.getenv("INKSCAPE_PROFILE_DIR"):
        return Path(profile).expanduser() / "extensions" / "inkscape_mcp_live"
    return (
        Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        / "inkscape"
        / "extensions"
        / "inkscape_mcp_live"
    )


def _atomic_write(path: Path, data: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".mcp-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def install_live_extension(config=None) -> dict:
    """Install only this bundled inspection/append effect; never called at startup."""
    del config  # Kept for the public install helper's configuration-compatible API.
    if not sys.platform.startswith("linux"):
        raise InkscapeExecutionError("The live extension bridge currently supports Linux desktops")
    destination = extension_directory()
    destination.mkdir(parents=True, exist_ok=True)
    changed = []
    for name in ("mcp_edit_xml.py", "mcp_edit_xml.inx"):
        payload = files("inkscape_mcp").joinpath("plugins", name).read_bytes()
        target = destination / name
        if not target.is_file() or target.read_bytes() != payload:
            _atomic_write(target, payload)
            target.chmod(0o755 if name.endswith(".py") else 0o644)
            changed.append(name)
    return {
        "success": True,
        "installed": True,
        "install_dir": str(destination),
        "files_changed": changed,
        "needs_restart": bool(changed),
        "action": EXTENSION_ACTION,
        "message": "Live SVG extension installed; restart Inkscape if it was already open"
        if changed
        else "Live SVG extension is already installed",
    }


@contextmanager
def _state_lock(folder: Path):
    if fcntl is None:
        raise InkscapeExecutionError("Live extension file locking requires Linux")
    with (folder / "state.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


@asynccontextmanager
async def _client_lock(folder: Path):
    if fcntl is None:
        raise InkscapeExecutionError("Live extension file locking requires Linux")
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (folder / "client.lock").open("a") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


async def _activate(target: dict, timeout: float) -> None:
    bus_name = target.get("bus_name", "org.inkscape.Inkscape")
    object_path = target.get("object_path", "/org/inkscape/Inkscape")
    if not isinstance(bus_name, str) or not re.fullmatch(
        r"org\.inkscape\.Inkscape(?:\.[A-Za-z0-9_-]+)*", bus_name
    ):
        raise ValueError("Invalid Inkscape D-Bus service")
    if not isinstance(object_path, str) or not re.fullmatch(
        r"/org/inkscape/Inkscape(?:/[A-Za-z0-9_]+)*", object_path
    ):
        raise ValueError("Invalid Inkscape D-Bus object path")
    proc = await asyncio.create_subprocess_exec(
        "gdbus",
        "call",
        "--session",
        "--dest",
        bus_name,
        "--object-path",
        object_path,
        "--method",
        "org.gtk.Actions.Activate",
        EXTENSION_ACTION,
        "[]",
        "{}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        output, error = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (Exception, asyncio.CancelledError):
        await InkscapeCliWrapper._terminate_and_reap(proc)
        raise
    if proc.returncode:
        raise InkscapeExecutionError((error or output).decode(errors="replace").strip())


async def append_svg(svg_content: str, target: dict, timeout: float = 15.0) -> dict:
    """Invoke once; a timeout is an uncertain outcome and must never auto-retry."""
    if (
        not isinstance(svg_content, str)
        or not svg_content.strip()
        or len(svg_content.encode("utf-8")) > MAX_BYTES
    ):
        raise ValueError("A non-empty SVG document within 10 MiB is required")
    if not isinstance(target, dict) or not (target.get("root_id") or target.get("path")):
        raise ValueError("Expected document root_id or path is required")
    return await _request("append_svg", target, timeout, svg_content=svg_content)


async def inspect_document(target: dict, timeout: float = 15.0) -> dict:
    """Read live SVG and its native filename without returning XML to Inkscape.

    The caller must resolve a single-window target with get_session first.
    No previously known drawing identity is required; the SVG is never edited.
    """
    if not isinstance(target, dict):
        raise ValueError("Inspection requires a resolved document session")
    session_id = target.get("session_id")
    if not isinstance(session_id, str) or (
        session_id != "desktop" and not re.fullmatch(r"mcp_[a-f0-9]{32}", session_id)
    ):
        raise ValueError("Inspection requires an explicit valid document session ID")
    suffix = "" if session_id == "desktop" else "." + session_id
    path_suffix = "" if session_id == "desktop" else "/" + session_id
    if (
        target.get("bus_name") != "org.inkscape.Inkscape" + suffix
        or target.get("object_path") != "/org/inkscape/Inkscape" + path_suffix
    ):
        raise ValueError("Inspection target address differs from its document session")
    return await _request("inspect", target, timeout)


async def _request(operation: str, target: dict, timeout: float, **payload) -> dict:
    """Dispatch one scoped, correlated request; preserve the no-retry contract."""
    if not sys.platform.startswith("linux"):
        raise InkscapeExecutionError("The live extension bridge currently supports Linux desktops")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("Extension timeout must be finite and positive")
    folder = exchange_directory()
    session_id = target.get("session_id", "desktop")
    if session_id != "desktop":
        if not isinstance(session_id, str) or not re.fullmatch(r"mcp_[a-f0-9]{32}", session_id):
            raise ValueError("Invalid live extension session ID")
        # An effect delayed in another application must never claim this
        # application's next request, even when both documents share a name.
        folder = folder / "sessions" / session_id
    request_id = uuid4().hex
    request_path = folder / "request.json"
    result_path = folder / f"result-{request_id}.json"
    spec = {
        "request_id": request_id,
        "operation": operation,
        **payload,
        "target": target,
        "expires_at": time.time() + timeout,
    }
    activated = False
    activation = None
    try:
        async with asyncio.timeout(timeout):
            async with _client_lock(folder):
                with _state_lock(folder):
                    if request_path.exists():
                        # Do not overwrite an unresolved request from another
                        # process/version. It may already have been dispatched.
                        raise InkscapeExecutionError(
                            "Another live extension request is pending; inspect the active document"
                        )
                    _atomic_write(
                        request_path, json.dumps(spec, ensure_ascii=False).encode("utf-8")
                    )
                try:
                    activated = True
                    # GTK can acknowledge the D-Bus call only after the effect
                    # completes. Observe its correlated result independently;
                    # a slow acknowledgement must not hide a completed edit.
                    activation = asyncio.create_task(_activate(target, timeout))
                    while True:
                        if result_path.is_file():
                            result = json.loads(result_path.read_text(encoding="utf-8"))
                            if (
                                not isinstance(result, dict)
                                or result.get("request_id") != request_id
                            ):
                                raise InkscapeExecutionError(
                                    "Live extension returned an uncorrelated result"
                                )
                            if result.get("ok") is not True:
                                raise InkscapeExecutionError(
                                    result.get("error", "Live SVG extension failed")
                                )
                            return result
                        if activation.done():
                            activation.result()
                        await asyncio.sleep(0.05)
                finally:
                    if activation is not None:
                        if not activation.done():
                            activation.cancel()
                        await asyncio.gather(activation, return_exceptions=True)
                    with _state_lock(folder):
                        if request_path.is_file():
                            pending = json.loads(request_path.read_text(encoding="utf-8"))
                            if pending.get("request_id") == request_id:
                                request_path.unlink()
                        if not result_path.is_file():
                            _atomic_write(folder / f"cancel-{request_id}", b"cancelled\n")
    except TimeoutError as exc:
        detail = (
            "The live SVG extension did not confirm completion"
            if activated
            else "The live SVG extension is busy"
        )
        raise InkscapeExecutionError(
            f"{detail} within {timeout}s. Inspect the active document before retrying; no automatic retry was sent. "
            "Check that the extension is installed and Inkscape was restarted."
        ) from exc
