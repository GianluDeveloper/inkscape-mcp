"""Public MCP contracts and non-destructive validation for live document editing."""

import asyncio
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastmcp import Client

from inkscape_mcp.cli_wrapper import InkscapeExecutionError
from inkscape_mcp.main import InkscapeMCPServer
from inkscape_mcp.tools.system import inkscape_system
from inkscape_mcp.utils import live_document

SVG = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="20" height="10"/></svg>'


@pytest.fixture
def live_server():
    server = InkscapeMCPServer()
    server._register_portmanteau_tools()
    return server


@pytest.fixture
def live_config():
    return SimpleNamespace(inkscape_executable="inkscape", process_timeout=10, max_file_size_mb=1)


@pytest.mark.asyncio
async def test_live_operations_are_exposed_in_mcp_schema(live_server):
    async with Client(live_server.mcp) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}

    properties = tools["inkscape_system"].inputSchema["properties"]
    assert {
        "active_document",
        "insert_svg",
        "draw_test",
        "install_live_extension",
        "list_documents",
        "open_document",
        "new_document",
        "save_document",
        "save_copy",
        "close_document",
    } <= set(properties["operation"]["enum"])
    assert {"svg_content", "text", "session_id", "input_path", "output_path"} <= properties.keys()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["", " ", "\t\n", "; ;"])
async def test_blank_live_action_does_not_launch_inkscape(action):
    wrapper = AsyncMock()
    config = SimpleNamespace(inkscape_executable="inkscape", process_timeout=10)

    result = await inkscape_system(
        operation="hands_in_command", action=action, cli_wrapper=wrapper, config=config
    )

    assert result["success"] is False
    assert result["operation"] == "hands_in_command"
    assert result["message"]
    wrapper._execute_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        "",
        " ",
        "<svg>",
        "<html/>",
        "<svg/>",
        '<svg xmlns="http://www.w3.org/2000/svg"/>',
        '<svg xmlns="http://www.w3.org/2000/svg"><text xmlns="urn:foreign">Invisible</text></svg>',
        '<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>',
        '<!DOCTYPE svg [<!ENTITY text "expanded">]>'
        '<svg xmlns="http://www.w3.org/2000/svg"><text>&text;</text></svg>',
    ],
)
async def test_invalid_live_svg_is_rejected_before_desktop_access(
    monkeypatch, live_config, content
):
    subprocess = AsyncMock(side_effect=AssertionError("Invalid SVG must not access the desktop"))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", subprocess)
    wrapper = AsyncMock()

    with pytest.raises(ValueError):
        await live_document.insert_svg(content, wrapper, live_config)

    subprocess.assert_not_awaited()
    wrapper._run_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_live_svg_size_limit_is_checked_before_desktop_access(monkeypatch, live_config):
    subprocess = AsyncMock(side_effect=AssertionError("Oversized SVG must not access the desktop"))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", subprocess)
    content = SVG.replace("<rect", "<!--" + "a" * (1024 * 1024) + "--><rect")

    with pytest.raises(ValueError, match="size limit"):
        await live_document.insert_svg(content, AsyncMock(), live_config)

    subprocess.assert_not_awaited()


@pytest.mark.asyncio
async def test_extension_payload_limit_is_enforced_before_desktop_access(monkeypatch, live_config):
    live_config.max_file_size_mb = 100
    resolve = AsyncMock(side_effect=AssertionError("Oversized payload must not access the desktop"))
    effect = AsyncMock()
    monkeypatch.setattr(live_document, "get_session", resolve)
    monkeypatch.setattr(live_document, "append_svg", effect)
    content = SVG.replace("<rect", "<!--" + "a" * (10 * 1024 * 1024) + "--><rect")

    with pytest.raises(ValueError, match="size limit of 10 MiB"):
        await live_document.insert_svg(content, AsyncMock(), live_config)

    resolve.assert_not_awaited()
    effect.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepared_payload_limit_includes_verification_markers(monkeypatch, live_config):
    resolve = AsyncMock()
    monkeypatch.setattr(live_document, "get_session", resolve)
    monkeypatch.setattr(live_document, "MAX_INSERTION_BYTES", len(SVG.encode()) + 1)

    with pytest.raises(ValueError, match="Prepared live insertion.*size limit"):
        await live_document.insert_svg(SVG, AsyncMock(), live_config)

    resolve.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("limit_mb", [1, 100])
async def test_live_snapshot_uses_configured_document_limit(
    monkeypatch, live_config, tmp_path, limit_mb
):
    live_config.max_file_size_mb = limit_mb
    path = tmp_path / "snapshot.svg"
    content = SVG.replace("<rect", "<!--" + "a" * (10 * 1024 * 1024) + "--><rect")

    async def export_snapshot(*_args):
        path.write_text(content, encoding="utf-8")

    monkeypatch.setattr(live_document, "_live_command", export_snapshot)
    monkeypatch.setattr(live_document.asyncio, "sleep", AsyncMock())
    if limit_mb == 1:
        with pytest.raises(ValueError, match="configured size limit of 1 MiB"):
            await live_document._snapshot(AsyncMock(), live_config, path, {})
    else:
        root = await live_document._snapshot(AsyncMock(), live_config, path, {})
        assert root.find(f"{{{live_document.SVG_NS}}}rect").get("width") == "20"


