"""Failure-path regressions for native Inkscape processes and atomic exports."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest

from inkscape_mcp.cli_wrapper import InkscapeExecutionError
from inkscape_mcp.cli_wrapper import InkscapeTimeoutError

pytestmark = pytest.mark.asyncio
SVG = '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0L10 10"/></svg>'


class Process:
    def __init__(self, stdout=b"", stderr=b"", returncode=0):
        self.stdout_bytes = stdout
        self.stderr_bytes = stderr
        self.returncode = returncode
        self.killed = False
        self.reaped = False

    async def communicate(self):
        return self.stdout_bytes, self.stderr_bytes

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        self.reaped = True
        return self.returncode


async def test_warnings_do_not_contaminate_numeric_results(mock_cli_wrapper):
    process = Process(b"42\n", b"Gtk-WARNING: harmless font warning\n")
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
        result = await mock_cli_wrapper._execute_command(["inkscape", "--query-width"], 5)
    assert float(result) == 42


@pytest.mark.parametrize(
    "stderr",
    [
        b"InkscapeApplication::parse_actions: could not find action for: bogus\n",
        b"Error: cannot open output file\n",
        b"Emergency save activated!\n",
        b"Failed to load document\n",
        b"InkFileExportCmd::do_export: Unknown export type: wrong\n",
        b"action:object_trace: selection empty!\n",
    ],
)
async def test_native_errors_are_failures_even_with_zero_exit(mock_cli_wrapper, stderr):
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=Process(stderr=stderr))):
        with pytest.raises(InkscapeExecutionError):
            await mock_cli_wrapper._execute_command(["inkscape", "--version"], 5)


@pytest.mark.parametrize(
    "action",
    [
        "active-window-end",
        "select-all;active-window-start;export-do",
        "app.active-window-end",
        " active-window-end : ",
        "select-all\nquit",
    ],
)
@pytest.mark.parametrize("gui", [False, True])
async def test_unsafe_actions_rejected_before_spawn(mock_cli_wrapper, action, gui):
    args = ["inkscape", "--actions", action]
    if gui:
        args.append("--active-window")
    with patch("asyncio.create_subprocess_exec", AsyncMock()) as spawn:
        with pytest.raises(InkscapeExecutionError):
            await mock_cli_wrapper._execute_command(args, 5)
        spawn.assert_not_awaited()


@pytest.mark.parametrize(
    "failure", ["crash", "missing", "empty", "invalid_svg", "timeout", "cancel"]
)
async def test_failed_export_preserves_existing_destination(
    mock_cli_wrapper, sample_svg_file, tmp_path, failure
):
    destination = tmp_path / "existing.svg"
    destination.write_text(SVG)
    staged = []

    async def export(args, _timeout):
        target = Path(
            next(arg.partition("=")[2] for arg in args if arg.startswith("--export-filename="))
        )
        staged.append(target)
        if failure == "missing":
            target.unlink()
        elif failure == "invalid_svg":
            target.write_text("<svg")
        elif failure != "empty":
            target.write_text(SVG)
            if failure == "timeout":
                raise InkscapeTimeoutError("timed out")
            if failure == "cancel":
                raise asyncio.CancelledError
            raise InkscapeExecutionError("native crash")
        return ""

    mock_cli_wrapper._execute_command = AsyncMock(side_effect=export)
    exception = asyncio.CancelledError if failure == "cancel" else InkscapeExecutionError
    if failure == "timeout":
        exception = InkscapeTimeoutError
    with pytest.raises(exception):
        await mock_cli_wrapper.execute_actions(
            str(sample_svg_file), ["object-to-path"], str(destination)
        )
    assert destination.read_text() == SVG
    assert staged and all(not path.exists() for path in staged)


async def test_inplace_export_keeps_source_until_commit(mock_cli_wrapper, sample_svg_file):
    original = sample_svg_file.read_text()

    async def export(args, _timeout):
        assert sample_svg_file.read_text() == original
        target = Path(
            next(arg.partition("=")[2] for arg in args if arg.startswith("--export-filename="))
        )
        assert target != sample_svg_file
        assert target.parent == sample_svg_file.parent
        target.write_text(SVG)
        return ""

    mock_cli_wrapper._execute_command = AsyncMock(side_effect=export)
    await mock_cli_wrapper.execute_actions(
        str(sample_svg_file), ["object-to-path"], str(sample_svg_file)
    )
    assert sample_svg_file.read_text() == SVG


@pytest.mark.parametrize(
    "action",
    ["file-save", "file-save-as:/tmp/unmanaged.svg", "file-close", "export-filename:other.svg"],
)
async def test_managed_export_cannot_bypass_staging(
    mock_cli_wrapper, sample_svg_file, tmp_path, action
):
    mock_cli_wrapper._execute_command = AsyncMock()
    with pytest.raises(InkscapeExecutionError, match="managed output_path"):
        await mock_cli_wrapper.execute_actions(
            str(sample_svg_file), [action], str(tmp_path / "result.svg")
        )
    mock_cli_wrapper._execute_command.assert_not_awaited()


@pytest.mark.parametrize("cancel", [False, True])
async def test_interruption_kills_and_reaps_child(mock_cli_wrapper, cancel):
    started = asyncio.Event()
    killed = asyncio.Event()

    class HangingProcess(Process):
        async def communicate(self):
            started.set()
            await killed.wait()
            return b"", b""

        def kill(self):
            super().kill()
            killed.set()

    process = HangingProcess(returncode=None)
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
        task = asyncio.create_task(
            mock_cli_wrapper._execute_command(["inkscape", "--version"], 1 if cancel else 0.02)
        )
        await started.wait()
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else InkscapeTimeoutError):
            await task
    assert process.killed and process.reaped
    assert mock_cli_wrapper._slots._value == mock_cli_wrapper.config.max_concurrent_processes


@pytest.mark.parametrize("gui", [False, True])
async def test_concurrency_limits_and_gui_serialization(mock_cli_wrapper, gui):
    active = 0
    peak = 0
    commands = []

    class ConcurrentProcess(Process):
        async def communicate(self):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return b"ok", b""

    async def spawn(*args, **_kwargs):
        commands.append(args)
        return ConcurrentProcess()

    command = (
        ["inkscape", "--active-window", "--actions=select-all"]
        if gui
        else ["inkscape", "--version"]
    )
    with patch("asyncio.create_subprocess_exec", spawn):
        await asyncio.gather(*(mock_cli_wrapper._execute_command(command, 5) for _ in range(5)))
    assert peak == (1 if gui else mock_cli_wrapper.config.max_concurrent_processes)
    if gui:
        assert all("--batch-process" not in args for args in commands)
    else:
        tags = [next(a for a in args if a.startswith("--app-id-tag=")) for args in commands]
        assert len(set(tags)) == 5


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
async def test_invalid_timeout_is_rejected_before_spawn(mock_cli_wrapper, timeout):
    with patch("asyncio.create_subprocess_exec", AsyncMock()) as spawn:
        with pytest.raises(InkscapeExecutionError, match="Timeout"):
            await mock_cli_wrapper._execute_command(["inkscape", "--version"], timeout)
        spawn.assert_not_awaited()


@pytest.mark.parametrize("export_type", ["png", "pdf"])
async def test_truncated_binary_export_preserves_destination(
    mock_cli_wrapper, sample_svg_file, tmp_path, export_type
):
    destination = tmp_path / f"existing.{export_type}"
    original = b"previous user file"
    destination.write_bytes(original)

    async def export(args, _timeout):
        target = Path(
            next(arg.partition("=")[2] for arg in args if arg.startswith("--export-filename="))
        )
        target.write_bytes(
            b"%PDF-1.5\ntruncated" if export_type == "pdf" else b"\x89PNG\r\n\x1a\ntruncated"
        )
        return ""

    mock_cli_wrapper._execute_command = AsyncMock(side_effect=export)
    with pytest.raises(InkscapeExecutionError):
        await mock_cli_wrapper.export_file(str(sample_svg_file), str(destination), export_type)
    assert destination.read_bytes() == original
    assert not list(tmp_path.glob("inkscape-mcp-*"))
