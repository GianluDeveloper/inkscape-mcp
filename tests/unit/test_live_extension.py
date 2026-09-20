"""Correlated extension transport and transactional SVG append regressions."""

import asyncio
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock

import inkex
import pytest
from lxml import etree

from inkscape_mcp.cli_wrapper import InkscapeExecutionError
from inkscape_mcp.plugins import mcp_edit_xml as plugin
from inkscape_mcp.utils import live_extension as bridge

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 20 10"><rect width="20" height="10"/><text x="2" y="5">Prova &amp; caffè</text></svg>'
ORIGINAL = (
    '<svg xmlns="http://www.w3.org/2000/svg" id="original"><circle id="existing" r="10"/></svg>'
)


def request(**overrides):
    return {
        "request_id": "1" * 32,
        "expires_at": time.time() + 30,
        "operation": "append_svg",
        "svg_content": SVG,
        "target": {"root_id": "original"},
        **overrides,
    }


def test_append_preserves_original_and_source_viewport():
    original = etree.fromstring(ORIGINAL)
    candidate, result = plugin.prepare_append(original, request())
    assert etree.tostring(original) == ORIGINAL.encode()
    assert etree.tostring(candidate[0]) == etree.tostring(original[0])
    inserted = candidate[-1]
    assert inserted.tag == f"{{{plugin.SVG_NS}}}svg"
    assert inserted.get("viewBox") == "0 0 20 10"
    assert inserted.get("width") == "200"
    assert inserted.find(f"{{{plugin.SVG_NS}}}text").text == "Prova & caffè"
    assert len(result["inserted_ids"]) == result["inserted_count"] == 2
    assert len({node.get("id") for node in candidate.iter()}) == len(list(candidate.iter()))


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"target": {"root_id": "other-document"}}, "differs"),
        ({"target": {"root_id": "original", "path": "/different.svg"}}, "differs"),
        ({"expires_at": time.time() - 1}, "expired"),
        ({"operation": "execute_python"}, "Only append_svg"),
        ({"request_id": "../../file"}, "request_id"),
        (
            {
                "svg_content": '<svg xmlns="http://www.w3.org/2000/svg"><rect xmlns="urn:foreign"/></svg>'
            },
            "drawable",
        ),
        (
            {"svg_content": '<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg/>'},
            "entity",
        ),
        (
            {"svg_content": '<svg xmlns="http://www.w3.org/2000/svg"><rect id="existing"/></svg>'},
            "ID",
        ),
        (
            {
                "svg_content": '<svg xmlns="http://www.w3.org/2000/svg"><rect id="same"/><text id="same"/></svg>'
            },
            "ID",
        ),
    ],
)
def test_invalid_requests_never_partly_mutate_original(changes, expected):
    original = etree.fromstring(ORIGINAL)
    with pytest.raises(ValueError, match=expected):
        plugin.prepare_append(original, request(**changes))
    assert etree.tostring(original) == ORIGINAL.encode()


def test_request_can_be_claimed_only_once(tmp_path):
    plugin.atomic_json(tmp_path / "request.json", request())
    claimed = plugin.claim_request(tmp_path)
    assert claimed[0]["request_id"] == "1" * 32
    assert claimed[1].is_file()
    assert plugin.claim_request(tmp_path) is None
    plugin.atomic_json(tmp_path / "request.json", request())
    assert plugin.claim_request(tmp_path) is None


@pytest.mark.parametrize("cancelled", [False, True])
def test_effect_reports_correlated_result_and_commits_only_valid_requests(
    tmp_path, monkeypatch, cancelled
):
    monkeypatch.setattr(plugin, "exchange_directory", lambda: tmp_path)
    spec = request()
    plugin.atomic_json(tmp_path / "request.json", spec)
    if cancelled:
        (tmp_path / f"cancel-{spec['request_id']}").touch()
    extension = plugin.McpEditXml()
    extension.document = inkex.load_svg(ORIGINAL)
    extension.effect()
    result = json.loads((tmp_path / f"result-{spec['request_id']}.json").read_text())
    assert result["request_id"] == spec["request_id"]
    assert result["ok"] is not cancelled
    assert len(extension.document.getroot()) == (1 if cancelled else 2)
    assert not list(tmp_path.glob("processing-*"))