def test_demo_keeps_user_text_as_editable_text():
    text = 'Prova <MCP> & "caffè" — OK'
    root = ET.fromstring(live_document.build_test_svg(text))

    assert root.find(f"{{{live_document.SVG_NS}}}rect") is not None
    labels = root.findall(f"{{{live_document.SVG_NS}}}text")
    assert len(labels) == 1
    assert labels[0].text == text
    assert len(labels[0]) == 0


@pytest.mark.parametrize("text", ["", "  ", "x" * 201])
def test_demo_rejects_empty_or_excessively_long_text(text):
    with pytest.raises(ValueError, match="text"):
        live_document.build_test_svg(text)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "arguments", "helper_name"),
    [
        ("active_document", {}, "active_document"),
        ("insert_svg", {"svg_content": SVG}, "insert_svg"),
        ("draw_test", {"text": "Prova MCP"}, "insert_svg"),
    ],
)
async def test_live_helper_errors_remain_structured_through_mcp(
    monkeypatch, live_server, operation, arguments, helper_name
):
    helper = AsyncMock(side_effect=RuntimeError("Desktop session is unavailable"))
    monkeypatch.setattr(live_document, helper_name, helper)
    live_server.cli_wrapper = AsyncMock()
    live_server.config.inkscape_executable = "inkscape"
    session_id = "mcp_" + "b" * 32

    async with Client(live_server.mcp) as client:
        result = await client.call_tool(
            "inkscape_system", {"operation": operation, "session_id": session_id, **arguments}
        )

    assert result.data["success"] is False
    assert result.data["operation"] == operation
    assert "Desktop session is unavailable" in result.data["message"]
    helper.assert_awaited_once()
    assert helper.call_args.args[-1] == session_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        ("insert_svg", {"svg_content": SVG}),
        ("draw_test", {"text": "Prova <MCP> & caffè"}),
    ],
)
async def test_live_payload_reaches_helper_through_mcp(
    monkeypatch, live_server, operation, arguments
):
    helper = AsyncMock(return_value={"verified": True, "inserted_count": 2})
    monkeypatch.setattr(live_document, "insert_svg", helper)
    live_server.cli_wrapper = AsyncMock()
    live_server.config.inkscape_executable = "inkscape"
    session_id = "mcp_" + "b" * 32

    async with Client(live_server.mcp) as client:
        result = await client.call_tool(
            "inkscape_system", {"operation": operation, "session_id": session_id, **arguments}
        )

    assert result.data["success"] is True
    assert result.data["data"]["verified"] is True
    helper.assert_awaited_once()
    assert helper.call_args.args[-1] == session_id
    received = helper.call_args.args[0]
    if operation == "insert_svg":
        assert received == SVG
    else:
        root = ET.fromstring(received)
        assert root.find(f"{{{live_document.SVG_NS}}}text").text == arguments["text"]


