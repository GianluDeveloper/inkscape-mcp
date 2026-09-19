"""Shell protocol and process lifecycle regression tests."""

import asyncio
import sys
from unittest.mock import AsyncMock

import pytest

from inkscape_mcp.shell_wrapper import ShellModeError
from inkscape_mcp.shell_wrapper import ShellModePool
from inkscape_mcp.shell_wrapper import ShellModeWrapper


class FakeInput:
    def __init__(self, process):
        self.process = process
        self.writes = []
        self.block_drain = False

    def write(self, value):
        self.writes.append(value)
        if value == b"quit\n":
            self.process.finish(0)
        elif self.process.respond:
            self.process.stdout.feed_data(value + b"> ")

    async def drain(self):
        if self.block_drain:
            await asyncio.Event().wait()

    def close(self):
        pass


class FakeProcess:
    def __init__(self, *, prompt=True, respond=True):
        self.pid = 1234
        self.returncode = None
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdin = FakeInput(self)
        self.respond = respond
        self.killed = False
        self.waited = False
        self.exited = asyncio.Event()
        if prompt:
            self.stdout.feed_data(b"Inkscape interactive shell\n> ")

    def finish(self, code):
        if self.returncode is None:
            self.returncode = code
            self.stdout.feed_eof()
            self.stderr.feed_eof()
            self.exited.set()

    def kill(self):
        self.killed = True
        self.finish(-9)

    async def wait(self):
        await self.exited.wait()
        self.waited = True
        return self.returncode


@pytest.fixture
def spawn(monkeypatch):
    factory = AsyncMock()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", factory)
    return factory


async def test_isolated_process_and_graceful_close(spawn):
    process = FakeProcess()
    spawn.return_value = process
    async with ShellModeWrapper(sys.executable) as shell:
        assert await shell.run_actions("select-all", "path-union") == "select-all;path-union"
        args = spawn.call_args.args
        assert "--batch-process" in args
        assert any(arg.startswith("--app-id-tag=inkscape_mcp_") for arg in args)
        assert spawn.call_args.kwargs["stderr"] == asyncio.subprocess.STDOUT
    assert process.waited
    assert not shell.is_running
    assert not process.killed


async def test_timeout_during_stdin_drain_invalidates_session(spawn):
    process = FakeProcess()
    spawn.return_value = process
    shell = ShellModeWrapper(sys.executable, timeout=0.01)
    await shell.start()
    process.stdin.block_drain = True
    with pytest.raises(ShellModeError, match="timeout"):
        await shell.run_actions("select-all")
    assert process.killed and process.waited
    assert not shell.is_running
    with pytest.raises(ShellModeError, match="not running"):
        await shell.run_actions("select-all")


async def test_timeout_waiting_for_response_invalidates_session(spawn):
    process = FakeProcess(respond=False)
    spawn.return_value = process
    shell = ShellModeWrapper(sys.executable, timeout=0.01)
    await shell.start()
    with pytest.raises(ShellModeError, match="timeout"):
        await shell.run_actions("select-all")
    assert process.killed and process.waited


async def test_startup_timeout_reaps_child(spawn):
    process = FakeProcess(prompt=False)
    spawn.return_value = process
    shell = ShellModeWrapper(sys.executable, startup_timeout=0.01)
    with pytest.raises(ShellModeError, match="failed to start"):
        await shell.start()
    assert process.killed and process.waited
    assert not shell.is_running


@pytest.mark.parametrize("during_startup", [False, True])
async def test_cancellation_reaps_child(spawn, during_startup):
    process = FakeProcess(prompt=not during_startup, respond=False)
    spawn.return_value = process
    shell = ShellModeWrapper(sys.executable)
    if during_startup:
        task = asyncio.create_task(shell.start())
        while not spawn.await_count:
            await asyncio.sleep(0)
    else:
        await shell.start()
        task = asyncio.create_task(shell.run_actions("select-all"))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.killed and process.waited
    assert not shell.is_running