def test_installation_is_explicit_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("INKSCAPE_PROFILE_DIR", str(tmp_path))
    destination = bridge.extension_directory()
    assert not destination.exists()
    installed = bridge.install_live_extension()
    assert installed["needs_restart"]
    assert len(installed["files_changed"]) == 2
    assert "Copyright (c) 2026 Aravind EV" in (destination / "mcp_edit_xml.py").read_text()
    assert "exec(" not in (destination / "mcp_edit_xml.py").read_text()
    assert not bridge.install_live_extension()["needs_restart"]


@pytest.fixture
def exchange(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "exchange_directory", lambda: tmp_path)
    return tmp_path


async def test_bridge_ignores_stale_results_and_matches_request_id(exchange, monkeypatch):
    (exchange / ("result-" + "0" * 32 + ".json")).write_text('{"ok": true}')

    async def activate(target, timeout):
        assert target["root_id"] == "original"
        assert timeout > 0
        spec = json.loads((exchange / "request.json").read_text())
        plugin.atomic_json(
            exchange / f"result-{spec['request_id']}.json",
            {"ok": True, "request_id": spec["request_id"]},
        )

    action = AsyncMock(side_effect=activate)
    monkeypatch.setattr(bridge, "_activate", action)
    result = await bridge.append_svg(SVG, {"root_id": "original"})
    assert result["ok"] is True
    assert result["request_id"] != "0" * 32
    assert not (exchange / "request.json").exists()
    action.assert_awaited_once()


async def test_bridge_rejects_a_result_with_wrong_request_id(exchange, monkeypatch):
    async def activate(_target, _timeout):
        spec = json.loads((exchange / "request.json").read_text())
        plugin.atomic_json(
            exchange / f"result-{spec['request_id']}.json", {"ok": True, "request_id": "0" * 32}
        )

    monkeypatch.setattr(bridge, "_activate", activate)
    with pytest.raises(InkscapeExecutionError, match="uncorrelated"):
        await bridge.append_svg(SVG, {"root_id": "original"})


async def test_completed_edit_does_not_wait_for_slow_dbus_acknowledgement(exchange, monkeypatch):
    reaped = asyncio.Event()

    async def activate(_target, _timeout):
        spec = json.loads((exchange / "request.json").read_text())
        plugin.atomic_json(
            exchange / f"result-{spec['request_id']}.json",
            {"ok": True, "request_id": spec["request_id"]},
        )
        try:
            await asyncio.Future()
        finally:
            reaped.set()

    action = AsyncMock(side_effect=activate)
    monkeypatch.setattr(bridge, "_activate", action)
    result = await bridge.append_svg(SVG, {"root_id": "original"}, timeout=0.5)
    assert result["ok"] is True
    assert reaped.is_set()
    action.assert_awaited_once()


async def test_timeout_cancels_pending_request_without_retry(exchange, monkeypatch):
    activate = AsyncMock()
    monkeypatch.setattr(bridge, "_activate", activate)
    with pytest.raises(InkscapeExecutionError, match="no automatic retry"):
        await bridge.append_svg(SVG, {"root_id": "original"}, timeout=0.02)
    activate.assert_awaited_once()
    assert not (exchange / "request.json").exists()
    assert len(list(exchange.glob("cancel-*"))) == 1
    assert plugin.claim_request(exchange) is None


async def test_cancelled_request_is_retracted_and_lock_released(exchange, monkeypatch):
    activated = asyncio.Event()

    async def activate(_target, _timeout):
        activated.set()

    monkeypatch.setattr(bridge, "_activate", activate)
    operation = asyncio.create_task(bridge.append_svg(SVG, {"root_id": "original"}))
    await activated.wait()
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert not (exchange / "request.json").exists()
    assert len(list(exchange.glob("cancel-*"))) == 1
    async with bridge._client_lock(exchange):
        pass


