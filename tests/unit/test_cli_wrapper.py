"""
Unit tests for Inkscape CLI wrapper module.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest
from PIL import Image

from inkscape_mcp.cli_wrapper import InkscapeCliError
from inkscape_mcp.cli_wrapper import InkscapeCliWrapper
from inkscape_mcp.cli_wrapper import InkscapeExecutionError
from inkscape_mcp.cli_wrapper import InkscapeTimeoutError


class _FakeProcess:
    """Stand-in for the asyncio subprocess object returned by create_subprocess_exec."""

    def __init__(self, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.killed = False

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True

    async def wait(self):
        return None


SVG = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'


async def _write_export(command, _timeout):
    target = next(arg.partition("=")[2] for arg in command if arg.startswith("--export-filename="))
    if Path(target).suffix == ".png":
        Image.new("RGB", (2, 2)).save(target)
    else:
        Path(target).write_text(SVG)
    return ""


class TestInkscapeCliWrapper:
    """Test InkscapeCliWrapper class functionality."""

    def test_initialization(self, mock_inkscape_config):
        """Test wrapper initializes correctly."""
        wrapper = InkscapeCliWrapper(mock_inkscape_config)

        assert wrapper.config == mock_inkscape_config
        assert wrapper.config.inkscape_executable.endswith("inkscape.exe")

    def test_initialization_invalid_config(self):
        """Test initialization with invalid config raises InkscapeCliError."""
        with pytest.raises(InkscapeCliError):
            InkscapeCliWrapper(None)

    @pytest.mark.asyncio
    async def test_execute_command_success(self, mock_cli_wrapper):
        """Test successful command execution."""
        fake_process = _FakeProcess(returncode=0, stdout=b"test output", stderr=b"")

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fake_process)):
            result = await mock_cli_wrapper._execute_command(["--version"], timeout=5)

        assert result == "test output"

    @pytest.mark.asyncio
    async def test_execute_command_failure(self, mock_cli_wrapper):
        """Test failed command execution raises InkscapeExecutionError."""
        fake_process = _FakeProcess(returncode=1, stdout=b"", stderr=b"Error: bad option")

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fake_process)):
            with pytest.raises(InkscapeExecutionError):
                await mock_cli_wrapper._execute_command(["--invalid-option"], timeout=5)

    @pytest.mark.asyncio
    async def test_execute_command_timeout(self, mock_cli_wrapper):
        """Test command execution timeout raises InkscapeTimeoutError."""
        fake_process = _FakeProcess(returncode=0)

        with (
            patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fake_process)),
            patch("asyncio.wait_for", AsyncMock(side_effect=TimeoutError)),
        ):
            with pytest.raises(InkscapeTimeoutError):
                await mock_cli_wrapper._execute_command(["--version"], timeout=0.001)

        assert fake_process.killed is True

    @pytest.mark.asyncio
    async def test_execute_actions_success(self, mock_cli_wrapper, sample_svg_file):
        """Test successful actions execution."""
        mock_cli_wrapper._execute_command = AsyncMock(return_value="Actions executed successfully")

        result = await mock_cli_wrapper.execute_actions(
            input_path=str(sample_svg_file), actions=["select-all", "export-do"]
        )

        assert result == "Actions executed successfully"
        mock_cli_wrapper._execute_command.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "actions",
        [
            ["select-all", "object-to-path"],
            ["select-all", "object-to-path", "export-do"],
            ["select-all;object-to-path;export-do"],
        ],
    )
    async def test_execute_actions_with_export(
        self, mock_cli_wrapper, sample_svg_file, tmp_path, actions
    ):
        """Export actions stay separate from the filename and run exactly once."""
        mock_cli_wrapper._execute_command = AsyncMock(return_value="")
        original_actions = actions.copy()
        output_path = str(tmp_path / "output image.svg")
        mock_cli_wrapper._execute_command.side_effect = _write_export

        await mock_cli_wrapper.execute_actions(
            input_path=str(sample_svg_file),
            actions=actions,
            output_path=output_path,
        )

        cmd_args = mock_cli_wrapper._execute_command.call_args.args[0]
        target = Path(
            next(arg.partition("=")[2] for arg in cmd_args if arg.startswith("--export-filename="))
        )
        assert target.parent == tmp_path
        assert target != Path(output_path)
        assert Path(output_path).read_text() == SVG
        assert not target.exists()
        assert "--actions=select-all;object-to-path" in cmd_args
        assert "--no-remote-resources" not in cmd_args
        assert actions == original_actions

    @pytest.mark.asyncio
    async def test_execute_verbs_uses_actions_api(self, mock_cli_wrapper, sample_svg_file):
        """Legacy verb commands must not include the unsupported remote-resource flag."""
        mock_cli_wrapper._execute_command = AsyncMock(return_value="")

        await mock_cli_wrapper.execute_verbs(str(sample_svg_file), ["EditSelectAll"])

        cmd_args = mock_cli_wrapper._execute_command.call_args.args[0]
        assert "--batch-process" in cmd_args
        assert "--verb" not in cmd_args
        assert "--actions=select-all" in cmd_args
        assert "--no-remote-resources" not in cmd_args

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["execute_actions", "execute_verbs"])
    async def test_batch_commands_use_distinct_application_ids(
        self, mock_cli_wrapper, sample_svg_file, method
    ):
        """Concurrent batch jobs must not be forwarded to each other or the open GUI."""
        mock_cli_wrapper._execute_command = AsyncMock(return_value="")

        await asyncio.gather(
            *(
                getattr(mock_cli_wrapper, method)(str(sample_svg_file), ["select-all"])
                for _ in range(3)
            )
        )

        application_ids = []
        for call in mock_cli_wrapper._execute_command.call_args_list:
            command = call.args[0]
            assert "--batch-process" in command
            tags = [arg for arg in command if arg.startswith("--app-id-tag=")]
            assert len(tags) == 1
            assert tags[0].startswith("--app-id-tag=inkscape-mcp-")
            application_ids.append(tags[0])
        assert len(set(application_ids)) == 3

    @pytest.mark.asyncio
    async def test_export_file_success(self, mock_cli_wrapper, temp_file, tmp_path):
        """Test successful file export builds the expected CLI arguments."""
        mock_cli_wrapper._execute_command = AsyncMock(return_value="")

        mock_cli_wrapper._execute_command.side_effect = _write_export
        result = await mock_cli_wrapper.export_file(
            input_path=str(temp_file),
            output_path=str(tmp_path / "output.png"),
            export_type="png",
            dpi=300,
        )

        assert result == ""
        cmd_args = mock_cli_wrapper._execute_command.call_args.args[0]
        assert "--export-dpi" in cmd_args
        assert "300" in cmd_args
        assert "--export-area-drawing" in cmd_args

    @pytest.mark.asyncio
    async def test_export_file_rejects_unknown_format(self, mock_cli_wrapper, temp_file):
        mock_cli_wrapper._execute_command = AsyncMock(return_value="")
        with pytest.raises(InkscapeExecutionError, match="Unsupported"):
            await mock_cli_wrapper.export_file(
                str(temp_file), "output.invalid", export_type="invalid"
            )
        mock_cli_wrapper._execute_command.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_query_object_success(self, mock_cli_wrapper, sample_svg_file):
        """Test object querying returns the raw CLI output string (no parsing)."""
        mock_cli_wrapper._execute_command = AsyncMock(return_value="10,20,100,50")

        result = await mock_cli_wrapper.query_object(
            input_path=str(sample_svg_file), object_id="rect1", query_type="bbox"
        )

        assert result == "10,20,100,50"
        cmd_args = mock_cli_wrapper._execute_command.call_args.args[0]
        assert "--query-id" in cmd_args
        assert "rect1" in cmd_args
        assert "--query-bbox" not in cmd_args
        assert all(f"--query-{axis}" in cmd_args for axis in ("x", "y", "width", "height"))

    @pytest.mark.asyncio
    async def test_query_object_width_query_type(self, mock_cli_wrapper, sample_svg_file):
        """Test that query_type='width' selects the --query-width flag."""
        mock_cli_wrapper._execute_command = AsyncMock(return_value="42")

        result = await mock_cli_wrapper.query_object(
            input_path=str(sample_svg_file), object_id="rect1", query_type="width"
        )

        assert result == "42"
        cmd_args = mock_cli_wrapper._execute_command.call_args.args[0]
        assert "--query-width" in cmd_args


class TestInkscapeCliError:
    """Test custom exception classes."""

    def test_cli_error_creation(self):
        """Test InkscapeCliError creation."""
        error = InkscapeCliError("Test error message")
        assert str(error) == "Test error message"
        assert isinstance(error, Exception)

    def test_timeout_error_creation(self):
        """Test InkscapeTimeoutError creation."""
        error = InkscapeTimeoutError("Timeout occurred")
        assert str(error) == "Timeout occurred"
        assert isinstance(error, InkscapeCliError)

    def test_execution_error_creation(self):
        """Test InkscapeExecutionError creation."""
        error = InkscapeExecutionError("Execution failed")
        assert str(error) == "Execution failed"
        assert isinstance(error, InkscapeCliError)


class TestCliWrapperIntegration:
    """Integration tests for CLI wrapper functionality."""

    @pytest.mark.asyncio
    async def test_full_workflow(self, mock_cli_wrapper, temp_svg_content, temp_file):
        """Test a complete workflow from file creation to querying object dimensions."""
        temp_file.write_text(temp_svg_content)
        mock_cli_wrapper._execute_command = AsyncMock(return_value="10,20,80,80")

        result = await mock_cli_wrapper.query_object(
            input_path=str(temp_file), object_id="rect1", query_type="bbox"
        )

        assert result == "10,20,80,80"

    @pytest.mark.asyncio
    async def test_error_handling_chain(self, mock_cli_wrapper):
        """Test error handling through the call chain."""
        # A missing executable at process-spawn time surfaces as InkscapeExecutionError
        with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=FileNotFoundError)):
            with pytest.raises(InkscapeExecutionError):
                await mock_cli_wrapper._execute_command(["--version"], timeout=5)

        # A nonzero return code also raises InkscapeExecutionError
        fake_process = _FakeProcess(returncode=1, stdout=b"", stderr=b"Inkscape error")
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fake_process)):
            with pytest.raises(InkscapeExecutionError):
                await mock_cli_wrapper._execute_command(["--invalid"], timeout=5)

    @pytest.mark.asyncio
    async def test_concurrent_operations(self, mock_cli_wrapper):
        """Test concurrent operations don't interfere."""

        async def mock_operation(task_id: int):
            fake_process = _FakeProcess(returncode=0, stdout=f"Task {task_id} completed".encode())
            with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fake_process)):
                return await mock_cli_wrapper._execute_command(["--version"], timeout=5)

        results = await asyncio.gather(*[mock_operation(i) for i in range(3)])

        assert len(results) == 3
        assert all("completed" in r for r in results)
