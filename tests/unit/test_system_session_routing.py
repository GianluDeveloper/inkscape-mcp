"""Raw live actions must respect explicit document sessions and package versions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkscape_mcp import __version__
from inkscape_mcp.cli_wrapper import InkscapeExecutionError
from inkscape_mcp.tools.system import inkscape_system
from inkscape_mcp.utils import document_sessions

SESSION = "mcp_" + "a" * 32


@pytest.fixture
def configuration():
    return SimpleNamespace(inkscape_executable="/usr/bin/inkscape", process_timeout=10)


async def test_raw_actions_route_to_requested_managed_instance(monkeypatch, configuration):
    wrapper = AsyncMock()
    wrapper._execute_command.return_value = "target,10,20,30,40\n"
    resolve = AsyncMock(return_value={"managed": True, "app_id_tag": SESSION})
    monkeypatch.setattr(document_sessions, "get_session", resolve)
    result = await inkscape_system(
        operation="hands_in_command",
        action="query-all",
        session_id=SESSION,
        cli_wrapper=wrapper,
        config=configuration,
    )
    assert result["success"]
    assert result["data"]["session_id"] == SESSION
    resolve.assert_awaited_once_with(SESSION, wrapper, configuration)
    command = wrapper._execute_command.await_args.args[0]
    assert f"--app-id-tag={SESSION}" in command
    assert "--active-window" in command
    assert command[-2:] == ["--actions", "query-all"]


@pytest.mark.parametrize("error", ["Unknown document session", "Document session is not open"])
async def test_unknown_or_closed_session_cannot_mutate_desktop(monkeypatch, configuration, error):
    wrapper = AsyncMock()
    monkeypatch.setattr(
        document_sessions,
        "get_session",
        AsyncMock(side_effect=InkscapeExecutionError(error)),
    )
    result = await inkscape_system(
        operation="hands_in_command",
        action="select-all;delete-selection",
        session_id=SESSION,
        cli_wrapper=wrapper,
        config=configuration,
    )
    assert not result["success"]
    assert error in result["error"]
    wrapper._execute_command.assert_not_awaited()


async def test_invalid_resolved_target_does_not_fall_back_to_desktop(monkeypatch, configuration):
    wrapper = AsyncMock()
    monkeypatch.setattr(
        document_sessions, "get_session", AsyncMock(return_value={"managed": False})
    )
    result = await inkscape_system(
        operation="hands_in_command",
        action="select-all",
        session_id=SESSION,
        cli_wrapper=wrapper,
        config=configuration,
    )
    assert not result["success"]
    wrapper._execute_command.assert_not_awaited()


async def test_legacy_desktop_actions_do_not_require_linux_session_discovery(
    monkeypatch, configuration
):
    wrapper = AsyncMock()
    wrapper._execute_command.return_value = ""
    resolve = AsyncMock(side_effect=AssertionError("Desktop CLI must remain cross-platform"))
    monkeypatch.setattr(document_sessions, "get_session", resolve)
    result = await inkscape_system(
        operation="hands_in_command",
        action="select-all",
        cli_wrapper=wrapper,
        config=configuration,
    )
    assert result["success"]
    resolve.assert_not_awaited()
    command = wrapper._execute_command.await_args.args[0]
    assert not any(arg.startswith("--app-id-tag") for arg in command)


@pytest.mark.parametrize("operation", ["status", "version"])
async def test_reported_version_comes_from_package(operation):
    result = await inkscape_system(operation=operation)
    assert result["success"]
    data = result["data"]
    if operation == "status":
        assert data["server"]["version"] == __version__
        assert "agent_lab_phase" not in data["server"]
    else:
        assert data["version"] == __version__
        assert data["server"].endswith(f"v{__version__}")
        assert "Agent Lab" not in data["architecture"]
