"""
Unit tests for Inkscape vector operations tool.
"""

from unittest.mock import AsyncMock

import pytest

from inkscape_mcp.cli_wrapper import InkscapeCliWrapper
from inkscape_mcp.config import InkscapeConfig
from inkscape_mcp.tools.vector_operations import inkscape_vector


@pytest.fixture
def mock_wrapper():
    """Create a mock CLI wrapper. Async methods on the real class are auto-mocked as AsyncMock."""
    return AsyncMock(spec=InkscapeCliWrapper)


@pytest.fixture
def mock_config():
    """Create a lightweight real InkscapeConfig for vector operation tests."""
    return InkscapeConfig(inkscape_executable="mock_inkscape")


class TestInkscapeVectorTool:
    """Test the inkscape_vector portmanteau tool."""

    @pytest.mark.asyncio
    async def test_trace_image_success(self, mock_wrapper, mock_config, temp_file):
        """Test successful bitmap tracing (the real operation is 'trace_image')."""
        mock_wrapper._execute_actions.return_value = "Tracing completed"

        result = await inkscape_vector(
            operation="trace_image",
            input_path=str(temp_file),
            output_path="output.svg",
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )

        assert result["success"] is True
        assert "Traced bitmap" in result["message"]
        mock_wrapper._execute_actions.assert_called_once()

    @pytest.mark.asyncio
    async def test_trace_image_failure(self, mock_wrapper, mock_config, temp_file):
        """Test bitmap tracing failure surfaces the underlying CLI error."""
        mock_wrapper._execute_actions.side_effect = Exception("Error: Invalid image")

        result = await inkscape_vector(
            operation="trace_image",
            input_path=str(temp_file),
            output_path="output.svg",
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )

        assert result["success"] is False
        assert "Bitmap tracing failed" in result["message"]

    @pytest.mark.asyncio
    async def test_apply_boolean_union(self, mock_wrapper, mock_config, temp_file):
        """Test boolean union operation (real param name is operation_type, not boolean_type)."""
        mock_wrapper._execute_actions.return_value = "Union completed"

        result = await inkscape_vector(
            operation="apply_boolean",
            operation_type="union",
            object_ids=["rect1", "rect2"],
            input_path=str(temp_file),
            output_path="output.svg",
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )

        assert result["success"] is True
        assert "union" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_apply_boolean_difference(self, mock_wrapper, mock_config, temp_file):
        """Test boolean difference operation with select_all instead of object_ids."""
        mock_wrapper._execute_actions.return_value = "Difference completed"

        result = await inkscape_vector(
            operation="apply_boolean",
            operation_type="difference",
            select_all=True,
            input_path=str(temp_file),
            output_path="output.svg",
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )

        assert result["success"] is True
        assert "difference" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_apply_boolean_missing_selection(self, mock_wrapper, mock_config, temp_file):
        """Test apply_boolean rejects requests with neither object_ids nor select_all."""
        result = await inkscape_vector(
            operation="apply_boolean",
            operation_type="union",
            input_path=str(temp_file),
            output_path="output.svg",
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )

        assert result["success"] is False
        assert "select_all" in result["message"]

    @pytest.mark.asyncio
    async def test_measure_object_success(self, mock_wrapper, mock_config, temp_file):
        """Test successful object measurement (x, y, width, height queried in that order)."""
        mock_wrapper._execute_command.side_effect = ["10.0", "20.0", "100.0", "50.0"]

        result = await inkscape_vector(
            operation="measure_object",
            input_path=str(temp_file),
            object_id="rect1",
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )

        assert result["success"] is True
        assert result["data"]["x"] == 10.0
        assert result["data"]["width"] == 100.0

    @pytest.mark.asyncio
    async def test_measure_object_not_found(self, mock_wrapper, mock_config, temp_file):
        """Test measurement failure when the queried object doesn't exist."""
        mock_wrapper._execute_command.side_effect = Exception("Object 'nonexistent' not found")

        result = await inkscape_vector(
            operation="measure_object",
            input_path=str(temp_file),
            object_id="nonexistent",
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )

        assert result["success"] is False
        assert "not found" in result["message"]

    @pytest.mark.asyncio
    async def test_generate_barcode_qr(self, mock_wrapper, mock_config, tmp_path):
        """Test QR/barcode generation writes an SVG file directly (no CLI wrapper call)."""
        output_path = tmp_path / "qr.svg"

        result = await inkscape_vector(
            operation="generate_barcode_qr",
            output_path=str(output_path),
            barcode_data="test data",
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )

        assert result["success"] is True
        assert "test data" in result["message"]
        assert output_path.exists()

    @pytest.mark.asyncio
    async def test_generate_laser_dot(self, mock_wrapper, mock_config, tmp_path):
        """Test laser dot generation (Easter egg) writes an SVG file directly."""
        output_path = tmp_path / "laser.svg"

        result = await inkscape_vector(
            operation="generate_laser_dot",
            output_path=str(output_path),
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )

        assert result["success"] is True
        assert "laser dot" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_construct_svg_from_params(self, mock_wrapper, mock_config, tmp_path):
        """Test SVG construction from raw element params (real API takes params, not description)."""
        output_path = tmp_path / "constructed.svg"

        result = await inkscape_vector(
            operation="construct_svg",
            output_path=str(output_path),
            element_type="circle",
            params={"body": '<circle cx="50" cy="50" r="40" fill="blue"/>'},
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )

        assert result["success"] is True
        assert "Constructed SVG" in result["message"]
        assert "circle" in output_path.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_optimize_svg(self, mock_wrapper, mock_config, temp_file):
        """Test SVG optimization (vacuum defs + cleanup)."""
        mock_wrapper._execute_actions.return_value = "SVG optimized"

        result = await inkscape_vector(
            operation="optimize_svg",
            input_path=str(temp_file),
            output_path="optimized.svg",
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )

        assert result["success"] is True
        assert "Optimized" in result["message"]

    @pytest.mark.asyncio
    async def test_scour_svg(self, mock_wrapper, mock_config, temp_file):
        """Test the more aggressive scour_svg operation (separate from optimize_svg)."""
        mock_wrapper._execute_actions.return_value = "SVG scoured"

        result = await inkscape_vector(
            operation="scour_svg",
            input_path=str(temp_file),
            output_path="scoured.svg",
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )

        assert result["success"] is True
        assert "Scoured" in result["message"]

    @pytest.mark.asyncio
    async def test_path_simplify(self, mock_wrapper, mock_config, temp_file):
        """Test path simplification (there is no generic 'path_operations' operation)."""
        mock_wrapper._execute_actions.return_value = "Path simplified"

        result = await inkscape_vector(
            operation="path_simplify",
            object_id="path1",
            threshold=2.0,
            input_path=str(temp_file),
            output_path="result.svg",
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )

        assert result["success"] is True
        assert "Simplified" in result["message"]

    @pytest.mark.asyncio
    async def test_count_nodes(self, mock_wrapper, mock_config, temp_file):
        """Test node counting counts --query-all lines matching the object id."""
        mock_wrapper._execute_command.return_value = (
            "rect1,10,20,80,80\nrect1,10,20,80,80\ncircle1,0,0,10,10"
        )

        result = await inkscape_vector(
            operation="count_nodes",
            input_path=str(temp_file),
            object_id="rect1",
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )

        assert result["success"] is True
        assert result["data"]["node_count"] == 2

    @pytest.mark.asyncio
    async def test_export_dxf(self, mock_wrapper, mock_config, temp_file):
        """Test DXF export."""
        mock_wrapper._execute_actions.return_value = "DXF exported"

        result = await inkscape_vector(
            operation="export_dxf",
            input_path=str(temp_file),
            output_path="output.dxf",
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )

        assert result["success"] is True
        assert "exported successfully" in result["message"]

    @pytest.mark.asyncio
    async def test_layers_to_files(self, mock_wrapper, mock_config, temp_file, tmp_path):
        """Test layer separation (real API takes output_dir, not output_path)."""
        mock_wrapper._execute_command.return_value = "layer1,0,0,100,100\nlayer2,0,0,100,100"
        mock_wrapper._execute_actions.return_value = "exported"
        out_dir = tmp_path / "layers_out"

        result = await inkscape_vector(
            operation="layers_to_files",
            input_path=str(temp_file),
            output_dir=str(out_dir),
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )

        assert result["success"] is True
        assert len(result["data"]["exported"]) == 2
        assert mock_wrapper._execute_actions.call_count == 2

    @pytest.mark.asyncio
    async def test_fit_canvas_to_drawing(self, mock_wrapper, mock_config, temp_file):
        """Test canvas fitting."""
        mock_wrapper._execute_actions.return_value = "Canvas fitted"

        result = await inkscape_vector(
            operation="fit_canvas_to_drawing",
            input_path=str(temp_file),
            output_path="fitted.svg",
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )

        assert result["success"] is True
        assert "Canvas fitted" in result["message"]

    @pytest.mark.asyncio
    async def test_object_raise(self, mock_wrapper, mock_config, temp_file):
        """Test object raising (Z-order)."""
        mock_wrapper._execute_actions.return_value = "Object raised"

        result = await inkscape_vector(
            operation="object_raise",
            input_path=str(temp_file),
            object_id="rect1",
            output_path="raised.svg",
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )

        assert result["success"] is True
        assert "Raised object" in result["message"]

    @pytest.mark.asyncio
    async def test_object_lower(self, mock_wrapper, mock_config, temp_file):
        """Test object lowering (Z-order)."""
        mock_wrapper._execute_actions.return_value = "Object lowered"

        result = await inkscape_vector(
            operation="object_lower",
            input_path=str(temp_file),
            object_id="rect1",
            output_path="lowered.svg",
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )

        assert result["success"] is True
        assert "Lowered object" in result["message"]

    @pytest.mark.asyncio
    async def test_set_document_units(self, mock_wrapper, mock_config, temp_file):
        """Test document units setting."""
        mock_wrapper._execute_actions.return_value = "Units set"

        result = await inkscape_vector(
            operation="set_document_units",
            input_path=str(temp_file),
            units="mm",
            output_path="units_set.svg",
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )

        assert result["success"] is True
        assert "unit hint 'mm'" in result["message"]

    @pytest.mark.asyncio
    async def test_invalid_operation(self, mock_wrapper, mock_config):
        """Test invalid/unknown operation handling falls through to the not-implemented branch."""
        result = await inkscape_vector(
            operation="invalid_operation", cli_wrapper=mock_wrapper, config=mock_config
        )

        assert result["success"] is False
        assert "not yet implemented" in result["message"]


