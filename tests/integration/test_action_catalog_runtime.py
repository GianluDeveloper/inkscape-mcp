"""Discover real installed actions without touching the user's live document."""

import pytest

from inkscape_mcp.tools.system import inkscape_system


@pytest.mark.integration
@pytest.mark.inkscape
@pytest.mark.asyncio
async def test_installed_action_catalog(integration_wrapper, integration_config):
    result = await inkscape_system(
        operation="list_actions",
        search="select-all",
        limit=10,
        cli_wrapper=integration_wrapper,
        config=integration_config,
    )
    assert result["success"] is True, result
    assert result["data"]["total_actions"] > 10
    assert any(action["name"] == "select-all" for action in result["data"]["actions"])
    assert result["data"]["scope"] == "cli"
