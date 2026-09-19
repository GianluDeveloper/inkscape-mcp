"""Runtime regressions against a real, isolated Inkscape installation."""

import asyncio
import logging
import re
import xml.etree.ElementTree as ET

import pytest
from fastmcp import Client
from PIL import Image

from inkscape_mcp.cli_wrapper import InkscapeCliWrapper
from inkscape_mcp.cli_wrapper import InkscapeExecutionError
from inkscape_mcp.main import InkscapeMCPServer
from inkscape_mcp.shell_wrapper import ShellModePool
from inkscape_mcp.shell_wrapper import ShellModeWrapper
from inkscape_mcp.tools.system import inkscape_system

pytestmark = [pytest.mark.integration, pytest.mark.inkscape, pytest.mark.asyncio]

SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"
 viewBox="0 0 100 100"><rect id="target" x="10" y="20" width="30" height="40"
 fill="red"/></svg>"""


@pytest.fixture
def runtime_wrapper(integration_config):
    return InkscapeCliWrapper(integration_config)


@pytest.fixture
def drawing(tmp_path):
    # Spaces and non-ASCII names exercise argument handling on real subprocesses.
    path = tmp_path / "disegno è 测试.svg"
    path.write_text(SVG, encoding="utf-8")
    return path


@pytest.mark.parametrize("export_type", ["png", "pdf", "svg"])
async def test_export_produces_readable_artifact(runtime_wrapper, drawing, tmp_path, export_type):
    output = tmp_path / f"risultato è.{export_type}"
    await runtime_wrapper.export_file(
        str(drawing), str(output), export_type=export_type, dpi=96, export_area="page"
    )

    assert drawing.read_text(encoding="utf-8") == SVG
    assert output.stat().st_size > 0
    if export_type == "png":
        with Image.open(output) as image:
            image.load()
            assert image.size == (100, 100)
            assert image.convert("RGB").getpixel((20, 30)) == (255, 0, 0)
    elif export_type == "pdf":
        assert output.read_bytes().startswith(b"%PDF-")
    else:
        assert ET.parse(output).getroot().tag == "{http://www.w3.org/2000/svg}svg"


async def test_actions_save_transformed_svg_without_changing_input(
    runtime_wrapper, drawing, tmp_path, caplog
):
    output = tmp_path / "converted.svg"
    actions = ["select-by-id:target", "object-to-path"]

    with caplog.at_level(logging.WARNING, logger="inkscape_mcp.cli_wrapper"):
        await runtime_wrapper.execute_actions(str(drawing), actions, str(output))

    root = ET.parse(output).getroot()
    assert root.find(".//{http://www.w3.org/2000/svg}path[@id='target']") is not None
    assert root.find(".//{http://www.w3.org/2000/svg}rect[@id='target']") is None
    assert drawing.read_text(encoding="utf-8") == SVG
    assert actions == ["select-by-id:target", "object-to-path"]
    assert "Unknown export type" not in caplog.text
    assert "No export type specified" not in caplog.text


@pytest.mark.parametrize("use_actions", [False, True])
async def test_saved_svg_keeps_linked_images_when_output_directory_changes(
    runtime_wrapper, tmp_path, use_actions
):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    output_dir = tmp_path / "destination"
    output_dir.mkdir()
    Image.new("RGB", (10, 10), color=(0, 255, 0)).save(source_dir / "linked.png")
    source = source_dir / "drawing.svg"
    source_content = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        'width="100" height="100"><image x="0" y="0" width="100" height="100" '
        'xlink:href="linked.png"/></svg>'
    )
    source.write_text(source_content, encoding="utf-8")
    output = output_dir / "saved.svg"
    if use_actions:
        await runtime_wrapper.execute_actions(str(source), ["select-all"], str(output))
    else:
        await runtime_wrapper.export_file(str(source), str(output), export_type="svg")
    preview = output_dir / "preview.png"
    await runtime_wrapper.export_file(str(output), str(preview), dpi=96, export_area="page")

    with Image.open(preview) as image:
        assert image.convert("RGB").getpixel((50, 50)) == (0, 255, 0)
    assert source.read_text(encoding="utf-8") == source_content


async def test_actions_can_replace_input_atomically(runtime_wrapper, drawing):
    await runtime_wrapper.execute_actions(
        str(drawing), ["select-by-id:target", "object-to-path"], str(drawing)
    )

    root = ET.parse(drawing).getroot()
    assert root.find(".//{http://www.w3.org/2000/svg}path[@id='target']") is not None


@pytest.mark.parametrize("query_type", ["bbox", "all"])
async def test_bbox_queries_return_only_numeric_output(runtime_wrapper, drawing, query_type):
    output = await runtime_wrapper.query_object(str(drawing), "target", query_type)

    assert [float(value) for value in re.split(r"[,\s]+", output.strip())] == [10, 20, 30, 40]


@pytest.mark.parametrize("query_type", ["bbox", "x", "all"])
async def test_missing_object_is_not_silently_replaced_by_drawing_bounds(
    runtime_wrapper, drawing, query_type
):
    with pytest.raises(InkscapeExecutionError):
        await runtime_wrapper.query_object(str(drawing), "missing-object", query_type)


async def test_cancelled_native_process_is_reaped_and_destination_preserved(
    runtime_wrapper, drawing, tmp_path, monkeypatch
):
    spawned = asyncio.Event()
    processes = []
    original_spawn = asyncio.create_subprocess_exec

    async def record_process(*args, **kwargs):
        process = await original_spawn(*args, **kwargs)
        processes.append(process)
        spawned.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", record_process)
    destination = tmp_path / "existing.png"
    destination.write_bytes(b"original destination")
    task = asyncio.create_task(runtime_wrapper.export_file(str(drawing), str(destination), dpi=96))
    try:
        await asyncio.wait_for(spawned.wait(), timeout=10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert len(processes) == 1
    assert processes[0].returncode is not None
    assert destination.read_bytes() == b"original destination"
    assert not list(tmp_path.glob(".inkscape-mcp-*"))


async def test_concurrent_exports_remain_separate(runtime_wrapper, tmp_path):
    async def export(index):
        source = tmp_path / f"source-{index}.svg"
        color = "red" if index % 2 == 0 else "blue"
        source.write_text(SVG.replace('fill="red"', f'fill="{color}"'), encoding="utf-8")
        output = tmp_path / f"result-{index}.png"
        await runtime_wrapper.export_file(str(source), str(output), dpi=96, export_area="page")
        with Image.open(output) as image:
            expected = (255, 0, 0) if color == "red" else (0, 0, 255)
            assert image.convert("RGB").getpixel((20, 30)) == expected

    await asyncio.gather(*(export(index) for index in range(4)))


async def test_invalid_actions_report_failure_and_preserve_destination(
    runtime_wrapper, drawing, tmp_path
):
    output = tmp_path / "existing.svg"
    output.write_text(SVG, encoding="utf-8")

    with pytest.raises(InkscapeExecutionError):
        await runtime_wrapper.execute_actions(
            str(drawing), ["nonexistent-mcp-regression-action"], str(output)
        )

    assert output.read_text(encoding="utf-8") == SVG


@pytest.mark.parametrize(
    "action",
    ["active-window-start;select-all", "select-all;active-window-end", "app.active-window-end"],
)
async def test_internal_gui_actions_return_structured_errors_without_launching_process(
    runtime_wrapper, integration_config, monkeypatch, action
):
    async def unexpected_process(*_args, **_kwargs):
        pytest.fail("An internal bridge action must be rejected before reaching Inkscape")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", unexpected_process)
    result = await inkscape_system(
        operation="hands_in_command",
        action=action,
        cli_wrapper=runtime_wrapper,
        config=integration_config,
    )

    assert result["success"] is False
    assert result["operation"] == "hands_in_command"
    assert "internal Inkscape action" in result["error"]


async def test_public_mcp_tools_convert_and_report_native_failures(
    runtime_wrapper, integration_config, drawing, tmp_path, monkeypatch
):
    server = InkscapeMCPServer()
    server.config = integration_config
    server.cli_wrapper = runtime_wrapper
    server._register_portmanteau_tools()
    original_spawn = asyncio.create_subprocess_exec

    async def batch_only_process(*args, **kwargs):
        if "--active-window" in args or "-q" in args:
            pytest.fail("Rejected bridge actions must never reach the running GUI")
        return await original_spawn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", batch_only_process)
    raster = tmp_path / "mcp-export.png"
    destination = tmp_path / "mcp-existing.svg"
    destination.write_text(SVG, encoding="utf-8")

    async with Client(server.mcp) as client:
        converted = await client.call_tool(
            "inkscape_file",
            {
                "operation": "convert",
                "input_path": str(drawing),
                "output_path": str(raster),
                "format": "png",
            },
        )
        failed = await client.call_tool(
            "inkscape_vector",
            {
                "operation": "object_to_path",
                "input_path": str(drawing),
                "output_path": str(destination),
                "object_id": "missing-object",
            },
        )
        rejected = await client.call_tool(
            "inkscape_system",
            {"operation": "hands_in_command", "action": "active-window-end"},
        )

    assert converted.data["success"] is True
    assert converted.data["operation"] == "convert"
    with Image.open(raster) as image:
        image.verify()
    assert failed.data["success"] is False
    assert failed.data["operation"] == "object_to_path"
    assert "missing-object" in failed.data["error"]
    assert destination.read_text(encoding="utf-8") == SVG
    assert rejected.data["success"] is False
    assert rejected.data["operation"] == "hands_in_command"
    assert "internal Inkscape action" in rejected.data["error"]


async def test_shell_pipeline_exports_complete_svg(integration_config, drawing, tmp_path):
    output = tmp_path / "shell.svg"
    async with ShellModeWrapper(str(integration_config.inkscape_executable)) as shell:
        await shell.run_full_pipeline(
            str(drawing), str(output), ["select-by-id:target", "object-to-path"]
        )
        assert shell.is_running
        assert (
            ET.parse(output).getroot().find(".//{http://www.w3.org/2000/svg}path[@id='target']")
            is not None
        )

    assert not shell.is_running
    assert drawing.read_text(encoding="utf-8") == SVG


async def test_shell_pool_concurrent_documents_are_isolated(integration_config, tmp_path):
    pool = ShellModePool(str(integration_config.inkscape_executable), size=2)
    await pool.start()
    both_acquired = asyncio.Event()
    pids = set()

    async def transform(index):
        source = tmp_path / f"pool-source-{index}.svg"
        source.write_text(SVG.replace('id="target"', f'id="target{index}"'), encoding="utf-8")
        output = tmp_path / f"pool-output-{index}.svg"
        async with pool.acquire() as shell:
            assert shell.pid not in pids, "Two concurrent borrowers received the same shell"
            pids.add(shell.pid)
            if len(pids) == 2:
                both_acquired.set()
            await asyncio.wait_for(both_acquired.wait(), timeout=10)
            await shell.run_full_pipeline(
                str(source), str(output), ["select-all", "object-to-path"]
            )
        root = ET.parse(output).getroot()
        assert root.find(f".//{{http://www.w3.org/2000/svg}}path[@id='target{index}']") is not None
        assert root.find(f".//*[@id='target{1 - index}']") is None

    try:
        await asyncio.gather(transform(0), transform(1))
    finally:
        await pool.close()
