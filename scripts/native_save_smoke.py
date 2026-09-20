#!/usr/bin/env python3
"""Verify native inspection/save state on a private Xvfb display and session bus.

Run: uv run python scripts/native_save_smoke.py --output-dir /tmp/inkscape-save-check
Requires Xvfb, xauth, dbus-run-session, xwininfo, xprop, and X11/XTest libraries.
The launcher always creates an isolated profile, cache, display, and D-Bus bus.
It never uses AT-SPI or contacts an existing Inkscape desktop.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import ctypes.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote
from urllib.parse import urlsplit

SVG_NS = "http://www.w3.org/2000/svg"
EMPTY_SVG = (
    f'<svg xmlns="{SVG_NS}" width="800" height="600" id="save-check">'
    '<rect id="original" x="10" y="10" width="50" height="50" fill="blue"/></svg>'
)


async def command(*args: str) -> str:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        output, error = await asyncio.wait_for(process.communicate(), 15)
    except BaseException:
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise RuntimeError(error.decode(errors="replace") or f"Command failed: {args[0]}")
    return output.decode(errors="replace")


async def windows() -> dict[str, str]:
    tree = await command("xwininfo", "-root", "-tree")
    return dict(re.findall(r'^\s*(0x[0-9a-fA-F]+)\s+"([^"\n]*)"', tree, re.MULTILINE))


async def title(window: str) -> str:
    properties = await command("xprop", "-id", window, "_NET_WM_NAME", "WM_NAME")
    found = re.search(r'^(?:_NET_WM_NAME|WM_NAME)\([^)]*\) = "(.*)"$', properties, re.MULTILINE)
    if not found:
        raise RuntimeError(f"Window {window} has no readable X11 title")
    return found.group(1)


async def wait_window(filename: str) -> str:
    for _ in range(150):
        matching = [window for window, name in (await windows()).items() if filename in name]
        if len(matching) == 1:
            return matching[0]
        await asyncio.sleep(0.1)
    raise AssertionError(f"No unique Inkscape window for {filename}: {await windows()}")


async def wait_dirty(window: str, expected: bool) -> str:
    for _ in range(100):
        value = await title(window)
        if ("*" in value) == expected:
            return value
        await asyncio.sleep(0.1)
    raise AssertionError(f"Expected dirty={expected}, actual title={value!r}")


async def wait_viewable(window: str) -> None:
    # XQueryTree sees a GTK dialog before it has been mapped. Focusing an
    # unmapped window raises BadMatch and the default Xlib handler exits.
    for _ in range(100):
        info = await command("xwininfo", "-id", window)
        if "Map State: IsViewable" in info:
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"Save As dialog {window} did not become viewable")


def type_save_path(window: str, path: Path) -> None:
    """Enter a Save As path using X11/XTest on the isolated display only."""
    x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
    xtest = ctypes.CDLL(ctypes.util.find_library("Xtst") or "libXtst.so.6")
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XSetInputFocus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
    x11.XStringToKeysym.restype = ctypes.c_ulong
    x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XKeysymToKeycode.restype = ctypes.c_uint
    x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    x11.XSetErrorHandler.argtypes = [ctypes.c_void_p]
    x11.XSetErrorHandler.restype = ctypes.c_void_p
    xtest.XTestFakeKeyEvent.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.c_ulong,
    ]
    display = x11.XOpenDisplay(None)
    if not display:
        raise RuntimeError("Cannot connect to the private X11 display")
    errors = []

    @ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    def handle_error(_display, _event):
        errors.append("X11 rejected a Save As input event")
        return 0

    previous_handler = x11.XSetErrorHandler(ctypes.cast(handle_error, ctypes.c_void_p))

    def key(name: str, down: bool) -> None:
        symbol = x11.XStringToKeysym(name.encode("ascii"))
        code = x11.XKeysymToKeycode(display, symbol)
        if not code:
            raise ValueError(f"Unsupported test key: {name}")
        xtest.XTestFakeKeyEvent(display, code, int(down), 0)

    def tap(name: str) -> None:
        key(name, True)
        key(name, False)

    try:
        x11.XSetInputFocus(display, int(window, 16), 2, 0)
        key("Control_L", True)
        tap("l")
        key("Control_L", False)
        key("Control_L", True)
        tap("a")
        key("Control_L", False)
        names = {"/": "slash", "-": "minus", ".": "period", "_": "underscore"}
        for character in str(path):
            if not (
                character.isascii()
                and (character.islower() or character.isdigit() or character in names)
            ):
                raise ValueError(
                    "Save As smoke paths must contain lowercase ASCII, digits, /, -, _, ."
                )
            shift = character == "_"
            if shift:
                key("Shift_L", True)
            tap(names.get(character, character))
            if shift:
                key("Shift_L", False)
        tap("Return")
        x11.XSync(display, False)
        if errors:
            raise RuntimeError(errors[0])
    finally:
        x11.XCloseDisplay(display)
        x11.XSetErrorHandler(previous_handler)


def text_labels(path: Path) -> list[str]:
    return ["".join(node.itertext()) for node in ET.parse(path).iter(f"{{{SVG_NS}}}text")]


def image_reference(root: ET.Element, document: Path) -> tuple[str, Path]:
    image = root.find(f"{{{SVG_NS}}}image")
    assert image is not None
    href = image.get("href") or image.get("{http://www.w3.org/1999/xlink}href")
    assert href
    address = urlsplit(href)
    assert address.scheme in {"", "file"} and address.netloc in {"", "localhost"}
    path = Path(unquote(address.path))
    return href, (path if path.is_absolute() else document.parent / path).resolve()


async def exercise(run_dir: Path) -> dict:
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    from PIL import Image

    from inkscape_mcp.utils.document_sessions import get_session
    from inkscape_mcp.utils.live_document import _window_action
    from inkscape_mcp.utils.live_extension import inspect_document

    if os.environ.get("INKSCAPE_MCP_NATIVE_SAVE_ISOLATED") != str(run_dir):
        raise RuntimeError("Use the launcher; an isolated display and bus are required")
    assert os.environ["INKSCAPE_PROFILE_DIR"] == str(run_dir / "profile")
    assert os.environ["GDK_BACKEND"] == "x11" and not os.environ.get("WAYLAND_DISPLAY")
    assert os.environ["NO_AT_BRIDGE"] == "1"
    records = []
    managed = []
    desktop = None
    report = {"success": False, "output_dir": str(run_dir), "checks": records}

    def checkpoint() -> None:
        (run_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    def record(check: str, **details) -> None:
        records.append({"check": check, "success": True, **details})
        checkpoint()
        print(check, flush=True)

    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "inkscape_mcp.main", "--mode", "stdio"],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=dict(os.environ),
        keep_alive=False,
    )
    checkpoint()
    try:
        async with Client(transport, timeout=60) as client:

            async def call(operation: str, *, expect_failure: bool = False, **arguments) -> dict:
                result = await client.call_tool(
                    "inkscape_system", {"operation": operation, **arguments}
                )
                data = result.data
                if bool(data.get("success")) == expect_failure:
                    raise AssertionError(f"Unexpected result from {operation}: {data}")
                return data if expect_failure else data["data"]

            await call("install_live_extension")
            for mode in ("desktop", "managed"):
                source = run_dir / f"{mode}-original.svg"
                source.write_text(EMPTY_SVG, encoding="utf-8")
                original = source.read_bytes()
                if mode == "desktop":
                    log = (run_dir / "desktop.log").open("wb")
                    try:
                        desktop = await asyncio.create_subprocess_exec(
                            shutil.which("inkscape") or "inkscape",
                            "--with-gui",
                            str(source),
                            stdout=log,
                            stderr=log,
                        )
                    finally:
                        log.close()
                    session_id = "desktop"
                else:
                    entry = await call("open_document", input_path=str(source))
                    managed.append(entry)
                    session_id = entry["session_id"]
                window = await wait_window(source.name)
                target = await get_session(session_id)
                clean_title = await wait_dirty(window, False)
                inspection = await inspect_document(target, timeout=30)
                assert inspection["active_document"]["path"] == str(source)
                assert inspection["active_document"]["path_source"] == "DOCUMENT_PATH"
                await call("active_document", session_id=session_id)
                assert await wait_dirty(window, False) == clean_title
                assert source.read_bytes() == original
                record(f"{mode}: inspection leaves document clean", title=clean_title)

                label = f"{mode} native save — caffè"
                await call("draw_test", session_id=session_id, text=label)
                dirty_title = await wait_dirty(window, True)
                assert source.read_bytes() == original
                await inspect_document(target, timeout=30)
                await wait_dirty(window, True)
                record(
                    f"{mode}: edit is dirty and inspection preserves dirty state", title=dirty_title
                )

                rejected_path = run_dir / f"{mode}-rejected.svg"
                rejected = await call(
                    "save_document",
                    session_id=session_id,
                    output_path=str(rejected_path),
                    expect_failure=True,
                )
                assert "No save was sent" in str(rejected)
                assert not rejected_path.exists() and source.read_bytes() == original
                await wait_dirty(window, True)
                record(f"{mode}: different output_path is rejected without saving")

                copied = run_dir / f"{mode}-copy.svg"
                copy_result = await call(
                    "save_copy", session_id=session_id, output_path=str(copied)
                )
                assert copy_result["verified"] and not copy_result["live_document_saved"]
                assert label in text_labels(copied) and source.read_bytes() == original
                await wait_dirty(window, True)
                record(f"{mode}: save_copy preserves dirty state and original file")

                saved = await call("save_document", session_id=session_id)
                assert saved["verified"] and saved["live_document_saved"]
                assert saved["output_path"] == str(source) and label in text_labels(source)
                await wait_dirty(window, False)
                await call("active_document", session_id=session_id)
                await wait_dirty(window, False)
                record(f"{mode}: native save updates disk and clears dirty state")

                if mode == "managed":
                    previous = source.read_bytes()
                    renamed = run_dir / "managed-renamed.svg"
                    known = set(await windows())
                    # GTK may keep the activation call pending until its modal
                    # file chooser closes. Dispatch once while driving X11.
                    save_as = asyncio.create_task(_window_action(target, "document-save-as"))
                    for _ in range(100):
                        dialogs = {
                            key: value
                            for key, value in (await windows()).items()
                            if key not in known
                        }
                        candidates = [
                            key for key, value in dialogs.items() if "save" in value.lower()
                        ]
                        if len(candidates) == 1:
                            break
                        await asyncio.sleep(0.1)
                    else:
                        raise AssertionError(f"Save As dialog not found: {await windows()}")
                    await wait_viewable(candidates[0])
                    type_save_path(candidates[0], renamed)
                    for _ in range(150):
                        if renamed.is_file() and renamed.name in await title(window):
                            break
                        await asyncio.sleep(0.1)
                    else:
                        raise AssertionError(f"Native Save As did not complete: {await windows()}")
                    # The document title and new file prove the GUI action
                    # completed even if its D-Bus acknowledgement timed out.
                    await asyncio.gather(save_as, return_exceptions=True)
                    registry = json.loads(
                        (run_dir / "cache/inkscape-mcp/document-sessions.json").read_text()
                    )
                    assert registry["sessions"][session_id]["input_path"] == str(source)
                    inspection = await inspect_document(target, timeout=30)
                    assert inspection["active_document"]["path"] == str(renamed)
                    extra_label = "After native Save As"
                    await call("draw_test", session_id=session_id, text=extra_label)
                    await wait_dirty(window, True)
                    saved = await call("save_document", session_id=session_id)
                    assert saved["output_path"] == str(renamed)
                    assert extra_label in text_labels(renamed) and source.read_bytes() == previous
                    await wait_dirty(window, False)
                    registry = json.loads(
                        (run_dir / "cache/inkscape-mcp/document-sessions.json").read_text()
                    )
                    assert registry["sessions"][session_id]["input_path"] == str(renamed)
                    record(
                        "managed: native Save As overrides stale registry and later save refreshes it"
                    )

            linked = run_dir / "linked.svg"
            Image.new("RGB", (10, 10), (20, 200, 40)).save(run_dir / "linked.png")
            linked.write_text(
                EMPTY_SVG.replace(
                    "<svg ", '<svg xmlns:xlink="http://www.w3.org/1999/xlink" '
                ).replace("</svg>", '<image xlink:href="linked.png" width="50" height="50"/></svg>')
            )
            entry = await call("open_document", input_path=str(linked))
            managed.append(entry)
            target = await get_session(entry["session_id"])
            window = await wait_window(linked.name)
            inspection = await inspect_document(target, timeout=30)
            root = ET.fromstring(inspection["svg_content"])
            (run_dir / "linked-inspection.svg").write_text(inspection["svg_content"])
            href, inspected_image = image_reference(root, linked)
            assert inspected_image == run_dir / "linked.png" and inspected_image.is_file(), (
                f"Inspection href {href!r} resolves to {inspected_image}, not the source linked.png"
            )
            await wait_dirty(window, False)
            original_linked = linked.read_bytes()
            untouched = await call("save_document", session_id=entry["session_id"])
            assert untouched["verified"] and linked.read_bytes() == original_linked
            await wait_dirty(window, False)
            record("linked image: native save of a clean document is verified without rewriting it")
            await call("draw_test", session_id=entry["session_id"], text="Linked image save")
            before_save = await inspect_document(target, timeout=30)
            (run_dir / "linked-before-save.svg").write_text(before_save["svg_content"])
            saved = await call("save_document", session_id=entry["session_id"])
            assert saved["verified"] and "Linked image save" in text_labels(linked)
            saved_href, saved_image = image_reference(ET.parse(linked).getroot(), linked)
            assert saved_image == inspected_image and saved_image.is_file(), (
                f"Saved href {saved_href!r} no longer resolves to {inspected_image}"
            )
            await wait_dirty(window, False)
            record(
                "linked image: inspection and native save preserve the referenced image",
                inspected_href=href,
                saved_href=saved_href,
            )

            for entry in reversed(managed):
                await call("close_document", session_id=entry["session_id"])
            target = await get_session("desktop")
            quitting = asyncio.create_task(
                _window_action({**target, "window_path": target["object_path"]}, "quit")
            )
            # The desktop can exit before D-Bus acknowledges native quit.
            await asyncio.wait_for(desktop.wait(), 15)
            await asyncio.gather(quitting, return_exceptions=True)
        report["success"] = True
        checkpoint()
        return report
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        checkpoint()
        raise
    finally:
        if desktop and desktop.returncode is None:
            desktop.terminate()
            await desktop.wait()
        for entry in managed:
            pid = entry.get("pid")
            if not pid:
                continue
            try:
                arguments = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
                if f"--app-id-tag={entry['session_id']}".encode() in arguments:
                    os.kill(pid, signal.SIGTERM)
            except (FileNotFoundError, ProcessLookupError):
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/inkscape-native-save-smoke"))
    parser.add_argument("--isolated-run", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.isolated_run:
        print(json.dumps(asyncio.run(exercise(args.isolated_run.resolve())), indent=2))
        return
    required = ["xvfb-run", "Xvfb", "xauth", "dbus-run-session", "xprop", "xwininfo", "inkscape"]
    missing = [name for name in required if not shutil.which(name)]
    if missing:
        parser.error("Missing executables: " + ", ".join(missing))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="native-save-", dir=args.output_dir.resolve()))
    environment = dict(os.environ)
    for key in [
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "DBUS_SESSION_BUS_ADDRESS",
        "DBUS_STARTER_ADDRESS",
        "DBUS_STARTER_BUS_TYPE",
        "AT_SPI_BUS_ADDRESS",
        "GTK_MODULES",
        "SESSION_MANAGER",
        "INKSCAPE_MCP_SESSION_ID",
        "INKSCAPE_APP_ID_TAG",
        "SELF_CALL",
    ]:
        environment.pop(key, None)
    for key, folder in {
        "INKSCAPE_PROFILE_DIR": "profile",
        "XDG_CONFIG_HOME": "config",
        "XDG_CACHE_HOME": "cache",
        "XDG_DATA_HOME": "data",
        "XDG_RUNTIME_DIR": "runtime",
    }.items():
        path = run_dir / folder
        path.mkdir(mode=0o700)
        environment[key] = str(path)
    environment.update(
        {
            "GDK_BACKEND": "x11",
            "NO_AT_BRIDGE": "1",
            "GTK_USE_PORTAL": "0",
            "GSETTINGS_BACKEND": "memory",
            "GIO_USE_VFS": "local",
            "LANG": "C.UTF-8",
            "FASTMCP_CHECK_FOR_UPDATES": "off",
            "INKSCAPE_MCP_NATIVE_SAVE_ISOLATED": str(run_dir),
        }
    )
    result = subprocess.run(
        [
            "xvfb-run",
            "-a",
            "-s",
            "-screen 0 1280x800x24",
            "dbus-run-session",
            "--",
            sys.executable,
            str(Path(__file__).resolve()),
            "--isolated-run",
            str(run_dir),
        ],
        env=environment,
        check=False,
    )
    print(f"Report: {run_dir / 'report.json'}", flush=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
