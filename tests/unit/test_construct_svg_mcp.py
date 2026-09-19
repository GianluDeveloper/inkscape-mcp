"""Exercise SVG construction through the public MCP schema and dispatcher."""

import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock

import pytest
from fastmcp import Client

from inkscape_mcp.main import InkscapeMCPServer

SVG = '<svg xmlns="http://www.w3.org/2000/svg"><circle id="sun" r="20"/></svg>'


@pytest.fixture
def server():
    instance = InkscapeMCPServer()
    instance._register_portmanteau_tools()
    return instance


@pytest.mark.asyncio
async def test_construct_svg_public_mcp_roundtrip(server, tmp_path):
    path = tmp_path / "sun.svg"
    async with Client(server.mcp) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        properties = tools["inkscape_vector"].inputSchema["properties"]
        assert {"svg_content", "params", "element_type"} <= properties.keys()
        result = await client.call_tool(
            "inkscape_vector",
            {
                "operation": "construct_svg",
                "output_path": str(path),
                "svg_content": SVG,
            },
        )
    assert result.data["success"] is True
    root = ET.parse(path).getroot()
    assert root.find("{http://www.w3.org/2000/svg}circle").get("id") == "sun"


@pytest.mark.asyncio
async def test_construct_svg_body_reaches_handler(server, tmp_path):
    path = tmp_path / "from-body.svg"
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "inkscape_vector",
            {
                "operation": "construct_svg",
                "output_path": str(path),
                "params": {"body": '<circle id="sun" r="20"/>'},
                "element_type": "circle",
            },
        )
    assert result.data["success"] is True
    assert result.data["data"]["element_type"] == "circle"
    assert ET.parse(path).getroot().find("{http://www.w3.org/2000/svg}circle") is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["", "<svg>", "<html/>"])
async def test_invalid_construction_preserves_existing_file(server, tmp_path, content):
    path = tmp_path / "existing.svg"
    path.write_text(SVG)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "inkscape_vector",
            {
                "operation": "construct_svg",
                "output_path": str(path),
                "svg_content": content,
            },
        )
    assert result.data["success"] is False
    assert path.read_text() == SVG


@pytest.mark.asyncio
async def test_construct_svg_respects_allowed_directories(server, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    server.config.allowed_directories = [str(allowed)]
    path = tmp_path / "outside.svg"
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "inkscape_vector",
            {
                "operation": "construct_svg",
                "output_path": str(path),
                "svg_content": SVG,
            },
        )
    assert result.data["success"] is False
    assert "allowed_directories" in result.data["error"]
    assert not path.exists()


@pytest.mark.asyncio
async def test_gui_action_reaches_cli_through_mcp(server):
    server.config.inkscape_executable = "/usr/bin/inkscape"
    server.cli_wrapper = AsyncMock()
    server.cli_wrapper._execute_command.return_value = ""
    action = "file-open:/tmp/sun.svg;window-open"
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "inkscape_system",
            {
                "operation": "hands_in_command",
                "action": action,
            },
        )
    assert result.data["success"] is True
    server.cli_wrapper._execute_command.assert_awaited_once_with(
        ["/usr/bin/inkscape", "--active-window", "--actions", action],
        server.config.process_timeout,
    )