async def test_crash_reports_stderr_and_reaps_child(spawn):
    process = FakeProcess(respond=False)
    spawn.return_value = process
    shell = ShellModeWrapper(sys.executable)
    await shell.start()
    task = asyncio.create_task(shell.run_actions("select-all"))
    await asyncio.sleep(0)
    process.stdout.feed_data(b"sp_repr_save_stream: simulated native crash\n")
    process.finish(-11)
    with pytest.raises(ShellModeError, match="simulated native crash"):
        await task
    assert process.waited
    assert not shell.is_running


async def test_merged_diagnostics_are_drained_and_bounded(spawn):
    process = FakeProcess(respond=False)
    spawn.return_value = process
    async with ShellModeWrapper(sys.executable) as shell:
        task = asyncio.create_task(shell.run_actions("select-all"))
        await asyncio.sleep(0)
        process.stdout.feed_data(b"x" * 200_000 + b"last diagnostic\n> ")
        assert (await task).endswith("last diagnostic")
        assert len(shell._output_tail) == 16_384


@pytest.mark.parametrize("exit_code", [None, 0])
async def test_unknown_action_is_rejected_even_without_failed_exit(spawn, exit_code):
    process = FakeProcess(respond=False)
    spawn.return_value = process
    shell = ShellModeWrapper(sys.executable)
    await shell.start()
    task = asyncio.create_task(shell.run_actions("nonexistent-action"))
    await asyncio.sleep(0)
    process.stdout.feed_data(
        b"nonexistent-action\n"
        b"InkscapeApplication::parse_actions: could not find action for: nonexistent-action\n> "
    )
    if exit_code is not None:
        process.finish(exit_code)
    with pytest.raises(ShellModeError, match="could not find action"):
        await task
    assert process.waited and not shell.is_running


async def test_simplify_uses_supported_action(spawn):
    process = FakeProcess()
    spawn.return_value = process
    async with ShellModeWrapper(sys.executable) as shell:
        await shell.path_simplify()
        assert process.stdin.writes == [b"select-all;path-simplify\n"]
        with pytest.raises(ShellModeError, match="custom threshold"):
            await shell.path_simplify(threshold=0.2)
        with pytest.raises(ShellModeError, match="no vacuum-defs shell action"):
            await shell.vacuum_defs()


async def test_svg_angle_bracket_is_not_prompt(spawn):
    process = FakeProcess(respond=False)
    spawn.return_value = process
    async with ShellModeWrapper(sys.executable) as shell:
        task = asyncio.create_task(shell.run_actions("query-all"))
        await asyncio.sleep(0)
        process.stdout.feed_data(b"<svg>")
        await asyncio.sleep(0)
        assert not task.done()
        process.stdout.feed_data(b"\n</svg>\n> ")
        assert await task == "<svg>\n</svg>"


async def test_concurrent_commands_are_serialized(spawn):
    process = FakeProcess(respond=False)
    spawn.return_value = process
    async with ShellModeWrapper(sys.executable) as shell:
        first = asyncio.create_task(shell.run_actions("first"))
        second = asyncio.create_task(shell.run_actions("second"))
        await asyncio.sleep(0)
        assert process.stdin.writes == [b"first\n"]
        process.stdout.feed_data(b"first result\n> ")
        assert await first == "first result"
        await asyncio.sleep(0)
        assert process.stdin.writes == [b"first\n", b"second\n"]
        process.stdout.feed_data(b"second result\n> ")
        assert await second == "second result"


async def test_cancelled_close_still_reaps_child_after_active_command(spawn):
    process = FakeProcess(respond=False)
    spawn.return_value = process
    shell = ShellModeWrapper(sys.executable)
    await shell.start()
    command = asyncio.create_task(shell.run_actions("query-all"))
    await asyncio.sleep(0)
    closing = asyncio.create_task(shell.close())
    await asyncio.sleep(0)
    closing.cancel()
    process.stdout.feed_data(b"result\n> ")
    assert await command == "result"
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert process.waited and not shell.is_running


@pytest.mark.parametrize(
    "action",
    [
        "select-all\nquit",
        "select-all\rquit",
        "select-all\0",
        "active-window-start",
        "select-all;active-window-end",
    ],
)
async def test_rejects_multiple_shell_lines(spawn, action):
    shell = ShellModeWrapper(sys.executable)
    with pytest.raises(ShellModeError):
        await shell.run_actions(action)
    spawn.assert_not_called()


