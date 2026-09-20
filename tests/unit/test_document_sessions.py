"""Document routing and lifecycle checks without changing desktop state."""

import json
import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest
from fastmcp import Client

from inkscape_mcp.cli_wrapper import InkscapeExecutionError
from inkscape_mcp.main import InkscapeMCPServer
from inkscape_mcp.utils import document_sessions as sessions

SESSION = "mcp_" + "a" * 32


@pytest.fixture(autouse=True)
def isolated_sessions(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(sessions, "_require_desktop", lambda: None)
    monkeypatch.setattr(sessions, "_PROCESSES", {})


def write_registry(entries):
    path = sessions._registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    sessions._save_registry(path, entries)
    return path


@pytest.mark.asyncio
async def test_resolve_target_never_falls_back_to_desktop(monkeypatch):
    write_registry({SESSION: {"input_path": "/work/named.svg"}})
    monkeypatch.setattr(sessions, "_bus_names", AsyncMock(return_value={"org.inkscape.Inkscape"}))
    with pytest.raises(InkscapeExecutionError, match="not open"):
        await sessions.get_session(SESSION)
    with pytest.raises(InkscapeExecutionError, match="Unknown"):
        await sessions.get_session("mcp_" + "b" * 32)
    with pytest.raises(ValueError, match="session_id"):
        await sessions.get_session("../../../desktop")


@pytest.mark.asyncio
async def test_resolve_uses_tagged_bus_and_actual_window_id(monkeypatch):
    write_registry({SESSION: {"input_path": "/work/named.svg"}})
    monkeypatch.setattr(
        sessions, "_bus_names", AsyncMock(return_value={f"org.inkscape.Inkscape.{SESSION}"})
    )
    windows = AsyncMock(return_value=[7])
    monkeypatch.setattr(sessions, "_windows", windows)
    result = await sessions.get_session(SESSION)
    assert result["window_id"] == 7
    assert result["bus_name"] == f"org.inkscape.Inkscape.{SESSION}"
    assert result["object_path"] == f"/org/inkscape/Inkscape/{SESSION}"
    assert result["window_path"].endswith("/window/7")
    assert result["input_path"] == "/work/named.svg"


@pytest.mark.asyncio
@pytest.mark.parametrize("window_ids", [[], [1, 2]])
async def test_ambiguous_desktop_refused(monkeypatch, window_ids):
    monkeypatch.setattr(sessions, "_bus_names", AsyncMock(return_value={"org.inkscape.Inkscape"}))
    monkeypatch.setattr(sessions, "_windows", AsyncMock(return_value=window_ids))
    with pytest.raises(InkscapeExecutionError, match="exactly one"):
        await sessions.get_session("desktop")


@pytest.mark.asyncio
async def test_list_reports_live_sessions_and_ambiguous_desktop(monkeypatch):
    stale = "mcp_" + "c" * 32
    write_registry(
        {SESSION: {"input_path": "/work/open.svg"}, stale: {"input_path": "/work/closed.svg"}}
    )
    monkeypatch.setattr(
        sessions,
        "_bus_names",
        AsyncMock(return_value={"org.inkscape.Inkscape", f"org.inkscape.Inkscape.{SESSION}"}),
    )
    monkeypatch.setattr(sessions, "_windows", AsyncMock(side_effect=[[1, 2], [1]]))
    result = await sessions.list_documents()
    assert result["count"] == 2
    assert result["documents"][0]["session_id"] == "desktop"
    assert result["documents"][0]["editable"] is False
    assert result["documents"][1]["session_id"] == SESSION
    assert result["documents"][1]["editable"] is True


@pytest.mark.asyncio
async def test_open_same_file_reuses_session(monkeypatch, sample_svg_file, mock_inkscape_config):
    write_registry({SESSION: {"input_path": str(sample_svg_file.resolve())}})
    monkeypatch.setattr(
        sessions, "_bus_names", AsyncMock(return_value={f"org.inkscape.Inkscape.{SESSION}"})
    )
    monkeypatch.setattr(sessions, "_windows", AsyncMock(return_value=[1]))
    spawn = Mock()
    monkeypatch.setattr(sessions.subprocess, "Popen", spawn)
    result = await sessions.open_document(str(sample_svg_file), config=mock_inkscape_config)
    assert result["session_id"] == SESSION
    assert result["reused"] is True
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_starting_session_does_not_launch_duplicate(
    monkeypatch, sample_svg_file, mock_inkscape_config
):
    write_registry({SESSION: {"input_path": str(sample_svg_file.resolve()), "pid": 123}})
    monkeypatch.setattr(sessions, "_bus_names", AsyncMock(return_value=set()))
    monkeypatch.setattr(sessions, "_managed_process_running", Mock(return_value=True))
    spawn = Mock()
    monkeypatch.setattr(sessions.subprocess, "Popen", spawn)
    with pytest.raises(InkscapeExecutionError, match="still starting"):
        await sessions.open_document(str(sample_svg_file), config=mock_inkscape_config)
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_open_persists_session_and_waits_for_bus(
    monkeypatch, sample_svg_file, mock_inkscape_config
):
    monkeypatch.setattr(sessions, "uuid4", lambda: Mock(hex="a" * 32))
    monkeypatch.setattr(
        sessions, "_bus_names", AsyncMock(side_effect=[set(), {f"org.inkscape.Inkscape.{SESSION}"}])
    )
    monkeypatch.setattr(sessions, "_windows", AsyncMock(return_value=[1]))
    process = Mock(pid=987, poll=Mock(return_value=None))
    spawn = Mock(return_value=process)
    monkeypatch.setattr(sessions.subprocess, "Popen", spawn)
    result = await sessions.open_document(str(sample_svg_file), config=mock_inkscape_config)
    assert result["reused"] is False
    assert result["session_id"] == SESSION
    assert spawn.call_args.args[0] == [
        mock_inkscape_config.inkscape_executable,
        f"--app-id-tag={SESSION}",
        "--with-gui",
        str(sample_svg_file.resolve()),
    ]
    registry = json.loads(sessions._registry_path().read_text())
    assert registry["sessions"][SESSION]["input_path"] == str(sample_svg_file.resolve())
    assert spawn.call_args.kwargs["env"]["INKSCAPE_MCP_SESSION_ID"] == SESSION
    assert spawn.call_args.kwargs["env"]["INKSCAPE_APP_ID_TAG"] == SESSION


@pytest.mark.asyncio
async def test_registry_failure_cannot_leave_an_untracked_gui(
    monkeypatch, sample_svg_file, mock_inkscape_config
):
    monkeypatch.setattr(sessions, "_bus_names", AsyncMock(return_value=set()))
    monkeypatch.setattr(sessions, "_save_registry", Mock(side_effect=OSError("disk full")))
    spawn = Mock()
    monkeypatch.setattr(sessions.subprocess, "Popen", spawn)
    with pytest.raises(OSError, match="disk full"):
        await sessions.open_document(str(sample_svg_file), config=mock_inkscape_config)
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_new_document_never_overwrites_existing_file(
    monkeypatch, sample_svg_file, mock_inkscape_config
):
    original = sample_svg_file.read_bytes()
    opener = AsyncMock()
    monkeypatch.setattr(sessions, "open_document", opener)
    with pytest.raises(FileExistsError):
        await sessions.new_document(str(sample_svg_file), config=mock_inkscape_config)
    assert sample_svg_file.read_bytes() == original
    opener.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_document_creates_named_valid_svg(monkeypatch, tmp_path, mock_inkscape_config):
    output = tmp_path / "new" / "design.svg"
    opener = AsyncMock(return_value={"session_id": SESSION})
    monkeypatch.setattr(sessions, "open_document", opener)
    result = await sessions.new_document(str(output), config=mock_inkscape_config)
    assert result["created"] is True
    assert ET.parse(output).getroot().get("viewBox") == "0 0 800 600"
    opener.assert_awaited_once_with(str(output), cli_wrapper=None, config=mock_inkscape_config)
    assert list(output.parent.iterdir()) == [output]


@pytest.mark.asyncio
async def test_invalid_or_disallowed_svg_does_not_spawn(
    monkeypatch, tmp_path, mock_inkscape_config
):
    svg = tmp_path / "bad.svg"
    svg.write_text("<html/>")
    spawn = Mock()
    monkeypatch.setattr(sessions.subprocess, "Popen", spawn)
    with pytest.raises(ValueError, match="root must be svg"):
        await sessions.open_document(str(svg), config=mock_inkscape_config)
    mock_inkscape_config.allowed_directories = [str(tmp_path / "allowed")]
    with pytest.raises(ValueError, match="outside allowed"):
        await sessions.new_document(str(tmp_path / "outside.svg"), config=mock_inkscape_config)
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_corrupt_registry_is_not_overwritten(monkeypatch):
    path = write_registry({})
    path.write_text("not valid json")
    monkeypatch.setattr(sessions, "_bus_names", AsyncMock(return_value=set()))
    with pytest.raises(InkscapeExecutionError, match="Cannot read"):
        await sessions.list_documents()
    assert path.read_text() == "not valid json"


@pytest.mark.asyncio
async def test_session_operations_public_mcp_dispatch(monkeypatch, mock_inkscape_config):
    server = InkscapeMCPServer()
    server.config = mock_inkscape_config
    server._register_portmanteau_tools()
    opener = AsyncMock(return_value={"session_id": SESSION})
    monkeypatch.setattr(sessions, "open_document", opener)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "inkscape_system", {"operation": "open_document", "input_path": "/work/drawing.svg"}
        )
    assert result.data["success"] is True
    assert result.data["data"]["session_id"] == SESSION
    opener.assert_awaited_once_with("/work/drawing.svg", None, mock_inkscape_config)