@pytest.fixture
def live_target():
    return {
        "session_id": "mcp_" + "a" * 32,
        "bus_name": "org.inkscape.Inkscape.mcp_" + "a" * 32,
        "object_path": "/org/inkscape/Inkscape/managed",
        "window_path": "/org/inkscape/Inkscape/managed/window/1",
        "app_id_tag": "mcp_" + "a" * 32,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("zoom_fails", [False, True])
async def test_successful_live_insertion_requires_readback_and_preserves_existing_objects(
    monkeypatch, live_config, live_target, zoom_fails
):
    before = ET.fromstring(
        '<svg xmlns="http://www.w3.org/2000/svg" id="original"><circle id="existing" r="10"/></svg>'
    )
    after = ET.fromstring(ET.tostring(before))

    async def apply_effect(payload, target, *, timeout):
        assert target["session_id"] == live_target["session_id"]
        assert target["root_id"] == "original"
        assert timeout == live_config.process_timeout
        inserted = ET.fromstring(payload).find(f"{{{live_document.SVG_NS}}}rect")
        inserted.set("id", "inserted")
        after.append(inserted)
        return {"success": True}

    snapshot = AsyncMock(side_effect=[before, after])
    action = AsyncMock(side_effect=RuntimeError("Zoom action unavailable") if zoom_fails else None)
    effect = AsyncMock(side_effect=apply_effect)
    resolve = AsyncMock(return_value=live_target)
    monkeypatch.setattr(live_document, "get_session", resolve)
    monkeypatch.setattr(live_document, "append_svg", effect)
    monkeypatch.setattr(live_document, "_snapshot", snapshot)
    monkeypatch.setattr(live_document, "_window_action", action)
    wrapper = SimpleNamespace(_gui_lock=asyncio.Lock())

    result = await live_document.insert_svg(SVG, wrapper, live_config, live_target["session_id"])

    assert result["verified"] is True
    assert result["backend"] == "inkex-extension"
    assert result["session_id"] == live_target["session_id"]
    assert result["document_id"] == "original"
    assert result["objects_before"] == 1
    assert result["objects_after"] == 2
    assert result["inserted_ids"] == ["inserted"]
    assert bool(result["view_warning"]) is zoom_fails
    assert snapshot.await_count == 2
    assert all(call.args[3] == live_target for call in snapshot.await_args_list)
    resolve.assert_awaited_once_with(live_target["session_id"], wrapper, live_config)
    effect.assert_awaited_once()
    action.assert_awaited_once_with(live_target, "canvas-zoom-drawing")


@pytest.mark.asyncio
@pytest.mark.parametrize("document_changed", ["root_id", "missing_original_object"])
async def test_insertion_never_claims_success_if_original_document_changes(
    monkeypatch, live_config, live_target, document_changed
):
    before = ET.fromstring(
        '<svg xmlns="http://www.w3.org/2000/svg" id="original"><circle id="existing" r="10"/></svg>'
    )
    after = ET.fromstring(ET.tostring(before))
    if document_changed == "root_id":
        after.set("id", "other_document")
    else:
        after.remove(after[0])

    async def apply_effect(payload, _target, *, timeout):
        assert timeout > 0
        inserted = ET.fromstring(payload).find(f"{{{live_document.SVG_NS}}}rect")
        inserted.set("id", "inserted")
        after.append(inserted)
        return {"success": True}

    action = AsyncMock()
    effect = AsyncMock(side_effect=apply_effect)
    monkeypatch.setattr(live_document, "get_session", AsyncMock(return_value=live_target))
    monkeypatch.setattr(live_document, "append_svg", effect)
    monkeypatch.setattr(live_document, "_snapshot", AsyncMock(side_effect=[before, after]))
    monkeypatch.setattr(live_document, "_window_action", action)
    wrapper = SimpleNamespace(_gui_lock=asyncio.Lock())

    with pytest.raises(InkscapeExecutionError, match="document changed"):
        await live_document.insert_svg(SVG, wrapper, live_config)

    effect.assert_awaited_once()
    action.assert_not_awaited()


@pytest.mark.asyncio
async def test_unverified_live_insertion_fails_without_repeating_mutation(
    monkeypatch, live_config, live_target
):
    snapshot = ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg" id="original"/>')
    effect = AsyncMock(return_value={"success": True})
    action = AsyncMock()
    monkeypatch.setattr(live_document, "get_session", AsyncMock(return_value=live_target))
    monkeypatch.setattr(live_document, "append_svg", effect)
    monkeypatch.setattr(live_document, "_snapshot", AsyncMock(return_value=snapshot))
    monkeypatch.setattr(live_document, "_window_action", action)
    monkeypatch.setattr(live_document.asyncio, "sleep", AsyncMock())
    wrapper = SimpleNamespace(_gui_lock=asyncio.Lock())

    with pytest.raises(InkscapeExecutionError, match="not verified"):
        await live_document.insert_svg(SVG, wrapper, live_config)

    effect.assert_awaited_once()
    action.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_extension_result_cannot_report_success(monkeypatch, live_config, live_target):
    snapshot = ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg" id="original"/>')
    effect = AsyncMock(return_value={"success": False, "error": "Extension request rejected"})
    snapshot_mock = AsyncMock(return_value=snapshot)
    monkeypatch.setattr(live_document, "get_session", AsyncMock(return_value=live_target))
    monkeypatch.setattr(live_document, "append_svg", effect)
    monkeypatch.setattr(live_document, "_snapshot", snapshot_mock)
    wrapper = SimpleNamespace(_gui_lock=asyncio.Lock())

    with pytest.raises(InkscapeExecutionError, match="Extension request rejected"):
        await live_document.insert_svg(SVG, wrapper, live_config)

    snapshot_mock.assert_awaited_once()
    effect.assert_awaited_once()


@pytest.mark.asyncio
async def test_active_document_returns_only_the_requested_session(
    monkeypatch, live_config, live_target
):
    root = ET.fromstring(
        '<svg xmlns="http://www.w3.org/2000/svg" id="original"><text id="label">Unsaved</text></svg>'
    )
    resolve = AsyncMock(return_value=live_target)
    snapshot = AsyncMock(return_value=root)
    monkeypatch.setattr(live_document, "get_session", resolve)
    monkeypatch.setattr(live_document, "_snapshot", snapshot)
    wrapper = SimpleNamespace(_gui_lock=asyncio.Lock())

    result = await live_document.active_document(wrapper, live_config, live_target["session_id"])

    resolve.assert_awaited_once_with(live_target["session_id"], wrapper, live_config)
    assert snapshot.call_args.args[3] == live_target
    assert result["session_id"] == live_target["session_id"]
    assert result["objects"][0]["text"] == "Unsaved"
    assert "Unsaved" in result["svg_content"]