async def test_concurrent_clients_do_not_mix_requests(exchange, monkeypatch):
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    seen = []

    async def activate(_target, _timeout):
        spec = json.loads((exchange / "request.json").read_text())
        seen.append(spec["request_id"])
        if len(seen) == 1:
            first_started.set()
            await release_first.wait()
        plugin.atomic_json(
            exchange / f"result-{spec['request_id']}.json",
            {"ok": True, "request_id": spec["request_id"]},
        )

    monkeypatch.setattr(bridge, "_activate", activate)
    first = asyncio.create_task(bridge.append_svg(SVG, {"root_id": "original"}))
    await first_started.wait()
    second = asyncio.create_task(bridge.append_svg(SVG, {"root_id": "original"}))
    await asyncio.sleep(0.01)
    assert len(seen) == 1
    release_first.set()
    results = await asyncio.gather(first, second)
    assert len({result["request_id"] for result in results}) == 2


async def test_managed_service_is_used_by_native_activation(monkeypatch):
    process = AsyncMock()
    process.communicate.return_value = (b"()", b"")
    process.returncode = 0
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    target = {
        "bus_name": "org.inkscape.Inkscape.mcp_abc",
        "object_path": "/org/inkscape/Inkscape/mcp_abc",
    }
    await bridge._activate(target, 1)
    assert target["bus_name"] in spawn.call_args.args
    assert target["object_path"] in spawn.call_args.args
    assert bridge.EXTENSION_ACTION in spawn.call_args.args


@pytest.mark.parametrize("valid", [False, True])
def test_standalone_inkex_runner_outputs_only_valid_mutations(tmp_path, valid):
    cache = tmp_path / "cache"
    exchange = cache / "inkscape-mcp" / "live-extension"
    exchange.mkdir(parents=True)
    source = tmp_path / "drawing.svg"
    source.write_text(ORIGINAL, encoding="utf-8")
    spec = request(target={"root_id": "original" if valid else "different"})
    plugin.atomic_json(exchange / "request.json", spec)
    completed = subprocess.run(
        [sys.executable, str(Path(plugin.__file__)), str(source)],
        capture_output=True,
        check=True,
        timeout=10,
        env={**os.environ, "XDG_CACHE_HOME": str(cache)},
    )
    result = json.loads((exchange / f"result-{spec['request_id']}.json").read_text())
    assert result["ok"] is valid
    assert source.read_text(encoding="utf-8") == ORIGINAL
    if valid:
        rendered = etree.fromstring(completed.stdout)
        assert len(rendered) == 2
        assert rendered[-1].find(f"{{{plugin.SVG_NS}}}text").text == "Prova & caffè"
    else:
        assert completed.stdout == b""


async def test_requests_for_same_named_documents_are_isolated_by_application(exchange, monkeypatch):
    session_a = "mcp_" + "a" * 32
    session_b = "mcp_" + "b" * 32

    async def activate(target, _timeout):
        folder = exchange / "sessions" / target["session_id"]
        spec = json.loads((folder / "request.json").read_text())
        other = exchange / "sessions" / session_a
        assert plugin.claim_request(other) is None
        plugin.atomic_json(
            folder / f"result-{spec['request_id']}.json",
            {"ok": True, "request_id": spec["request_id"]},
        )

    monkeypatch.setattr(bridge, "_activate", activate)
    result = await bridge.append_svg(SVG, {"root_id": "original", "session_id": session_b})
    assert result["ok"]
    assert not (exchange / "request.json").exists()