class TestVectorOperationsErrorHandling:
    """Test error handling in vector operations."""

    @pytest.mark.asyncio
    async def test_wrapper_not_provided(self):
        """cli_wrapper=None surfaces as a failed result rather than an unhandled exception."""
        result = await inkscape_vector(operation="trace_image")

        assert result["success"] is False
        assert result["error"]

    @pytest.mark.asyncio
    async def test_config_not_provided(self, mock_wrapper):
        """config=None surfaces as a failed result rather than an unhandled exception."""
        result = await inkscape_vector(operation="trace_image", cli_wrapper=mock_wrapper)

        assert result["success"] is False
        assert result["error"]

    @pytest.mark.asyncio
    async def test_file_not_found(self, mock_wrapper, mock_config):
        """Test that a FileNotFoundError from the CLI wrapper surfaces in the failure message."""
        mock_wrapper._execute_actions.side_effect = FileNotFoundError("File not found")

        result = await inkscape_vector(
            operation="trace_image",
            input_path="/nonexistent/file.png",
            output_path="output.svg",
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )

        assert result["success"] is False
        assert "File not found" in result["message"]


class TestVectorOperationsIntegration:
    """Integration tests for vector operations."""

    @pytest.mark.asyncio
    async def test_workflow_chain(self, mock_wrapper, mock_config, sample_svg_file):
        """Test a complete workflow chain: measure, boolean-union, then optimize."""
        mock_wrapper._execute_actions.return_value = "Operation successful"
        mock_wrapper._execute_command.side_effect = ["10", "20", "100", "50"]

        measure_result = await inkscape_vector(
            operation="measure_object",
            input_path=str(sample_svg_file),
            object_id="rect1",
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )
        assert measure_result["success"] is True

        boolean_result = await inkscape_vector(
            operation="apply_boolean",
            operation_type="union",
            select_all=True,
            input_path=str(sample_svg_file),
            output_path="union_result.svg",
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )
        assert boolean_result["success"] is True

        optimize_result = await inkscape_vector(
            operation="optimize_svg",
            input_path="union_result.svg",
            output_path="optimized.svg",
            cli_wrapper=mock_wrapper,
            config=mock_config,
        )
        assert optimize_result["success"] is True

        # Verify all operations were called
        assert mock_wrapper._execute_actions.call_count == 2  # boolean + optimize
        assert mock_wrapper._execute_command.call_count == 4  # measure (x, y, width, height)
