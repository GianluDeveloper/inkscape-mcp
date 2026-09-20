"""Verified native save/copy and guarded close behavior for addressed documents."""

import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest
from PIL import Image

from inkscape_mcp.cli_wrapper import InkscapeCliWrapper
from inkscape_mcp.cli_wrapper import InkscapeExecutionError
from inkscape_mcp.utils import document_lifecycle as lifecycle

SVG = '<svg xmlns="http://www.w3.org/2000/svg" id="document"><rect id="existing" width="20" height="10"/></svg>'


@pytest.fixture
def session(tmp_path, monkeypatch, mock_cli_wrapper):
    source = tmp_path / "original.svg"
    source.write_text(SVG)
    target = {
        "session_id": "mcp_test",
        "bus_name": "org.inkscape.Inkscape.mcp_test",
        "object_path": "/org/inkscape/Inkscape/mcp_test",
        "window_path": "/org/inkscape/Inkscape/mcp_test/window/1",
        "managed": True,
        "input_path": str(source),
    }
    monkeypatch.setattr(lifecycle.document_sessions, "get_session", AsyncMock(return_value=target))
    records = {"mcp_test": target}

    @asynccontextmanager
    async def registry():
        yield tmp_path / "registry.json", records

    monkeypatch.setattr(lifecycle.document_sessions, "_registry", registry)
    monkeypatch.setattr(lifecycle.document_sessions, "_save_registry", Mock())
    inspection = {
        "active_document": {"path": str(source), "path_source": "DOCUMENT_PATH"},
        "svg_content": SVG,
    }
    inspector = AsyncMock(return_value=inspection)
    monkeypatch.setattr(lifecycle, "inspect_document", inspector)
    return SimpleNamespace(
        target=target,
        source=source,
        wrapper=mock_cli_wrapper,
        config=mock_cli_wrapper.config,
        records=records,
        inspection=inspection,
        inspector=inspector,
    )


async def test_save_inspects_without_exporting_the_live_document(session, monkeypatch):
    snapshot = AsyncMock()
    action = AsyncMock()
    monkeypatch.setattr(lifecycle, "_snapshot", snapshot)
    monkeypatch.setattr(lifecycle, "_window_action", action)
    result = await lifecycle.document_lifecycle(
        "save_document", "mcp_test", "", session.wrapper, session.config
    )
    assert result["verified"]
    assert result["live_document_saved"]
    assert not result["saved_copy"]
    assert session.source.read_text() == SVG
    action.assert_awaited_once_with(session.target, "document-save")
    snapshot.assert_not_awaited()
    session.inspector.assert_awaited_once()


async def test_desktop_native_save_updates_disk(session, monkeypatch):
    session.target.update(managed=False, session_id="desktop")
    session.target.pop("input_path")
    edited = SVG.replace('width="20"', 'width="50"')
    session.inspection["svg_content"] = edited

    async def native_save(target, action):
        assert target is session.target
        assert action == "document-save"
        session.source.write_text(edited)

    monkeypatch.setattr(lifecycle, "_window_action", native_save)
    result = await lifecycle.document_lifecycle(
        "save_document", "desktop", "", session.wrapper, session.config
    )
    assert result["verified"] and result["live_document_saved"]
    assert result["output_path"] == str(session.source)
    assert session.source.read_text() == edited


async def test_save_rejects_different_destination_before_native_action(session, monkeypatch):
    destination = session.source.with_name("save-as.svg")
    action = AsyncMock()
    monkeypatch.setattr(lifecycle, "_window_action", action)
    with pytest.raises(ValueError, match="different output_path is not Save As"):
        await lifecycle.document_lifecycle(
            "save_document", "mcp_test", str(destination), session.wrapper, session.config
        )
    action.assert_not_awaited()
    assert session.source.read_text() == SVG
    assert not destination.exists()


async def test_save_follows_native_filename_after_gui_save_as(session, monkeypatch):
    current = session.source.with_name("gui-save-as.svg")
    edited = SVG.replace('width="20"', 'width="50"')
    current.write_text(SVG)
    session.inspection["active_document"]["path"] = str(current)
    session.inspection["svg_content"] = edited
    action = AsyncMock(side_effect=lambda *_: current.write_text(edited))
    monkeypatch.setattr(lifecycle, "_window_action", action)
    result = await lifecycle.document_lifecycle(
        "save_document", "mcp_test", str(current), session.wrapper, session.config
    )
    assert result["output_path"] == str(current)
    assert current.read_text() == edited
    assert session.source.read_text() == SVG
    assert session.records["mcp_test"]["input_path"] == str(current)
    action.assert_awaited_once_with(session.target, "document-save")


@pytest.mark.parametrize("native_path", ["", "relative.svg"])
async def test_unnamed_save_fails_without_opening_a_dialog(session, monkeypatch, native_path):
    session.inspection["active_document"]["path"] = native_path
    action = AsyncMock()
    monkeypatch.setattr(lifecycle, "_window_action", action)
    with pytest.raises(ValueError, match="File > Save As"):
        await lifecycle.document_lifecycle(
            "save_document", "mcp_test", "", session.wrapper, session.config
        )
    action.assert_not_awaited()


