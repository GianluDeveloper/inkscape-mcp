"""File saves must remain explicit disk exports and guide live-save requests."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastmcp import Client

from inkscape_mcp.main import InkscapeMCPServer
from inkscape_mcp.utils import document_lifecycle

SVG = '<svg xmlns="http://www.w3.org/2000/svg"><text>Saved content on disk</text></svg>'


@pytest.fixture
def server(monkeypatch):
    instance = InkscapeMCPServer()
    instance.cli_wrapper = AsyncMock()
    instance._register_portmanteau_tools()
    # A file request must never be redirected to a user's active GUI document.
    monkeypatch.setattr(
        document_lifecycle,
        "document_lifecycle",
        AsyncMock(side_effect=AssertionError("File save must not access the GUI")),
    )
    return instance


@pytest.mark.parametrize("input_path", ["", "   "])
async def test_missing_file_source_guides_live_save_without_touching_destination(
    server, tmp_path, input_path
):
    destination = tmp_path / "existing.svg"
    destination.write_text(SVG)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "inkscape_file",
            {"operation": "save", "input_path": input_path, "output_path": str(destination)},
        )
    assert not result.data["success"]
    assert "input_path" in result.data["error"]
    assert "inkscape_system" in result.data["error"]
    assert "save_document" in result.data["error"]
    assert "save_copy" in result.data["error"]
    assert destination.read_text() == SVG
    server.cli_wrapper._execute_actions.assert_not_awaited()


async def test_file_save_uses_explicit_disk_source_through_public_mcp(server, tmp_path):
    source = tmp_path / "source.svg"
    destination = tmp_path / "copy.svg"
    source.write_text(SVG)

    async def export_file(*, input_path, output_path, **_kwargs):
        Path(output_path).write_text(Path(input_path).read_text())

    server.cli_wrapper._execute_actions.side_effect = export_file
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "inkscape_file",
            {"operation": "save", "input_path": str(source), "output_path": str(destination)},
        )
    assert result.data["success"]
    assert destination.read_text() == source.read_text() == SVG
    assert result.data["data"]["output_path"] == str(destination)
    assert "file on disk" in result.data["message"]
    arguments = server.cli_wrapper._execute_actions.await_args.kwargs
    assert arguments["input_path"] == str(source)
    assert arguments["output_path"] == str(destination)


async def test_nonexistent_file_source_does_not_fall_back_to_gui(server, tmp_path):
    destination = tmp_path / "copy.svg"
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "inkscape_file",
            {
                "operation": "save",
                "input_path": str(tmp_path / "missing.svg"),
                "output_path": str(destination),
            },
        )
    assert not result.data["success"]
    assert "File not found" in result.data["error"]
    assert not destination.exists()
    server.cli_wrapper._execute_actions.assert_not_awaited()


async def test_file_tool_schema_explains_disk_and_live_save_contracts(server):
    async with Client(server.mcp) as client:
        tool = next(tool for tool in await client.list_tools() if tool.name == "inkscape_file")
    assert set(tool.inputSchema["properties"]) == {
        "operation",
        "input_path",
        "output_path",
        "format",
    }
    assert "file on disk" in tool.description
    assert "save_document" in tool.description
    assert "save_copy" in tool.description