async def test_full_pipeline_is_one_atomic_command(spawn, tmp_path):
    process = FakeProcess()
    spawn.return_value = process
    async with ShellModeWrapper(sys.executable) as shell:
        await shell.run_full_pipeline(
            str(tmp_path / "in.svg"), str(tmp_path / "out.svg"), ["select-all"]
        )
        assert len(process.stdin.writes) == 1
        assert process.stdin.writes[0].count(b"export-do") == 1


@pytest.mark.parametrize("size", [0, -1, True, 1.5])
def test_invalid_pool_size(size):
    with pytest.raises(ValueError):
        ShellModePool(sys.executable, size=size)


async def test_pool_leases_are_exclusive_and_release_waiter(spawn):
    spawn.side_effect = [FakeProcess(), FakeProcess()]
    pool = ShellModePool(sys.executable, size=2)
    await pool.start()
    first_lease, second_lease, third_lease = pool.acquire(), pool.acquire(), pool.acquire()
    try:
        first, second = await first_lease.__aenter__(), await second_lease.__aenter__()
        assert first is not second
        waiting = asyncio.create_task(third_lease.__aenter__())
        await asyncio.sleep(0)
        assert not waiting.done()
        await first_lease.__aexit__()
        assert await waiting is first
        await third_lease.__aexit__()
        await second_lease.__aexit__()
    finally:
        await pool.close()


async def test_pool_close_wakes_waiting_acquisition(spawn):
    spawn.return_value = FakeProcess()
    pool = ShellModePool(sys.executable, size=1)
    await pool.start()
    lease = pool.acquire()
    await lease.__aenter__()
    waiting = asyncio.create_task(pool.acquire().__aenter__())
    await asyncio.sleep(0)
    await pool.close()
    with pytest.raises(ShellModeError, match="not running"):
        await waiting
    await lease.__aexit__()


async def test_failed_pool_start_closes_successful_siblings(spawn):
    process = FakeProcess()
    spawn.side_effect = [process, OSError("cannot spawn")]
    pool = ShellModePool(sys.executable, size=2)
    with pytest.raises(ShellModeError, match="cannot spawn"):
        await pool.start()
    assert process.waited and process.returncode is not None
    with pytest.raises(ShellModeError, match="not running"):
        async with pool.acquire():
            pass


async def test_failed_pool_restart_does_not_lose_capacity(spawn):
    process, replacement = FakeProcess(), FakeProcess()
    spawn.side_effect = [process, OSError("cannot restart"), replacement]
    pool = ShellModePool(sys.executable, size=1)
    await pool.start()
    process.finish(-11)
    with pytest.raises(ShellModeError, match="cannot restart"):
        async with pool.acquire():
            pass
    async with pool.acquire() as shell:
        assert shell.is_running
    await pool.close()
    assert replacement.waited


@pytest.mark.parametrize(
    "diagnostic",
    [
        "action:object_trace: selection empty!",
        "action:transform_translate: expected argument",
        "action:transform_scale: parsing arguments failed",
    ],
)
async def test_action_argument_failures_invalidate_shell(spawn, diagnostic):
    process = FakeProcess(respond=False)
    spawn.return_value = process
    shell = ShellModeWrapper(sys.executable)
    await shell.start()
    task = asyncio.create_task(shell.run_actions("object-trace"))
    await asyncio.sleep(0)
    process.stdout.feed_data(f"{diagnostic}\n> ".encode())
    try:
        with pytest.raises(ShellModeError, match="action error"):
            await task
        assert process.waited and not shell.is_running
    finally:
        await shell.close()


@pytest.mark.parametrize("exit_code", [0, -11])
async def test_exit_after_prompt_is_not_reported_as_success(spawn, exit_code):
    process = FakeProcess(respond=False)
    spawn.return_value = process
    shell = ShellModeWrapper(sys.executable)
    await shell.start()
    task = asyncio.create_task(shell.run_actions("query-all"))
    await asyncio.sleep(0)
    process.stdout.feed_data(b"result\n> ")
    process.finish(exit_code)
    try:
        with pytest.raises(ShellModeError, match="exited"):
            await task
        assert process.waited and not shell.is_running
    finally:
        await shell.close()
