"""Exercise the legacy server entry point through its public MCP and ASGI APIs."""

from unittest.mock import AsyncMock
from unittest.mock import Mock

import httpx
import pytest
from fastmcp import Client

import inkscape_mcp.server as server_module
from inkscape_mcp.server import InkscapeMcpServer


@pytest.fixture
def legacy_server(mock_inkscape_config):
    server = InkscapeMcpServer(mock_inkscape_config)
    server.inkscape._execute_command = AsyncMock(return_value="123.5\n")
    return server


@pytest.mark.asyncio
async def test_legacy_mcp_binds_dependencies_and_hides_them(legacy_server, sample_svg_file):
    async with Client(legacy_server.mcp) as client:
        tools = await client.list_tools()
        for tool in tools:
            properties = tool.inputSchema.get("properties", {})
            assert "cli_wrapper" not in properties, tool.name
            assert "config" not in properties, tool.name

        result = await client.call_tool(
            "inkscape_file", {"operation": "load", "input_path": str(sample_svg_file)}
        )

    assert result.data["success"] is True, result.data
    assert result.data["data"]["width"] == 123.5
    legacy_server.inkscape._execute_command.assert_awaited_once_with(
        [legacy_server.config.inkscape_executable, str(sample_svg_file), "--query-width"],
        legacy_server.config.process_timeout,
    )


@pytest.mark.asyncio
async def test_legacy_mcp_dependencies_are_per_instance(legacy_server, sample_svg_file):
    other = InkscapeMcpServer(legacy_server.config)
    other.inkscape._execute_command = AsyncMock(return_value="456\n")

    for server, expected_width in ((legacy_server, 123.5), (other, 456)):
        async with Client(server.mcp) as client:
            result = await client.call_tool(
                "inkscape_file", {"operation": "load", "input_path": str(sample_svg_file)}
            )
        assert result.data["data"]["width"] == expected_width


@pytest.mark.asyncio
async def test_legacy_app_is_callable_asgi_and_module_proxy_stays_stable(mock_inkscape_config):
    module_app = server_module.app
    server = InkscapeMcpServer(mock_inkscape_config)

    assert server_module.app is module_app
    assert callable(server.app)
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/missing-endpoint")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_lazy_asgi_initializes_once_and_delegates(monkeypatch):
    inner = AsyncMock()
    constructor = Mock(return_value=Mock(app=inner))
    monkeypatch.setattr(server_module, "InkscapeMcpServer", constructor)
    lazy = server_module._LazyASGI()
    scope, receive, send = {"type": "http"}, AsyncMock(), AsyncMock()

    await lazy(scope, receive, send)
    await lazy(scope, receive, send)

    constructor.assert_called_once_with()
    assert inner.await_count == 2
    inner.assert_awaited_with(scope, receive, send)