async def test_failed_inspection_never_sends_save(session, monkeypatch):
    session.inspector.side_effect = InkscapeExecutionError("inspection timed out")
    action = AsyncMock()
    monkeypatch.setattr(lifecycle, "_window_action", action)
    with pytest.raises(InkscapeExecutionError, match="inspection timed out"):
        await lifecycle.document_lifecycle(
            "save_document", "mcp_test", "", session.wrapper, session.config
        )
    action.assert_not_awaited()


async def test_copy_preserves_previous_destination_when_snapshot_fails(
    session, monkeypatch, tmp_path
):
    destination = tmp_path / "copy.svg"
    destination.write_text("previous user file")

    async def snapshot(_wrapper, _config, path, _target):
        path.write_text("incomplete export")
        raise InkscapeExecutionError("snapshot failed")

    monkeypatch.setattr(lifecycle, "_snapshot", snapshot)
    with pytest.raises(InkscapeExecutionError, match="snapshot failed"):
        await lifecycle.document_lifecycle(
            "save_copy", "mcp_test", str(destination), session.wrapper, session.config
        )
    assert destination.read_text() == "previous user file"
    assert not list(tmp_path.glob("inkscape-mcp-*"))


@pytest.mark.parametrize("normalized_padding", [0, 10 * 1024 * 1024])
async def test_native_save_noop_verifies_normalized_disk_without_overwriting(
    session, monkeypatch, normalized_padding
):
    minimal = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="20" height="10"/></svg>'
    session.source.write_text(minimal)

    async def normalize(input_path, output_path, export_type, export_area):
        assert Path(input_path).parent == session.source.parent
        assert export_type == "svg"
        assert export_area == "page"
        assert session.source.read_text() == minimal
        assert Path(output_path).parent == session.source.parent
        normalized = SVG.replace("</svg>", "<!--" + "a" * normalized_padding + "--></svg>")
        Path(output_path).write_text(normalized)

    export = AsyncMock(side_effect=normalize)
    monkeypatch.setattr(session.wrapper, "export_file", export)
    monkeypatch.setattr(lifecycle, "_window_action", AsyncMock())
    result = await lifecycle.document_lifecycle(
        "save_document", "mcp_test", "", session.wrapper, session.config
    )
    assert result["verified"]
    assert session.source.read_text() == minimal
    assert export.await_count == 2
    assert not list(session.source.parent.glob("inkscape-mcp-snapshot-*"))


@pytest.mark.parametrize("operation", ["save_document", "save_copy"])
async def test_large_document_save_uses_configured_limit(session, monkeypatch, operation):
    session.config.max_file_size_mb = 100
    content = SVG.replace("</svg>", "<!--" + "a" * (10 * 1024 * 1024) + "--></svg>")
    session.source.write_text(content)
    session.inspection["svg_content"] = content
    destination = (
        session.source if operation == "save_document" else session.source.with_name("copy.svg")
    )

    async def snapshot(_wrapper, _config, path, _target):
        path.write_text(content)
        return ET.fromstring(content)

    monkeypatch.setattr(lifecycle, "_snapshot", snapshot)
    monkeypatch.setattr(lifecycle, "_window_action", AsyncMock())
    result = await lifecycle.document_lifecycle(
        operation, "mcp_test", str(destination), session.wrapper, session.config
    )

    assert result["verified"]
    assert result["live_document_saved"] is (operation == "save_document")
    assert result["bytes"] > 10 * 1024 * 1024
    assert destination.read_text() == content
    assert session.source.read_text() == content


async def test_normalization_does_not_hide_unsaved_drawing_changes(session, monkeypatch):
    expected = SVG.replace('width="20"', 'width="50"')
    session.inspection["svg_content"] = expected

    async def normalize(input_path, output_path, export_type, export_area):
        assert export_type == "svg"
        assert export_area == "page"
        Path(output_path).write_text(Path(input_path).read_text())

    export = AsyncMock(side_effect=normalize)
    monkeypatch.setattr(session.wrapper, "export_file", export)
    monkeypatch.setattr(lifecycle, "_window_action", AsyncMock())
    monkeypatch.setattr(lifecycle.asyncio, "sleep", AsyncMock())
    with pytest.raises(InkscapeExecutionError, match="could not be verified"):
        await lifecycle.document_lifecycle(
            "save_document", "mcp_test", "", session.wrapper, session.config
        )
    assert session.source.read_text() == SVG
    assert export.await_count == 2


async def test_close_uses_guarded_application_quit_and_removes_registry(session, monkeypatch):
    action = AsyncMock()
    monkeypatch.setattr(lifecycle, "_window_action", action)
    monkeypatch.setattr(lifecycle.document_sessions, "_bus_names", AsyncMock(return_value=set()))
    result = await lifecycle.document_lifecycle(
        "close_document", "mcp_test", "", session.wrapper, session.config
    )
    assert result["closed"]
    assert not session.records
    assert action.await_args.args[0]["window_path"] == session.target["object_path"]
    assert action.await_args.args[1] == "quit"