def test_extension_rejects_another_application_even_when_document_ids_match(tmp_path, monkeypatch):
    session = "mcp_" + "a" * 32
    monkeypatch.setenv("INKSCAPE_MCP_SESSION_ID", session)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert (
        plugin.exchange_directory()
        == tmp_path / "inkscape-mcp" / "live-extension" / "sessions" / session
    )
    original = etree.fromstring(ORIGINAL)
    with pytest.raises(ValueError, match="application differs"):
        plugin.prepare_append(
            original, request(target={"root_id": "original", "session_id": "desktop"})
        )
    assert etree.tostring(original) == ORIGINAL.encode()


@pytest.mark.parametrize("native_path", ["", "/actual/drawing.svg"])
def test_inspection_reads_native_path_without_modifying_input(monkeypatch, native_path):
    monkeypatch.setenv("DOCUMENT_PATH", native_path)
    original = etree.fromstring(ORIGINAL)
    original.set(f"{{{plugin.SODIPODI_NS}}}docname", "/stale/export-name.svg")
    before = etree.tostring(original)
    result = plugin.prepare_inspection(
        original, request(operation="inspect", target={"session_id": "desktop"})
    )
    assert result["active_document"] == {
        "root_id": "original",
        "docname": "/stale/export-name.svg",
        "path": native_path,
        "path_source": "DOCUMENT_PATH",
    }
    assert result["svg_content"].encode() == before
    assert etree.tostring(original) == before


@pytest.mark.parametrize("tag", ["image", "use", "a"])
@pytest.mark.parametrize("attribute", ["href", plugin.XLINK_HREF])
def test_inspection_restores_temporary_links_without_changing_xml_base(
    tmp_path, monkeypatch, tag, attribute
):
    native_file = tmp_path / "project" / "drawing.svg"
    temporary_file = tmp_path / "ink_ext_temp.svg"
    monkeypatch.setenv("DOCUMENT_PATH", str(native_file))
    original = etree.fromstring(ORIGINAL)
    linked = etree.SubElement(original, f"{{{plugin.SVG_NS}}}{tag}")
    linked.set(attribute, "project/images/caff%C3%A8%20%231.png?size=2#part")
    linked.set("{http://www.w3.org/XML/1998/namespace}base", "unchanged/")
    linked.set("style", "fill:url(project/paint.svg#color)")
    before = etree.tostring(original)
    result = plugin.prepare_inspection(
        original,
        request(operation="inspect", target={"session_id": "desktop"}),
        str(temporary_file),
    )
    restored = etree.fromstring(result["svg_content"])[-1]
    assert restored.get(attribute) == "images/caff%C3%A8%20%231.png?size=2#part"
    assert restored.get("{http://www.w3.org/XML/1998/namespace}base") == "unchanged/"
    assert restored.get("style") == linked.get("style")
    assert etree.tostring(original) == before


@pytest.mark.parametrize(
    "href",
    [
        "",
        "#local",
        "?query",
        "/absolute.png",
        "//server/asset.png",
        "https://example.test/a",
        "data:image/png;base64,AA==",
        "FILE:linked.png",
        "FiLe:linked.png",
    ],
)
def test_native_serializer_exclusions_are_preserved(tmp_path, href):
    original = etree.fromstring(ORIGINAL)
    original[0].set("href", href)
    restored = plugin.restore_document_links(
        original, str(tmp_path / "temporary.svg"), str(tmp_path / "project" / "drawing.svg")
    )
    assert restored[0].get("href") == href


def test_link_restoration_matches_native_href_priority_and_unnamed_document(tmp_path):
    original = etree.fromstring(ORIGINAL)
    original[0].set("href", "project/linked%20image.png#part")
    original[0].set(plugin.XLINK_HREF, "already-native.png")
    restored = plugin.restore_document_links(original, str(tmp_path / "temporary.svg"), "")
    assert restored[0].get("href") == (tmp_path / "project" / "linked image.png").as_uri() + "#part"
    assert restored[0].get(plugin.XLINK_HREF) == "already-native.png"


