"""Regression coverage for injected contexts and MCP sampling capability errors."""

from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp import FastMCP
from mcp.types import SamplingCapability
from mcp.types import SamplingToolsCapability

from inkscape_mcp.agentic import register_agentic_tools

SVG = '<svg xmlns="http://www.w3.org/2000/svg"><circle cx="50" cy="50" r="20"/></svg>'
TOOL_ARGUMENTS = [
    ("generate_svg", {"description": "a stylized sun"}),
    ("agentic_inkscape_workflow", {"workflow_prompt": "draw a sun"}),
    (
        "intelligent_vector_processing",
        {"documents": [], "processing_goal": "draw a sun", "available_operations": []},
    ),
    ("conversational_inkscape_assistant", {"user_query": "how can I draw a sun?"}),
]


@pytest.fixture
def agentic_server():
    server = FastMCP("agentic-regression-tests")
    register_agentic_tools(server)
    return server


async def test_context_is_not_a_public_tool_argument(agentic_server):
    async with Client(agentic_server) as client:
        tool_schemas = {tool.name: tool.inputSchema for tool in await client.list_tools()}

    for tool_name, _ in TOOL_ARGUMENTS:
        assert "ctx" not in tool_schemas[tool_name].get("properties", {})
        assert "ctx" not in tool_schemas[tool_name].get("required", [])


@pytest.mark.parametrize(("tool_name", "arguments"), TOOL_ARGUMENTS)
async def test_real_client_receives_injected_context(agentic_server, tmp_path, monkeypatch, tool_name, arguments):
    monkeypatch.chdir(tmp_path)
    sampling_requests = []

    async def sample(_messages, params, _context):
        sampling_requests.append(params)
        return SVG

    async with Client(
        agentic_server,
        sampling_handler=sample,
        sampling_capabilities=SamplingCapability(tools=SamplingToolsCapability()),
    ) as client:
        result = await client.call_tool(tool_name, arguments)

    assert result.data["success"] is True
    assert len(sampling_requests) == 1
    assert sampling_requests[0].tools
    if tool_name == "generate_svg":
        assert Path(result.data["svg_path"]).read_text() == SVG
    else:
        assert result.data["message"] == SVG


@pytest.mark.parametrize("supports_plain_sampling", [False, True])
async def test_generate_svg_explains_missing_sampling_capabilities(
    agentic_server, tmp_path, monkeypatch, supports_plain_sampling
):
    monkeypatch.chdir(tmp_path)

    async def sample(_messages, _params, _context):
        pytest.fail("The unsupported sampling request must not be sent to the client")

    async with Client(agentic_server, sampling_handler=sample if supports_plain_sampling else None) as client:
        result = await client.call_tool("generate_svg", {"description": "a stylized sun"})

    assert result.data["success"] is False
    assert result.data["error_code"] == "sampling_unavailable"
    assert "construct_svg" in result.data["message"]
    assert "sampling.tools" in result.data["message"]
    assert not (tmp_path / "generated_svgs").exists()