async def test_close_handles_bus_disappearing_between_native_calls(session, monkeypatch):
    monkeypatch.setattr(lifecycle, "_window_action", AsyncMock())
    monkeypatch.setattr(
        lifecycle.document_sessions,
        "_bus_names",
        AsyncMock(side_effect=[{session.target["bus_name"]}, set()]),
    )
    monkeypatch.setattr(
        lifecycle.document_sessions,
        "_windows",
        AsyncMock(side_effect=InkscapeExecutionError("ServiceUnknown")),
    )
    result = await lifecycle.document_lifecycle(
        "close_document", "mcp_test", "", session.wrapper, session.config
    )
    assert result["closed"]


async def test_close_handles_exit_before_activation_reply(session, monkeypatch):
    monkeypatch.setattr(
        lifecycle, "_window_action", AsyncMock(side_effect=InkscapeExecutionError("NoReply"))
    )
    monkeypatch.setattr(lifecycle.document_sessions, "_bus_names", AsyncMock(return_value=set()))
    result = await lifecycle.document_lifecycle(
        "close_document", "mcp_test", "", session.wrapper, session.config
    )
    assert result["closed"]


async def test_unsaved_changes_dialog_is_never_forced_closed(session, monkeypatch):
    action = AsyncMock()
    monkeypatch.setattr(lifecycle, "_window_action", action)
    monkeypatch.setattr(
        lifecycle.document_sessions,
        "_bus_names",
        AsyncMock(return_value={session.target["bus_name"]}),
    )
    monkeypatch.setattr(lifecycle.document_sessions, "_windows", AsyncMock(return_value=[1]))
    monkeypatch.setattr(lifecycle.asyncio, "sleep", AsyncMock())
    with pytest.raises(InkscapeExecutionError, match="no changes were discarded"):
        await lifecycle.document_lifecycle(
            "close_document", "mcp_test", "", session.wrapper, session.config
        )
    assert session.records
    action.assert_awaited_once()
    assert action.await_args.args[1] == "quit"


async def test_unmanaged_desktop_cannot_be_closed(session, monkeypatch):
    session.target["managed"] = False
    action = AsyncMock()
    monkeypatch.setattr(lifecycle, "_window_action", action)
    with pytest.raises(ValueError, match="managed session"):
        await lifecycle.document_lifecycle(
            "close_document", "desktop", "", session.wrapper, session.config
        )
    action.assert_not_awaited()


def test_fingerprint_keeps_meaningful_spaces_between_tspans():
    spaced = ET.fromstring(
        '<svg xmlns="http://www.w3.org/2000/svg"><text><tspan>A</tspan> <tspan>B</tspan></text></svg>'
    )
    joined = ET.fromstring(
        '<svg xmlns="http://www.w3.org/2000/svg"><text><tspan>A</tspan><tspan>B</tspan></text></svg>'
    )
    assert lifecycle.drawing_fingerprint(spaced) != lifecycle.drawing_fingerprint(joined)


def test_fingerprint_ignores_indentation_and_inkscape_version():
    pretty = ET.fromstring(
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        'inkscape:version="1.4" id="document">\n  <rect id="existing" width="20" height="10"/>\n</svg>'
    )
    assert lifecycle.drawing_fingerprint(pretty) == lifecycle.drawing_fingerprint(
        ET.fromstring(SVG)
    )


@pytest.mark.integration
@pytest.mark.inkscape
async def test_saved_copy_renders_linked_images_from_new_directory(
    integration_config, tmp_path, monkeypatch
):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    destination_dir = tmp_path / "copy"
    destination_dir.mkdir()
    image = source_dir / "linked.png"
    Image.new("RGB", (10, 10), color=(20, 200, 40)).save(image)
    source = source_dir / "drawing.svg"
    source.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        'width="100" height="100"><image x="0" y="0" width="100" height="100" xlink:href="linked.png"/></svg>'
    )
    wrapper = InkscapeCliWrapper(integration_config)
    monkeypatch.setattr(
        lifecycle.document_sessions,
        "get_session",
        AsyncMock(return_value={"managed": True, "input_path": str(source)}),
    )

    async def native_snapshot(_wrapper, _config, path, _target):
        # Reproduce native SVG path rebasing without manipulating a GUI window.
        await wrapper.export_file(str(source), str(path), export_type="svg")
        return ET.parse(path).getroot()

    monkeypatch.setattr(lifecycle, "_snapshot", native_snapshot)
    destination = destination_dir / "saved.svg"
    result = await lifecycle.document_lifecycle(
        "save_copy", "test", str(destination), wrapper, integration_config
    )
    assert result["verified"]
    preview = destination_dir / "preview.png"
    await wrapper.export_file(str(destination), str(preview), dpi=96, export_area="page")
    with Image.open(preview) as rendered:
        assert rendered.convert("RGB").getpixel((50, 50)) == (20, 200, 40)
    assert source.read_text().find('xlink:href="linked.png"') > 0