def test_append_restores_existing_links_and_keeps_new_links_native(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCUMENT_PATH", str(tmp_path / "project" / "drawing.svg"))
    original = etree.fromstring(ORIGINAL)
    original[0].set(plugin.XLINK_HREF, (tmp_path / "project" / "existing.png").as_uri())
    before = etree.tostring(original)
    content = '<svg xmlns="http://www.w3.org/2000/svg"><image href="new.png"/></svg>'
    candidate, _ = plugin.prepare_append(
        original, request(svg_content=content), str(tmp_path / "temporary.svg")
    )
    assert candidate[0].get(plugin.XLINK_HREF) == "existing.png"
    assert candidate[-1][0].get("href") == "new.png"
    assert etree.tostring(original) == before


@pytest.mark.parametrize("operation", ["inspect", "append_svg"])
def test_standalone_effect_rebases_native_temporary_input_links(tmp_path, operation):
    cache = tmp_path / "cache"
    exchange = cache / "inkscape-mcp" / "live-extension"
    exchange.mkdir(parents=True)
    source = tmp_path / "ink_ext_temporary.svg"
    original = etree.fromstring(ORIGINAL)
    original[0].set(plugin.XLINK_HREF, "project/linked.png")
    source.write_bytes(etree.tostring(original))
    spec = request(operation=operation, target={"session_id": "desktop", "root_id": "original"})
    plugin.atomic_json(exchange / "request.json", spec)
    completed = subprocess.run(
        [sys.executable, str(Path(plugin.__file__)), str(source)],
        capture_output=True,
        check=True,
        timeout=10,
        env={
            **os.environ,
            "XDG_CACHE_HOME": str(cache),
            "INKSCAPE_MCP_SESSION_ID": "desktop",
            "DOCUMENT_PATH": str(tmp_path / "project" / "drawing.svg"),
        },
    )
    result = json.loads((exchange / f"result-{spec['request_id']}.json").read_text())
    assert result["ok"], result
    restored = etree.fromstring(
        result["svg_content"] if operation == "inspect" else completed.stdout
    )
    assert restored[0].get(plugin.XLINK_HREF) == "linked.png"
    assert source.read_bytes() == etree.tostring(original)
    if operation == "inspect":
        assert completed.stdout == b""


@pytest.mark.parametrize(
    "target,message",
    [
        ({}, "explicit document session"),
        ({"session_id": "mcp_" + "a" * 32}, "application differs"),
        ({"session_id": "../desktop"}, "Invalid live extension session"),
    ],
)
def test_inspection_rejects_missing_or_other_document_session(monkeypatch, target, message):
    monkeypatch.delenv("INKSCAPE_MCP_SESSION_ID", raising=False)
    monkeypatch.setenv("DOCUMENT_PATH", "/actual/drawing.svg")
    with pytest.raises(ValueError, match=message):
        plugin.prepare_inspection(
            etree.fromstring(ORIGINAL), request(operation="inspect", target=target)
        )


def test_inspection_never_guesses_path_from_document_metadata(monkeypatch):
    monkeypatch.delenv("DOCUMENT_PATH", raising=False)
    with pytest.raises(ValueError, match="native DOCUMENT_PATH"):
        plugin.prepare_inspection(
            etree.fromstring(ORIGINAL),
            request(operation="inspect", target={"session_id": "desktop"}),
        )


@pytest.mark.parametrize("cancelled", [False, True])
def test_inspection_suppresses_svg_even_if_loader_changes_serialization(
    tmp_path, monkeypatch, cancelled
):
    monkeypatch.setattr(plugin, "exchange_directory", lambda: tmp_path)
    monkeypatch.setenv("DOCUMENT_PATH", "")
    spec = request(operation="inspect", target={"session_id": "desktop"})
    plugin.atomic_json(tmp_path / "request.json", spec)
    if cancelled:
        (tmp_path / f"cancel-{spec['request_id']}").touch()
    extension = plugin.McpEditXml()
    extension.document = inkex.load_svg(ORIGINAL)
    extension.effect()
    # Even if inkex regards its parsed document as changed, inspect must not
    # send an SVG back to Inkscape's rebase path.
    stream = io.BytesIO()
    extension.save(stream)
    assert stream.getvalue() == b""
    result = json.loads((tmp_path / f"result-{spec['request_id']}.json").read_text())
    assert result["ok"] is not cancelled
    assert len(extension.document.getroot()) == 1


@pytest.mark.parametrize(
    "native_path",
    ["", "/actual/unsaved-changes.svg", pytest.param(None, id="reject-inkex-path-fallback")],
)
def test_standalone_inspection_writes_result_without_svg_stdout(tmp_path, native_path):
    cache = tmp_path / "cache"
    exchange = cache / "inkscape-mcp" / "live-extension"
    exchange.mkdir(parents=True)
    source = tmp_path / "ink_ext_temporary.svg"
    source.write_text(ORIGINAL, encoding="utf-8")
    spec = request(operation="inspect", target={"session_id": "desktop"})
    plugin.atomic_json(exchange / "request.json", spec)
    environment = {
        **os.environ,
        "XDG_CACHE_HOME": str(cache),
        "INKSCAPE_MCP_SESSION_ID": "desktop",
    }
    if native_path is None:
        environment.pop("DOCUMENT_PATH", None)
    else:
        environment["DOCUMENT_PATH"] = native_path
    completed = subprocess.run(
        [sys.executable, str(Path(plugin.__file__)), str(source)],
        capture_output=True,
        check=True,
        timeout=10,
        env=environment,
    )
    result = json.loads((exchange / f"result-{spec['request_id']}.json").read_text())
    if native_path is None:
        assert result["ok"] is False
        assert "native DOCUMENT_PATH" in result["error"]
        assert "active_document" not in result
        assert "svg_content" not in result
    else:
        assert result["ok"] is True
        assert result["active_document"]["path"] == native_path
        assert etree.fromstring(result["svg_content"]).get("id") == "original"
    assert completed.stdout == b""
    assert completed.stderr == b""
    assert source.read_text(encoding="utf-8") == ORIGINAL


@pytest.mark.parametrize("session_id", ["desktop", "mcp_" + "a" * 32])
async def test_inspection_bridge_requires_no_drawing_identity(exchange, monkeypatch, session_id):
    suffix = "" if session_id == "desktop" else "." + session_id
    path_suffix = suffix.replace(".", "/")
    target = {
        "session_id": session_id,
        "bus_name": "org.inkscape.Inkscape" + suffix,
        "object_path": "/org/inkscape/Inkscape" + path_suffix,
    }
    folder = exchange if session_id == "desktop" else exchange / "sessions" / session_id

    async def activate(address, _timeout):
        assert address == target
        spec = json.loads((folder / "request.json").read_text())
        assert spec["operation"] == "inspect"
        assert "svg_content" not in spec
        plugin.atomic_json(
            folder / f"result-{spec['request_id']}.json",
            {"ok": True, "request_id": spec["request_id"], "svg_content": ORIGINAL},
        )

    monkeypatch.setattr(bridge, "_activate", activate)
    result = await bridge.inspect_document(target)
    assert result["svg_content"] == ORIGINAL


@pytest.mark.parametrize(
    "target",
    [
        {},
        {"session_id": "desktop"},
        {
            "session_id": "mcp_" + "a" * 32,
            "bus_name": "org.inkscape.Inkscape",
            "object_path": "/org/inkscape/Inkscape",
        },
    ],
)
async def test_inspection_bridge_rejects_unresolved_target_before_dispatch(
    exchange, monkeypatch, target
):
    activate = AsyncMock()
    monkeypatch.setattr(bridge, "_activate", activate)
    with pytest.raises(ValueError, match="Inspection"):
        await bridge.inspect_document(target)
    activate.assert_not_awaited()
    assert not list(exchange.iterdir())
