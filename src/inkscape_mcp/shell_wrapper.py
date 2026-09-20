"""Persistent, isolated Inkscape shell sessions for multi-step SVG operations.

Calls on a wrapper are serialized. A complete pipeline is sent as one command;
use a pool lease to keep a sequence of separate calls on the same document.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import os
import re
from collections import deque
from pathlib import Path
from uuid import uuid4

from inkscape_mcp.utils.inkscape_actions import validate_actions

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0
_DIAGNOSTIC_LIMIT = 16_384
_RESPONSE_LIMIT = 8 * 1024 * 1024
_PROMPT = re.compile(rb"(?:^|\n)>[ \t\r]*$")
_ACTION_ERROR = re.compile(
    r"(?im)(?:^|\n).*?(?:parse_actions:.*(?:could not find|invalid)|"
    r"unknown (?:option|action)|unable to (?:open|export)|"
    r"unknown export type|no export type specified|"
    r"failed to (?:load|open|save|export)|(?:^|\s)error:|"
    r"cannot be opened|failed to create document|tracing failed|"
    r"did not find object with id|"
    r"action:[^\n]*(?:selection empty|expected argument|parsing arguments failed)|"
    r"emergency save activated|segmentation fault)"
)


class ShellModeError(Exception):
    """Raised when the Inkscape shell session fails."""


class ShellModeWrapper:
    """Persistent Inkscape --shell process, usable as an async context manager."""

    def __init__(
        self,
        inkscape_exe: str,
        timeout: float = _DEFAULT_TIMEOUT,
        startup_timeout: float = 10.0,
    ) -> None:
        if not Path(inkscape_exe).is_file():
            raise ShellModeError(f"Inkscape executable not found: {inkscape_exe}")
        if any(not math.isfinite(value) or value <= 0 for value in (timeout, startup_timeout)):
            raise ValueError("Shell timeouts must be finite and positive")
        self._exe = inkscape_exe
        self._timeout = timeout
        self._startup_timeout = startup_timeout
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._output_tail = bytearray()

    async def start(self) -> None:
        """Launch an independent headless process and await its initial prompt."""
        async with self._lock:
            if self.is_running:
                return
            await self._stop(graceful=False)
            self._output_tail.clear()
            try:
                tag = f"inkscape_mcp_{uuid4().hex}"
                self._proc = await asyncio.create_subprocess_exec(
                    self._exe,
                    f"--app-id-tag={tag}",
                    "--batch-process",
                    "--shell",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    # One ordered stream makes action errors visible before the
                    # following prompt, even when Inkscape keeps running/returns 0.
                    stderr=asyncio.subprocess.STDOUT,
                    # Apply isolation before Inkscape's constructor probes the
                    # default D-Bus name; the CLI flag is processed too late.
                    env={**os.environ, "INKSCAPE_APP_ID_TAG": tag},
                )
                await asyncio.wait_for(self._read_until_prompt(), timeout=self._startup_timeout)
            except asyncio.CancelledError:
                await self._stop(graceful=False)
                raise
            except (OSError, TimeoutError, ShellModeError) as exc:
                await self._stop(graceful=False)
                raise ShellModeError(
                    f"Inkscape shell failed to start within {self._startup_timeout}s: "
                    f"{exc}{self._diagnostics()}"
                ) from exc
            logger.info("Inkscape shell ready (pid=%s)", self.pid)

    async def close(self) -> None:
        """Close the session, kill it if necessary, and reap the child process."""
        await self._finish_cleanup(asyncio.create_task(self._close_when_idle()))

    async def _close_when_idle(self) -> None:
        async with self._lock:
            await self._stop(graceful=True)

    async def _stop(self, *, graceful: bool) -> None:
        """Finish cleanup even when the caller is cancelled a second time."""
        if self._proc is not None:
            await self._finish_cleanup(asyncio.create_task(self._stop_process(graceful=graceful)))

    @staticmethod
    async def _finish_cleanup(cleanup: asyncio.Task[None]) -> None:
        cancelled = False
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                cancelled = True
        cleanup.result()
        if cancelled:
            raise asyncio.CancelledError

    async def _stop_process(self, *, graceful: bool) -> None:
        proc = self._proc
        if proc is None:
            return
        # Keep the merged output pipe drained while the child is exiting.
        stdout_task = asyncio.create_task(self._discard_stdout(proc))
        try:
            if proc.returncode is None and graceful:
                try:
                    async with asyncio.timeout(5.0):
                        if proc.stdin is not None:
                            proc.stdin.write(b"quit\n")
                            await proc.stdin.drain()
                        await proc.wait()
                except (OSError, TimeoutError):
                    pass
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
            await proc.wait()
            await stdout_task
        finally:
            if proc.stdin is not None:
                proc.stdin.close()
            stdout_task.cancel()
            self._proc = None
            logger.info("Inkscape shell closed")

    async def _discard_stdout(self, proc: asyncio.subprocess.Process) -> None:
        if proc.stdout is not None:
            while chunk := await proc.stdout.read(65536):
                self._remember_output(chunk)

    def _remember_output(self, chunk: bytes) -> None:
        self._output_tail.extend(chunk)
        del self._output_tail[:-_DIAGNOSTIC_LIMIT]

    def _diagnostics(self) -> str:
        diagnostics = self._output_tail.decode("utf-8", errors="replace").strip()
        return f"; output: {diagnostics}" if diagnostics else ""

    async def __aenter__(self) -> ShellModeWrapper:
        await self.start()
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    async def run_actions(self, *actions: str) -> str:
        """Run one action sequence; failures invalidate the session until restarted."""
        try:
            command = ";".join(validate_actions(list(actions)))
        except ValueError as exc:
            raise ShellModeError(str(exc)) from exc
        if not command:
            raise ShellModeError("At least one shell action is required")
        async with self._lock:
            self._ensure_running()
            self._output_tail.clear()
            assert self._proc is not None and self._proc.stdin is not None
            try:
                # Include stdin backpressure in the command deadline.
                async with asyncio.timeout(self._timeout):
                    self._proc.stdin.write((command + "\n").encode())
                    await self._proc.stdin.drain()
                    response = await self._read_until_prompt()
                    # Readline echoes the command. A filename containing a word
                    # such as 'error:' must not itself be treated as an error.
                    diagnostics = "\n".join(
                        line for line in response.splitlines() if line != command
                    )
                    if _ACTION_ERROR.search(diagnostics):
                        raise ShellModeError("Inkscape reported an action error")
                    if self._proc.returncode is not None:
                        raise ShellModeError(
                            f"Inkscape shell exited with return code {self._proc.returncode}"
                        )
            except asyncio.CancelledError:
                await self._stop(graceful=False)
                raise
            except (OSError, TimeoutError, ShellModeError) as exc:
                await self._stop(graceful=False)
                raise ShellModeError(
                    f"Inkscape shell command failed (timeout {self._timeout}s): "
                    f"{exc}{self._diagnostics()}"
                ) from exc
            return response

    @staticmethod
    def _action_path(path: str) -> str:
        # The action grammar has no escaping for semicolons or line breaks.
        if not path or any(c in str(path) for c in ";\r\n\0"):
            raise ShellModeError(
                "Action paths cannot be empty or contain semicolons, newlines or NUL bytes"
            )
        return str(Path(path).expanduser().resolve())

    async def open_file(self, path: str) -> str:
        """Open an SVG file in the shell session."""
        return await self.run_actions(f"file-open:{self._action_path(path)}")

    async def save_file(self, output_path: str, plain_svg: bool = True) -> str:
        """Export the current document to output_path."""
        actions = [f"export-filename:{self._action_path(output_path)}"]
        if plain_svg:
            actions.append("export-plain-svg")
        actions.append("export-do")
        return await self.run_actions(*actions)

    async def select_all(self) -> str:
        return await self.run_actions("select-all")

    async def path_union(self) -> str:
        return await self.run_actions("select-all", "path-union")

    async def path_difference(self) -> str:
        return await self.run_actions("select-all", "path-difference")

    async def path_intersection(self) -> str:
        return await self.run_actions("select-all", "path-intersection")

    async def path_simplify(self, threshold: float = 1.0) -> str:
        """Simplify using Inkscape preferences; shell actions have no threshold argument."""
        if threshold != 1.0:
            raise ShellModeError("The path-simplify action does not support a custom threshold")
        return await self.run_actions("select-all", "path-simplify")

    async def text_to_path(self) -> str:
        return await self.run_actions("select-all", "object-to-path")

    async def fit_canvas_to_drawing(self) -> str:
        return await self.run_actions("fit-canvas-to-drawing")

    async def vacuum_defs(self) -> str:
        raise ShellModeError(
            "Inkscape exposes no vacuum-defs shell action; use the CLI --vacuum-defs option"
        )

    async def run_action_sequence(self, actions: list[str]) -> str:
        """Run a pre-built list of action strings as one command."""
        return await self.run_actions(*actions)

    async def run_full_pipeline(self, input_path: str, output_path: str, actions: list[str]) -> str:
        """Open, transform and export atomically with respect to other calls."""
        return await self.run_actions(
            f"file-open:{self._action_path(input_path)}",
            *actions,
            f"export-filename:{self._action_path(output_path)}",
            "export-plain-svg",
            "export-do",
        )

    def _ensure_running(self) -> None:
        if not self.is_running:
            raise ShellModeError(
                "Inkscape shell is not running; call start() or use its async context manager"
            )

    async def _read_until_prompt(self) -> str:
        """Recognize a prompt on its own line, not '>' inside SVG or diagnostics."""
        buf = bytearray()
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            chunk = await self._proc.stdout.read(4096)
            if not chunk:
                raise ShellModeError("Inkscape shell process closed unexpectedly")
            self._remember_output(chunk)
            buf.extend(chunk)
            if len(buf) > _RESPONSE_LIMIT:
                raise ShellModeError("Inkscape shell response exceeded the 8 MiB limit")
            if prompt := _PROMPT.search(buf):
                return buf[: prompt.start()].decode("utf-8", errors="replace").strip()

    @property
    def is_running(self) -> bool:
        return bool(self._proc and self._proc.returncode is None)

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc else None


class ShellModePool:
    """Pool with exclusive leases; each workflow gets its own document session."""

    def __init__(self, inkscape_exe: str, size: int = 3) -> None:
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            raise ValueError("Shell pool size must be a positive integer")
        self._exe = inkscape_exe
        self._size = size
        self._wrappers: list[ShellModeWrapper] = []
        self._available: deque[ShellModeWrapper] = deque()
        self._condition = asyncio.Condition()
        self._lifecycle_lock = asyncio.Lock()
        self._started = False

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._started:
                return
            wrappers = [ShellModeWrapper(self._exe) for _ in range(self._size)]
            try:
                results = await asyncio.gather(
                    *(wrapper.start() for wrapper in wrappers), return_exceptions=True
                )
                for result in results:
                    if isinstance(result, BaseException):
                        raise result
            except BaseException:
                await asyncio.gather(
                    *(wrapper.close() for wrapper in wrappers), return_exceptions=True
                )
                raise
            async with self._condition:
                self._wrappers = wrappers
                self._available.extend(wrappers)
                self._started = True
                self._condition.notify_all()

    async def close(self) -> None:
        async with self._lifecycle_lock:
            async with self._condition:
                self._started = False
                wrappers, self._wrappers = self._wrappers, []
                self._available.clear()
                self._condition.notify_all()
            await asyncio.gather(*(wrapper.close() for wrapper in wrappers))

    def acquire(self) -> ShellModePool._AcquiredShell:
        return ShellModePool._AcquiredShell(self)

    async def _release(self, wrapper: ShellModeWrapper) -> None:
        async with self._condition:
            if self._started and wrapper in self._wrappers:
                self._available.append(wrapper)
                self._condition.notify()

    class _AcquiredShell:
        def __init__(self, pool: ShellModePool) -> None:
            self._pool = pool
            self._wrapper: ShellModeWrapper | None = None

        async def __aenter__(self) -> ShellModeWrapper:
            if self._wrapper is not None:
                raise ShellModeError("A shell lease cannot be entered twice")
            async with self._pool._condition:
                await self._pool._condition.wait_for(
                    lambda: self._pool._available or not self._pool._started
                )
                if not self._pool._started:
                    raise ShellModeError("Inkscape shell pool is not running")
                wrapper = self._pool._available.popleft()
            try:
                if not wrapper.is_running:
                    await wrapper.start()
                if not self._pool._started or wrapper not in self._pool._wrappers:
                    raise ShellModeError("Inkscape shell pool closed while acquiring a session")
            except BaseException:
                await self._pool._release(wrapper)
                raise
            self._wrapper = wrapper
            return wrapper

        async def __aexit__(self, *args) -> None:
            if self._wrapper is not None:
                await self._pool._release(self._wrapper)
                self._wrapper = None
