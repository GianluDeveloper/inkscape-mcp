"""Regressions for document-safe action chains and file operation failures."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkscape_mcp.tools.file_operations import inkscape_file
from inkscape_mcp.tools.vector_operations import inkscape_vector


@pytest.fixture
def action_config():
    return SimpleNamespace(inkscape_executable="inkscape", process_timeout=10)


@pytest.fixture
def svg_path(tmp_path):
    source = tmp_path / "input.svg"
    source.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
        '<rect id="shape" width="10" height="10"/></svg>',
        encoding="utf-8",
    )
    return source


@pytest.mark.asyncio
async def test_trace_does_not_reopen_save_or_close_active_document(
    action_config, svg_path, tmp_path
):
    wrapper = AsyncMock()
    output = tmp_path / "output;with delimiter.svg"
    result = await inkscape_vector(
        operation="trace_image",
        input_path=str(svg_path),
        output_path=str(output),
        cli_wrapper=wrapper,
        config=action_config,
    )
    assert result["success"]
    call = wrapper._execute_actions.call_args.kwargs
    assert call["output_path"] == str(output)
    assert call["actions"] == [
        "select-by-element:image",
        "object-trace:8,true,true,false,2,1,0.2",
        "export-type:svg",
        "export-do",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("boolean_type", ["union", "difference", "intersection", "exclusion"])
async def test_boolean_uses_registered_headless_actions(
    boolean_type, action_config, svg_path, tmp_path
):
    wrapper = AsyncMock()
    output = tmp_path / "union;output.svg"
    result = await inkscape_vector(
        operation="apply_boolean",
        operation_type=boolean_type,
        select_all=True,
        input_path=str(svg_path),
        output_path=str(output),
        cli_wrapper=wrapper,
        config=action_config,
    )
    assert result["success"]
    call = wrapper._execute_actions.call_args.kwargs
    assert f"path-{boolean_type}" in call["actions"]
    assert "export-filename" not in call["actions"]
    assert call["output_path"] == str(output)


@pytest.mark.asyncio
async def test_simplify_uses_parameterless_registered_action(action_config, svg_path, tmp_path):
    wrapper = AsyncMock()
    result = await inkscape_vector(
        operation="path_simplify",
        object_id="shape",
        input_path=str(svg_path),
        output_path=str(tmp_path / "simplified.svg"),
        cli_wrapper=wrapper,
        config=action_config,
    )
    assert result["success"]
    assert "path-simplify" in wrapper._execute_actions.call_args.kwargs["actions"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["path_clean", "optimize_svg", "scour_svg"])
async def test_cleanup_uses_vacuum_flag_instead_of_unknown_actions(
    operation, action_config, svg_path, tmp_path
):
    wrapper = AsyncMock()
    result = await inkscape_vector(
        operation=operation,
        input_path=str(svg_path),
        output_path=str(tmp_path / "clean.svg"),
        cli_wrapper=wrapper,
        config=action_config,
    )
    assert result["success"]
    call = wrapper._execute_actions.call_args.kwargs
    assert call["vacuum_defs"] is True
    assert "file-vacuum-defs" not in call["actions"]
    assert "file-cleanup" not in call["actions"]


@pytest.mark.asyncio
async def test_save_uses_svg_export_without_gui_save(action_config, svg_path, tmp_path):
    wrapper = AsyncMock()
    output = tmp_path / "saved;document.svg"
    result = await inkscape_file(
        operation="save",
        input_path=str(svg_path),
        output_path=str(output),
        cli_wrapper=wrapper,
        config=action_config,
    )
    assert result["success"]
    call = wrapper._execute_actions.call_args.kwargs
    assert call["actions"] == ["export-type:svg", "export-do"]
    assert call["output_path"] == str(output)


@pytest.mark.asyncio
async def test_convert_normalizes_format_and_preserves_wrapper_failure(
    action_config, svg_path, tmp_path
):
    wrapper = AsyncMock()
    wrapper._execute_actions.side_effect = RuntimeError("Inkscape failed to produce output")
    result = await inkscape_file(
        operation="convert",
        input_path=str(svg_path),
        output_path=str(tmp_path / "output.png"),
        format="PNG",
        cli_wrapper=wrapper,
        config=action_config,
    )
    assert not result["success"]
    assert "failed to produce output" in result["message"]
    assert wrapper._execute_actions.call_args.kwargs["actions"] == ["export-type:png", "export-do"]


@pytest.mark.asyncio
@pytest.mark.parametrize("format_name", ["", "ai", "cdr", "svg;file-close"])
async def test_convert_rejects_unsupported_formats(format_name, action_config, svg_path, tmp_path):
    wrapper = AsyncMock()
    result = await inkscape_file(
        operation="convert",
        input_path=str(svg_path),
        output_path=str(tmp_path / "output.svg"),
        format=format_name,
        cli_wrapper=wrapper,
        config=action_config,
    )
    assert not result["success"]
    wrapper._execute_actions.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_formats_needs_no_input_file():
    result = await inkscape_file(operation="list_formats")
    assert result["success"]
    assert "svg" in result["data"]["formats"]
    assert "ai" not in result["data"]["formats"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation", ["trace_image", "apply_boolean", "object_to_path", "optimize_svg"]
)
async def test_file_edits_require_explicit_output_path(operation, action_config, svg_path):
    wrapper = AsyncMock()
    result = await inkscape_vector(
        operation=operation,
        input_path=str(svg_path),
        cli_wrapper=wrapper,
        config=action_config,
    )
    assert not result["success"]
    assert "output_path" in result["message"]
    wrapper._execute_actions.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("stdout", ["", "nan", "inf", "Failed to open file"])
async def test_validate_rejects_empty_or_invalid_cli_output(stdout, action_config, svg_path):
    wrapper = AsyncMock()
    wrapper._execute_command.return_value = stdout
    result = await inkscape_file(
        operation="validate",
        input_path=str(svg_path),
        cli_wrapper=wrapper,
        config=action_config,
    )
    assert not result["success"]
    assert not result["data"]["valid"]


@pytest.mark.asyncio
@pytest.mark.parametrize("document", ["<svg", "<html/>"])
async def test_validate_rejects_invalid_svg_before_native_process(
    document, action_config, svg_path
):
    svg_path.write_text(document, encoding="utf-8")
    wrapper = AsyncMock()
    result = await inkscape_file(
        operation="validate",
        input_path=str(svg_path),
        cli_wrapper=wrapper,
        config=action_config,
    )
    assert not result["success"]
    wrapper._execute_command.assert_not_awaited()
