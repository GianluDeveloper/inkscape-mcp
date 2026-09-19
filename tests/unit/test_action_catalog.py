"""Installed action discovery must be accurate, bounded, and read-only."""

from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest
from fastmcp import Client

from inkscape_mcp.cli_wrapper import InkscapeExecutionError
from inkscape_mcp.main import InkscapeMCPServer
from inkscape_mcp.tools.system import inkscape_system
from inkscape_mcp.utils.action_catalog import list_actions
from inkscape_mcp.utils.action_catalog import parse_action_catalog

CATALOG = """select-by-id        : Select objects by ID: comma-separated list
layer-new           : Create a new layer
com.example.effect  : Example extension
export-do           : Export the document
layer-hide          : Hide current layer
"""


@pytest.fixture
def wrapper():
    return Mock(_execute_command=AsyncMock(return_value=CATALOG))


def test_parser_handles_real_cli_layout_and_colons():
    catalog = parse_action_catalog(
        "\nInkscape diagnostic without a colon\ninvalid name : ignored\n"
        + CATALOG
        + "layer-new: Create a new layer\n"
    )
    assert len(catalog) == 5
    assert [item["name"] for item in catalog] == [
        "com.example.effect",
        "export-do",
        "layer-hide",
        "layer-new",
        "select-by-id",
    ]
    assert catalog[-1]["description"] == "Select objects by ID: comma-separated list"


@pytest.mark.asyncio
async def test_search_pagination_uses_configured_binary(wrapper, mock_inkscape_config):
    result = await list_actions(
        cli_wrapper=wrapper, config=mock_inkscape_config, search=" LAYER ", limit=1
    )
    assert result["total_actions"] == 5
    assert result["matched_actions"] == 2
    assert result["actions"][0]["name"] == "layer-hide"
    assert result["returned"] == 1
    assert result["has_more"] is True
    assert result["next_offset"] == 1
    wrapper._execute_command.assert_awaited_once_with(
        [mock_inkscape_config.inkscape_executable, "--action-list"],
        mock_inkscape_config.process_timeout,
    )
    last = await list_actions(
        cli_wrapper=wrapper, config=mock_inkscape_config, search="layer", limit=1, offset=1
    )
    assert last["actions"][0]["name"] == "layer-new"
    assert last["has_more"] is False
    assert last["next_offset"] is None


@pytest.mark.asyncio
async def test_search_matches_description_and_handles_no_matches(wrapper, mock_inkscape_config):
    result = await list_actions(
        cli_wrapper=wrapper, config=mock_inkscape_config, search="COMMA-SEPARATED"
    )
    assert [item["name"] for item in result["actions"]] == ["select-by-id"]
    result = await list_actions(
        cli_wrapper=wrapper, config=mock_inkscape_config, search="nonexistent action"
    )
    assert result["actions"] == []
    assert result["matched_actions"] == 0
    assert result["has_more"] is False
    assert result["next_offset"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 501}, {"limit": True}, {"offset": -1}])
async def test_invalid_pagination_does_not_launch_inkscape(wrapper, mock_inkscape_config, kwargs):
    with pytest.raises(ValueError):
        await list_actions(cli_wrapper=wrapper, config=mock_inkscape_config, **kwargs)
    wrapper._execute_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_catalog_is_not_cached(wrapper, mock_inkscape_config):
    wrapper._execute_command.side_effect = [
        InkscapeExecutionError("temporarily unavailable"),
        CATALOG,
    ]
    first = await inkscape_system(
        operation="list_actions", cli_wrapper=wrapper, config=mock_inkscape_config
    )
    assert first["success"] is False
    assert "temporarily unavailable" in first["message"]
    recovered = await inkscape_system(
        operation="list_actions", cli_wrapper=wrapper, config=mock_inkscape_config
    )
    assert recovered["success"] is True
    assert recovered["data"]["total_actions"] == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("output", ["", "no recognizable action rows"])
async def test_empty_or_malformed_catalog_is_reported_as_failure(
    wrapper, mock_inkscape_config, output
):
    wrapper._execute_command.return_value = output
    result = await inkscape_system(
        operation="list_actions", cli_wrapper=wrapper, config=mock_inkscape_config
    )
    assert result["success"] is False
    assert "no recognizable" in result["message"]


@pytest.mark.asyncio
async def test_list_actions_without_inkscape_returns_actionable_failure():
    result = await inkscape_system(operation="list_actions")
    assert result["success"] is False
    assert "INKSCAPE_PATH" in result["message"]


@pytest.mark.asyncio
async def test_action_catalog_public_mcp_schema_and_dispatch(wrapper, mock_inkscape_config):
    server = InkscapeMCPServer()
    server.config = mock_inkscape_config
    server.cli_wrapper = wrapper
    server._register_portmanteau_tools()
    async with Client(server.mcp) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        properties = tools["inkscape_system"].inputSchema["properties"]
        assert "list_actions" in properties["operation"]["enum"]
        assert {"search", "limit", "offset"} <= properties.keys()
        result = await client.call_tool(
            "inkscape_system",
            {"operation": "list_actions", "search": "LAYER", "limit": 1, "offset": 1},
        )
    assert result.data["success"] is True
    assert [item["name"] for item in result.data["data"]["actions"]] == ["layer-new"]


@pytest.mark.asyncio
async def test_changing_executable_does_not_reuse_another_binary_catalog(
    wrapper, mock_inkscape_config
):
    wrapper._execute_command.side_effect = [
        CATALOG,
        "different-action: Other Inkscape installation",
    ]
    await list_actions(cli_wrapper=wrapper, config=mock_inkscape_config)
    other_config = mock_inkscape_config.model_copy(
        update={"inkscape_executable": "/other/inkscape"}
    )
    result = await list_actions(cli_wrapper=wrapper, config=other_config)
    assert result["total_actions"] == 1
    assert result["actions"][0]["name"] == "different-action"
    assert wrapper._execute_command.call_args.args[0] == ["/other/inkscape", "--action-list"]
